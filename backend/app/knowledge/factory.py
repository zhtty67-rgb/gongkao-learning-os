"""Factory for obtaining the active KnowledgeProvider based on configuration."""
import os
import sys
from typing import Literal

from .disabled import DisabledProvider
from .fixture import FixtureProvider
from .knowledge_hub import KnowledgeHubProvider
from .provider import KnowledgeProvider

ProviderMode = Literal['disabled', 'fixture', 'knowledge_hub']

VALID_MODES = ('disabled', 'fixture', 'knowledge_hub')


def _default_mode() -> str:
    """Resolve the provider mode when KNOWLEDGE_PROVIDER is not set.

    Production defaults to the real Knowledge Hub; unconfigured hub is reported
    honestly as unavailable, never substituted with demo data. Under pytest the
    deterministic fixture is the default (mirrors the AI mock convention), and
    remains an explicit test/demo-only opt-in.
    """
    is_pytest = bool(os.environ.get('PYTEST_CURRENT_TEST') or 'pytest' in sys.modules)
    return 'fixture' if is_pytest else 'knowledge_hub'


def get_knowledge_provider(
    mode: str | None = None,
    **kwargs,
) -> KnowledgeProvider:
    """Return the configured KnowledgeProvider instance.

    Modes:
      - 'disabled': Null provider that returns empty results and never fails.
      - 'fixture': In-memory demo fixtures. Explicit test/demo opt-in only;
        evidence is visibly marked as demo data, never presented as real material.
      - 'knowledge_hub': Connects to Universal Knowledge Hub REST API.

    Unknown explicit values raise ValueError instead of silently falling back.
    """
    configured_mode = (mode if mode is not None else os.environ.get('KNOWLEDGE_PROVIDER'))
    if configured_mode is None or not configured_mode.strip():
        configured_mode = _default_mode()
    else:
        configured_mode = configured_mode.strip().lower()

    if configured_mode == 'disabled':
        return DisabledProvider()
    elif configured_mode == 'knowledge_hub':
        return KnowledgeHubProvider(**kwargs)
    elif configured_mode == 'fixture':
        return FixtureProvider(**kwargs)
    else:
        raise ValueError(
            f'未知的 KNOWLEDGE_PROVIDER 配置: {configured_mode!r}，'
            f'可选值: {", ".join(VALID_MODES)}'
        )
