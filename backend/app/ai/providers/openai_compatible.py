"""Generic OpenAI-compatible HTTP REST provider (DeepSeek, OpenAI, Ollama, Gemini, etc.)."""
import asyncio
import json
import logging
import re
from urllib.parse import urlsplit
from typing import Any
import httpx

from ..schemas import (
    Message,
    ModelPolicyConfig,
    ProviderUnavailableError,
    TruncatedGenerationError,
)

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider:
    """Universal model provider communicating over standard /chat/completions REST protocol."""

    provider_name: str = 'openai_compatible'

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._custom_client = client

    async def generate(
        self,
        messages: list[Message],
        config: ModelPolicyConfig,
        json_mode: bool = False,
    ) -> tuple[str, dict[str, int]]:
        base_url = (config.base_url or 'https://api.openai.com/v1').rstrip('/')
        url = f'{base_url}/chat/completions'

        headers = {'Content-Type': 'application/json'}
        if config.api_key:
            headers['Authorization'] = f'Bearer {config.api_key}'

        payload: dict[str, Any] = {
            'model': config.model,
            'messages': [{'role': m.role, 'content': (
                [{'type': 'text', 'text': m.content},
                 *[{'type': 'image_url', 'image_url': {'url': url}} for url in m.images]]
                if m.images else m.content
            )} for m in messages],
            'temperature': config.temperature,
            'max_tokens': config.max_tokens,
        }
        if json_mode:
            payload['response_format'] = {'type': 'json_object'}
        # The official Flash endpoint defaults to high reasoning effort. Keep
        # visual tutoring within its bounded response budget instead of letting
        # hidden reasoning consume the entire answer allocation.
        if any(m.images for m in messages) and urlsplit(base_url).hostname == 'api.deepseek.com' and config.model == 'deepseek-flash':
            payload['reasoning_effort'] = 'low'

        resp = None
        for attempt in range(2):  # Max 1 retry (2 attempts total) with exponential backoff
            try:
                if self._custom_client is not None:
                    resp = await self._custom_client.post(
                        url, json=payload, headers=headers, timeout=config.timeout_seconds
                    )
                else:
                    async with httpx.AsyncClient(timeout=config.timeout_seconds, trust_env=False) as client:
                        resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    break
                elif resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                else:
                    raise ProviderUnavailableError(f'Model provider returned HTTP {resp.status_code}: {resp.text}')
            except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError) as exc:
                if attempt == 0:
                    await asyncio.sleep(1.5)
                    continue
                raise ProviderUnavailableError(f'Model request to {url} failed: {exc}') from exc

        try:
            data = resp.json()
            choice = data['choices'][0]
            finish_reason = choice.get('finish_reason', 'stop')
            msg = choice.get('message', {})
            content = msg.get('content') or ''

            # 1. Clean think tags if wrapped in content by reasoning models
            if '<think>' in content:
                content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()

            # 2. Strict isolation: NEVER substitute internal reasoning_content as user answer.
            # If the model ran out of token budget during reasoning before generating content,
            # or if the generation was cut off midway:
            if finish_reason == 'length':
                logger.warning('Model %s generation truncated by token budget (finish_reason=length)', config.model)
                if not content.strip():
                    raise TruncatedGenerationError(
                        f'Model {config.model} token budget exhausted during reasoning before answer generation.'
                    )
                # If content was partially generated, raise TruncatedGenerationError so gateway fallback can retry
                raise TruncatedGenerationError(
                    f'Model {config.model} output was truncated due to token budget limit.'
                )

            usage = data.get('usage', {})
            return content, {
                'prompt_tokens': int(usage.get('prompt_tokens', 0)),
                'completion_tokens': int(usage.get('completion_tokens', 0)),
                'total_tokens': int(usage.get('total_tokens', 0)),
            }
        except TruncatedGenerationError:
            raise
        except Exception as exc:
            raise ProviderUnavailableError(f'Malformed completion response from model endpoint: {exc}') from exc
