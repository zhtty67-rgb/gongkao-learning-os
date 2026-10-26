"""Persisted orchestration only. Attempts, assessment, tutoring and projections remain authoritative."""
import json
import os
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field
from ..ai.schemas import StrictModel
from ..db import connect
from . import assessor, tutor
from .exam import require_ai_allowed
from .exposure import record_exposure
from .learning_framework import record_error_event, rebuild_error_overlay, rebuild_learning_stage
from .mastery import rebuild_mastery
from .review import rebuild_reviews
from .cat import estimate_ability_theta, difficulty_to_b, fisher_information
from .attempt_verdict import correct_expr


class StartTeaching(StrictModel):
    skill_id: str
    goal: str = Field(min_length=1, max_length=1000)
    review_attempt_id: str | None = None


class TeachingAction(StrictModel):
    action: str = Field(pattern='^(advance|answer|hint)$')
    revision: int = Field(ge=0)
    request_id: str = Field(min_length=1, max_length=100)
    answer: str = Field(default='', max_length=8000)
    confidence: float = Field(default=0.6)
    hint_level: int = Field(default=1, ge=1, le=4)


RECALL = {
    'growth': '不看选项，请回忆增长率的定义、计算公式，以及分母为什么使用基期量。',
    'two_period': '不看选项，请回忆两期比重的比较条件，说明分子增长率与分母增长率如何决定比重升降。',
    'work': '不看选项，请回忆工作总量、效率、时间的关系，以及合作时应该相加的量。',
    'logic': '不看选项，请回忆充分条件 P→Q 的有效推理方向及逆否命题，说明哪些逆向推断无效。',
}
RECALL_RUBRICS = {
    'growth': '必须正确表述增长率=(现期量-基期量)/基期量，并说明基期量是比较基准；不能使用现期量作分母。',
    'two_period': '正的分子分母下，现期比重/基期比重=(1+分子增长率)/(1+分母增长率)；分子增速大于分母则比重上升，反之下降，相等不变。',
    'work': '工作量=效率×时间；合作效率是各效率之和，不能把完成时间相加；完成时间=总量/合作效率。',
    'logic': 'P→Q 可肯前推后、否后推否前，逆否为非Q→非P；不能肯后推前或否前推否后。',
}


def now():
    return datetime.now(timezone.utc).isoformat()


def guard(db, sid=None):
    require_ai_allowed(db, session_id=sid)
    # A fresh PRACTICE session must not provide a bypass around an active exam.
    for exam in db.execute("SELECT id FROM sessions WHERE mode='EXAM' AND status='active'"):
        require_ai_allowed(db, session_id=exam['id'])


def skill(db, sid):
    row = db.execute("SELECT * FROM learning_skills WHERE id=? AND status='active'", (sid,)).fetchone()
    if not row:
        raise HTTPException(404, '正式学习技能不存在')
    return dict(row)


def prerequisite_order(db, target):
    """Stable topological order, with cycle detection even for legacy databases."""
    result, visiting, visited = [], set(), set()
    def walk(node):
        skill(db, node)
        if node in visiting:
            raise HTTPException(409, '前置关系存在环，请先修复课程关系')
        if node in visited:
            return
        visiting.add(node)
        for row in db.execute("SELECT source_skill_id FROM learning_relations WHERE target_skill_id=? AND relation_type='prerequisite' ORDER BY weight DESC,source_skill_id", (node,)):
            walk(row[0])
        visiting.remove(node)
        visited.add(node)
        result.append(node)
    walk(target)
    return result


def questions(db, sid):
    # Require both official skill binding and existing mastery mapping; never invent a mapping.
    rows = [dict(r) for r in db.execute('''SELECT DISTINCT q.* FROM questions q
      JOIN question_skill_bindings b ON b.question_id=q.id
      JOIN question_knowledge_map m ON m.question_id=q.id
      JOIN knowledge_nodes n ON n.id=m.knowledge_node_id
      WHERE b.learning_skill_id=? AND b.status='active' AND q.is_verified=1
      AND COALESCE(json_extract(CASE WHEN json_valid(n.metadata_json) THEN n.metadata_json ELSE '{}' END,'$.mastery_eligible'),1)!=0
      ORDER BY q.difficulty,q.id''', (sid,))]
    return [q for q in rows if len(json.loads(q['options_json']))>=2 and q['answer'] in json.loads(q['options_json'])]


