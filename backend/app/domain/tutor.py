"""Domain service for Hint Ladder and tutoring interactions."""
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any
from fastapi import HTTPException
from pydantic import Field

logger = logging.getLogger(__name__)

from ..ai import Message, get_model_gateway
from ..ai.schemas import StrictModel, TruncatedGenerationError
from ..knowledge import (
    evaluate_evidence_adoption,
    filter_candidate_evidences,
    format_evidence_prompt_block,
    get_knowledge_provider,
    validate_and_adopt_citation,
    verify_evidence_support,
)


class HintOutput(StrictModel):
    hint_level: int = Field(ge=1, le=4)
    direction: str = Field(min_length=1)
    method: str = Field(default='')
    partial_step: str = Field(default='')
    full_explanation: str = Field(default='')
    message: str = Field(min_length=1)
    citation: str | None = None
    adopted_evidence_id: str | None = None


HINT_LEVEL_DESCRIPTIONS = {
    1: '第一级（方向指引）：指出题干中的隐含条件、比较维度或核心关键词，引导用户自主发现突破口，绝不透露解题算法或选项正误。',
    2: '第二级（方法公式）：明确适用的核心公式、推导法则或速算技巧，但不代入具体数字计算。',
    3: '第三级（部分步骤）：演示前半段关键计算或中间结论推导，保留最后一步计算由用户自行完成。',
    4: '第四级（完整解析）：给出全流程严密推导解析，分析各选项正误原因，解答认知盲区。',
}


async def generate_hint(db, attempt_id: str, requested_level: int, *, persist: bool = True) -> HintOutput:
    """Generate structured hint for active attempt and record hint_level in DB."""
    if requested_level not in (1, 2, 3, 4):
        raise HTTPException(400, 'hint_level 必须在 1 到 4 之间')

    attempt = db.execute(
        '''SELECT a.*, q.stem, q.options_json, q.answer, q.explanation, q.module, q.subject, q.difficulty
           FROM attempts a
           JOIN questions q ON q.id=a.question_id
           WHERE a.id=?''',
        (attempt_id,),
    ).fetchone()

    if attempt is None:
        raise HTTPException(404, '待提示的作答不存在')
    if attempt['submitted_at'] is not None:
        raise HTTPException(409, '已提交的作答不能再请求提示')

    # Fetch knowledge evidence from provider
    provider = get_knowledge_provider()
    namespace = f"gongkao/xingce/{MODULE_NAMESPACE_SLUGS.get(attempt['module'], 'reasoning')}"

    try:
        raw_evidences = await provider.retrieve(query=attempt['stem'][:100], namespace=namespace, limit=3)
    except Exception:
        raw_evidences = []

    # Quality and topic consistency filtering
    candidates = filter_candidate_evidences(raw_evidences, attempt['stem'], module=attempt['module'])
    evidence_block, evidence_rule = format_evidence_prompt_block(candidates)

    # Construct prompt
    options_dict = json.loads(attempt['options_json'])
    options_text = '\n'.join(f'{k}. {v}' for k, v in options_dict.items())
    level_instruction = HINT_LEVEL_DESCRIPTIONS[requested_level]

    messages = [
        Message(
            role='system',
            content=(
                '你是公考 AI Learning OS 的专职助教（Tutor）。\n'
                '遵循铁律：\n'
                '1. 严格遵守用户请求的提示等级，低等级绝不能提前透露后续步骤或最终答案。\n'
                '2. 语气温和启发，重点破解认知障碍，不讽刺、不敷衍。\n'
                '3. 如果有教材参考，优先依托教材公理与方法。\n\n'
                f'当前要求等级：Level {requested_level} - {level_instruction}\n\n'
                f'{evidence_rule}'
            ),
        ),
        Message(
            role='user',
            content=(
                f'【题目】：{attempt["stem"]}\n'
                f'【选项】：\n{options_text}\n'
                f'【标准解析依据】：{attempt["explanation"]}\n'
                f'{evidence_block}\n'
                f'请生成 Level {requested_level} 的启发提示。'
            ),
        ),
    ]

    if attempt['module'] in ('图形推理', '立体图推'):
        from .question_vision import question_image_input, VISION_RULE
        images, labels = question_image_input(db, attempt['question_id'])
        messages[0].content += VISION_RULE
        messages[-1].images = images
        messages[-1].content += '\n【本轮图片顺序】\n' + labels

    gateway = get_model_gateway()
    result = await gateway.generate(
        task_type='tutor_hint',
        messages=messages,
        schema=HintOutput,
        model_policy='FAST',
    )
    hint: HintOutput = result.data
    # Validate declared evidence_id against candidates strictly
    # Only exact evidence_id declared by model is accepted
    res = evaluate_evidence_adoption(
        declared_evidence_id=hint.adopted_evidence_id,
        candidates=candidates,
        answer_text=result.raw_text,
        query=attempt['stem'],
        module=attempt['module'],
    )
    if res.source_identity == 'valid' and res.can_reference and res.adopted_evidence and res.canonical_citation:
        hint.citation = res.canonical_citation
        hint.adopted_evidence_id = res.adopted_evidence.evidence_id
    else:
        hint.citation = None
        hint.adopted_evidence_id = None

    # Record hint_level escalation in database
    new_level = max(attempt['hint_level'], requested_level)
    if persist:
        db.execute('UPDATE attempts SET hint_level=? WHERE id=?', (new_level, attempt_id))
        db.commit()

    return hint


