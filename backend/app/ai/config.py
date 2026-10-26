"""Configuration loader for ModelGateway policies and provider settings."""
import json
import os
import sys
from pathlib import Path
import tomllib
from urllib.parse import urlsplit
from typing import Any

from .schemas import GatewayConfig, ModelPolicy, ModelPolicyConfig, TaskType

DEFAULT_POLICIES: dict[ModelPolicy, dict[str, Any]] = {
    'FAST': {
        'provider': 'mock',
        'model': 'fast-model-v1',
        'temperature': 0.1,
        'max_tokens': 512,
        'timeout_seconds': 5.0,
    },
    'BALANCED': {
        'provider': 'mock',
        'model': 'balanced-model-v1',
        'temperature': 0.2,
        'max_tokens': 3584,
        'timeout_seconds': 60.0,
    },
    'STRONG': {
        'provider': 'mock',
        'model': 'strong-model-v1',
        'temperature': 0.2,
        'max_tokens': 2048,
        'timeout_seconds': 20.0,
    },
}

DEFAULT_TASK_MAP: dict[TaskType, ModelPolicy] = {
    'tutor_hint': 'FAST',
    'error_diagnosis': 'BALANCED',
    'tutor_explanation': 'BALANCED',
    'shenlun_assessment': 'STRONG',
    'question_generation': 'STRONG',
    'weekly_analysis': 'STRONG',
    'rag_answer': 'BALANCED',
}


def load_gateway_config(config_path: Path | None = None) -> GatewayConfig:
    """Load GatewayConfig from file or environment variables."""
    root = Path(__file__).resolve().parents[3]
    candidate_paths = [
        config_path,
        root / 'model_config.toml',
        root / 'model_config.json',
    ]

    loaded_raw: dict[str, Any] = {}
    for p in candidate_paths:
        if p and p.is_file():
            try:
                if p.suffix == '.toml':
                    loaded_raw = tomllib.loads(p.read_text(encoding='utf-8'))
                elif p.suffix == '.json':
                    loaded_raw = json.loads(p.read_text(encoding='utf-8'))
                break
            except Exception:
                continue

    # Assemble policies
    policies: dict[ModelPolicy, ModelPolicyConfig] = {}
    raw_policies = loaded_raw.get('policies', {})

    default_provider = os.environ.get('AI_PROVIDER', 'mock')
    explicit_provider = os.environ.get('AI_PROVIDER')
    global_base_url = os.environ.get('AI_BASE_URL') or os.environ.get('OPENAI_BASE_URL')
    global_api_key = os.environ.get('AI_API_KEY') or os.environ.get('OPENAI_API_KEY')

    if not global_api_key:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
                val, _ = winreg.QueryValueEx(k, "AI_API_KEY")
                if val:
                    global_api_key = val
        except Exception:
            pass

    if not global_base_url:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Environment") as k:
                val, _ = winreg.QueryValueEx(k, "AI_BASE_URL")
                if val:
                    global_base_url = val
        except Exception:
            pass

    is_pytest = bool(os.environ.get('PYTEST_CURRENT_TEST') or 'pytest' in sys.modules)
    if is_pytest and os.environ.get('USE_REAL_AI') != '1':
        default_provider = os.environ.get('AI_PROVIDER', 'mock')
    else:
        default_provider = os.environ.get('AI_PROVIDER', 'openai_compatible' if global_api_key else 'mock')

    for pol_name, defaults in DEFAULT_POLICIES.items():
        pol_raw = raw_policies.get(pol_name, {})
        if is_pytest and os.environ.get('USE_REAL_AI') != '1':
            provider = 'mock'
            model = defaults['model']
        else:
            provider = os.environ.get(f'AI_{pol_name}_PROVIDER') or explicit_provider or pol_raw.get('provider') or default_provider
            model = pol_raw.get('model') or os.environ.get(f'AI_{pol_name}_MODEL') or defaults['model']
        base_url = pol_raw.get('base_url') or global_base_url
        api_key = pol_raw.get('api_key') or global_api_key
        temp = float(pol_raw.get('temperature', defaults['temperature']))
        tokens = int(pol_raw.get('max_tokens', defaults['max_tokens']))
        timeout = float(pol_raw.get('timeout_seconds', defaults['timeout_seconds']))

        policies[pol_name] = ModelPolicyConfig(
            provider=provider,
            model=model,
            base_url=base_url,
            api_key=api_key,
            temperature=temp,
            max_tokens=tokens,
            timeout_seconds=timeout,
            supports_vision=bool(pol_raw.get('supports_vision',
                urlsplit(base_url or '').hostname == 'api.deepseek.com' and model in
                {'deepseek-flash', 'deepseek-v4-flash-vision-exp'})),
        )

    task_map: dict[TaskType, ModelPolicy] = dict(DEFAULT_TASK_MAP)
    raw_task_map = loaded_raw.get('task_policy_map', {})
    for task_name, pol in raw_task_map.items():
        if pol in ('FAST', 'BALANCED', 'STRONG'):
            task_map[task_name] = pol

    # Load optional fallback model config
    fallback_cfg: ModelPolicyConfig | None = None
    raw_fallback = loaded_raw.get('fallback', {})
    if raw_fallback and not is_pytest and explicit_provider != 'mock':
        fb_provider = raw_fallback.get('provider', 'openai_compatible')
        fb_model = raw_fallback.get('model', 'fallback-model')
        fb_base_url = raw_fallback.get('base_url') or os.environ.get('FALLBACK_BASE_URL')
        fb_api_key = raw_fallback.get('api_key') or os.environ.get('FALLBACK_API_KEY') or global_api_key
        fb_temp = float(raw_fallback.get('temperature', 0.2))
        fb_tokens = int(raw_fallback.get('max_tokens', 4096))
        fb_timeout = float(raw_fallback.get('timeout_seconds', 30.0))
        fallback_cfg = ModelPolicyConfig(
            provider=fb_provider,
            model=fb_model,
            base_url=fb_base_url,
            api_key=fb_api_key,
            temperature=fb_temp,
            max_tokens=fb_tokens,
            timeout_seconds=fb_timeout,
            supports_vision=bool(raw_fallback.get('supports_vision', False)),
        )

    return GatewayConfig(policies=policies, task_policy_map=task_map, fallback=fallback_cfg)
