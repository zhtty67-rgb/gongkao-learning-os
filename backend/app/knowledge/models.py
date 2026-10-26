"""Typed domain DTOs and exceptions for KnowledgeProvider."""
from datetime import datetime, timezone
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class KnowledgeEvidence(StrictModel):
    """Normalized evidence item consumed by Learning OS."""
    evidence_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_version_id: str | None = None
    chunk_id: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    text: str = Field(min_length=1)
    score: float = Field(ge=0.0, le=1.0)
    page: int | None = None
    source_locator: str | None = None
    source_reference: str | None = None
    citation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceDocument(StrictModel):
    """Full or section source document reference."""
    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    version_id: str | None = None
    content_type: str = 'text/plain'
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentContext(StrictModel):
    """Surrounding context snippet for citation/highlighting."""
    document_id: str = Field(min_length=1)
    locator: str | None = None
    surrounding_text: str = Field(min_length=1)
    headings: list[str] = Field(default_factory=list)
    page: int | None = None


class ProviderHealth(StrictModel):
    """Health check outcome for knowledge provider."""
    status: Literal['healthy', 'degraded', 'unavailable']
    provider: str = Field(min_length=1)
    latency_ms: float | None = None
    message: str | None = None
    checked_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class KnowledgeProviderError(Exception):
    """Base error for knowledge provider failures."""
    pass


class UpstreamTimeoutError(KnowledgeProviderError):
    """Upstream service timed out."""
    pass


class UpstreamAuthError(KnowledgeProviderError):
    """Authentication or authorization failure with Knowledge Hub."""
    pass


class UpstreamUnavailableError(KnowledgeProviderError):
    """Upstream Knowledge Hub is unreachable or returned 5xx."""
    pass


class MalformedResponseError(KnowledgeProviderError):
    """Upstream returned an invalid response structure."""
    pass