class TutorExplanationOutput(StrictModel):
    summary: str = Field(min_length=1)
    core_concept: str = Field(min_length=1)
    step_by_step: list[str] = Field(default_factory=list)
    common_pitfalls: list[str] = Field(default_factory=list)
    recommended_action: str = Field(min_length=1)
    citation: str | None = None
    adopted_evidence_id: str | None = None


async def generate_explanation(db, attempt_id: str) -> TutorExplanationOutput:
    """Generate in-depth pedagogic explanation blending Question State, Attempt facts, and Knowledge Evidence."""
    attempt = db.execute(
        '''SELECT a.*, q.stem, q.options_json, q.answer, q.explanation, q.module, q.subject
           FROM attempts a
           JOIN questions q ON q.id=a.question_id
           WHERE a.id=?''',
        (attempt_id,),
    ).fetchone()

    if attempt is None:
        raise HTTPException(404, '作答记录不存在')
    if attempt['submitted_at'] is None:
        raise HTTPException(400, '尚未提交作答，不能请求深度解析（请先独立思考或使用提示）')

    # Fetch knowledge evidence with priority on Actual Error Skill
    provider = get_knowledge_provider()
    namespace = f"gongkao/xingce/{MODULE_NAMESPACE_SLUGS.get(attempt['module'], 'reasoning')}"

    actual_error_binding = db.execute(
        '''SELECT esb.*, ls.name AS skill_name
           FROM error_events ee
           JOIN error_skill_bindings esb ON esb.error_event_id = ee.id
           JOIN learning_skills ls ON ls.id = esb.learning_skill_id
           WHERE ee.attempt_id = ? AND esb.role = 'primary'
           ORDER BY ee.created_at DESC LIMIT 1''',
        (attempt_id,),
    ).fetchone()
    actual_error_kn_code = actual_error_binding['knowledge_node_code'] if actual_error_binding else None
    actual_error_skill_name = actual_error_binding['skill_name'] if actual_error_binding else None

    q_primary_binding = db.execute(
        '''SELECT qsb.*, ls.name AS skill_name
           FROM question_skill_bindings qsb
           JOIN learning_skills ls ON ls.id = qsb.learning_skill_id
           WHERE qsb.question_id = ? AND qsb.role = 'primary' LIMIT 1''',
        (attempt['question_id'],),
    ).fetchone()
    q_primary_kn_code = q_primary_binding['knowledge_node_code'] if q_primary_binding else None

    evidences = []
    # Priority 1: Evidence for Actual Error Skill
    if actual_error_kn_code:
        try:
            evs = await provider.retrieve(
                query=attempt['stem'][:100],
                namespace=namespace,
                filters={'knowledge_node_code': actual_error_kn_code},
                limit=2,
            )
            evidences.extend(evs)
        except Exception:
            pass

    # Priority 2: Evidence for Question Primary Skill (if distinct or if no error evidence yet)
    if q_primary_kn_code and (not actual_error_kn_code or q_primary_kn_code != actual_error_kn_code):
        try:
            evs_q = await provider.retrieve(
                query=attempt['stem'][:100],
                namespace=namespace,
                filters={'knowledge_node_code': q_primary_kn_code},
                limit=2,
            )
            for e in evs_q:
                if not any(existing.chunk_id == e.chunk_id for existing in evidences):
                    evidences.append(e)
        except Exception:
            pass

    # Fallback to general query if empty
    if not evidences:
        try:
            evidences = await provider.retrieve(query=attempt['stem'][:100], namespace=namespace, limit=3)
        except Exception:
            evidences = []

    # Quality and topical consistency filtering
    candidates = filter_candidate_evidences(evidences, attempt['stem'], module=attempt['module'])
    evidence_block, evidence_rule = format_evidence_prompt_block(candidates)

    options_dict = json.loads(attempt['options_json'])
    options_text = '\n'.join(f'{k}. {v}' for k, v in options_dict.items())

    error_context = ''
    if actual_error_skill_name:
        error_context = f'【考生实际失误能力点】：{actual_error_skill_name}（知识编码：{actual_error_kn_code}）\n'

    messages = [
        Message(
            role='system',
            content=(
                '你是公考 AI Learning OS 的专职资深学科导师（AI Tutor）。\n'
                '你正在辅导考生进行题后深度复盘。结合题目标准答案、考生的真实作答选择与教材公理，\n'
                '特别关注考生真正犯错的认知能力缺陷，提供条理分明、直击考点本质的深度解析，重点指出易错陷阱与下一步针对性动作。\n\n'
                f'{evidence_rule}\n\n'
                '必须返回合法的 JSON，匹配严格 Schema。'
            ),
        ),
        Message(
            role='user',
            content=(
                f'【题目】：{attempt["stem"]}\n'
                f'【选项】：\n{options_text}\n'
                f'【标准答案】：{attempt["answer"]}\n'
                f'【考生所选】：{attempt["selected_answer"]}（{"正确" if attempt["correct"] else "错误"}）\n'
                f'{error_context}'
                f'【标准解析】：{attempt["explanation"]}\n'
                f'{evidence_block}\n'
                '请生成针对该题的深度复盘解析。'
            ),
        ),
    ]

    if attempt['module'] in ('图形推理', '立体图推'):
        from .question_vision import question_image_input, VISION_RULE
        images, labels = question_image_input(db, attempt['question_id'])
        messages[0].content += VISION_RULE
        messages[-1].images = images
        messages[-1].content += '\n【本轮图片顺序】\n' + labels

    gateway = get_model_gateway()
    result = await gateway.generate(
        task_type='tutor_explanation',
        messages=messages,
        schema=TutorExplanationOutput,
        model_policy='BALANCED',
    )
    explanation: TutorExplanationOutput = result.data
    # Validate declared evidence_id against candidates strictly
    # Only exact evidence_id declared by model is accepted
    res = evaluate_evidence_adoption(
        declared_evidence_id=explanation.adopted_evidence_id,
        candidates=candidates,
        answer_text=result.raw_text,
        query=attempt['stem'],
        module=attempt['module'],
    )
    if res.source_identity == 'valid' and res.can_reference and res.adopted_evidence and res.canonical_citation:
        explanation.citation = res.canonical_citation
        explanation.adopted_evidence_id = res.adopted_evidence.evidence_id
    else:
        explanation.citation = None
        explanation.adopted_evidence_id = None

    return explanation


