"""Concept tutoring grounded in the selected knowledge node; no mastery writes.

2026-10 起：教学对话服务端持久化（node_teaching_sessions/turns，migration 049），
按 节点+模式 自动接续最近 active 会话；跨会话/跨设备可恢复。仍然不写掌握度。
"""
import json
from datetime import datetime, timezone
from fastapi import HTTPException
from uuid import uuid4
from ..ai import Message, get_model_gateway
from ..knowledge.evidence_filter import filter_candidate_evidences, format_evidence_prompt_block
from .module_teacher_service import ModuleTeacherService
from .review_context import verify_followup_support
from .tutor import get_knowledge_provider, MODULE_NAMESPACE_SLUGS, format_followup_references
from .guided_teacher_review import PHASE_INSTRUCTIONS, hint_leaks_answer
from .student_work_check import STUDENT_WORK_RULE

LEARNING_INSTRUCTIONS = {
    'qa': '直接回答学生不懂的知识点，用通俗语言解释定义、适用条件和易混点，再给一个明确标为自编的简短例子。不要强制学生先回答，允许继续追问。',
    'self_check': '开展知识点自查。首次每次只出一道围绕当前考点的理解题，明确标为自编，暂不公布答案或把答案写在提示里，等待学生回答。已有学生作答时先根据答案和理由检查概念、适用条件、反例与迁移能力，指出具体遗漏或错误，给最小提示并请学生重答；学生修正后再讲解并继续下一题。信息不足时说明无法判断，不凭一次回答宣称已经掌握，不生成虚假掌握度分数。',
    'feynman': '开展费曼学习法。首次请学生把当前知识点讲给一个初学者听，用自己的话说明概念、适用条件，并举一个自编例子，不要先替学生给出整段标准讲解。已有学生讲解时，逐项反馈准确之处、术语堆砌或逻辑跳跃、遗漏的前提和例子是否成立；针对最关键的一处提出追问，让学生重新用更简单的话讲一遍。根据修订再反馈，循环讲解、找缺口、简化、重讲。依据不足时说明无法核实，不因讲得流畅就宣称已经掌握，不生成虚假掌握度分数。',
    'socratic': (
        '开展严格苏格拉底追问练习。规则：'
        '① 每轮只围绕一个关键问题追问（概念边界、适用条件或反例），明确等待学生回答，不连续自问自答；'
        '② 不抢先给出完整答案或整段标准讲解；学生答错或卡住时，先给最小提示（缩小范围、给反例的一半），仍卡住再升一级提示；'
        '③ 学生明确说「不会/直接讲」时，简要给出该问题的答案要点并转入下一个关键问题；'
        '④ 学生要求结束时，总结本轮暴露的疑点清单（明确标注哪些是待验证问题），不宣布掌握；'
        '⑤ 学生提出想直接听完整解析时，提示可切换到「知识点答疑」模式或题目复盘的完整解析入口。'
    ),
}

TEACHING_MODES = set(LEARNING_INSTRUCTIONS) | {'breakthrough', 'concept'}
HISTORY_WINDOW = 8


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 会话持久化（migration 049）
# ---------------------------------------------------------------------------

def get_or_create_session(db, node_id: str, mode: str, *, new_session: bool = False,
                          session_id: str | None = None):
    """按 节点+模式 接续最近 active 会话；new_session 或指定 session_id 时按需新建/校验。"""
    if session_id:
        row = db.execute(
            'SELECT * FROM node_teaching_sessions WHERE id=?', (session_id,)).fetchone()
        if row is None:
            raise HTTPException(404, '教学会话不存在')
        if row['knowledge_node_id'] != node_id or row['mode'] != mode:
            raise HTTPException(409, '会话与考点/模式不匹配，请刷新后重试')
        if row['status'] != 'active':
            raise HTTPException(409, '会话已结束；请新开一个会话继续。')
        return row
    if not new_session:
        row = db.execute(
            """SELECT * FROM node_teaching_sessions
               WHERE knowledge_node_id=? AND mode=? AND status='active'
               ORDER BY last_message_at DESC LIMIT 1""", (node_id, mode)).fetchone()
        if row is not None:
            return row
    sid = f'nts_{uuid4().hex[:12]}'
    ts = _now_iso()
    db.execute(
        '''INSERT INTO node_teaching_sessions
           (id,knowledge_node_id,mode,status,title,created_at,last_message_at)
           VALUES (?,?,?,?,?,?,?)''',
        (sid, node_id, mode, 'active', None, ts, ts))
    return db.execute('SELECT * FROM node_teaching_sessions WHERE id=?', (sid,)).fetchone()


