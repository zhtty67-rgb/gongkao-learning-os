"""Domain service for objective assessment and AI error diagnosis (Assessor)."""
import json
from typing import Literal
from fastapi import HTTPException
from pydantic import Field

from ..ai import Message, get_model_gateway
from ..ai.schemas import StrictModel
from ..domain.analytics import ERROR_LABELS
from ..knowledge import (
    evaluate_evidence_adoption,
    filter_candidate_evidences,
    format_evidence_prompt_block,
    get_knowledge_provider,
    validate_and_adopt_citation,
)

ErrorType = Literal[
    'knowledge_gap',
    'conceptual_error',
    'method_selection',
    'reading_error',
    'calculation_error',
    'time_pressure',
    'careless_error',
    'transfer_failure',
    'unknown',
]


class DiagnosisOutput(StrictModel):
    error_type: ErrorType
    error_label: str = Field(default='')
    confidence: float = Field(ge=0.0, le=1.0)
    cause: str = Field(min_length=1)
    recommended_intervention: str = Field(min_length=1)
    citation: str | None = None
    adopted_evidence_id: str | None = None


async def generate_diagnosis(db, attempt_id: str) -> DiagnosisOutput:
    """Independent assessment evaluating user mistake without reading Tutor conversation."""
    attempt = db.execute(
        '''SELECT a.*, q.stem, q.options_json, q.answer, q.explanation, q.module, q.estimated_seconds
           FROM attempts a
           JOIN questions q ON q.id=a.question_id
           WHERE a.id=?''',
        (attempt_id,),
    ).fetchone()

    if attempt is None:
        raise HTTPException(404, '待诊断的作答记录不存在')
    if attempt['submitted_at'] is None:
        raise HTTPException(400, '尚未提交的作答不能进行错因诊断')
    if attempt['correct']:
        raise HTTPException(409, '正确作答不进行错因归因诊断')

    # Fetch knowledge context
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
        '言语理解与表达': 'verbal',
        '数量关系': 'quantitative',
        '政治理论': 'general-knowledge',
        '常识判断': 'general-knowledge',
    }.get(attempt['module'], 'reasoning')
    namespace = f"gongkao/xingce/{module_slug}"

    try:
        raw_evidences = await provider.retrieve(query=attempt['stem'][:100], namespace=namespace, limit=3)
    except Exception:
        raw_evidences = []

    # Quality and topic consistency filtering
    candidates = filter_candidate_evidences(raw_evidences, attempt['stem'], module=attempt['module'])
    evidence_block, evidence_rule = format_evidence_prompt_block(candidates)

    options_dict = json.loads(attempt['options_json'])
    options_text = '\n'.join(f'{k}. {v}' for k, v in options_dict.items())

    error_types_desc = '\n'.join(f'- {k}: {v}' for k, v in ERROR_LABELS.items())

    # Assessor prompt: Evaluates objectively based on facts, without reading Tutor's guidance
    messages = [
        Message(
            role='system',
            content=(
                '你是公考 AI Learning OS 的独立学习评估器（Assessor）。\n'
                '职责是客观诊断考生的失误类型，并输出结构化评估数据。\n'
                '可选错因分类（error_type）：\n'
                f'{error_types_desc}\n\n'
                f'{evidence_rule}\n\n'
                '必须返回合法的 JSON，匹配严格 Schema。'
            ),
        ),
        Message(
            role='user',
            content=(
                f'【题目】：{attempt["stem"]}\n'
                f'【选项】：\n{options_text}\n'
                f'【正确答案】：{attempt["answer"]}\n'
                f'【考生所选】：{attempt["selected_answer"]}\n'
                f'【考生耗时】：{attempt["elapsed_ms"]} ms（建议时间：{attempt["estimated_seconds"] * 1000} ms）\n'
                f'【考生信心】：{str(int(attempt["confidence"] * 100)) + "%" if attempt["confidence"] is not None else "未记录"}\n'
                f'【解析考点】：{attempt["explanation"]}\n'
                f'{evidence_block}\n'
                '请进行客观诊断：确定最可能的错误类型、置信度、归因解释与针对性巩固建议。'
            ),
        ),
    ]

    gateway = get_model_gateway()
    result = await gateway.generate(
        task_type='error_diagnosis',
        messages=messages,
        schema=DiagnosisOutput,
        model_policy='BALANCED',
    )
    diag: DiagnosisOutput = result.data
    diag.error_label = ERROR_LABELS.get(diag.error_type, '尚不确定')
    # Validate declared evidence_id against candidates strictly
    # Only exact evidence_id declared by model is accepted
    res = evaluate_evidence_adoption(
        declared_evidence_id=diag.adopted_evidence_id,
        candidates=candidates,
        answer_text=result.raw_text,
        query=attempt['stem'],
        module=attempt['module'],
    )
    if res.source_identity == 'valid' and res.can_reference and res.adopted_evidence and res.canonical_citation:
        diag.citation = res.canonical_citation
        diag.adopted_evidence_id = res.adopted_evidence.evidence_id
    else:
        diag.citation = None
        diag.adopted_evidence_id = None

    return diag


class TeachingAssessment(StrictModel):
    correct: bool
    confidence: float = Field(ge=0, le=1)
    feedback: str = Field(min_length=1, max_length=2200)
    failure_kind: Literal['none','current_node','prerequisite_gap','other_skill']
    missing_skill_id: str | None = None
    error_type: ErrorType = 'unknown'
    provider: str = ''


async def assess_teaching_check(question: dict, check: dict, answer: str,
                                prerequisites: list[dict], other_skills: list[dict]) -> TeachingAssessment:
    """Independent assessment from raw response and rubric, never the Tutor conversation."""
    if check['format']=='choice' and answer == question['answer']:
        return TeachingAssessment(correct=True,confidence=1,feedback='选项正确，还需自由回忆或应用题验证。',failure_kind='none',provider='deterministic')
    result = await get_model_gateway().generate(
        task_type='error_diagnosis',schema=TeachingAssessment,model_policy='BALANCED',
        messages=[Message(role='system',content=(
            'ADAPTIVE_CHECK_ASSESSOR：你是独立 Assessor，只依据当前检查要求、评分依据和学生原文评价。'
            '自由回忆按方法、条件和定义判分，不要求背出参考题的数字或选项；应用题要求结论和理由。'
            '不读取 Tutor 的教法，不因学生自称理解就判通过。'
            '只能读取题干文字；图片路径不表示你已看见图片。若判断依赖未读取的图示，应返回confidence<0.75，不猜测判分。'
            '失败区分当前概念未理解、明确前置缺口、其他技能错因。'
            '缺失技能必须来自给定正式技能集合，写清具体失败步骤；证据不足 confidence<0.75 且 missing_skill_id=null。'
            '仅填写评分，不负责讲课或创造技能。')),
            Message(role='user',content=json.dumps({'question':question,'check':check,'raw_answer':answer,
                'prerequisites':prerequisites,'other_skills':other_skills},ensure_ascii=False))])
    assessment=result.data
    assessment.provider=result.provider_name
    if check['format']=='choice':
        assessment.correct=answer==question['answer']
    if assessment.correct:
        assessment.failure_kind='none';assessment.missing_skill_id=None
    elif assessment.failure_kind=='prerequisite_gap' and assessment.missing_skill_id not in {n['id'] for n in prerequisites}:
        assessment.failure_kind='current_node';assessment.missing_skill_id=None
    elif assessment.failure_kind=='other_skill' and assessment.missing_skill_id not in {n['id'] for n in other_skills}:
        assessment.failure_kind='current_node';assessment.missing_skill_id=None
    return assessment