def choose(db, state, sid):
    # Never reuse a checked question or teaching example within this session.
    used = set(state['used_questions'])
    pool = [q for q in questions(db, sid) if q['id'] not in used]
    if not pool:
        raise HTTPException(409, f'{skill(db,sid)["name"]}缺少新的已核验题，请补充题池后继续；未改变学习状态')
    # Prefer independent unseen evidence, not recognition of a previously solved question.
    responses=db.execute(f'''SELECT q.difficulty,{correct_expr(db)} AS correct FROM attempts a
      JOIN questions q ON q.id=a.question_id JOIN question_skill_bindings b ON b.question_id=q.id
      WHERE b.learning_skill_id=? AND b.status='active' AND a.valid_for_stats=1
      AND a.submitted_at IS NOT NULL AND a.hint_level=0 AND a.exposure_state='NO_ASSISTANCE'
      ORDER BY a.submitted_at DESC LIMIT 30''',(sid,)).fetchall()
    theta,_=estimate_ability_theta([(r['difficulty'],r['correct']) for r in responses])
    pool.sort(key=lambda q: (db.execute('SELECT COUNT(*) FROM attempts WHERE question_id=? AND submitted_at IS NOT NULL', (q['id'],)).fetchone()[0], -fisher_information(theta,difficulty_to_b(q['difficulty'])), q['id']))
    return pool[0]


def task(db, state, sid, fmt, q):
    prompt = RECALL.get(sid) if fmt == 'recall' else None
    if fmt == 'recall' and not prompt:
        fmt = 'application'
    return {'skill_id': sid, 'question_id': q['id'], 'format': fmt,
            'prompt': prompt or q['stem'], 'rubric': RECALL_RUBRICS[sid] if fmt=='recall' else q['explanation'],
            'options': json.loads(q['options_json']) if fmt == 'choice' else {},
            'started_at': now()}


def attach_attempt(db, sid, state, check):
    qid = check['question_id']
    position = db.execute('SELECT COUNT(*) FROM session_questions WHERE session_id=?', (sid,)).fetchone()[0]
    db.execute('INSERT INTO session_questions(session_id,question_id,position) VALUES(?,?,?)', (sid, qid, position))
    aid = str(uuid4())
    source = 'AUTO_TEST' if os.environ.get('GONGKAO_ENV') == 'test' else 'REAL_STUDY'
    db.execute('''INSERT INTO attempts(id,question_id,session_id,started_at,mode,source_type,valid_for_stats,exposure_state,attempt_number,time_estimation_method)
      VALUES(?,?,?,?,'PRACTICE',?,?, 'NO_ASSISTANCE',?,'SERVER_MEASURED')''',
      (aid, qid, sid, check['started_at'], source, int(source == 'REAL_STUDY'), 1))
    check['attempt_id'] = aid
    state['used_questions'].append(qid)
    state['check'] = check


def load(db, sid):
    row = db.execute('SELECT * FROM adaptive_teaching_sessions WHERE session_id=?', (sid,)).fetchone()
    if not row:
        raise HTTPException(404, '教学会话不存在')
    return dict(row), json.loads(row['state_json'])


