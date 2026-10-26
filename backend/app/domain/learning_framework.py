"""Phase LF1: Learning Framework, Error Overlay, and Pedagogic Skill Mapping.

Provides:
- LearningFramework, LearningSkill, LearningObjective, LearningRelation entities.
- QuestionSkillBinding (multi-skill per question: primary, secondary, supporting).
- ErrorEvent & ErrorSkillBinding (Question Primary Skill != Actual Error Skill).
- Fixed Error Taxonomy & Provenance tracking.
- High-confidence error (confidence >= 0.8 and correct == 0) misconception detection.
- Deterministic, fully reproducible projections:
  - rebuild_error_overlay(db)
  - rebuild_learning_stage(db)
- Deterministic error lifecycle status resolution:
  - 'open' -> 'improving' -> 'resolved' -> 'recurred'.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any, Literal
from uuid import uuid4

from fastapi import HTTPException

from .attempt_verdict import correct_expr
from pydantic import BaseModel, ConfigDict, Field

from ..ai.schemas import StrictModel
from ..knowledge import get_knowledge_provider


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# Fixed Error Taxonomy & Types
# =============================================================================

FixedErrorType = Literal[
    'knowledge_gap',        # 知识盲区/未学习
    'concept_confusion',    # 概念混淆/易混点混淆
    'formula_selection',    # 公式选错/方法选择不当
    'calculation_error',    # 纯计算/数字粗心失误
    'condition_misread',    # 题干审题不清/看漏条件
    'reasoning_error',      # 逻辑推导断裂/充分必要倒置
    'option_trap',          # 掉入典型选项干扰陷阱
    'time_pressure',        # 答题耗时受限慌乱蒙题
    'careless_error',       # 非概念性粗心大意
    'uncertain_guess',      # 低置信度凭感觉猜测
    # Legacy compatibility
    'conceptual_error',
    'method_selection',
    'reading_error',
    'transfer_failure',
    'unknown',
]

ERROR_TAXONOMY_LABELS: dict[str, str] = {
    'knowledge_gap': '知识缺口',
    'concept_confusion': '概念混淆',
    'formula_selection': '公式/方法选择错误',
    'calculation_error': '计算失误',
    'condition_misread': '审题不清/漏看条件',
    'reasoning_error': '逻辑推导错误',
    'option_trap': '选项陷阱',
    'time_pressure': '时间压力',
    'careless_error': '粗心失误',
    'uncertain_guess': '不确定蒙猜',
    # Legacy fallbacks
    'conceptual_error': '概念理解',
    'method_selection': '方法选择',
    'reading_error': '审题偏差',
    'transfer_failure': '迁移困难',
    'unknown': '尚不确定',
}

SkillRole = Literal['primary', 'secondary', 'supporting']
ErrorSkillRole = Literal['primary', 'contributing', 'prerequisite_gap']
DiagnosisSource = Literal['deterministic', 'assessor', 'user_confirmed', 'imported']
ErrorStatus = Literal['open', 'improving', 'resolved', 'recurred']
LearningStageName = Literal['UNSEEN', 'INTRODUCED', 'GUIDED_PRACTICE', 'INDEPENDENT_PRACTICE', 'MASTERED', 'MAINTENANCE']


# =============================================================================
# Pydantic Schemas / DTOs
# =============================================================================

class LearningFrameworkDTO(StrictModel):
    id: str
    code: str
    name: str
    description: str | None = None
    version: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class LearningSkillDTO(StrictModel):
    id: str
    framework_id: str
    code: str
    parent_id: str | None = None
    knowledge_node_code: str | None = None
    name: str
    canonical_name: str
    skill_type: str = 'skill'
    description: str | None = None
    difficulty_band: str = 'medium'
    mastery_threshold: float = 0.8
    sort_order: int = 0
    status: str = 'active'
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class LearningSkillTreeItem(LearningSkillDTO):
    children: list[LearningSkillTreeItem] = Field(default_factory=list)


class LearningObjectiveDTO(StrictModel):
    id: str
    learning_skill_id: str
    code: str
    description: str
    objective_type: str = 'mastery'
    target_value: float = 0.8
    sort_order: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class LearningRelationDTO(StrictModel):
    id: str
    framework_id: str
    source_skill_id: str
    relation_type: str
    target_skill_id: str
    weight: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuestionSkillBindingDTO(StrictModel):
    id: str
    question_id: str
    learning_skill_id: str
    skill_name: str
    knowledge_node_code: str | None = None
    role: SkillRole
    weight: float = 1.0
    provenance: str = 'migrated'
    status: str = 'active'


class ErrorSkillBindingDTO(StrictModel):
    id: str
    error_event_id: str
    learning_skill_id: str
    skill_name: str
    knowledge_node_code: str | None = None
    role: ErrorSkillRole
    weight: float = 1.0
    provenance: str = 'deterministic'
    confidence: float = 1.0


class ErrorEventDTO(StrictModel):
    id: str
    attempt_id: str
    question_id: str
    error_type: str
    error_type_label: str
    error_subtype: str | None = None
    diagnosis_source: str
    diagnosis_confidence: float | None = None
    severity: float = 1.0
    status: ErrorStatus
    explanation: str = ''
    high_confidence_error: bool
    occurred_at: str
    resolved_at: str | None = None
    actual_error_skills: list[ErrorSkillBindingDTO] = Field(default_factory=list)


class QuestionLearningMapResponse(StrictModel):
    question_id: str
    stem: str
    module: str
    primary_skill: QuestionSkillBindingDTO | None = None
    secondary_skills: list[QuestionSkillBindingDTO] = Field(default_factory=list)
    supporting_skills: list[QuestionSkillBindingDTO] = Field(default_factory=list)
    knowledge_node_codes: list[str] = Field(default_factory=list)


class AttemptErrorLocationResponse(StrictModel):
    attempt_id: str
    question_id: str
    selected_answer: str | None = None
    correct_answer: str
    confidence: float | None = None
    high_confidence_error: bool
    question_primary_skill: QuestionSkillBindingDTO | None = None
    actual_error_skill: ErrorSkillBindingDTO | None = None
    error_type: str
    error_type_label: str
    error_subtype: str | None = None
    diagnosis_source: str
    status: ErrorStatus
    knowledge_node_code: str | None = None
    explanation: str = ''
    occurred_at: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)


class ErrorOverlayItem(StrictModel):
    learning_skill_id: str
    skill_name: str
    knowledge_node_code: str | None = None
    attempt_count: int
    wrong_count: int
    error_rate: float
    recent_error_count: int
    recurrence_count: int
    high_confidence_error_count: int
    dominant_error_type: str | None = None
    dominant_error_label: str | None = None
    open_error_count: int
    resolved_error_count: int
    last_error_at: str | None = None
    mastery_score: float = 0.5
    learning_stage: LearningStageName = 'UNSEEN'


class LearningStageItem(StrictModel):
    learning_skill_id: str
    skill_name: str
    stage: LearningStageName
    mastery_score: float
    attempt_count: int
    accuracy: float | None = None
    hint_dependency: float = 0.0
    review_count: int = 0
    last_updated_at: str


class SkillErrorsResponse(StrictModel):
    skill_id: str
    skill_name: str
    knowledge_node_code: str | None = None
    mastery_score: float
    learning_stage: LearningStageName
    error_overlay: ErrorOverlayItem
    error_events: list[ErrorEventDTO] = Field(default_factory=list)


class KnowledgeMapSummaryResponse(StrictModel):
    total_skills: int
    mastered_skills: int
    high_confidence_error_count: int
    skills: list[ErrorOverlayItem] = Field(default_factory=list)


# =============================================================================
# Domain Queries & Tree Assembly
# =============================================================================

def get_learning_framework(db, framework_id_or_code: str = 'gongkao-learning-v1') -> LearningFrameworkDTO:
    row = db.execute(
        'SELECT * FROM learning_frameworks WHERE id=? OR code=?',
        (framework_id_or_code, framework_id_or_code),
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"学习框架 '{framework_id_or_code}' 不存在")

    meta = json.loads(row['metadata_json']) if row['metadata_json'] else {}
    return LearningFrameworkDTO(
        id=row['id'],
        code=row['code'],
        name=row['name'],
        description=row['description'],
        version=row['version'],
        status=row['status'],
        metadata=meta,
        created_at=row['created_at'],
        updated_at=row['updated_at'],
    )


def get_learning_skill_tree(db, framework_id: str = 'gongkao-learning-v1') -> list[LearningSkillTreeItem]:
    """Fetch all skills in a framework and assemble into a nested tree."""
    rows = db.execute(
        '''SELECT * FROM learning_skills
           WHERE framework_id=?
           ORDER BY sort_order ASC, name ASC''',
        (framework_id,),
    ).fetchall()

    items_by_id: dict[str, LearningSkillTreeItem] = {}
    for r in rows:
        meta = json.loads(r['metadata_json']) if r['metadata_json'] else {}
        items_by_id[r['id']] = LearningSkillTreeItem(
            id=r['id'],
            framework_id=r['framework_id'],
            code=r['code'],
            parent_id=r['parent_id'],
            knowledge_node_code=r['knowledge_node_code'],
            name=r['name'],
            canonical_name=r['canonical_name'] or r['name'],
            skill_type=r['skill_type'],
            description=r['description'],
            difficulty_band=r['difficulty_band'],
            mastery_threshold=float(r['mastery_threshold']),
            sort_order=int(r['sort_order']),
            status=r['status'],
            metadata=meta,
            created_at=r['created_at'],
            updated_at=r['updated_at'],
            children=[],
        )

    roots: list[LearningSkillTreeItem] = []
    for r in rows:
        item = items_by_id[r['id']]
        if r['parent_id'] and r['parent_id'] in items_by_id:
            items_by_id[r['parent_id']].children.append(item)
        else:
            roots.append(item)

    return roots


def get_question_learning_map(db, question_id: str) -> QuestionLearningMapResponse:
    """Retrieve full pedagogical skill bindings for a given question."""
    q_row = db.execute('SELECT id, stem, module FROM questions WHERE id=?', (question_id,)).fetchone()
    if q_row is None:
        raise HTTPException(404, f"题目 '{question_id}' 不存在")

    bindings = db.execute(
        '''SELECT qsb.*, ls.name AS skill_name
           FROM question_skill_bindings qsb
           JOIN learning_skills ls ON ls.id = qsb.learning_skill_id
           WHERE qsb.question_id=?
           ORDER BY CASE qsb.role WHEN 'primary' THEN 1 WHEN 'secondary' THEN 2 ELSE 3 END, qsb.weight DESC''',
        (question_id,),
    ).fetchall()

    primary = None
    secondary: list[QuestionSkillBindingDTO] = []
    supporting: list[QuestionSkillBindingDTO] = []
    node_codes: list[str] = []

    for b in bindings:
        dto = QuestionSkillBindingDTO(
            id=b['id'],
            question_id=b['question_id'],
            learning_skill_id=b['learning_skill_id'],
            skill_name=b['skill_name'],
            knowledge_node_code=b['knowledge_node_code'],
            role=b['role'],
            weight=float(b['weight']),
            provenance=b['provenance'],
            status=b['status'],
        )
        if b['knowledge_node_code']:
            node_codes.append(b['knowledge_node_code'])

        if b['role'] == 'primary' and primary is None:
            primary = dto
        elif b['role'] == 'secondary':
            secondary.append(dto)
        else:
            supporting.append(dto)

    return QuestionLearningMapResponse(
        question_id=q_row['id'],
        stem=q_row['stem'],
        module=q_row['module'],
        primary_skill=primary,
        secondary_skills=secondary,
        supporting_skills=supporting,
        knowledge_node_codes=list(dict.fromkeys(node_codes)),
    )


# =============================================================================
# Error Resolution Lifecycle Engine
# =============================================================================

def determine_error_lifecycle_status(
    db,
    error_event_id: str,
    skill_id: str,
    occurred_at: str,
) -> tuple[ErrorStatus, str | None]:
    """Deterministically project error status: 'open' -> 'improving' -> 'resolved' -> 'recurred'.
    
    Policy Decision:
    - If any subsequent attempt with this actual error skill failed -> 'recurred'
    - If at least N=2 consecutive subsequent attempts on questions bound to this skill are correct
      with zero hint usage (hint_level == 0) and no recurring error -> 'resolved'
    - If 1 subsequent correct attempt -> 'improving'
    - Otherwise -> 'open'
    """
    # Check subsequent attempts linked to this skill
    cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
    valid_filter = "AND a.valid_for_stats = 1" if 'valid_for_stats' in cols else ""
    subsequent = db.execute(
        f'''SELECT a.id, {correct_expr(db)} AS correct, a.hint_level, a.submitted_at, ee.id AS subsequent_error_id
           FROM attempts a
           JOIN question_skill_bindings qsb ON qsb.question_id = a.question_id AND qsb.learning_skill_id = ?
           LEFT JOIN error_events ee ON ee.attempt_id = a.id
           WHERE a.submitted_at > ? {valid_filter}
           ORDER BY a.submitted_at ASC''',
        (skill_id, occurred_at),
    ).fetchall()

    if not subsequent:
        return 'open', None

    consecutive_independent_correct = 0
    last_correct_at = None

    for att in subsequent:
        if att['correct'] == 0:
            # Re-occurred
            return 'recurred', None
        if att['correct'] == 1 and (att['hint_level'] or 0) == 0:
            consecutive_independent_correct += 1
            last_correct_at = att['submitted_at']
        else:
            consecutive_independent_correct = 0

    if consecutive_independent_correct >= 2:
        return 'resolved', last_correct_at
    if consecutive_independent_correct >= 1:
        return 'improving', None

    return 'open', None


# =============================================================================
# Structured Error Event Recording
# =============================================================================

def record_error_event(
    db,
    *,
    attempt_id: str,
    error_type: str,
    error_subtype: str | None = None,
    actual_error_skill_id: str | None = None,
    diagnosis_source: str = 'user_confirmed',
    diagnosis_confidence: float = 1.0,
    explanation: str = '',
    severity: float = 1.0,
) -> ErrorEventDTO:
    """Record a validated ErrorEvent and bind Question Primary Skill != Actual Error Skill."""
    attempt = db.execute(
        '''SELECT a.*, q.id AS q_id, q.stem, q.answer
           FROM attempts a
           JOIN questions q ON q.id=a.question_id
           WHERE a.id=?''',
        (attempt_id,),
    ).fetchone()

    if attempt is None or attempt['submitted_at'] is None:
        raise HTTPException(404, '已提交的作答不存在')
    if attempt['correct']:
        raise HTTPException(409, '正确作答不记录错因')

    # Normalize error type
    canonical_error_type = error_type
    if error_type in ('conceptual_error', 'concept_confusion'):
        canonical_error_type = 'concept_confusion'
    elif error_type in ('method_selection', 'formula_selection'):
        canonical_error_type = 'formula_selection'
    elif error_type in ('reading_error', 'condition_misread'):
        canonical_error_type = 'condition_misread'

    now_iso = utc_now_iso()
    event_id = str(uuid4())

    # Re-use existing un-superseded event if duplicate payload
    latest = db.execute(
        'SELECT * FROM error_events WHERE attempt_id=? ORDER BY created_at DESC, id DESC LIMIT 1',
        (attempt_id,),
    ).fetchone()

    # Determine Actual Error Skill vs Question Primary Skill
    target_skill_id = actual_error_skill_id
    if target_skill_id is None:
        # Fall back to Question Primary Skill
        q_skill = db.execute(
            '''SELECT learning_skill_id, knowledge_node_code
               FROM question_skill_bindings
               WHERE question_id=? AND role='primary' LIMIT 1''',
            (attempt['question_id'],),
        ).fetchone()
        if q_skill:
            target_skill_id = q_skill['learning_skill_id']
        else:
            # Fallback to legacy question_knowledge_map
            qkm = db.execute(
                '''SELECT knowledge_node_id FROM question_knowledge_map WHERE question_id=? LIMIT 1''',
                (attempt['question_id'],),
            ).fetchone()
            if qkm:
                target_skill_id = qkm['knowledge_node_id']

    if target_skill_id is None:
        raise HTTPException(400, '无法确定题目或实际错误对应的学习技能')

    # Resolve skill metadata
    skill_row = db.execute('SELECT id, name, knowledge_node_code FROM learning_skills WHERE id=?', (target_skill_id,)).fetchone()
    if skill_row is None:
        raise HTTPException(404, f"指定的学习技能 '{target_skill_id}' 不存在")
    skill_name = skill_row['name']
    kn_code = skill_row['knowledge_node_code']

    db.execute(
        '''INSERT INTO error_events
           (id, attempt_id, question_id, error_type, error_subtype, diagnosis_source, diagnosis_confidence, severity, status, explanation, source, ai_confidence, occurred_at, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (
            event_id,
            attempt_id,
            attempt['question_id'],
            canonical_error_type,
            error_subtype,
            diagnosis_source,
            diagnosis_confidence,
            severity,
            'open',
            explanation.strip(),
            'USER' if diagnosis_source == 'user_confirmed' else 'ASSESSOR',
            diagnosis_confidence,
            now_iso,
            now_iso,
        ),
    )

    esb_id = f"esb_{event_id}_{target_skill_id}_primary"
    db.execute(
        '''INSERT OR IGNORE INTO error_skill_bindings
           (id, error_event_id, learning_skill_id, knowledge_node_code, role, weight, provenance, confidence, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        (esb_id, event_id, target_skill_id, kn_code, 'primary', 1.0, diagnosis_source, diagnosis_confidence, now_iso),
    )

    is_high_conf = bool(attempt['confidence'] is not None and float(attempt['confidence']) >= 0.8 and attempt['correct'] == 0)

    # Rebuild overlay projection for this skill
    rebuild_error_overlay(db, specific_skill_id=target_skill_id)

    return ErrorEventDTO(
        id=event_id,
        attempt_id=attempt_id,
        question_id=attempt['question_id'],
        error_type=canonical_error_type,
        error_type_label=ERROR_TAXONOMY_LABELS.get(canonical_error_type, canonical_error_type),
        error_subtype=error_subtype,
        diagnosis_source=diagnosis_source,
        diagnosis_confidence=diagnosis_confidence,
        severity=severity,
        status='open',
        explanation=explanation.strip(),
        high_confidence_error=is_high_conf,
        occurred_at=now_iso,
        actual_error_skills=[
            ErrorSkillBindingDTO(
                id=esb_id,
                error_event_id=event_id,
                learning_skill_id=target_skill_id,
                skill_name=skill_name,
                knowledge_node_code=kn_code,
                role='primary',
                weight=1.0,
                provenance=diagnosis_source,
                confidence=diagnosis_confidence,
            )
        ],
    )


# =============================================================================
# Attempt Error Location & Traceability
# =============================================================================

async def get_attempt_error_location(db, attempt_id: str) -> AttemptErrorLocationResponse:
    """Answer: What did the question test? What did the user actually get wrong? Which KnowledgeNode does it map to?"""
    att = db.execute(
        '''SELECT a.*, q.stem, q.answer, q.module
           FROM attempts a
           JOIN questions q ON q.id=a.question_id
           WHERE a.id=?''',
        (attempt_id,),
    ).fetchone()
    if att is None:
        raise HTTPException(404, f"作答记录 '{attempt_id}' 不存在")

    is_high_conf = bool(att['confidence'] is not None and float(att['confidence']) >= 0.8 and att['correct'] == 0)

    # Question Primary Skill
    q_map = get_question_learning_map(db, att['question_id'])
    primary_q_skill = q_map.primary_skill

    # Actual Error Skill from ErrorEvent
    ee = db.execute(
        '''SELECT * FROM error_events WHERE attempt_id=? ORDER BY created_at DESC, id DESC LIMIT 1''',
        (attempt_id,),
    ).fetchone()

    actual_err_skill: ErrorSkillBindingDTO | None = None
    error_type = 'unknown' if not att['correct'] else 'none'
    error_subtype = None
    diag_source = 'deterministic'
    err_status: ErrorStatus = 'open'
    kn_code = None
    explanation = ''
    occurred_at = att['submitted_at'] or att['started_at']

    if ee:
        error_type = ee['error_type']
        error_subtype = ee['error_subtype']
        diag_source = ee['diagnosis_source']
        err_status = ee['status']
        explanation = ee['explanation']
        occurred_at = ee['occurred_at']

        # Query error skill binding
        esb = db.execute(
            '''SELECT esb.*, ls.name AS skill_name
               FROM error_skill_bindings esb
               JOIN learning_skills ls ON ls.id=esb.learning_skill_id
               WHERE esb.error_event_id=? AND esb.role='primary' LIMIT 1''',
            (ee['id'],),
        ).fetchone()
        if esb:
            actual_err_skill = ErrorSkillBindingDTO(
                id=esb['id'],
                error_event_id=esb['error_event_id'],
                learning_skill_id=esb['learning_skill_id'],
                skill_name=esb['skill_name'],
                knowledge_node_code=esb['knowledge_node_code'],
                role=esb['role'],
                weight=float(esb['weight']),
                provenance=esb['provenance'],
                confidence=float(esb['confidence'] or 1.0),
            )
            kn_code = esb['knowledge_node_code']
    elif not att['correct'] and primary_q_skill:
        # Default projection if no explicit error event recorded yet
        kn_code = primary_q_skill.knowledge_node_code

    # Optional retrieval of Knowledge Hub Evidence for the actual error concept
    evidences_list: list[dict[str, Any]] = []
    target_node_code = kn_code or (primary_q_skill.knowledge_node_code if primary_q_skill else None)
    if target_node_code:
        provider = get_knowledge_provider()
        module_slug = {
            '资料分析': 'data-analysis',
            '判断推理': 'reasoning',
            '图形推理': 'reasoning',
            '立体图推': 'reasoning',
            '定义判断': 'reasoning',
            '类比推理': 'reasoning',
            '逻辑判断': 'reasoning',
            '言语理解': 'verbal',
            '数量关系': 'quantitative',
            '政治理论': 'general-knowledge',
        '常识判断': 'general-knowledge',
        }.get(att['module'], 'data-analysis')
        namespace = f"gongkao/xingce/{module_slug}"

        try:
            evs = await provider.retrieve(
                query=att['stem'][:100],
                namespace=namespace,
                limit=2,
                filters={'knowledge_node_code': target_node_code},
            )
            evidences_list = [
                {
                    'evidence_id': e.evidence_id,
                    'document_title': e.document_title,
                    'text': e.text,
                    'page': e.citation.page if e.citation else (e.source_locator.page if e.source_locator else None),
                    'citation': e.citation.label if e.citation else e.document_title,
                    'source_locator': str(e.source_locator) if e.source_locator else None,
                }
                for e in evs
            ]
        except Exception:
            evidences_list = []

    return AttemptErrorLocationResponse(
        attempt_id=att['id'],
        question_id=att['question_id'],
        selected_answer=att['selected_answer'],
        correct_answer=att['answer'],
        confidence=float(att['confidence']) if att['confidence'] is not None else None,
        high_confidence_error=is_high_conf,
        question_primary_skill=primary_q_skill,
        actual_error_skill=actual_err_skill,
        error_type=error_type,
        error_type_label=ERROR_TAXONOMY_LABELS.get(error_type, error_type),
        error_subtype=error_subtype,
        diagnosis_source=diag_source,
        status=err_status,
        knowledge_node_code=kn_code,
        explanation=explanation,
        occurred_at=occurred_at,
        evidence=evidences_list,
    )


# =============================================================================
# Deterministic Projections: rebuild_error_overlay & rebuild_learning_stage
# =============================================================================

def rebuild_error_overlay(db, specific_skill_id: str | None = None) -> None:
    """Fully recomputable projection rebuilding error_overlay purely from raw immutable facts."""
    now_iso = utc_now_iso()
    skills_stmt = 'SELECT id, name, knowledge_node_code FROM learning_skills'
    params = ()
    if specific_skill_id:
        skills_stmt += ' WHERE id=?'
        params = (specific_skill_id,)

    skills = db.execute(skills_stmt, params).fetchall()

    for s in skills:
        skill_id = s['id']
        kn_code = s['knowledge_node_code']

        # Total attempts for questions bound to this skill (formal stats only)
        cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
        valid_filter = "AND a.valid_for_stats = 1" if 'valid_for_stats' in cols else ""
        att_row = db.execute(
            f'''SELECT COUNT(a.id) AS total_attempts
               FROM attempts a
               JOIN question_skill_bindings qsb ON qsb.question_id = a.question_id AND qsb.learning_skill_id = ?
               WHERE a.submitted_at IS NOT NULL {valid_filter}''',
            (skill_id,),
        ).fetchone()
        attempt_count = att_row['total_attempts'] if att_row else 0

        # Error events for this actual error skill
        errors = db.execute(
            '''SELECT ee.*, a.confidence
               FROM error_events ee
               JOIN error_skill_bindings esb ON esb.error_event_id = ee.id
               JOIN attempts a ON a.id = ee.attempt_id
               WHERE esb.learning_skill_id = ?
               ORDER BY ee.occurred_at DESC''',
            (skill_id,),
        ).fetchall()

        wrong_count = len(errors)
        error_rate = (wrong_count / attempt_count) if attempt_count > 0 else 0.0

        # High confidence errors (confidence >= 0.8)
        high_conf_errors = sum(1 for e in errors if e['confidence'] is not None and float(e['confidence']) >= 0.8)

        # Recent errors (in the latest 5 attempts)
        recent_err_count = sum(1 for e in errors[:5])

        # Recurrence count (skills appearing in >= 2 error events)
        recurrence_count = max(0, wrong_count - 1) if wrong_count >= 2 else 0

        # Dominant error type (most frequent)
        dominant_type = None
        if errors:
            type_counts: dict[str, int] = {}
            for e in errors:
                t = e['error_type']
                type_counts[t] = type_counts.get(t, 0) + 1
            dominant_type = max(type_counts.keys(), key=lambda k: type_counts[k])

        # Open and resolved counts
        open_count = sum(1 for e in errors if e['status'] in ('open', 'recurred', 'improving'))
        resolved_count = sum(1 for e in errors if e['status'] == 'resolved')

        last_error_at = errors[0]['occurred_at'] if errors else None

        db.execute(
            '''INSERT INTO error_overlay (
                 learning_skill_id, knowledge_node_code, attempt_count, wrong_count,
                 error_rate, recent_error_count, recurrence_count, high_confidence_error_count,
                 dominant_error_type, open_error_count, resolved_error_count, last_error_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(learning_skill_id) DO UPDATE SET
                 knowledge_node_code=excluded.knowledge_node_code,
                 attempt_count=excluded.attempt_count,
                 wrong_count=excluded.wrong_count,
                 error_rate=excluded.error_rate,
                 recent_error_count=excluded.recent_error_count,
                 recurrence_count=excluded.recurrence_count,
                 high_confidence_error_count=excluded.high_confidence_error_count,
                 dominant_error_type=excluded.dominant_error_type,
                 open_error_count=excluded.open_error_count,
                 resolved_error_count=excluded.resolved_error_count,
                 last_error_at=excluded.last_error_at,
                 updated_at=excluded.updated_at''',
            (
                skill_id,
                kn_code,
                attempt_count,
                wrong_count,
                round(error_rate, 4),
                recent_err_count,
                recurrence_count,
                high_conf_errors,
                dominant_type,
                open_count,
                resolved_count,
                last_error_at,
                now_iso,
            ),
        )


def rebuild_learning_stage(db, specific_skill_id: str | None = None) -> None:
    """Deterministically project learning_stages from mastery, attempt count, hints, and FSRS reviews."""
    now_iso = utc_now_iso()
    skills_stmt = 'SELECT id, name FROM learning_skills'
    params = ()
    if specific_skill_id:
        skills_stmt += ' WHERE id=?'
        params = (specific_skill_id,)

    skills = db.execute(skills_stmt, params).fetchall()

    for s in skills:
        skill_id = s['id']

        # Get mastery state
        ms = db.execute('SELECT * FROM mastery_state WHERE knowledge_node_id=?', (skill_id,)).fetchone()
        mastery_score = float(ms['mastery_score']) if ms else 0.5
        attempt_count = int(ms['attempt_count']) if ms else 0
        hint_dependency = float(ms['hint_dependency']) if ms else 0.0
        recent_acc = float(ms['recent_accuracy']) if ms and ms['recent_accuracy'] is not None else None

        # Check review card state
        rc = db.execute(
            '''SELECT SUM(review_count) AS total_reviews, AVG(stability) AS avg_stability
               FROM review_cards rc
               JOIN question_skill_bindings qsb ON qsb.question_id = rc.question_id
               WHERE qsb.learning_skill_id=?''',
            (skill_id,),
        ).fetchone()
        total_reviews = rc['total_reviews'] or 0
        stability = rc['avg_stability'] or 0.0

        # Deterministic stage projection policy
        if attempt_count == 0:
            stage = 'UNSEEN'
        elif attempt_count <= 2:
            stage = 'INTRODUCED'
        elif mastery_score >= 0.85 and (total_reviews >= 2 or stability >= 7.0):
            stage = 'MAINTENANCE'
        elif mastery_score >= 0.80 and hint_dependency <= 0.15:
            stage = 'MASTERED'
        elif hint_dependency <= 0.35 and (recent_acc is None or recent_acc >= 0.60):
            stage = 'INDEPENDENT_PRACTICE'
        else:
            stage = 'GUIDED_PRACTICE'

        db.execute(
            '''INSERT INTO learning_stages (
                 learning_skill_id, stage, mastery_score, attempt_count, accuracy,
                 hint_dependency, review_count, last_updated_at
               ) VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(learning_skill_id) DO UPDATE SET
                 stage=excluded.stage,
                 mastery_score=excluded.mastery_score,
                 attempt_count=excluded.attempt_count,
                 accuracy=excluded.accuracy,
                 hint_dependency=excluded.hint_dependency,
                 review_count=excluded.review_count,
                 last_updated_at=excluded.last_updated_at''',
            (
                skill_id,
                stage,
                round(mastery_score, 4),
                attempt_count,
                recent_acc,
                round(hint_dependency, 4),
                total_reviews,
                now_iso,
            ),
        )


def get_knowledge_map_summary(db) -> KnowledgeMapSummaryResponse:
    """Aggregate full curriculum knowledge map blending Mastery + Error Overlay + LearningStage."""
    rebuild_error_overlay(db)
    rebuild_learning_stage(db)

    rows = db.execute(
        '''SELECT ls.id AS learning_skill_id, ls.name AS skill_name, ls.knowledge_node_code,
                  eo.attempt_count, eo.wrong_count, eo.error_rate, eo.recent_error_count,
                  eo.recurrence_count, eo.high_confidence_error_count, eo.dominant_error_type,
                  eo.open_error_count, eo.resolved_error_count, eo.last_error_at,
                  COALESCE(ms.mastery_score, 0.5) AS mastery_score,
                  COALESCE(st.stage, 'UNSEEN') AS learning_stage
           FROM learning_skills ls
           LEFT JOIN error_overlay eo ON eo.learning_skill_id = ls.id
           LEFT JOIN mastery_state ms ON ms.knowledge_node_id = ls.id
           LEFT JOIN learning_stages st ON st.learning_skill_id = ls.id
           ORDER BY ls.sort_order ASC, ls.name ASC'''
    ).fetchall()

    items: list[ErrorOverlayItem] = []
    mastered_count = 0
    total_high_conf_errors = 0

    for r in rows:
        m_score = float(r['mastery_score'])
        stage = r['learning_stage']
        high_conf = int(r['high_confidence_error_count'] or 0)
        total_high_conf_errors += high_conf

        if stage in ('MASTERED', 'MAINTENANCE') or m_score >= 0.8:
            mastered_count += 1

        dom_type = r['dominant_error_type']
        items.append(
            ErrorOverlayItem(
                learning_skill_id=r['learning_skill_id'],
                skill_name=r['skill_name'],
                knowledge_node_code=r['knowledge_node_code'],
                attempt_count=int(r['attempt_count'] or 0),
                wrong_count=int(r['wrong_count'] or 0),
                error_rate=float(r['error_rate'] or 0.0),
                recent_error_count=int(r['recent_error_count'] or 0),
                recurrence_count=int(r['recurrence_count'] or 0),
                high_confidence_error_count=high_conf,
                dominant_error_type=dom_type,
                dominant_error_label=ERROR_TAXONOMY_LABELS.get(dom_type) if dom_type else None,
                open_error_count=int(r['open_error_count'] or 0),
                resolved_error_count=int(r['resolved_error_count'] or 0),
                last_error_at=r['last_error_at'],
                mastery_score=round(m_score, 4),
                learning_stage=stage,
            )
        )

    return KnowledgeMapSummaryResponse(
        total_skills=len(items),
        mastered_skills=mastered_count,
        high_confidence_error_count=total_high_conf_errors,
        skills=items,
    )
