"""Attempt-scoped teaching dialogue, stored in existing followup metadata.

The original attempt, error attribution and mastery are never updated here.
"""
import json
import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from ..ai import Message, get_model_gateway
from .review_context import build_unified_review_context_with_hub, format_unified_prompt_blocks, verify_followup_support
from .tutor import format_followup_references
from ..knowledge.models import KnowledgeEvidence
from .module_teacher_service import ModuleTeacherService
from .student_work_check import check_student_work, work_check_prompt, missed_work_correction
from .question_vision import vision_availability, question_image_input, question_image_urls, VISION_RULE, graphic_transfer_question, format_graphic_transfer


PHASE_INSTRUCTIONS = {
    'followup': '学生对完整解析或概念追问。先核对他引用的数值与推导来源，纠正最早错误；概念性疑问从知识树考点讲解定义、适用条件与易混点，再直接回答当前疑问，不重复整篇解析。',
    'hint': '学生刚提交原思路。只依据自述指出一个最关键的遗漏条件或错误步骤，保留合理思路；给一个最小提示和引导问题，等待学生重新作答。禁止公布本题正确选项、最终数值或完整推导；不要一次列出全部代入算式，提示控制在150字左右。学生说完全不会时，从辨认已知和所求开始，不凭空归因。',
    'explain': '完整回复控制在600字以内，避免重复列式。学生已重新作答。先核对重答与理由，再对比原思路，给完整解析：考点、适用条件、具体推导、答案核验、易错边界。仍错时明确指出未解决的一步。提示后答对仅表示在帮助下完成，不能宣称掌握。',
    'direct': '学生主动选择直接看解析。给完整解析：考点、适用条件、具体推导、答案核验、易错边界，不编造学生思路或诊断。',
    'transfer': '完整解析后，给一道明确标注为自编的同考点新变式，条件与原题不同，暂不公布答案或推导，等待学生独立作答。不得将原题答案当成新题答案。',
    'check_transfer': '核验学生对上轮自编变式的答案和理由，必要时给针对性提示。缺少变式题干或理由时先追问，不凭空宣称掌握。此对话练习不写入正式成绩或掌握度。',
    'teach': '学生带着疑问主动请教。从知识树考点与教材证据出发直接教学：先讲清概念定义、适用条件与易混点，再结合本题情境回答当前疑问，并引导学生自己走通一步。答对的题目可对照正确选项讲透；未答对的题目不公布本题答案与选项，围绕概念与方法本身讲解。',
}

# Skipped re-answer: the student stays stuck and asks for the full explanation
# instead of fabricating an option. Never counted as a new wrong answer.
EXPLAIN_STILL_STUCK = ('学生表示在提示后仍不会，选择跳过重答，直接看解析。给完整解析：考点、适用条件、具体推导、答案核验、易错边界；'
                       '若学生写明卡点，优先回应该卡点。不要编造学生的重答选项或思路；明确跳过重答不作为掌握证据。')

# Skipped re-answer without any prior hint: the learner skips straight to explanation.
EXPLAIN_SKIPPED_WITHOUT_HINT = ('学生未获取提示，选择跳过重答并直接看完整解析。给完整解析：考点、适用条件、具体推导、答案核验、易错边界；'
                                '若学生写明卡点，优先回应该卡点。不要编造学生的重答选项或思路；明确跳过重答不作为掌握证据。')

# Correct first answer: full teaching explanation on request, no re-answer gate.
EXPLAIN_CORRECT = ('学生首次独立作答正确，主动查看完整讲解。给完整讲解：解法、方法的适用条件、关键推导、答案核验、易错点与易混边界。'
                   '提醒答对不等于掌握；若学生自述靠猜测或存在明显漏洞，明确指出并建议用变式自测验证。不编造学生未提供的思路。')

# A correct attempt has already demonstrated the skill; submitting the approach
# should trigger confirmation and concept teaching, not hint-gated re-answering.
THOUGHT_CORRECT_TEACHING = ('学生已答对本题并提交作答思路。先核对自述思路与正确推导是否一致；'
                            '再从知识树考点出发讲解概念理解：这个方法为什么适用、关键条件与易混点在哪。'
                            '不要求学生重新作答；自述有实质漏洞或属于碰对时明确指出，并建议用变式自测验证。')