def append_turn(db, session_id: str, role: str, content: str, *, phase: str | None = None,
                status: str = 'completed', meta: dict | None = None):
    row = db.execute('SELECT COALESCE(MAX(seq),0)+1 n FROM node_teaching_turns WHERE session_id=?',
                     (session_id,)).fetchone()
    tid = f'ntt_{uuid4().hex[:12]}'
    ts = _now_iso()
    db.execute(
        '''INSERT INTO node_teaching_turns
           (id,session_id,seq,role,content,phase,status,meta_json,created_at)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        (tid, session_id, row['n'], role, content, phase, status,
         json.dumps(meta or {}, ensure_ascii=False), ts))
    db.execute('UPDATE node_teaching_sessions SET last_message_at=? WHERE id=?', (ts, session_id))
    return tid


def load_session_history(db, session_id: str, limit: int = HISTORY_WINDOW):
    rows = db.execute(
        '''SELECT * FROM node_teaching_turns WHERE session_id=?
           ORDER BY seq DESC LIMIT ?''', (session_id, limit)).fetchall()
    return [{'role': r['role'], 'content': r['content']} for r in reversed(rows)]


def list_sessions(db, node_id: str, mode: str | None = None, include_closed: bool = False):
    where, params = ['knowledge_node_id=?'], [node_id]
    if mode:
        where.append('mode=?')
        params.append(mode)
    if not include_closed:
        where.append("status='active'")
    rows = db.execute(
        f'''SELECT s.*,
                   (SELECT COUNT(*) FROM node_teaching_turns t WHERE t.session_id=s.id) turn_count,
                   (SELECT content FROM node_teaching_turns t WHERE t.session_id=s.id
                     AND t.role='user' ORDER BY seq LIMIT 1) first_question
            FROM node_teaching_sessions s WHERE {" AND ".join(where)}
            ORDER BY s.last_message_at DESC LIMIT 20''', params).fetchall()
    return [{'id': r['id'], 'mode': r['mode'], 'status': r['status'],
             'turn_count': r['turn_count'], 'first_question': r['first_question'],
             'created_at': r['created_at'], 'last_message_at': r['last_message_at']}
            for r in rows]


def get_session_detail(db, session_id: str, limit: int = 200):
    row = db.execute('SELECT * FROM node_teaching_sessions WHERE id=?', (session_id,)).fetchone()
    if row is None:
        raise HTTPException(404, '教学会话不存在')
    turns = db.execute(
        '''SELECT * FROM node_teaching_turns WHERE session_id=? ORDER BY seq LIMIT ?''',
        (session_id, limit)).fetchall()
    return {
        'id': row['id'], 'knowledge_node_id': row['knowledge_node_id'], 'mode': row['mode'],
        'status': row['status'], 'title': row['title'],
        'created_at': row['created_at'], 'last_message_at': row['last_message_at'],
        'turns': [{'id': t['id'], 'seq': t['seq'], 'role': t['role'], 'content': t['content'],
                   'phase': t['phase'], 'status': t['status'],
                   'meta': json.loads(t['meta_json'] or '{}'), 'created_at': t['created_at']}
                  for t in turns],
    }


def close_session(db, session_id: str):
    ts = _now_iso()
    cur = db.execute(
        "UPDATE node_teaching_sessions SET status='closed', closed_at=? "
        "WHERE id=? AND status='active'", (ts, session_id))
    return {'closed': cur.rowcount}


def turn_to_study_task(db, turn_id: str, *, question: str | None = None):
    """把教学对话中的疑点/追问转为可确认的学习任务（study_tasks，自编自查题）。

    明确的语义：AI 提出的疑点只是「待验证假设」，进学习任务队列由用户作答确认；
    不写掌握度（与 048 隔离原则一致）。
    """
    turn = db.execute(
        '''SELECT t.*, s.knowledge_node_id, s.mode,
                  (SELECT kn.knowledge_node_code FROM knowledge_nodes kn
                   WHERE kn.id=s.knowledge_node_id) knowledge_node_code
           FROM node_teaching_turns t JOIN node_teaching_sessions s ON s.id=t.session_id
           WHERE t.id=?''', (turn_id,)).fetchone()
    if turn is None:
        raise HTTPException(404, '教学轮次不存在')
    if turn['role'] != 'assistant':
        raise HTTPException(422, '仅支持把 AI 回复中的疑点/追问转为学习任务')
    content = (question or '').strip() or turn['content'].strip()
    ts = _now_iso()
    set_row = db.execute(
        """SELECT * FROM study_task_sets
           WHERE knowledge_node_id=? AND status='published'
             AND title LIKE '%教学沉淀%' ORDER BY created_at DESC LIMIT 1""",
        (turn['knowledge_node_id'],)).fetchone()
    if set_row is None:
        set_id = f'sts_{uuid4().hex[:12]}'
        db.execute(
            '''INSERT INTO study_task_sets
               (id,knowledge_node_id,knowledge_node_code,title,status,provenance_json,
                generation_status,generation_note,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (set_id, turn['knowledge_node_id'], turn['knowledge_node_code'],
             '教学沉淀（AI 疑点待验证）', 'published',
             json.dumps({'source': 'node_teaching'}, ensure_ascii=False),
             'ok', 'teaching_pending_questions', ts, ts))
    else:
        set_id = set_row['id']
    task_id = f'stt_{uuid4().hex[:12]}'
    db.execute(
        '''INSERT INTO study_tasks
           (id,set_id,task_type,sort_order,title,content,detail_json,source_kind,
            provenance_json,status,result_json,done_at,created_at,updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (task_id, set_id, 'self_check', 0, content[:200], content,
         json.dumps({'origin': 'teaching_pending_question',
                     'rubric': '能独立说清即理解；不确定即回到对应考点再学'},
                    ensure_ascii=False),
         'ai_generated',
         json.dumps({'source': 'node_teaching', 'session_id': turn['session_id'],
                     'turn_id': turn_id, 'mode': turn['mode']}, ensure_ascii=False),
         'published', None, None, ts, ts))
    return {'set_id': set_id, 'task_id': task_id}


def node_teacher_context(db, node_id: str, question: str = '') -> dict:
    row=db.execute('SELECT * FROM knowledge_nodes WHERE id=?',(node_id,)).fetchone()
    if row is None: raise HTTPException(404,'知识节点不存在')
    node=dict(row); path=[node]; visited={node_id}; parent=node.get('parent_id')
    while parent and parent not in visited:
        visited.add(parent)
        ancestor=db.execute('SELECT * FROM knowledge_nodes WHERE id=?',(parent,)).fetchone()
        if not ancestor: break
        path.insert(0,dict(ancestor));parent=ancestor['parent_id']
    service=ModuleTeacherService();module=node['module']
    teacher_id=service.resolve_teacher_id_for_module(module)
    code=node.get('knowledge_node_code') or ''
    if not teacher_id:
        for fragment, candidate in [('reasoning.graphic','图形推理'),('reasoning.definition','定义判断'),('reasoning.conditional_logic','逻辑判断'),('reasoning.logic','逻辑判断'),('quantitative','数量关系'),('data_analysis','资料分析')]:
            if code.startswith('gongkao.xingce.'+fragment):
                module=candidate;teacher_id=service.resolve_teacher_id_for_module(module);break
    teachers=service.list_teachers().get('teachers',[])
    teacher=next((t for t in teachers if t['teacher_id']==teacher_id),None)
    method=service.get_teacher_context_for_review(module,node['name']+' '+question,explanation=node.get('description') or '') if teacher else None
    return {'node_id':node_id,'node_name':node['name'],'node_code':code,'module':module,
            'path':[p['name'] for p in path],'description':node.get('description') or '',
            'teacher':teacher,'teacher_context':method,'available':teacher is not None,'ai_available':True}


async def answer_node_teacher(db, node_id: str, question: str, mode: str, history: list[dict],
                              phase: str | None = None, *, session_id: str | None = None,
                              new_session: bool = False) -> dict:
    question=question.strip()
    if not question:
        if phase == 'hint':
            question = '请给出核心解题思路与提示引导。'
        elif phase == 'explain':
            question = '请给出考点完整解析与易错边界。'
        else:
            raise HTTPException(422,'请输入问题')
    ctx=node_teacher_context(db,node_id,question)
    if mode not in LEARNING_INSTRUCTIONS and not ctx['available']:raise HTTPException(409,'该考点暂未配置对应教师，请选择逻辑、定义、数量、资料或图推考点')
    if mode in LEARNING_INSTRUCTIONS and phase:
        raise HTTPException(422,'答疑、自查和费曼练习不使用专项突破阶段参数')
    # 会话接续与历史恢复：优先服务端持久化历史（跨会话），客户端回传仅作兜底
    session = get_or_create_session(db, node_id, mode, new_session=new_session,
                                    session_id=session_id)
    history = load_session_history(db, session['id']) or list(history or [])
    provider=get_knowledge_provider();candidates=[];source_status='empty'
    try:
        slug=MODULE_NAMESPACE_SLUGS.get(ctx['module'])
        namespace=('gongkao/shenlun' if ctx['node_code'].startswith('gongkao.shenlun.') else 'gongkao/xingce/'+slug if slug else None)
        if ctx['node_code'] and namespace:
            query=ctx['node_name']+' '+question
            evidence=await provider.retrieve(query=query,namespace=namespace,filters={'knowledge_node_code':ctx['node_code']},limit=3)
            if not evidence:
                evidence=await provider.retrieve(query=query,namespace=namespace,filters=None,limit=3)
            candidates=filter_candidate_evidences(evidence,ctx['node_name']+' '+ctx['description'],module=ctx['module'])
            source_status='matched' if candidates else 'empty'
        else: source_status='unmapped'
    except Exception:
        source_status='unavailable'
    evidence_block,evidence_rule=format_evidence_prompt_block(candidates)
    instruction=('先解释概念、适用条件和一个反例，再用一个简短检查问题帮助理解。'
                 if mode=='concept' else '针对用户自述卡点设计突破步骤：定位条件、演示一个明确标为自编的小例子、给一道自测并等待作答；不要凭空诊断用户错因或宣称掌握。')
    if phase:
        instruction=PHASE_INSTRUCTIONS[phase]+'概念问答中，重答指学生重新表述概念与适用条件。'
    if mode in LEARNING_INSTRUCTIONS:
        instruction=LEARNING_INSTRUCTIONS[mode]
    messages=[Message(role='system',content=(
        '你是当前考点的教师助教。知识树定义、公式和教材证据是主要依据，教师规则是补充，须核验适用条件。'
        '聚焦选中的考点；历史对话仅用于衔接，不覆盖当前节点身份和事实。问题超出该考点时提示用户切换相应考点。'
        '示例必须明确标为自编，不冒充老师课堂真题或原话。不能看到图片，不得声称观察了图形。'
        '没有证据时不得伪造教材页码或教师引语；节点信息缺失应说明。'+STUDENT_WORK_RULE+instruction+'\n'+evidence_rule)),
        Message(role='user',content=json.dumps({'selected_node':ctx,'textbook_evidence':evidence_block},ensure_ascii=False))]
    for turn in history[-8:]:messages.append(Message(role=turn['role'],content=turn['content']))
    messages.append(Message(role='user',content=question))
    result=None;status='completed';issues=[]
    try:
        result=await get_model_gateway().generate(task_type='tutor_followup',messages=messages,schema=None,model_policy='BALANCED')
        text=(result.raw_text or '').strip()
        validation=verify_followup_support(text,{},question)
        if not text or not validation.is_valid:
            issues=validation.issues or ['模型返回为空'];raise ValueError('未通过核验')
        if phase in {'hint','transfer'} and hint_leaks_answer(text):
            issues=['提示阶段提前公布了答案'];raise ValueError('提示提前揭示答案')
        if mode == 'self_check' and not any(t['role'] == 'assistant' for t in history) and hint_leaks_answer(text):
            issues=['自查首题提前公布了答案'];raise ValueError('自查提前揭示答案')
        basis='当前知识树信息与匹配教师规则' if ctx['teacher'] else '当前知识树信息（未配置专项教师规则）'
        text=format_followup_references(text,candidates,query=ctx['node_name'],module=ctx['module'],reference_basis=basis)
    except Exception as exc:
        status='failed';issues=issues or ['回答服务暂不可用（'+type(exc).__name__+'）']
        text='本次回答未完成：'+'；'.join(issues)+'。请重试；本次不作为考点掌握情况的判定。'
    # 双轮落库：用户输入 + AI 回复（failed 也落，保留中断证据与上下文连续性）
    append_turn(db, session['id'], 'user', question, phase=phase)
    assistant_turn_id = append_turn(
        db, session['id'], 'assistant', text, phase=phase, status=status,
        meta={'mode': mode, 'knowledge_source': source_status,
              'issues': issues} if status == 'failed' else {'mode': mode})
    return {'node_id':node_id,'teacher':ctx['teacher'],'content':text,'status':status,'phase':phase,'mode':mode,
            'session_id':session['id'],'assistant_turn_id':assistant_turn_id,
            'policies':(ctx['teacher_context'] or {}).get('policies',[]),
            'knowledge_source':{'status':source_status,'candidate_count':len(candidates)},
            'generation':{'model':getattr(result,'model_name',None),'provider':getattr(result,'provider_name',None),'issues':issues}}