def get_attempt_followups(db, attempt_id: str) -> list[dict]:
    """Retrieve all follow-up Q&A messages for an attempt in chronological order."""
    rows = db.execute(
        '''SELECT id, attempt_id, role, content, created_at
           FROM attempt_followups
           WHERE attempt_id = ?
           ORDER BY created_at ASC, rowid ASC''',
        (attempt_id,),
    ).fetchall()
    return [dict(r) for r in rows]


MODULE_NAMESPACE_SLUGS = {
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
}


async def retrieve_followup_evidence(db, attempt, question: str) -> list:
    """Retrieve textbook evidence for a follow-up question.

    Queries by the current follow-up question plus the question stem, scoped to the
    module namespace and the primary skill's knowledge node code when available.
    Filtered through content adequacy and topical relevance gates.
    """
    provider = get_knowledge_provider()
    module = attempt['module']
    namespace = f"gongkao/xingce/{MODULE_NAMESPACE_SLUGS.get(module, 'reasoning')}"

    node_code_row = db.execute(
        '''SELECT esb.knowledge_node_code AS code
           FROM error_events ee
           JOIN error_skill_bindings esb ON esb.error_event_id = ee.id
           WHERE ee.attempt_id = ? AND esb.role = 'primary' AND esb.knowledge_node_code IS NOT NULL
           ORDER BY ee.created_at DESC LIMIT 1''',
        (attempt['id'],),
    ).fetchone()
    node_code = node_code_row['code'] if node_code_row else None

    if not node_code:
        q_row = db.execute(
            '''SELECT qsb.knowledge_node_code AS code
               FROM question_skill_bindings qsb
               WHERE qsb.question_id = ? AND qsb.role = 'primary' AND qsb.knowledge_node_code IS NOT NULL LIMIT 1''',
            (attempt['question_id'],),
        ).fetchone()
        node_code = q_row['code'] if q_row else None

    query = ' '.join(part for part in (question.strip(), attempt['stem'][:80]) if part)[:200]

    raw_evidences: list = []
    try:
        if node_code:
            raw_evidences = await provider.retrieve(
                query=query, namespace=namespace, limit=3,
                filters={'knowledge_node_code': node_code},
            )
        if not raw_evidences:
            raw_evidences = await provider.retrieve(query=query, namespace=namespace, limit=3)
    except Exception as exc:
        logger.warning('Followup retrieval failed: %s', exc)
        return []

    # Quality and topical consistency filtering
    candidates = filter_candidate_evidences(
        raw_evidences, f"{question} {attempt['stem']}", module=module, node_code=node_code
    )
    return candidates


