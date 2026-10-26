"""Knowledge integration package for Learning OS."""
from .disabled import DisabledProvider
from .evidence_filter import (
    audit_retrieval_quality,
    evaluate_evidence_adoption,
    filter_candidate_evidences,
    format_evidence_prompt_block,
    is_content_adequate,
    is_topically_relevant,
    validate_and_adopt_citation,
    verify_evidence_support,
    EvidenceResolutionResult,
)
from .factory import get_knowledge_provider
from .fixture import FixtureProvider
from .knowledge_hub import KnowledgeHubProvider
from .models import (
    DocumentContext,
    KnowledgeEvidence,
    KnowledgeProviderError,
    MalformedResponseError,
    ProviderHealth,
    SourceDocument,
    UpstreamAuthError,
    UpstreamTimeoutError,
    UpstreamUnavailableError,
)
from .provider import KnowledgeProvider

__all__ = [
    'KnowledgeProvider',
    'KnowledgeEvidence',
    'SourceDocument',
    'DocumentContext',
    'ProviderHealth',
    'KnowledgeProviderError',
    'UpstreamTimeoutError',
    'UpstreamAuthError',
    'UpstreamUnavailableError',
    'MalformedResponseError',
    'DisabledProvider',
    'FixtureProvider',
    'KnowledgeHubProvider',
    'get_knowledge_provider',
    'filter_candidate_evidences',
    'validate_and_adopt_citation',
    'format_evidence_prompt_block',
    'is_content_adequate',
    'is_topically_relevant',
    'audit_retrieval_quality',
    'verify_evidence_support',
    'evaluate_evidence_adoption',
    'EvidenceResolutionResult',
]
