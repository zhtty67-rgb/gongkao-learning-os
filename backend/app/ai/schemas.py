"""Schemas and type definitions for AI Gateway."""
from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field, model_validator

T = TypeVar('T')

ModelPolicy = Literal['FAST', 'BALANCED', 'STRONG']
TaskType = Literal[
    'tutor_hint',
    'error_diagnosis',
    'tutor_explanation',
    'tutor_followup',
    'shenlun_assessment',
    'question_generation',
    'weekly_analysis',
    'rag_answer',
    'question_classification',
    'skill_classification',
    'answer_explanation_audit',
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Message(StrictModel):
    role: Literal['system', 'user', 'assistant']
    content: str = Field(min_length=1)
    images: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode='after')
    def image_role(self):
        if self.images and self.role != 'user':
            raise ValueError('Images must be attached to a user message')
        return self


class ModelPolicyConfig(StrictModel):
    provider: str = Field(default='mock')  # 'mock' | 'openai_compatible'
    model: str = Field(default='default-model')
    base_url: str | None = None
    api_key: str | None = None
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1)
    timeout_seconds: float = Field(default=10.0, ge=0.1)
    supports_vision: bool = False


class GatewayConfig(StrictModel):
    policies: dict[ModelPolicy, ModelPolicyConfig] = Field(default_factory=dict)
    task_policy_map: dict[TaskType, ModelPolicy] = Field(default_factory=dict)
    fallback: ModelPolicyConfig | None = None


class GenerationResult(StrictModel, Generic[T]):
    data: T
    raw_text: str
    policy_used: ModelPolicy
    model_name: str
    provider_name: str
    tokens_used: dict[str, int] = Field(default_factory=dict)

    @property
    def text(self) -> str:
        """Convenience property returning the raw model generated text."""
        return self.raw_text


class GatewayError(Exception):
    """Base error for AI Gateway."""
    pass


class PolicyNotConfiguredError(GatewayError):
    """Requested model policy has no provider configuration."""
    pass


class SchemaValidationError(GatewayError):
    """Model output failed schema validation."""
    pass


class ProviderUnavailableError(GatewayError):
    """Upstream model provider failed or timed out."""
    pass


class TruncatedGenerationError(ProviderUnavailableError):
    """Model output was truncated due to token budget limit (finish_reason='length')."""

    def __init__(self, message: str = '', partial_text: str = ''):
        super().__init__(message)
        self.partial_text = partial_text
