from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class KnowledgeNode(StrictModel):
    id: str = Field(min_length=1)
    parent_id: str | None = None
    subject: str = '行测'
    module: str = Field(min_length=1)
    name: str = Field(min_length=1)
    node_type: str = 'skill'
    weight: float = Field(default=1, gt=0)
    exam_priority: float = Field(default=1, ge=0)


class Mapping(StrictModel):
    knowledge_node_id: str
    weight: float = Field(default=1, gt=0)


class Question(StrictModel):
    id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    year: int | None = None
    exam_type: str = '演示'
    subject: Literal['行测'] = '行测'
    module: str = Field(min_length=1)
    stem: str = Field(min_length=1)
    options: dict[str, str]
    difficulty: float = Field(default=0.5, ge=0, le=1)
    answer: Literal['A', 'B', 'C', 'D']
    explanation: str = Field(min_length=1)
    estimated_seconds: int = Field(default=60, gt=0)
    is_verified: bool = True  # 手工 JSON 导入为运维权威路径，入池即可选题
    knowledge: list[Mapping] = Field(min_length=1)

    @model_validator(mode='after')
    def valid_options(self):
        if set(self.options) != set('ABCD') or any(not s.strip() for s in self.options.values()):
            raise ValueError('选项必须恰好包含非空的 A/B/C/D')
        ids = [m.knowledge_node_id for m in self.knowledge]
        if len(ids) != len(set(ids)):
            raise ValueError('知识点映射重复')
        return self


class QuestionBank(StrictModel):
    knowledge_nodes: list[KnowledgeNode]
    questions: list[Question] = Field(min_length=1)


# 三档信心（新）映射值 + 历史五档值。历史记录原值保留、原样可读，新提交使用三档值。
CONFIDENCE_VALUES = (0.2, 0.4, 0.5, 0.6, 0.8, 0.9, 1.0)


class Answer(StrictModel):
    attempt_id: str
    selected_answer: str | None = None
    confidence: float | None = None
    changed_answer: bool = False
    paused_ms: int = Field(default=0, ge=0)

    @model_validator(mode='after')
    def normalize_submission(self):
        # 允许不选任何答案直接提交（未作答/不会）；仅接受空或 A-D，绝不伪造选项。
        if self.selected_answer is not None:
            sel = self.selected_answer.strip().upper()
            if not sel:
                self.selected_answer = None
            elif sel not in ('A', 'B', 'C', 'D'):
                raise ValueError('答案必须为 A/B/C/D，或留空表示未作答')
        if self.confidence is not None and self.confidence not in CONFIDENCE_VALUES:
            raise ValueError('信心值无效：三档为 0.2/0.5/0.9（历史五档仍可读）')
        return self


class AdaptiveSessionInput(StrictModel):
    limit: int = Field(default=10, ge=1, le=25)


class StartExamInput(StrictModel):
    time_limit_seconds: int = Field(default=7200, ge=60)
    question_count: int | None = Field(default=None, ge=1, le=100)


class ShenlunSessionInput(StrictModel):
    material_id: str | None = None
    daily: bool = False
    next_task: bool = False


class ShenlunDraftInput(StrictModel):
    session_id: str = Field(min_length=1)
    draft_text: str = Field(default='')
    notes: dict[str, str] | None = None


class ShenlunSubmitInput(StrictModel):
    session_id: str = Field(min_length=1)
    final_answer: str = Field(min_length=1)


class DailyPlanInput(StrictModel):
    total_items: int = Field(default=10, ge=1, le=50)


class QuestionSkillBindInput(StrictModel):
    skill_id: str = Field(min_length=1)
    role: Literal['primary', 'secondary', 'supporting'] = 'primary'
    weight: float = Field(default=1.0, gt=0)


class StructuredErrorInput(StrictModel):
    error_type: str = Field(min_length=1)
    error_subtype: str | None = None
    actual_error_skill_id: str | None = None
    diagnosis_source: Literal['deterministic', 'assessor', 'user_confirmed', 'imported'] = 'user_confirmed'
    diagnosis_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    explanation: str = Field(default='')


class HintRequest(StrictModel):
    attempt_id: str = Field(min_length=1)
    requested_level: int = Field(ge=1, le=4)


class KnowledgeRetrieveInput(StrictModel):
    query: str = Field(min_length=1)
    namespace: str = Field(min_length=1)
    filters: dict[str, str | int | float | bool] | None = None
    limit: int = Field(default=5, ge=1, le=20)


class ErrorEventInput(StrictModel):
    error_type: Literal[
        'knowledge_gap', 'conceptual_error', 'method_selection', 'reading_error',
        'calculation_error', 'time_pressure', 'careless_error', 'transfer_failure', 'unknown',
    ]
    explanation: str = Field(default='', max_length=500)


class InteractiveDiagnosisFeedbackInput(StrictModel):
    feedback_type: Literal['CONFIRMED', 'CORRECTED', 'SKIPPED']
    selected_hypothesis_id: str | None = None
    user_text: str | None = None


class InteractiveReviewChatInput(StrictModel):
    message: str = Field(min_length=1)
    client_request_id: str | None = None


class SetReviewCauseInput(StrictModel):
    error_type: str = Field(min_length=1)
    explanation: str = Field(default='', max_length=500)
    stage_code: str | None = None
    knowledge_node_id: str | None = None
    supplementary_cause: str | None = None


class UpdateReviewPreferenceInput(StrictModel):
    preference_mode: Literal['AUTO_ASK', 'MANUAL', 'EXPLANATION_ONLY']




class CreateImportJobInput(StrictModel):
    source_document_id: str = Field(min_length=1)
    source_document_version_id: str | None = None
    answer_document_id: str | None = None
    answer_document_version_id: str | None = None
    filename: str = Field(default='')
    metadata: dict[str, Any] = Field(default_factory=dict)


class ProcessImportJobInput(StrictModel):
    parsed_document: dict[str, Any] | None = None
    answer_parsed_document: dict[str, Any] | None = None

