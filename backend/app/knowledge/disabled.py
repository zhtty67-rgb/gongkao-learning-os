"""Disabled fallback implementation of KnowledgeProvider."""
from datetime import datetime, timezone
from typing import Any

from .models import (
    DocumentContext,
    KnowledgeEvidence,
    ProviderHealth,
    SourceDocument,
)


class DisabledProvider:
    """Null provider when knowledge integration is explicitly disabled.
    
    Guarantees that Learning OS never fails when knowledge capabilities
    are switched off.
    """

    provider_name: str = 'disabled'

    async def retrieve(
        self,
        query: str,
        namespace: str,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[KnowledgeEvidence]:
        return []

    async def get_source(
        self,
        document_id: str,
        locator: str | None = None,
    ) -> SourceDocument | None:
        return None

    async def get_document_context(
        self,
        document_id: str,
        locator: str | None = None,
    ) -> DocumentContext | None:
        return None

    async def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            status='unavailable',
            provider=self.provider_name,
            latency_ms=0.0,
            message='Knowledge provider is disabled by configuration',
            checked_at=datetime.now(timezone.utc).isoformat(),
        )