def view(db, sid):
    row, state = load(db, sid)
    guard(db, sid)
    check = state.get('check')
    safe_check = None
    if check and row['phase'] in ('PROBE', 'CHECK'):
        safe_check = {k: v for k, v in check.items() if k not in ('rubric',)}
        q = db.execute('SELECT stem_assets_json,option_assets_json,passage_id FROM questions WHERE id=?', (check['question_id'],)).fetchone()
        safe_check['stem_assets'] = json.loads(q['stem_assets_json'] or '[]') if check['format'] != 'recall' else []
        safe_check['option_assets'] = json.loads(q['option_assets_json'] or '{}') if check['format'] == 'choice' else {}
        passage = db.execute('SELECT content,assets_json FROM question_passages WHERE id=?', (q['passage_id'],)).fetchone() if q['passage_id'] and check['format'] != 'recall' else None
        safe_check['passage'] = {'content': passage['content'], 'assets': json.loads(passage['assets_json'] or '[]')} if passage else None
    local=set(state['boundary'])|set(state['stack'])|{p['skill_id'] for p in state['probes']}|{row['goal_skill_id'],state.get('current')}
    nodes = [{'id': n, 'name': skill(db, n)['name'], 'boundary': state['boundary'].get(n, 'unknown'),
              'mastery': mastery(db,n)} for n in state['order'] if n in local]
    # Teaching progress is routing evidence, not a second mastery estimate.
    return {'id': sid, 'goal': row['goal'], 'goal_skill_id': row['goal_skill_id'],
            'phase': row['phase'], 'revision': row['revision'], 'current_skill_id': state.get('current'),
            'nodes': nodes, 'path': state.get('plan', []), 'return_stack': state['stack'],
            'check': safe_check, 'lesson': state.get('lesson'), 'hint': state.get('hint'),
            'last_result': state.get('last_result'), 'message': state.get('message',''),
            'events': [dict(r) for r in db.execute('SELECT phase,revision,attempt_id,payload_json FROM adaptive_teaching_events WHERE session_id=? ORDER BY revision', (sid,))]}


def mastery(db, sid):
    # Existing projections may map detailed knowledge nodes to a Skill.
    row = db.execute('SELECT mastery_score,attempt_count FROM mastery_state WHERE knowledge_node_id=?', (sid,)).fetchone()
    return dict(row) if row else {'mastery_score': 0.5, 'attempt_count': 0}


def start(db, body):
    guard(db)
    if body.review_attempt_id:
        att = db.execute("SELECT * FROM attempts WHERE id=? AND mode='REVIEW' AND submitted_at IS NOT NULL", (body.review_attempt_id,)).fetchone()
        if not att or (att['corrected_correct'] if att['corrected_correct'] is not None else att['correct']):
            raise HTTPException(422, '需要有效的复习失败记录')
        require_ai_allowed(db, attempt_id=att['id'])
        if not db.execute("SELECT 1 FROM question_skill_bindings WHERE question_id=? AND learning_skill_id=? AND status='active'", (att['question_id'],body.skill_id)).fetchone():
            raise HTTPException(422, '复习题与目标技能不匹配')
    order = prerequisite_order(db, body.skill_id)
    probes = []
    direct=[r[0] for r in db.execute("SELECT source_skill_id FROM learning_relations WHERE relation_type='prerequisite' AND target_skill_id=? ORDER BY weight DESC,source_skill_id",(body.skill_id,))]
    # Start near the goal. Probe deeper ancestors only if a direct prerequisite check fails.
    for n in direct+[body.skill_id]:
        pool = questions(db,n)
        # Need at least two independent forms; no silent skip if content is absent.
        if len(pool) < 2:
            raise HTTPException(409, f'{skill(db,n)["name"]}至少需要两道已核验且已关联掌握度的题目')
        probes.extend([{'skill_id':n,'format':'choice'}, {'skill_id':n,'format':'recall'}])
    state = {'order':order,'boundary':{},'probe_results':{},'probes':probes,'probe_index':0,
             'used_questions':[],'stack':[],'passed':[],'current':None,'failures':{},
             'review_attempt_id':body.review_attempt_id,'message':'先验证目标的前置知识，再检查目标本身；每个节点使用两种方式。'}
    sid = str(uuid4()); stamp = now()
    db.execute("INSERT INTO sessions(id,mode,started_at,status) VALUES(?,'PRACTICE',?,'active')", (sid,stamp))
    p = probes[0]; check = task(db,state,p['skill_id'],p['format'],choose(db,state,p['skill_id']))
    attach_attempt(db,sid,state,check)
    db.execute('INSERT INTO adaptive_teaching_sessions VALUES(?,?,?, ?,0,?,?,?)', (sid,body.skill_id,body.goal,'PROBE',json.dumps(state,ensure_ascii=False),stamp,stamp))
    return view(db,sid)