def format_followup_references(
    answer_text: str,
    candidates: list,
    is_error: bool = False,
    query: str | None = None,
    module: str = '数量关系',
    reference_basis: str = '题目解析与已有诊断结论',
) -> str:
    """Format reference appendix for follow-up responses.

    Strict guarantees:
    1. If is_error is True, NEVER attach any reference appendix.
    2. Strip any duplicate or imitated trailing reference blocks from model output.
    3. Adopt candidate ONLY if explicitly declared or accurately cited, and verified without contradiction.
    4. No single-candidate automatic adoption or loose page-number matching.
    5. If no candidate was adopted or candidates is empty, append explicit disclaimer.
    """
    if is_error:
        return answer_text

    # 1. Clean any duplicate/imitated trailing references block generated by model
    clean_text = re.sub(r'\n+---\n+📎\s*\*\*参考(?:依据|资料)\*\*.*$', '', answer_text, flags=re.DOTALL).strip()

    # 2. Clean raw declaration markup tags from visible answer text
    adopt_pattern = r'(?:本次答疑(?:切实)?采用(?:了)?教材证据[：:]?\s*)?(?:\[ADOPT_EVIDENCE:\s*|adopted_evidence_id\s*[:=]\s*|\[EVIDENCE:\s*)([a-zA-Z0-9_\-]+)\]?'
    clean_text = re.sub(adopt_pattern, '', clean_text, flags=re.IGNORECASE).strip()

    # 3. Detect declared candidate IDs strictly from explicit declaration markups
    declared_ids: list[str] = []
    for m in re.finditer(r'(?:\[ADOPT_EVIDENCE:\s*|adopted_evidence_id\s*[:=]\s*|\[EVIDENCE:\s*)([a-zA-Z0-9_\-]+)\]?', answer_text, re.IGNORECASE):
        declared_ids.append(m.group(1).strip())

    supported_cands = []
    if declared_ids and candidates:
        for did in declared_ids:
            res = evaluate_evidence_adoption(
                declared_evidence_id=did,
                candidates=candidates,
                answer_text=clean_text,
                query=query,
                module=module,
            )
            if res.source_identity == 'valid' and res.can_reference and res.adopted_evidence:
                if not any(sc.evidence_id == res.adopted_evidence.evidence_id for sc in supported_cands):
                    supported_cands.append(res.adopted_evidence)

    if supported_cands:
        refs = '\n'.join(
            f"- 《{c.document_title}》第{c.page}页（版本: {c.document_version_id or '标准版'}）"
            for c in supported_cands
        )
        return f'{clean_text}\n\n---\n📎 **参考资料**（本次回答引用资料）：\n{refs}'
    else:
        return f'{clean_text}\n\n---\n📎 **参考资料**：本次未引用外部教材资料，以上回答仅基于{reference_basis}。'