# 'review': wrong attempt straight after grading — re-answer, hint, ask and the
# bank explanation are all offered at once; 'correct': no re-answer gate, the
# full teacher explanation or a follow-up question is available immediately.
# 'thought' is a legacy stage name kept for old conversations; it is remapped
# in get_guided_review based on the recorded attempt result.
STAGE_ACTIONS = {'review': {'thought', 'dont_know', 'retry', 'hint', 'direct', 'ask'},
                 'retry': {'retry', 'hint', 'direct', 'ask'},
                 'complete': {'transfer', 'direct', 'followup'},
                 'transfer': {'check_transfer', 'hint', 'direct', 'ask'},
                 'correct': {'thought', 'full', 'direct', 'followup', 'ask'}}


def hint_leaks_answer(text: str) -> bool:
    """Catch explicit answer disclosures; pedagogical quality still needs evaluation."""
    return bool(re.search(r'(?:正确答案|标准答案|答案是|答案为|应选|选择选项|最终结果|最终答案)\s*[：:为是]?\s*[【\[（(]*\s*(?:[ABCD]|\d)', text)
                or re.search(r'(?:合作|完工|最终)[^。\n]{0,12}(?:需要|需|用时为|结果为)\s*\d', text))


def get_guided_review(db, attempt_id: str) -> dict:
    att = db.execute('SELECT question_id, submitted_at, correct FROM attempts WHERE id=?', (attempt_id,)).fetchone()
    if att is None:
        raise HTTPException(404, '作答记录不存在')
    if not att['submitted_at']:
        raise HTTPException(409, '请先完成首次作答')
    attempt_correct = bool(att['correct'])
    rows = db.execute('SELECT id,role,content,status,metadata_json FROM attempt_followups WHERE attempt_id=? ORDER BY created_at,rowid', (attempt_id,)).fetchall()
    turns = []
    stage = 'correct' if attempt_correct else 'review'
    for row in rows:
        meta = json.loads(row['metadata_json'] or '{}')
        guided = meta.get('guided_review')
        if guided:
            turns.append({**dict(row), 'guided_review': guided})
            if row['role'] == 'assistant' and row['status'] == 'completed':
                stage = guided['next_stage']
    if stage == 'thought':
        stage = 'correct' if attempt_correct else 'review'
    q = db.execute('SELECT module,options_json FROM questions WHERE id=?', (att['question_id'],)).fetchone()
    service = ModuleTeacherService()
    teacher_id = service.resolve_teacher_id_for_module(q['module'])
    teacher = next((t for t in service.list_teachers().get('teachers', []) if t['teacher_id'] == teacher_id), None)
    visual_ready, visual_reason = vision_availability(db, att['question_id']) if q['module'] in ('图形推理', '立体图推') else (False, None)
    available_actions = STAGE_ACTIONS[stage] if q['module'] not in ('图形推理', '立体图推') or visual_ready else {'direct'}
    transfer_question_id = next((t['guided_review'].get('transfer_question_id') for t in reversed(turns)
                                 if t['role'] == 'assistant' and t['status'] == 'completed' and t['guided_review'].get('transfer_question_id')), None)
    return {'attempt_id': attempt_id, 'stage': stage, 'messages': turns,
            'available_actions': sorted(available_actions),
            'unavailable_reason': visual_reason,
            'vision_available': visual_ready, 'transfer_question_id': transfer_question_id,
            'question_images': question_image_urls(db, att['question_id']),
            'options': json.loads(q['options_json']), 'module': q['module'],
            'attempt_correct': attempt_correct,
            'teacher_name': teacher['name'] if teacher else 'AI复盘助教（该模块未配置独立教师）',
            'assisted': bool(turns), 'mastery_updated': False}


