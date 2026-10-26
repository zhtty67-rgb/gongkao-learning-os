"""运行时系统设置：AI 模型网关与知识检索的可视化配置。

设置持久化到 data/settings.json，作为一层"叠加配置"：未保存任何设置时，
行为与原来完全一致（model_config.toml + 环境变量/注册表）；保存后，settings.json
中对相应字段的取值优先生效，且立即热重载（模型网关单例 + 知识 Provider 环境
变量），重启后依然生效。

api_key 约定：
- 读取时永远脱敏（仅返回 sk-****xxxx 形式的掩码）。
- 保存时 None/缺省 = 保持现值不变；空字符串 = 清除；含 "****" 的掩码值 = 视为未修改。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .ai.config import load_gateway_config
from .ai.gateway import ModelGateway, set_model_gateway
from .ai.providers.openai_compatible import OpenAICompatibleProvider
from .ai.schemas import GatewayConfig, Message, ModelPolicyConfig

ROOT = Path(__file__).resolve().parents[2]

POLICY_NAMES = ('FAST', 'BALANCED', 'STRONG')
MASK_PATTERN = re.compile(r'\*{4}')


def settings_path() -> Path:
    """Location of the persisted settings file (overridable for tests/packaging)."""
    env = os.environ.get('GONGKAO_SETTINGS_PATH')
    if env:
        return Path(env)
    return ROOT / 'data' / 'settings.json'


def is_pytest_context() -> bool:
    return bool(os.environ.get('PYTEST_CURRENT_TEST') or 'pytest' in sys.modules)


def mask_key(value: str | None) -> str | None:
    """Mask a secret for display: keep a short head/tail so users can recognise it."""
    if value is None:
        return None
    if not value:
        return ''
    if len(value) <= 8:
        return '****'
    return f'{value[:3]}****{value[-4:]}'


class PolicySettings(BaseModel):
    """Single model policy (FAST / BALANCED / STRONG) or the fallback policy."""

    model_config = ConfigDict(extra='forbid')

    provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)
    timeout_seconds: float | None = Field(default=None, ge=0.1)
    supports_vision: bool | None = None


class AiSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')

    policies: dict[str, PolicySettings] = Field(default_factory=dict)
    fallback: PolicySettings | None = None


class KnowledgeSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')

    provider: Literal['knowledge_hub', 'disabled', 'fixture'] | None = None
    hub_base_url: str | None = None
    hub_api_key: str | None = None
    hub_timeout_seconds: float | None = Field(default=None, ge=0.1)


class SystemSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')

    ai: AiSettings = Field(default_factory=AiSettings)
    knowledge: KnowledgeSettings | None = None


def load_settings() -> SystemSettings:
    """Load persisted settings; missing or malformed file yields defaults."""
    path = settings_path()
    if not path.is_file():
        return SystemSettings()
    try:
        raw = json.loads(path.read_text(encoding='utf-8'))
        return SystemSettings.model_validate(raw)
    except Exception:
        return SystemSettings()


def save_settings(settings: SystemSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(
        json.dumps(settings.model_dump(), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )
    tmp.replace(path)


def has_saved_settings() -> bool:
    return settings_path().is_file()


def _apply_policy_overlay(
    base: ModelPolicyConfig,
    overlay: PolicySettings | None,
) -> ModelPolicyConfig:
    """Merge one saved policy onto the effective (toml/env-resolved) policy.

    None fields keep the underlying value. api_key follows the masked-value
    convention: '' clears, a '****' mask means "unchanged", anything else replaces.
    """
    if overlay is None:
        return base
    data = base.model_dump()
    for field_name, value in overlay.model_dump().items():
        if value is None:
            continue
        if field_name == 'api_key':
            if MASK_PATTERN.search(value):
                continue
            data[field_name] = value
        else:
            data[field_name] = value
    return ModelPolicyConfig.model_validate(data)


def build_gateway_config(settings: SystemSettings | None = None) -> GatewayConfig:
    """Effective GatewayConfig = toml/env resolution overridden by saved settings."""
    settings = settings or load_settings()
    config = load_gateway_config()
    saved = settings.ai

    for name in POLICY_NAMES:
        overlay = saved.policies.get(name)
        if overlay is not None:
            config.policies[name] = _apply_policy_overlay(config.policies[name], overlay)

    if saved.fallback is not None:
        base = config.fallback or ModelPolicyConfig(
            provider='openai_compatible',
            model='fallback-model',
            temperature=0.2,
            max_tokens=4096,
            timeout_seconds=30.0,
        )
        config.fallback = _apply_policy_overlay(base, saved.fallback)
    elif 'fallback' in saved.model_fields_set:
        config.fallback = None
    return config


def apply_knowledge_env(settings: SystemSettings | None = None) -> None:
    """Push saved knowledge settings into process env (providers read env per call)."""
    settings = settings or load_settings()
    ks = settings.knowledge
    if ks is None:
        return
    if ks.provider is not None:
        os.environ['KNOWLEDGE_PROVIDER'] = ks.provider
    else:
        os.environ.pop('KNOWLEDGE_PROVIDER', None)
    if ks.hub_base_url:
        os.environ['KNOWLEDGE_HUB_BASE_URL'] = ks.hub_base_url
    else:
        os.environ.pop('KNOWLEDGE_HUB_BASE_URL', None)
    if ks.hub_api_key and not MASK_PATTERN.search(ks.hub_api_key):
        os.environ['KNOWLEDGE_HUB_API_KEY'] = ks.hub_api_key
    elif ks.hub_api_key == '':
        os.environ.pop('KNOWLEDGE_HUB_API_KEY', None)
    if ks.hub_timeout_seconds is not None:
        os.environ['KNOWLEDGE_HUB_TIMEOUT_SECONDS'] = str(ks.hub_timeout_seconds)


def apply_saved_settings() -> None:
    """Apply persisted settings at startup / after save (hot reload)."""
    settings = load_settings()
    apply_knowledge_env(settings)
    apply_saved_settings_gateway(settings)


def apply_saved_settings_gateway(settings: SystemSettings | None = None) -> None:
    """Hot-reload the model gateway singleton from the merged effective config.

    Always rebuilds: after a save that removed AI overrides the gateway must
    revert to the env/toml defaults instead of keeping the stale singleton.
    """
    settings = settings or load_settings()
    set_model_gateway(ModelGateway(build_gateway_config(settings)))


def resolve_policy_config(
    policy: str,
    override: PolicySettings | None = None,
) -> ModelPolicyConfig:
    """Effective policy config, optionally with unsaved test overrides on top."""
    config = build_gateway_config()
    if policy == 'fallback':
        base = config.fallback
        if base is None:
            raise ValueError('当前未配置 fallback 策略，请先在设置中启用。')
    else:
        if policy not in config.policies:
            raise ValueError(f'未知策略: {policy}')
        base = config.policies[policy]
    return _apply_policy_overlay(base, override)


async def test_ai_policy(config: ModelPolicyConfig) -> dict[str, Any]:
    """Live connectivity test against a model policy; never touches the gateway."""
    if config.provider != 'openai_compatible':
        return {
            'ok': True,
            'skipped': True,
            'message': f"provider={config.provider} 为内置提供方，无需连通性测试。",
            'latency_ms': None,
        }
    provider = OpenAICompatibleProvider()
    probe_config = config.model_copy(update={
        'timeout_seconds': min(config.timeout_seconds, 20.0),
        'max_tokens': 16,
    })
    start = time.perf_counter()
    try:
        content, usage = await provider.generate(
            [Message(role='user', content='连通性测试，请只回复两个字母：OK')],
            probe_config,
        )
        latency = round((time.perf_counter() - start) * 1000.0, 1)
        reply = (content or '').strip()
        return {
            'ok': True,
            'skipped': False,
            'message': f"连接成功（{latency} ms）：{reply[:80] or '(空回复)'}",
            'latency_ms': latency,
        }
    except Exception as exc:
        latency = round((time.perf_counter() - start) * 1000.0, 1)
        return {
            'ok': False,
            'skipped': False,
            'message': f'连接失败：{exc}',
            'latency_ms': latency,
        }


def policy_payload(name: str, config: ModelPolicyConfig) -> dict[str, Any]:
    data = config.model_dump()
    data['api_key'] = mask_key(config.api_key)
    data['api_key_set'] = bool(config.api_key)
    data['name'] = name
    return data


def normalize_incoming(raw: dict[str, Any]) -> dict[str, Any]:
    """Prepare a PUT payload for persistence: masked secrets mean "keep current"."""
    ai = raw.get('ai') or {}
    policies = ai.get('policies') or {}
    for overlay in policies.values():
        if isinstance(overlay, dict) and isinstance(overlay.get('api_key'), str) \
                and MASK_PATTERN.search(overlay['api_key']):
            overlay['api_key'] = None
    fallback = ai.get('fallback')
    if isinstance(fallback, dict) and isinstance(fallback.get('api_key'), str) \
            and MASK_PATTERN.search(fallback['api_key']):
        fallback['api_key'] = None
    knowledge = raw.get('knowledge')
    if isinstance(knowledge, dict) and isinstance(knowledge.get('hub_api_key'), str) \
            and MASK_PATTERN.search(knowledge['hub_api_key']):
        knowledge['hub_api_key'] = None
    return raw


def _merge_policy(base: PolicySettings | None, inc: PolicySettings) -> PolicySettings:
    """Overlay incoming non-None fields onto a saved policy (None = keep)."""
    fields = {k: v for k, v in inc.model_dump().items() if v is not None}
    return PolicySettings(**{**(base.model_dump() if base else {}), **fields})


def merge_settings(old: SystemSettings, incoming: SystemSettings) -> SystemSettings:
    """Merge a PUT payload onto persisted settings; omitted/None fields keep old values."""
    merged_policies = dict(old.ai.policies)
    for name, inc in incoming.ai.policies.items():
        merged_policies[name] = _merge_policy(merged_policies.get(name), inc)

    fallback = old.ai.fallback
    if incoming.ai.fallback is not None:
        fallback = _merge_policy(fallback, incoming.ai.fallback)
    elif 'fallback' in incoming.ai.model_fields_set:
        fallback = None

    knowledge = old.knowledge
    if 'knowledge' in incoming.model_fields_set:
        knowledge = incoming.knowledge
        if knowledge is not None and old.knowledge is not None and knowledge.hub_api_key is None:
            knowledge = knowledge.model_copy(update={'hub_api_key': old.knowledge.hub_api_key})

    return SystemSettings(
        ai=AiSettings(policies=merged_policies, fallback=fallback),
        knowledge=knowledge,
    )


def settings_snapshot() -> dict[str, Any]:
    """Full effective settings for the settings page (secrets masked everywhere)."""
    settings = load_settings()
    config = build_gateway_config(settings)

    policies = {name: policy_payload(name, cfg) for name, cfg in config.policies.items()}
    fallback = policy_payload('fallback', config.fallback) if config.fallback else None

    saved_policies: dict[str, Any] = {}
    for name, overlay in settings.ai.policies.items():
        item = overlay.model_dump()
        item['api_key'] = mask_key(overlay.api_key)
        saved_policies[name] = item
    saved_fallback = None
    if settings.ai.fallback is not None:
        saved_fallback = settings.ai.fallback.model_dump()
        saved_fallback['api_key'] = mask_key(settings.ai.fallback.api_key)

    env_provider = os.environ.get('KNOWLEDGE_PROVIDER') or 'knowledge_hub(默认)'
    saved_knowledge = settings.knowledge.model_dump() if settings.knowledge else None
    if saved_knowledge and saved_knowledge.get('hub_api_key'):
        saved_knowledge['hub_api_key'] = mask_key(saved_knowledge['hub_api_key'])
    knowledge: dict[str, Any] = {
        'provider': os.environ.get('KNOWLEDGE_PROVIDER'),
        'env_provider': env_provider,
        'hub_base_url': os.environ.get('KNOWLEDGE_HUB_BASE_URL', 'http://127.0.0.1:8200'),
        'hub_api_key_masked': mask_key(os.environ.get('KNOWLEDGE_HUB_API_KEY')),
        'hub_api_key_set': bool(os.environ.get('KNOWLEDGE_HUB_API_KEY')),
        'hub_timeout_seconds': float(os.environ.get('KNOWLEDGE_HUB_TIMEOUT_SECONDS', '3.0')),
        'saved': saved_knowledge,
    }

    return {
        'ai': {
            'policies': policies,
            'fallback': fallback,
            'saved': {
                'policies': saved_policies,
                'fallback': saved_fallback,
            },
        },
        'knowledge': knowledge,
        'has_saved_settings': has_saved_settings(),
        'settings_file': str(settings_path()),
    }