def snapshot(db, sid, body):
    row,state = load(db,sid); guard(db,sid)
    event = db.execute('SELECT payload_json FROM adaptive_teaching_events WHERE session_id=? AND request_id=?', (sid,body.request_id)).fetchone()
    if event:
        original=json.loads(event[0]).get('request')
        if original != body.model_dump():
            raise HTTPException(409,'请求编号已用于不同操作')
        return row,state,True
    if row['revision'] != body.revision:
        raise HTTPException(409,'学习状态已更新，请刷新后继续')
    phase=row['phase']
    valid = (body.action=='advance' and phase in ('PLAN','TEACH_NODE','UPDATE')) or (body.action=='answer' and phase in ('PROBE','CHECK')) or (body.action=='hint' and phase=='CHECK')
    if not valid:
        raise HTTPException(409,'请先完成当前检查，不能提前推进下一节点')
    if body.action=='answer' and (not body.answer.strip() or body.confidence not in (0.2,0.4,0.5,0.6,0.8,0.9,1.0)):
        raise HTTPException(422,'请填写答案并选择有效信心值')
    return row,state,False


async def act(path, sid, body):
    # Model calls run outside a SQLite write transaction. Commit checks the revision and exam lock again.
    received_at=now()
    with connect(path) as db:
        row,state,duplicate=snapshot(db,sid,body)
        if duplicate:
            return view(db,sid)
        phase=row['phase']; generated=None; q=None; example=None
        if body.action=='answer':
            check=state['check']; q=dict(db.execute('SELECT * FROM questions WHERE id=?',(check['question_id'],)).fetchone())
            if check['format']=='choice' and body.answer not in json.loads(q['options_json']):
                raise HTTPException(422,'请选择有效选项')
            candidates=[skill(db,n) for n in prerequisite_order(db,check['skill_id'])[:-1]]
            other_skills=[{'id':r['id'],'name':r['name']} for r in db.execute("SELECT id,name FROM learning_skills WHERE status='active' AND id!=?",(check['skill_id'],))]
        elif phase=='TEACH_NODE':
            q=choose(db,state,state['current'])
            pool=[e for e in questions(db,state['current']) if e['id']!=q['id'] and e['id'] not in state['used_questions']]
            if not pool:
                raise HTTPException(409,'缺少与检查题不同的核验示例，请补充题池后继续')
            example=pool[0]; node=skill(db,state['current'])
        elif body.action=='hint':
            check=state['check']
            require_ai_allowed(db,attempt_id=check['attempt_id'])
    if body.action=='answer':
        generated=await assessor.assess_teaching_check(q,state['check'],body.answer,candidates,other_skills)
    elif phase=='TEACH_NODE':
        generated=await tutor.teach_single_node(node,example)
    elif body.action=='hint':
        with connect(path) as db:
            guard(db,sid)
            generated=await tutor.generate_hint(db,check['attempt_id'],body.hint_level,persist=False)
    with connect(path) as db:
        db.execute('BEGIN IMMEDIATE')
        row,state,duplicate=snapshot(db,sid,body)
        if duplicate: return view(db,sid)
        event={'request':body.model_dump()}; aid=None
        if body.action=='hint':
            check=state['check']; aid=check['attempt_id']
            db.execute('UPDATE attempts SET hint_level=MAX(hint_level,?) WHERE id=? AND submitted_at IS NULL',(body.hint_level,aid))
            record_exposure(db,question_id=check['question_id'],attempt_id=aid,session_id=sid,
                            exposure_type='HINT',stage='PRE_SUBMISSION',source_action='ADAPTIVE_HINT',details={'hint_level':body.hint_level})
            state['hint']=generated.model_dump(); event['hint_level']=body.hint_level
        elif body.action=='answer':
            check=state['check']; aid=check['attempt_id']
            att=db.execute('SELECT * FROM attempts WHERE id=?',(aid,)).fetchone()
            fresh=db.execute('SELECT answer,explanation,is_verified FROM questions WHERE id=?',(check['question_id'],)).fetchone()
            if not fresh['is_verified'] or (fresh['answer'],fresh['explanation'])!=(q['answer'],q['explanation']):
                raise HTTPException(409,'题目答案或评分依据已更新，请重新提交检查')
            if att['submitted_at']:
                raise HTTPException(409,'检查已提交，不能覆盖原始作答')
            is_correct=generated.correct
            if check['format']!='choice' and generated.confidence<0.75:
                raise HTTPException(409,'评分依据不足，未更新作答或掌握度；请补充理由后重试')
            selected=body.answer if check['format']=='choice' else (q['answer'] if is_correct else next(k for k in json.loads(q['options_json']) if k!=q['answer']))
            stamp=received_at; elapsed=max(0,int((datetime.fromisoformat(stamp)-datetime.fromisoformat(att['started_at'])).total_seconds()*1000))
            db.execute('''UPDATE attempts SET submitted_at=?,elapsed_ms=?,raw_elapsed_ms=?,timing_valid=?,selected_answer=?,correct=?,confidence=?,audit_note=? WHERE id=?''',
                       (stamp,elapsed,elapsed,int(1000<=elapsed<=14400000),selected,int(is_correct),body.confidence,
                        'Adaptive CHECK: 自由回答原文与评分依据见教学事件；选项字段是规范化判分结果' if check['format']!='choice' else 'Adaptive CHECK',aid))
            if generated.provider=='mock':
                db.execute("UPDATE attempts SET source_type='DEMO',valid_for_stats=0 WHERE id=?",(aid,))
            # A correct answer with hints cannot advance the node; arrange a new independent check.
            passed=bool(is_correct and att['hint_level']==0 and att['exposure_state']!='ASSISTED')
            result={'attempt_id':aid,'skill_id':check['skill_id'],'correct':is_correct,'passed':passed,
                    'format':check['format'],'feedback':generated.feedback,'diagnosis':generated.model_dump(),
                    'hint_level':att['hint_level'],'raw_answer':body.answer,'assessment_provider':generated.provider}
            state['last_result']=result; state['hint']=None; event['result']=result
            event['check_specification']=check
            event['answer_key_at_assessment']=q['answer']
            if not is_correct:
                target=generated.missing_skill_id
                allowed={n['id'] for n in candidates} if generated.failure_kind=='prerequisite_gap' else {n['id'] for n in other_skills} if generated.failure_kind=='other_skill' else set()
                actual=target if target in allowed and generated.confidence>=0.75 else check['skill_id']
                record_error_event(db,attempt_id=aid,error_type=generated.error_type,actual_error_skill_id=actual,
                                   diagnosis_source='assessor',diagnosis_confidence=generated.confidence,explanation=generated.feedback)
            rebuild_mastery(db); rebuild_reviews(db); rebuild_error_overlay(db); rebuild_learning_stage(db)
            schedule=db.execute('SELECT due FROM review_cards WHERE question_id=?',(check['question_id'],)).fetchone()
            result['review_due']=schedule[0] if schedule else None
            if phase=='PROBE':
                n=check['skill_id']; state['probe_results'].setdefault(n,[]).append(passed)
                state['boundary'][n]='provisional' if passed else 'needs_learning'
                if len(state['probe_results'][n])==2:
                    state['boundary'][n]='verified' if all(state['probe_results'][n]) else 'needs_learning'
                    if state['boundary'][n]=='needs_learning':
                        scheduled={p['skill_id'] for p in state['probes']}
                        deeper=[r[0] for r in db.execute("SELECT source_skill_id FROM learning_relations WHERE target_skill_id=? AND relation_type='prerequisite' ORDER BY weight DESC,source_skill_id",(n,)) if r[0] not in scheduled]
                        available=[]
                        for p in deeper:
                            if len(questions(db,p))>=2: available.append(p)
                            else: state['boundary'][p]='needs_learning'
                        more=[{'skill_id':p,'format':f} for p in available for f in ('choice','recall')]
                        state['probes'][state['probe_index']+1:state['probe_index']+1]=more
                state['probe_index']+=1
                if state['probe_index']<len(state['probes']):
                    p=state['probes'][state['probe_index']]
                    attach_attempt(db,sid,state,task(db,state,p['skill_id'],p['format'],choose(db,state,p['skill_id'])))
                else:
                    row['phase']='PLAN';state['check']=None
                state['message']='边界验证已保存；选择题正确仍需自由回忆或应用验证。'
            else:
                row['phase']='UPDATE'; state['check']=None
                state['message']='检查结果已写入正式作答、掌握度和复习调度。'
        elif phase=='PLAN':
            state['plan']=[n for n in state['order'] if state['boundary'].get(n)=='needs_learning']
            if state['plan']:
                state['current']=state['plan'][0];row['phase']='TEACH_NODE'
                state['message']='已跳过通过两种边界验证的节点；本轮只学习一个节点。'
            else: row['phase']='COMPLETE';state['message']='本次边界验证已通过，仍需后续间隔复习验证保持情况。'
        elif phase=='TEACH_NODE':
            state['lesson']=generated.model_dump();state['used_questions'].append(example['id'])
            check=task(db,state,state['current'],'application',q)
            attach_attempt(db,sid,state,check);row['phase']='CHECK'
            event['lesson']=state['lesson'];event['example_question_id']=example['id']
            state['message']='请独立应用刚才的一个概念；通过检查前不会展开下一节点。'
        elif phase=='UPDATE':
            result=state['last_result']; current=state['current']
            if result['passed']:
                state['boundary'][current]='verified';state['passed'].append(current)
                if state['stack']:
                    state['current']=state['stack'].pop();state['message']='前置节点检查通过，返回原节点，用新题再次独立检查。'
                    row['phase']='TEACH_NODE'
                else:
                    remaining=[n for n in state['plan'] if state['boundary'].get(n)!='verified']
                    if remaining:
                        state['current']=remaining[0];row['phase']='TEACH_NODE';state['message']='当前节点检查通过，推进下一个相关节点。'
                    else: row['phase']='COMPLETE';state['message']='本次学习路径完成；新掌握情况需要延迟复习继续验证。'
            else:
                diagnosis=result['diagnosis']; missing=diagnosis.get('missing_skill_id')
                allowed=prerequisite_order(db,current)[:-1]
                if diagnosis['failure_kind']=='prerequisite_gap' and missing in allowed and diagnosis['confidence']>=0.75:
                    if missing in state['stack']:
                        raise HTTPException(409,'检测到重复补救路径，请核对前置关系')
                    state['stack'].append(current);state['current']=missing;state['boundary'][missing]='needs_learning'
                    state['message']='本题诊断发现前置缺口，先补该节点，通过后返回原节点。'
                elif diagnosis['failure_kind']=='other_skill' and missing and diagnosis['confidence']>=0.75:
                    skill(db,missing)
                    if missing==current or missing in state['stack']:
                        raise HTTPException(409,'诊断产生重复路径，请核对错因')
                    # Explicit remediation from existing official ontology, not an invented DAG edge.
                    if len(questions(db,missing))<2:
                        state['message']='已记录其他技能错因，但补救题池不足，请先补充核验题。'
                        raise HTTPException(409,state['message'])
                    state['stack'].append(current);state['current']=missing
                    if missing not in state['order']: state['order'].append(missing)
                    state['message']='错因属于另一正式技能，先进行针对性补救，再返回原节点。'
                else:
                    state['message']='未确认前置缺口；保留当前节点，依据具体错因换一个示例与新题检查。'
                state['failures'][current]=state['failures'].get(current,0)+1
                row['phase']='TEACH_NODE'
            state['lesson']=None;state['hint']=None
        if row['phase']=='COMPLETE':
            state['current']=None
            db.execute("UPDATE sessions SET status='completed',completed_at=? WHERE id=?",(now(),sid))
        revision=row['revision']+1
        db.execute('UPDATE adaptive_teaching_sessions SET phase=?,revision=?,state_json=?,updated_at=? WHERE session_id=?',
                   (row['phase'],revision,json.dumps(state,ensure_ascii=False),now(),sid))
        db.execute('INSERT INTO adaptive_teaching_events VALUES(?,?,?,?,?,?,?,?)',
                   (str(uuid4()),sid,body.request_id,revision,phase,aid,json.dumps(event,ensure_ascii=False),now()))
        return view(db,sid)
