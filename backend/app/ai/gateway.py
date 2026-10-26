"""Decoupled ModelGateway implementing policy-based routing and structured output validation."""
import json
import logging
from typing import Any, Type, TypeVar

from pydantic import BaseModel

from .config import load_gateway_config
from .providers.base import ModelProvider
from .providers.mock import MockModelProvider
from .providers.openai_compatible import OpenAICompatibleProvider
from .schemas import (
    GatewayConfig,
    GenerationResult,
    Message,
    ModelPolicy,
    ModelPolicyConfig,
    PolicyNotConfiguredError,
    ProviderUnavailableError,
    SchemaValidationError,
    TaskType,
    TruncatedGenerationError,
)

logger = logging.getLogger(__name__)
T = TypeVar('T', bound=BaseModel)


class ModelGateway:
    """Central AI Gateway for Learning OS.
    
    Business code uses only task_type and policy (FAST / BALANCED / STRONG).
    Concrete model names, providers, credentials, and endpoints are completely
    isolated behind external configuration.
    """

    def __init__(self, config: GatewayConfig | None = None, custom_provider: ModelProvider | None = None):
        self.config = config or load_gateway_config()
        self._custom_provider = custom_provider
        self._providers: dict[str, ModelProvider] = {
            'mock': MockModelProvider(),
            'openai_compatible': OpenAICompatibleProvider(),
        }

    def register_provider(self, name: str, provider: ModelProvider):
        self._providers[name] = provider

    def _resolve_provider(self, provider_name: str) -> ModelProvider:
        if self._custom_provider is not None:
            return self._custom_provider
        if provider_name not in self._providers:
            # Fallback to mock provider rather than crashing
            logger.warning('Provider %s not registered; falling back to mock.', provider_name)
            return self._providers['mock']
        return self._providers[provider_name]

    async def generate(
        self,
        task_type: TaskType | str,
        messages: list[Message],
        schema: Type[T] | None = None,
        model_policy: ModelPolicy | None = None,
    ) -> GenerationResult[Any]:
        """Generate model response with policy-based routing and optional strict schema validation."""
        # 1. Resolve policy
        policy: ModelPolicy = model_policy or self.config.task_policy_map.get(
            task_type, 'BALANCED'  # type: ignore
        )
        if policy not in self.config.policies:
            raise PolicyNotConfiguredError(f'Model policy {policy} is not configured')

        policy_cfg = self.config.policies[policy]

        try:
            return await self._call_model(policy_cfg, policy, messages, schema)
        except (ProviderUnavailableError, SchemaValidationError) as primary_err:
            if self.config.fallback is None or (any(m.images for m in messages) and not self.config.fallback.supports_vision):
                raise
            logger.warning(
                '[FALLBACK] Primary model %s/%s failed (%s), trying fallback %s/%s',
                policy_cfg.provider, policy_cfg.model,
                type(primary_err).__name__,
                self.config.fallback.provider, self.config.fallback.model,
            )
            try:
                return await self._call_model(self.config.fallback, policy, messages, schema)
            except Exception as fallback_err:
                logger.error('[FALLBACK] Fallback model also failed: %s', fallback_err)
                raise primary_err from fallback_err

    async def _call_model(
        self,
        policy_cfg: ModelPolicyConfig,
        policy: ModelPolicy,
        messages: list[Message],
        schema: Type[T] | None,
    ) -> GenerationResult[Any]:
        """Call a single model provider and validate the response."""
        provider = self._resolve_provider(policy_cfg.provider)
        if any(m.images for m in messages) and not policy_cfg.supports_vision:
            raise ProviderUnavailableError('当前策略未配置图片理解能力，未发送图片请求')

        # 2. Prepare system prompt / JSON formatting instruction if schema given
        processed_messages = list(messages)
        if schema is not None:
            json_schema_str = json.dumps(schema.model_json_schema(), ensure_ascii=False)
            format_msg = Message(
                role='system',
                content=f'You MUST reply with valid JSON conforming to this schema:\n{json_schema_str}',
            )
            # Insert after existing system message or at start
            if processed_messages and processed_messages[0].role == 'system':
                processed_messages[0] = Message(
                    role='system',
                    content=f'{processed_messages[0].content}\n\n{format_msg.content}',
                )
            else:
                processed_messages.insert(0, format_msg)

        # 3. Call underlying provider
        try:
            raw_text, usage = await provider.generate(
                messages=processed_messages, config=policy_cfg, json_mode=bool(schema is not None),
            )
        except TruncatedGenerationError:
            # Regenerate once with room for both reasoning and final output. Never
            # publish a partial response or mutate the configured default budget.
            budget = min(16384, max(8192, policy_cfg.max_tokens * 2))
            if budget <= policy_cfg.max_tokens:
                raise
            logger.warning('Truncated output; retrying once with budget %s', budget)
            raw_text, usage = await provider.generate(
                messages=processed_messages,
                config=policy_cfg.model_copy(update={'max_tokens': budget}),
                json_mode=bool(schema is not None),
            )

        # 4. Validate schema if requested
        if schema is not None:
            try:
                # Clean markdown backticks if returned
                cleaned = raw_text.strip()
                if cleaned.startswith('```'):
                    lines = cleaned.split('\n')
                    if lines[0].startswith('```'):
                        lines = lines[1:]
                    if lines and lines[-1].strip() == '```':
                        lines = lines[:-1]
                    cleaned = '\n'.join(lines).strip()

                parsed_data = schema.model_validate_json(cleaned)
            except Exception as exc:
                raise SchemaValidationError(
                    f'Model output failed schema validation for {schema.__name__}: {exc}\nRaw: {raw_text}'
                ) from exc
        else:
            parsed_data = raw_text

        return GenerationResult(
            data=parsed_data,
            raw_text=raw_text,
            policy_used=policy,
            model_name=policy_cfg.model,
            provider_name=policy_cfg.provider,
            tokens_used=usage,
        )


_default_gateway: ModelGateway | None = None


def get_model_gateway() -> ModelGateway:
    global _default_gateway
    if _default_gateway is None:
        _default_gateway = ModelGateway()
    return _default_gateway


def set_model_gateway(gateway: ModelGateway | None) -> None:
    global _default_gateway
    _default_gateway = gateway