async def guided_review_turn(db, attempt_id: str, action: str, message: str = '', answer: str = '', request_id: str | None = None) -> dict:
    state = get_guided_review(db, attempt_id)
    if state['module'] in ('图形推理', '立体图推') and not state['vision_available'] and action != 'direct':
        # A missing capability is not a transient generation failure. Reject it
        # before retrieval or persistence so retry cannot create endless pairs.
        raise HTTPException(409, state['unavailable_reason'])
    if request_id and any(t['guided_review'].get('request_id') == request_id and t['role'] == 'assistant' for t in state['messages']):
        return state
    if action == 'direct' and state['messages'] and state['messages'][-1]['status'] == 'completed' and state['messages'][-1]['guided_review']['action'] == 'direct':
        return state
    if action not in STAGE_ACTIONS[state['stage']]:
        raise HTTPException(409, '请按当前教学步骤操作')
    text = message.strip()
    if action in {'check_transfer', 'followup', 'ask'} and not text:
        raise HTTPException(422, '请写下思路、理由或具体卡点')
    skip_retry = False
    if action == 'retry':
        # An empty choice is an explicit "still stuck": record it as skipping the
        # re-answer, never as a fabricated answer or a new wrong attempt.
        answer = answer.strip().upper()
        skip_retry = not answer
        if answer and answer not in state['options']:
            raise HTTPException(422, '请选择重答选项')
    if action == 'thought' and not text:
        text = '我还没有思路，请从辨认已知条件和所求开始，给一个入门提示，不要编造我的思路。'
    if action == 'hint' and not text:
        text = ('我还没有思路，请从辨认已知条件和所求开始，给一个入门提示。'
                if state['stage'] == 'review' else '我仍不知道如何继续，请再给一个最小提示。')
    if action == 'dont_know':
        text = '我完全不会，请从识别已知条件和所求开始给一个提示。'
    if action == 'full':
        text = '请给出本题的完整讲解：解法、适用条件与易错点。'
    if action == 'direct':
        text = '我选择直接查看完整解析。'
    if action == 'transfer':
        text = '请给一道同考点的新变式自测，暂不公布答案。'
    if action == 'direct':
        from .review_context import build_unified_review_context
        ctx = build_unified_review_context(db, attempt_id)
    else:
        ctx = await build_unified_review_context_with_hub(db, attempt_id, query=text)
    phase = {'thought': 'hint', 'dont_know': 'hint', 'retry': 'explain', 'hint': 'hint',
             'direct': 'direct', 'full': 'explain', 'transfer': 'transfer', 'check_transfer': 'check_transfer', 'followup': 'followup',
             'ask': 'teach'}[action]
    thought_is_correct = action == 'thought' and ctx.get('is_correct')
    if thought_is_correct:
        phase = 'teach'
    transfer_question = None
    if state['module'] in ('图形推理', '立体图推') and action == 'transfer':
        excluded = [t['guided_review']['transfer_question_id'] for t in state['messages'] if t['guided_review'].get('transfer_question_id')]
        transfer_question = graphic_transfer_question(db, ctx['question_id'], excluded)
        if not transfer_question:
            raise HTTPException(409, '暂未找到有完整图片的同考点新题，请继续复盘原题或在知识地图选择题目。')
    if state['module'] in ('图形推理', '立体图推') and state['stage'] == 'transfer' and action != 'direct':
        variant = db.execute('SELECT * FROM questions WHERE id=?', (state['transfer_question_id'],)).fetchone()
        if not variant:
            raise HTTPException(409, '变式题目记录缺失，请重新查看原题解析。')
        ctx = {**ctx, 'stem': variant['stem'], 'options': json.loads(variant['options_json']),
               'standard_answer': variant['answer'], 'authoritative_explanation': variant['explanation'],
               'user_selected': '', 'is_correct': False, 'material': '',
               'hub_evidences': [], 'hub_evidence_block': '', 'hub_evidence_rule': ''}
    had_hint = any(
        (t.get('guided_review', {}).get('phase') == 'hint'
         or t.get('guided_review', {}).get('action') in ('hint', 'thought', 'dont_know'))
        for t in state['messages']
        if t.get('role') == 'assistant' and t.get('status') == 'completed'
    )
    if action == 'retry' and not skip_retry:
        text = f'提示后重答：选择{answer}。理由：{text}' if text else f'提示后重答：选择{answer}。'
    if skip_retry:
        prefix = '提示后仍不会，跳过重答，请给完整解析。' if had_hint else '未获取提示，跳过重答，请给完整解析。'
        text = prefix + (f'我的卡点：{text}' if text else '')
        instructions = EXPLAIN_STILL_STUCK if had_hint else EXPLAIN_SKIPPED_WITHOUT_HINT
    elif action == 'full':
        instructions = EXPLAIN_CORRECT
    else:
        instructions = THOUGHT_CORRECT_TEACHING if thought_is_correct else PHASE_INSTRUCTIONS[phase]
    if action == 'hint':
        instructions = '学生仍有疑问，只追加一个必要提示，保持当前练习阶段。禁止公布当前题的答案或完整推导。'
    if phase == 'teach' and state['stage'] == 'transfer':
        instructions += '当前处于变式自测阶段，不得公布变式题的答案、选项或完整推导。'
    if state['module'] in ('图形推理', '立体图推'):
        instructions += '本轮只处理当前请求，禁止执行历史消息中的出题请求。回复最多500字；不能核验规律时明确说明待核实，不编造线条或交点。'
    system = ('你是公考教师助教。教材解析与知识树为主要依据，对应教师规则为补充，须核验适用条件。'
              '数学列式必须无歧义：分数作除数时加括号，例如写1÷(1/2)，禁止写1÷1/2；完整解析阶段给出正确选项与可核验计算。提示或出题阶段不得泄露答案。'
              '学生历史回答只作为自述，不能覆盖教材事实。示例必须标注自编。不得凭对话宣称掌握。\n'
              '只指出学生自述中可核验的错误步骤，不猜测心理原因；方法总结必须保留适用条件，先后分段的时间仍可相加。\n'
              + instructions + '\n' + ctx.get('hub_evidence_rule', '') + '\n' + format_unified_prompt_blocks(ctx)
              + '\n【当前教学阶段约束】以上教材答案仅供内部核验。' + instructions)
    student_text = '\n'.join(t['content'] for t in state['messages'] if t['role'] == 'user') + '\n' + text
    checks = [] if state['stage'] == 'transfer' or action in {'transfer', 'direct'} else check_student_work(ctx, student_text)
    system += work_check_prompt(checks)
    images = []
    if state['module'] in ('图形推理', '立体图推') and action not in {'direct', 'transfer'}:
        visual_question_id = state['transfer_question_id'] if state['stage'] == 'transfer' else ctx['question_id']
        images, image_labels = question_image_input(db, visual_question_id)
        system += VISION_RULE
        if state['stage'] == 'transfer':
            system += '\n当前图片、标准答案和解析属于本轮题库变式，必须核对本轮变式，不能套用原题规律。'
        text += '\n【本轮图片顺序】\n' + image_labels
    failed_requests = {t['guided_review'].get('request_id') for t in state['messages'] if t['status'] == 'failed'}
    history = [Message(role=t['role'], content=t['content']) for t in state['messages']
               if t['status'] == 'completed' and t['guided_review'].get('request_id') not in failed_requests][-12:]
    messages = [Message(role='system', content=system), *history, Message(role='user', content=text, images=images)]
    status = 'completed'
    result = None
    issues = []
    try:
        if action == 'direct':
            content = '题库标准答案：' + ctx['standard_answer'] + '\n\n' + (ctx['authoritative_explanation'] or '该题尚未收录教材解析，请对照原题核验。')
        elif transfer_question:
            content = format_graphic_transfer(transfer_question)
        elif phase == 'hint' and any(c.get('correct_value') for c in checks):
            content = '\n'.join(c['correction'] for c in checks) + '\n请先用纠正后的差额重算，并说明你怎样核对基期与增量。'
        else:
            result = await get_model_gateway().generate(task_type='tutor_followup', messages=messages, schema=None, model_policy='BALANCED')
            content = (result.raw_text or '').strip()
        validation_ctx = {} if action == 'transfer' or (state['stage'] == 'transfer' and state['module'] not in ('图形推理', '立体图推')) else ctx
        validation = verify_followup_support(content, validation_ctx, text)
        issues = validation.issues
        if missed_work_correction(content, checks):
            issues.append('回复没有纠正已核验的上游计算错误')
            validation.is_valid = False
        if not content or not validation.is_valid:
            raise ValueError('回复未通过核验')
        # Teach stays leak-guarded while the recorded answer is not yet the
        # student's own (wrong attempt) or a transfer variant is on the table.
        leak_guarded = phase in {'hint', 'transfer'} or (phase == 'teach' and (not ctx.get('is_correct') or state['stage'] == 'transfer'))
        if leak_guarded and hint_leaks_answer(content):
            issues.append('当前阶段提前公布了答案')
            raise ValueError('教学回复提前揭示答案')
        if leak_guarded:
            # Do not append reference excerpts that could reveal a worked solution.
            content = content.strip()
        else:
            content = format_followup_references(content, [KnowledgeEvidence.model_validate(e) for e in ctx.get('hub_evidences', [])], query=ctx['stem'], module=ctx['module'], reference_basis='题库原解析、知识树信息、匹配教师规则与学生自述')
    except Exception as exc:
        status = 'failed'
        issues = issues or ['教师回复暂不可用（' + type(exc).__name__ + '）']
        content = '本次教学回复未完成：' + '；'.join(issues) + '。请重试，教学阶段和原始成绩未改变。'
        if ctx['module'] in ('图形推理', '立体图推') and not images:
            content += '当前没有图像输入，请对照原题图片；不能声称已读图。'
    # Viewing the bank explanation is a side entry: it must not interrupt an
    # ongoing re-answer or variant self-test, so the stage is preserved.
    # followup keeps its stage too: asking before the full explanation must not
    # remove the option to request it afterwards.
    next_stage = {'thought': 'retry', 'dont_know': 'retry', 'retry': 'complete', 'full': 'complete', 'direct': state['stage'],
                  'followup': state['stage'], 'transfer': 'transfer', 'check_transfer': 'transfer',
                  'hint': 'retry' if state['stage'] == 'review' else state['stage'], 'ask': state['stage']}[action]
    if thought_is_correct:
        next_stage = 'complete'
    metadata = {'guided_review': {'action': action, 'phase': phase, 'next_stage': next_stage,
                                 'request_id': request_id, 'assisted': True, 'mastery_updated': False},
                'generation': {'model': getattr(result, 'model_name', None), 'issues': issues},
                'vision': {'image_count': len(images)},
                'student_work_checks': checks,
                'teacher_context': ctx.get('teacher_context')}
    if action == 'retry':
        metadata['guided_review']['retry_answer'] = answer
        if skip_retry:
            metadata['guided_review']['skipped_retry'] = True
            metadata['guided_review']['had_hint'] = had_hint
            metadata['guided_review']['skip_label'] = '提示后仍不会／跳过重答' if had_hint else '未获取提示，跳过重答'
        else:
            metadata['guided_review']['matches_recorded_answer'] = answer == (ctx['standard_answer'] or '').strip().upper()
    metadata['guided_review']['request_payload'] = {'action': action, 'message': message, 'answer': answer}
    if transfer_question:
        metadata['guided_review']['transfer_question_id'] = transfer_question['id']
    elif state.get('transfer_question_id') and state['stage'] == 'transfer' and action != 'direct':
        metadata['guided_review']['transfer_question_id'] = state['transfer_question_id']
    current = get_guided_review(db, attempt_id)
    if [t['id'] for t in current['messages']] != [t['id'] for t in state['messages']]:
        if request_id and any(t['role'] == 'assistant' and t['guided_review'].get('request_id') == request_id for t in current['messages']):
            return current
        raise HTTPException(409, '其他页面已更新教学进度，请刷新后继续；本次未覆盖新进度')
    now = datetime.now(timezone.utc).isoformat()
    for role, body, msg_status in [('user', text, 'completed'), ('assistant', content, status)]:
        db.execute('INSERT INTO attempt_followups(id,attempt_id,question_id,role,content,turn_type,status,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                   (str(uuid.uuid4()), attempt_id, ctx['question_id'], role, body, 'guided_teacher', msg_status, json.dumps(metadata, ensure_ascii=False), now))
    return get_guided_review(db, attempt_id)