async def answer_followup(db, attempt_id: str, question: str, diagnosis: dict[str, Any] | None = None) -> dict:
    """Answer a user's follow-up question regarding a submitted attempt and save the conversation turn."""
    clean_question = question.strip()
    if not clean_question:
        raise HTTPException(400, '追问内容不能为空')

    attempt = db.execute(
        '''SELECT a.*, q.stem, q.options_json, q.answer, q.explanation, q.module, q.subject, q.ai_explanation_json
           FROM attempts a
           JOIN questions q ON q.id=a.question_id
           WHERE a.id=?''',
        (attempt_id,),
    ).fetchone()

    if attempt is None:
        raise HTTPException(404, '作答记录不存在')
    if attempt['submitted_at'] is None:
        raise HTTPException(400, '尚未提交作答，不能进行追问（请先提交作答并查看解析）')

    # Fetch existing conversation history for this attempt
    prior_messages = get_attempt_followups(db, attempt_id)

    # Format options
    try:
        options_dict = json.loads(attempt['options_json'])
        options_text = '\n'.join(f'{k}. {v}' for k, v in options_dict.items())
    except Exception:
        options_text = str(attempt['options_json'])

    # Include diagnosis context if provided
    diag_text = ''
    if diagnosis and isinstance(diagnosis, dict):
        diag_label = diagnosis.get('error_label') or diagnosis.get('error_type') or ''
        diag_cause = diagnosis.get('cause') or ''
        diag_rec = diagnosis.get('recommended_intervention') or ''
        diag_text = f'\n【本次 AI 错因诊断结论】：\n- 诊断错因：{diag_label}\n- 原因推断：{diag_cause}\n- 巩固建议：{diag_rec}'

    # Include AI explanation if available
    ai_exp_text = ''
    if attempt['ai_explanation_json']:
        try:
            ai_data = json.loads(attempt['ai_explanation_json'])
            ai_summary = ai_data.get('summary', '')
            ai_steps = '\n'.join(f'- {s}' for s in ai_data.get('step_by_step', []))
            ai_pitfalls = '\n'.join(f'- {p}' for p in ai_data.get('common_pitfalls', []))
            ai_exp_text = f'\n【此前 AI 深度复盘】：{ai_summary}'
            if ai_steps:
                ai_exp_text += f'\n【分步解析】：\n{ai_steps}'
            if ai_pitfalls:
                ai_exp_text += f'\n【常见误区】：\n{ai_pitfalls}'
        except Exception:
            pass

    # Retrieve textbook evidence for this follow-up (failure-isolated and quality-filtered)
    evidences = await retrieve_followup_evidence(db, attempt, clean_question)
    evidence_block, evidence_rule = format_evidence_prompt_block(evidences)

    # Four-module teacher intelligence context injection
    teacher_text = ""
    try:
        from .module_teacher_service import ModuleTeacherService
        mts = ModuleTeacherService()
        t_ctx = mts.get_teacher_context_for_review(
            module=attempt["module"] if "module" in attempt.keys() else "",
            stem=attempt["stem"] if "stem" in attempt.keys() else "",
            explanation=attempt["explanation"] if "explanation" in attempt.keys() else "",
            user_selected=attempt["selected_answer"] if "selected_answer" in attempt.keys() else "",
            student_thought=clean_question
        )
        if t_ctx:
            t_name = t_ctx.get("teacher_name")
            pols = t_ctx.get("policies", [])
            pol_lines = [f"• 【{p['name']}】({p['policy_id']})：{p['rule']}" for p in pols]
            if pols and pols[0].get("forbidden_transformations"):
                pol_lines.append(f"  * 易错避坑警示：{', '.join(pols[0]['forbidden_transformations'])}")
            crit = t_ctx.get("critique")
            crit_line = f"• 课堂针对性纠偏：{crit.get('diagnosis')}" if crit else ""
            teacher_text = (
                f"\n\n【{t_name} 教学方法参考（须核验适用条件）】：\n"
                + "\n".join(pol_lines)
                + (f"\n{crit_line}" if crit_line else "")
                + f"\n• 教学建议：{t_ctx.get('signature_advice', '')}"
                + "\n以上不构成对该考生的错因诊断，不可直接套用相似题答案。"
            )
    except Exception as exc:
        logger.debug("Failed to inject teacher context in tutor followup: %s", exc)

    from .student_work_check import check_student_work, work_check_prompt, missed_work_correction
    work_ctx = {'module': attempt['module'], 'stem': attempt['stem'], 'authoritative_explanation': attempt['explanation']}
    checks = check_student_work(work_ctx, '\n'.join(m['content'] for m in prior_messages if m['role'] == 'user') + '\n' + clean_question)
    # Build prompt messages
    system_prompt = (
        '你是公考 AI Learning OS 的专职资深学科导师（AI Tutor）。\n'
        '考生正在针对刚刚作答的题目及错因诊断结果向你发起追问。\n'
        '【辅导原则】：\n'
        '1. 认真倾听考生的疑问（例如：为什么诊断为该错因、思维盲区在哪、题目解法步骤疑问、选项辨析或防错技巧）；\n'
        '2. 针对考生的困惑点一针见血地解答，结合错因诊断结论与题干已知条件，讲透解题本质；\n'
        '3. 明确指出考生思维盲区与选项陷阱，给出行之有效的审题/做题避坑策略；\n'
        '4. 语气温和、耐心且专业，排版使用清晰的分段、序号与重点加粗，易于在移动端与桌面端快速阅读；\n'
        '5. 严守题目事实与公考命题规范，杜绝虚假推理与空话套话；\n'
        '6. 教学方法参考必须先核验题干条件；正确思路不得强行纠错，不可把课堂误区示例当作考生事实；\n'
        '7. 直接输出给考生看的最终回答，不要展示你的内部分析、草稿或推理过程。\n'
        f'{evidence_rule}' + work_check_prompt(checks)
    )

    user_context = (
        f'【题目】：{attempt["stem"]}\n'
        f'【选项】：\n{options_text}\n'
        f'【标准答案】：{attempt["answer"]}\n'
        f'【考生所选】：{attempt["selected_answer"]}（{"回答正确" if attempt["correct"] else "回答错误"}）\n'
        f'【官方解析】：{attempt["explanation"]}'
        f'{diag_text}'
        f'{ai_exp_text}'
        f'{evidence_block}'
        f'{teacher_text}'
    )

    messages = [
        Message(role='system', content=system_prompt),
        Message(role='user', content=f'这是当前题目的基本信息：\n\n{user_context}\n\n请准备好根据我的追问进行答疑辅导。'),
        Message(role='assistant', content='没问题！我是你的专职 AI 助教。针对这道题的题干已知条件、选项辨析或推导步骤，你有哪些疑问？请告诉我，我来帮你详细拆解。'),
    ]

    # Slicing to recent 10 messages (5 user + 5 assistant turns) to prevent prompt bloat
    recent_history = prior_messages[-10:] if len(prior_messages) > 10 else prior_messages
    for m in recent_history:
        messages.append(Message(role=m['role'], content=m['content']))

    # Append the new user question
    messages.append(Message(role='user', content=clean_question))

    now_iso = datetime.now(timezone.utc).isoformat()
    user_msg_id = str(uuid.uuid4())
    assistant_msg_id = str(uuid.uuid4())

    # Call AI Gateway (task_type='tutor_followup', schema=None for free-form formatted text)
    is_generation_error = False
    result = None
    generation_issues = []
    gateway = get_model_gateway()
    try:
        if attempt['module'] in ('图形推理', '立体图推'):
            from .question_vision import question_image_input, VISION_RULE
            images, labels = question_image_input(db, attempt['question_id'])
            messages[0].content += VISION_RULE
            messages[-1].images = images
            messages[-1].content += '\n【本轮图片顺序】\n' + labels
        result = await gateway.generate(
            task_type='tutor_followup',
            messages=messages,
            schema=None,
            model_policy='BALANCED',
        )
        answer_text = result.raw_text.strip()
        from .review_context import verify_followup_support
        validation = verify_followup_support(answer_text, {'stem':attempt['stem'], 'standard_answer':attempt['answer']}, clean_question)
        if missed_work_correction(answer_text, checks):
            validation.issues.append('回复没有纠正已核验的上游计算错误')
            validation.is_valid = False
        if not answer_text or not validation.is_valid:
            generation_issues.extend(validation.issues or ['模型返回为空'])
            raise ValueError('回复未通过支持性核验')
    except TruncatedGenerationError:
        is_generation_error = True
        generation_issues.append('模型输出被截断')
        answer_text = '抱歉，本次答疑生成的解答篇幅较长，受到单次输出预算限制未能完整输出。建议针对具体的解题步骤再次向我提问。'
    except Exception as exc:
        is_generation_error = True
        if not generation_issues:
            generation_issues.append('答疑服务暂时不可用（' + type(exc).__name__ + '）')
        logger.error('Failed to generate followup answer: %s', exc)
        answer_text = '本次答疑未完成：' + '；'.join(generation_issues or ['答疑服务暂时不可用']) + '。你的提问已保存，未展示未经核验的答案。'

    # Append reference section: if is_generation_error, references will NEVER be attached.
    # Candidates are only adopted if verify_evidence_support confirms support without contradiction.
    answer_text = format_followup_references(
        answer_text, evidences, is_error=is_generation_error, query=clean_question, module=attempt['module']
    )

    assistant_now_iso = datetime.now(timezone.utc).isoformat()
    # Save both user question and assistant answer in DB
    db.execute(
        '''INSERT INTO attempt_followups (id, attempt_id, role, content, created_at)
           VALUES (?, ?, 'user', ?, ?)''',
        (user_msg_id, attempt_id, clean_question, now_iso),
    )
    db.execute(
        '''INSERT INTO attempt_followups (id, attempt_id, question_id, role, content, status, metadata_json, created_at)
           VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?)''',
        (assistant_msg_id, attempt_id, attempt['question_id'], answer_text,
         'failed' if is_generation_error else 'completed',
         json.dumps({'teacher_context':locals().get('t_ctx'), 'generation':{
             'status':'failed' if is_generation_error else 'generated',
             'model':getattr(result,'model_name',None),'provider':getattr(result,'provider_name',None),
             'policy':'BALANCED','fallback_reasons':generation_issues,
             'validation_scope':'explicit_arithmetic_and_declared_current_answer','image_input':False}},ensure_ascii=False), assistant_now_iso),
    )
    db.commit()

    return {
        'id': assistant_msg_id,
        'user_message_id': user_msg_id,
        'attempt_id': attempt_id,
        'role': 'assistant',
        'content': answer_text,
        'status': 'failed' if is_generation_error else 'completed',
        'created_at': assistant_now_iso,
    }


