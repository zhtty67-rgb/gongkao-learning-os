"""Data models and schemas for Question Bank Importer (QI1)."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from ...ai.schemas import StrictModel


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Knowledge Hub Contract Compatibility Types
# =============================================================================

class BoundingBox(BaseModel):
    model_config = ConfigDict(frozen=True)

    page: int = Field(ge=1)
    x0: float = Field(ge=0, le=1)
    y0: float = Field(ge=0, le=1)
    x1: float = Field(ge=0, le=1)
    y1: float = Field(ge=0, le=1)
    coordinate_system: Literal["normalized_top_left"] = "normalized_top_left"


class ParsedBlock(BaseModel):
    model_config = ConfigDict(frozen=True)

    block_id: str
    block_type: str  # heading, paragraph, table, picture, list_item, etc.
    text: str
    page: int | None = Field(default=None, ge=1)
    bounding_box: BoundingBox | None = Field(default=None, validation_alias=AliasChoices('bounding_box', 'bbox'))
    reading_order: int = 0
    asset_refs: list[str] = Field(default_factory=list)
    heading_path: list[str] = Field(default_factory=list)
    asset_reference: str | None = None
    parser_reference: str | None = None


class ParsedDocument(BaseModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    document_version_id: str
    document_id: str | None = None
    parser: str = "docling"
    parser_version: str = "1.0.0"
    parsed_at: str | None = None
    markdown: str = ""
    pages: list[int] = Field(default_factory=list)
    blocks: list[ParsedBlock] = Field(default_factory=list)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    raw_parser_artifact: dict[str, Any] | None = None

    @model_validator(mode='before')
    @classmethod
    def adapt_qp1_response(cls, value):
        if not isinstance(value, dict) or 'page_count' not in value:
            return value
        data = dict(value)
        data['parser'] = data.get('parser_name', data.get('parser', 'docling'))
        data['pages'] = list(range(1, data['page_count'] + 1))
        data['assets'] = data.get('assets', [])
        urls = {a['asset_id']: a['download_url'] for a in data.get('assets', [])}
        blocks = []
        for raw in data.get('blocks', []):
            block = dict(raw)
            refs = [urls.get(ref, ref) for ref in block.get('asset_refs', [])]
            block['asset_refs'] = refs
            if refs:
                block['asset_reference'] = refs[0]
            blocks.append(block)
        data['blocks'] = sorted(blocks, key=lambda b: b.get('reading_order', 0))
        return data


# =============================================================================
# Enums for Jobs, Stages, Review, and Provenance
# =============================================================================

class JobStatus(str, Enum):
    QUEUED = 'queued'
    EXTRACTING = 'extracting'
    MATCHING_ANSWERS = 'matching_answers'
    CLASSIFYING = 'classifying'
    VALIDATING = 'validating'
    NEEDS_REVIEW = 'needs_review'
    READY_TO_PUBLISH = 'ready_to_publish'
    PUBLISHING = 'publishing'
    COMPLETED = 'completed'
    FAILED = 'failed'


class ValidationStatus(str, Enum):
    PENDING = 'PENDING'
    AUTO_ACCEPTED = 'AUTO_ACCEPTED'
    ACCEPTED_WITH_AUDIT = 'ACCEPTED_WITH_AUDIT'
    NEEDS_REVIEW = 'NEEDS_REVIEW'
    READY_TO_PUBLISH = 'READY_TO_PUBLISH'
    PUBLISHED = 'PUBLISHED'
    REJECTED = 'REJECTED'


ReviewStatus = ValidationStatus


class ReviewReason(str, Enum):
    QUESTION_BOUNDARY_AMBIGUOUS = 'QUESTION_BOUNDARY_AMBIGUOUS'
    OPTION_PARSE_FAILED = 'OPTION_PARSE_FAILED'
    ANSWER_MISSING = 'ANSWER_MISSING'
    ANSWER_CONFLICT = 'ANSWER_CONFLICT'
    EXPLANATION_MISMATCH = 'EXPLANATION_MISMATCH'
    KNOWLEDGE_LOW_CONFIDENCE = 'KNOWLEDGE_LOW_CONFIDENCE'
    SKILL_UNMAPPED = 'SKILL_UNMAPPED'
    SKILL_LOW_CONFIDENCE = 'SKILL_LOW_CONFIDENCE'
    IMAGE_MISSING = 'IMAGE_MISSING'
    MULTIPLE_PRIMARY_CANDIDATES = 'MULTIPLE_PRIMARY_CANDIDATES'


# =============================================================================
# Intermediate Extraction Objects
# =============================================================================

class ExtractedPassage(StrictModel):
    id: str
    source_document_id: str
    source_document_version_id: str | None = None
    source_page_start: int | None = None
    source_page_end: int | None = None
    source_locator: str | None = None
    question_range_start: int | None = None
    question_range_end: int | None = None
    content: str
    assets: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedQuestion(StrictModel):
    question_number: int
    raw_question_number_str: str
    passage_id: str | None = None
    passage_text: str | None = None
    subject: str = '行测'
    module: str = '资料分析'
    module_source: str = 'heading_rule'
    stem: str
    stem_assets: list[str] = Field(default_factory=list)
    options: dict[str, str] = Field(default_factory=dict)  # e.g. {"A": "10%", "B": "20%"}
    option_assets: dict[str, list[str]] = Field(default_factory=dict)  # e.g. {"A": ["asset_1"]}
    inline_answer: str | None = None
    inline_explanation: str | None = None
    source_document_id: str
    source_document_version_id: str | None = None
    source_page: int | None = None
    source_page_end: int | None = None
    source_block_ids: list[str] = Field(default_factory=list)
    source_locator: str | None = None
    bounding_box: BoundingBox | None = None
    content_fingerprint: str = ''
    review_reasons: list[ReviewReason] = Field(default_factory=list)


class ExtractedAnswerKeyItem(StrictModel):
    question_number: int
    answer: str  # 'A', 'B', 'C', 'D'
    source_page: int | None = None
    source_block_id: str | None = None


class ExtractedExplanationItem(StrictModel):
    question_number: int
    explanation: str
    extracted_answer: str | None = None
    source_page: int | None = None
    source_block_id: str | None = None


# =============================================================================
# AI Classification & Routing Schemas
# =============================================================================

class KnowledgeCandidate(StrictModel):
    id: str
    code: str
    name: str
    module: str
    canonical_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    relevance_score: float = 0.0


class SkillCandidate(StrictModel):
    id: str
    code: str
    name: str
    knowledge_node_code: str | None = None
    description: str | None = None
    difficulty_band: str = 'medium'


class KnowledgeClassificationOutput(StrictModel):
    primary_knowledge_node_code: str
    secondary_knowledge_node_codes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ''


class SkillClassificationOutput(StrictModel):
    primary_skill_code: str
    secondary_skill_codes: list[str] = Field(default_factory=list)
    supporting_skill_codes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ''


class AnswerExplanationAuditOutput(StrictModel):
    answer_matches_explanation: bool
    explanation_supported_answer: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ''


class ClassificationProvenance(StrictModel):
    classification_source: str  # 'heading_rule', 'alias_rule', 'model_fast', 'model_strong', 'human_confirmed', 'unmapped'
    classifier_type: str  # 'deterministic_heading', 'deterministic_alias', 'llm_fast', 'llm_strong', 'human'
    model_provider: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    prompt_version: str | None = None
    candidate_set: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    created_at: str = Field(default_factory=utc_now_iso)


# =============================================================================
# Draft Question & Import Job DTOs
# =============================================================================

class SkillBindingItem(StrictModel):
    learning_skill_id: str
    skill_code: str
    skill_name: str
    knowledge_node_code: str | None = None
    role: Literal['primary', 'secondary', 'supporting'] = 'primary'
    weight: float = 1.0


class DraftQuestionDTO(StrictModel):
    id: str
    job_id: str
    question_number: int
    raw_question_number_str: str | None = None
    passage_id: str | None = None
    passage_text: str | None = None
    subject: str = '行测'
    module: str = '资料分析'
    module_source: str = 'heading_rule'
    stem: str
    stem_assets: list[str] = Field(default_factory=list)
    options: dict[str, str] = Field(default_factory=dict)
    option_assets: dict[str, list[str]] = Field(default_factory=dict)
    answer: str | None = None
    answer_source: str | None = None
    answer_matched: int = 0
    explanation: str = ''
    explanation_source: str | None = None
    knowledge_node_id: str | None = None
    knowledge_node_code: str | None = None
    knowledge_confidence: float = 0.0
    knowledge_candidates: list[str] = Field(default_factory=list)
    skill_id: str | None = None
    skill_code: str | None = None
    skill_confidence: float = 0.0
    skill_candidates: list[str] = Field(default_factory=list)
    skill_bindings: list[SkillBindingItem] = Field(default_factory=list)
    classification_provenance: ClassificationProvenance | None = None
    validation_status: ValidationStatus = ValidationStatus.PENDING
    review_reasons: list[str] = Field(default_factory=list)
    source_document_id: str
    source_document_version_id: str | None = None
    source_page: int | None = None
    source_page_end: int | None = None
    source_block_ids: list[str] = Field(default_factory=list)
    source_locator: str | None = None
    content_fingerprint: str
    published_question_id: str | None = None
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    review_comment: str | None = None
    created_at: str
    updated_at: str


class QuestionImportBatch(StrictModel):
    question_document_id: str
    question_document_version_id: str | None = None
    answer_document_id: str | None = None
    answer_document_version_id: str | None = None
    filename: str = ''
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImportJobDTO(StrictModel):
    id: str
    source_document_id: str
    source_document_version_id: str | None = None
    filename: str = ''
    status: JobStatus = JobStatus.QUEUED
    stage: str = 'queued'
    total_candidates: int = 0
    parsed_questions: int = 0
    validated_questions: int = 0
    needs_review: int = 0
    published_questions: int = 0
    failed_questions: int = 0
    auto_accepted_count: int = 0
    review_reasons_summary: dict[str, int] = Field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class ReviewItemDTO(StrictModel):
    draft_id: str
    job_id: str
    question_number: int
    stem: str
    stem_assets: list[str] = Field(default_factory=list)
    options: dict[str, str] = Field(default_factory=dict)
    option_assets: dict[str, list[str]] = Field(default_factory=dict)
    passage_text: str | None = None
    answer: str | None = None
    answer_source: str | None = None
    answer_matched: int = 0
    explanation: str = ''
    module: str
    suggested_knowledge_node_code: str | None = None
    suggested_skill_code: str | None = None
    confidence: float = 0.0
    review_reasons: list[str] = Field(default_factory=list)
    source_page: int | None = None
    source_locator: str | None = None
    validation_status: ValidationStatus


class ReviewDecisionInput(StrictModel):
    action: Literal['accept', 'modify', 'reject']
    answer: str | None = None
    explanation: str | None = None
    knowledge_node_code: str | None = None
    skill_code: str | None = None
    module: str | None = None
    comment: str | None = None


class BatchPublishInput(StrictModel):
    job_id: str
    draft_ids: list[str] | None = None  # None means publish all READY/ACCEPTED drafts in job


class PublishResultDTO(StrictModel):
    job_id: str
    total_drafts: int
    published_count: int
    skipped_count: int
    failed_count: int
    published_question_ids: list[str] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)


class ReclassifyInput(StrictModel):
    job_id: str
    draft_ids: list[str] | None = None
    scope: Literal['unmapped', 'low_confidence', 'all_drafts'] = 'low_confidence'
    confidence_threshold: float = 0.70
    force_model_policy: Literal['FAST', 'STRONG'] | None = None


class ReclassifyResultDTO(StrictModel):
    job_id: str
    reclassified_count: int
    auto_accepted_count: int
    still_needs_review_count: int
