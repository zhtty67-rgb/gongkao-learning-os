"""Protocol contract for KnowledgeProvider in Learning OS."""
from typing import Any, Protocol, runtime_checkable

from .models import (
    DocumentContext,
    KnowledgeEvidence,
    ProviderHealth,
    SourceDocument,
)


@runtime_checkable
class KnowledgeProvider(Protocol):
    """Abstract protocol for retrieving domain knowledge and document contexts.
    
    Learning OS interacts only with this contract. It never accesses Knowledge Hub
    storage, vector DBs (Qdrant), parsers (MinerU/Docling), or RAG frameworks directly.
    """

    provider_name: str

    async def retrieve(
        self,
        query: str,
        namespace: str,
        filters: dict[str, Any] | None = None,
        limit: int = 5,
    ) -> list[KnowledgeEvidence]:
        """Retrieve relevant knowledge evidence chunks matching the query and namespace."""
        ...

    async def get_source(
        self,
        document_id: str,
        locator: str | None = None,
    ) -> SourceDocument | None:
        """Fetch the full or excerpted source document."""
        ...

    async def get_document_context(
        self,
        document_id: str,
        locator: str | None = None,
    ) -> DocumentContext | None:
        """Fetch surrounding context snippet around a citation locator."""
        ...

    async def health_check(self) -> ProviderHealth:
        """Check upstream health and connectivity."""
        ...