class MicroLesson(StrictModel):
    core_concept: str = Field(min_length=1, max_length=1800)
    example: str = Field(min_length=1, max_length=2200)
    adopted_evidence_id: str | None = None
    citation: str | None = None
    source_basis: str = '核验题原解析'


async def teach_single_node(node: dict, example: dict) -> MicroLesson:
    """One concept and one verified example. The orchestrator owns the independent CHECK."""
    provider = get_knowledge_provider()
    candidates = []
    module = example.get('module') or node.get('module', '')
    query = node['name'] + ' ' + example['stem'][:160]
    try:
        slug=MODULE_NAMESPACE_SLUGS.get(module,'')
        namespace='gongkao/xingce/'+slug if slug else 'gongkao/xingce'
        raw = await provider.retrieve(query=query, namespace=namespace,
                                      filters={'knowledge_node_code':node['knowledge_node_code']}, limit=3)
        candidates = filter_candidate_evidences(raw, query, module=module)
        # The Hub's document bindings can be more granular than the official Skill.
        # A module-scoped retry remains subject to the existing relevance/support gates.
        if not candidates:
            raw = await provider.retrieve(query=query, namespace=namespace, limit=3)
            candidates = filter_candidate_evidences(raw, query, module=module)
    except Exception:
        pass
    block, rule = format_evidence_prompt_block(candidates)
    result = await get_model_gateway().generate(
        task_type='tutor_explanation', schema=MicroLesson, model_policy='BALANCED',
        messages=[Message(role='system',content=(
            'ADAPTIVE_MICRO_LESSON：你是 Tutor，只教给定的一个核心概念、一个必要示例。系统随后给出唯一的独立应用检查。'
            '不得展开后续节点，不判断学生是否掌握，不给独立检查题的答案。'
            '示例来自给定核验题，说明适用条件；教材未命中时明确依据为题目原解析，不编造引用。'+rule)),
            Message(role='user',content=json.dumps({'node':node,'verified_example':example,'evidence':block},ensure_ascii=False))])
    lesson=result.data
    adoption=evaluate_evidence_adoption(declared_evidence_id=lesson.adopted_evidence_id,candidates=candidates,
                                       answer_text=result.raw_text,query=query,module=module)
    if adoption.source_identity=='valid' and adoption.can_reference and adoption.adopted_evidence and adoption.canonical_citation:
        lesson.adopted_evidence_id=adoption.adopted_evidence.evidence_id
        lesson.citation=adoption.canonical_citation;lesson.source_basis='核验题原解析与已核验教材证据'
    else:
        lesson.adopted_evidence_id=None;lesson.citation=None;lesson.source_basis='核验题原解析（未采用教材证据）'
    return lesson
