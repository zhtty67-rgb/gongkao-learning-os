"""Domain services for Shenlun Training: multi-version drafts, revision diff, and 5D structured assessment."""
from datetime import datetime, timezone
import difflib
import json
from uuid import uuid4
from fastapi import HTTPException
from pydantic import Field

from ..ai import Message, get_model_gateway
from ..ai.schemas import StrictModel
from .daily_goal import today, small_question_ids, completed_small_question_ids
from .shenlun_guidance import get_guidance, get_point_trace, mark_submitted, assess_point_trace, require_shenlun_ai
from .shenlun_teacher import (
    answer_hash,
    apply_semantic_review,
    get_latest_teacher_diagnosis,
    run_teacher_diagnosis,
)


class ShenlunAssessmentOutput(StrictModel):
    coverage: float = Field(ge=0.0, le=1.0)
    abstraction: float = Field(ge=0.0, le=1.0)
    precision: float = Field(ge=0.0, le=1.0)
    structure: float = Field(ge=0.0, le=1.0)
    conciseness: float = Field(ge=0.0, le=1.0)
    overall_score: float = Field(ge=0.0, le=100.0)
    missing_points: list[str] = Field(default_factory=list)
    redundant_points: list[str] = Field(default_factory=list)
    weak_abstractions: list[str] = Field(default_factory=list)
    wording_issues: list[str] = Field(default_factory=list)
    next_action: str = Field(min_length=1)


def compute_revision_diff(draft_a: str, draft_b: str) -> str:
    """Generate clean unified diff showing edits from draft A to final answer B."""
    lines_a = draft_a.splitlines(keepends=True)
    lines_b = draft_b.splitlines(keepends=True)
    diff = difflib.unified_diff(
        lines_a, lines_b,
        fromfile='初稿 (first_draft)',
        tofile='终稿 (final_answer)',
        n=2,
    )
    return ''.join(diff)


def start_shenlun_session(db, material_id: str | None = None, *, daily: bool = False, next_task: bool = False) -> dict:
    """Create or resume a Shenlun practice session."""
    # Find or default material
    mat = None
    if next_task and not daily:
        raise HTTPException(422, '继续下一题须使用每日任务模式')
    if daily:
        eligible = small_question_ids(db)
        done = completed_small_question_ids(db, today())
        if not eligible:
            raise HTTPException(404, '暂无材料完整、题干明确的申论小题')
        if material_id and material_id not in eligible:
            raise HTTPException(422, '该材料不属于每日小题候选；可在普通申论模式中打开')
        if not material_id:
            sessions = db.execute(
                """SELECT material_id,status,date(completed_at,'+8 hours') completed_date
                   FROM shenlun_sessions ORDER BY (status='active') DESC, started_at DESC, id DESC"""
            ).fetchall()
            for row in sessions:
                if row['material_id'] not in eligible:
                    continue
                if row['status'] == 'active' or (not next_task and row['material_id'] in done and row['completed_date'] == today()):
                    material_id = row['material_id']
                    break
            if not material_id:
                candidates = db.execute(
                    """SELECT m.id FROM shenlun_materials m
                       LEFT JOIN shenlun_sessions s ON s.material_id=m.id AND s.status='completed'
                       GROUP BY m.id ORDER BY COALESCE(MAX(s.completed_at),'') ASC, m.id ASC"""
                ).fetchall()
                material_id = next((r['id'] for r in candidates if r['id'] in eligible-done), None)
            if not material_id:
                raise HTTPException(409, '今日可用小题已练完，请补充题目或复盘已完成的作答')
        elif next_task and material_id in done:
            raise HTTPException(409, '该题今日已完成，请选择其他小题')
    if material_id:
        mat = db.execute('SELECT * FROM shenlun_materials WHERE id=?', (material_id,)).fetchone()
    if not mat:
        mat = db.execute('SELECT * FROM shenlun_materials ORDER BY exam_year DESC, id ASC LIMIT 1').fetchone()
    if not mat:
        raise HTTPException(404, '暂无可用的申论试题材料')

    mat_dict = dict(mat)
    mat_dict['materials'] = json.loads(mat_dict.pop('materials_json'))

    # 优先恢复进行中的会话；否则恢复同材料最近一次会话（刷新后可回到已完成的
    # 工作台：作答、诊断与追问历史保持可续看），没有任何会话时才新建。
    daily_filter = "AND (status='active' OR date(completed_at,'+8 hours')=?)" if daily else ''
    active = db.execute(
        f'''SELECT * FROM shenlun_sessions
           WHERE material_id=? {daily_filter}
           ORDER BY (status="active") DESC, started_at DESC, id DESC LIMIT 1''',
        (mat_dict['id'], today()) if daily else (mat_dict['id'],),
    ).fetchone()
    if active:
        sess_dict = dict(active)
        sess_dict['notes'] = json.loads(sess_dict.pop('notes_json'))
        sess_dict['material'] = mat_dict
        sess_dict['teacher_diagnosis'] = get_latest_teacher_diagnosis(db, sess_dict['id'])
        if not sess_dict['final_answer']:
            mat_dict['reference_answer'] = ''
        sess_dict['guidance'] = get_guidance(db, sess_dict['id'])
        sess_dict['point_trace'] = get_point_trace(db, sess_dict['id'])
        sess_dict['assessment'] = latest_assessment(db, sess_dict['id'], sess_dict['final_answer'])
        return sess_dict

    sid = str(uuid4())
    now_iso = datetime.now(timezone.utc).isoformat()
    db.execute(
        '''INSERT INTO shenlun_sessions (id, material_id, status, started_at, notes_json, created_at)
           VALUES (?,?,?,?,?,?)''',
        (sid, mat_dict['id'], 'active', now_iso, '{}', now_iso),
    )
    db.commit()

    mat_dict['reference_answer'] = ''
    return {
        'id': sid,
        'material_id': mat_dict['id'],
        'status': 'active',
        'started_at': now_iso,
        'notes': {},
        'first_draft': None,
        'final_answer': None,
        'revision_diff': None,
        'teacher_diagnosis': None,
        'material': mat_dict,
        'guidance': get_guidance(db, sid),
        'point_trace': None,
    }


def save_shenlun_draft(db, session_id: str, draft_text: str, notes: dict | None = None) -> dict:
    """Save user notes and record the initial draft if not already set."""
    sess = db.execute('SELECT * FROM shenlun_sessions WHERE id=?', (session_id,)).fetchone()
    if not sess:
        raise HTTPException(404, '申论会话不存在')

    notes_json = json.dumps(notes or {}, ensure_ascii=False)
    first_draft = sess['first_draft'] or draft_text

    db.execute(
        '''UPDATE shenlun_sessions
           SET notes_json=?, first_draft=?
           WHERE id=?''',
        (notes_json, first_draft, session_id),
    )
    db.commit()
    return {'session_id': session_id, 'saved': True, 'has_first_draft': bool(first_draft)}


_in_progress_assessments: set[tuple[str, str]] = set()  # (session_id, answer_hash)


async def submit_shenlun_assessment(db, session_id: str, final_answer: str) -> dict:
    """Evaluate final Shenlun submission: save answer first, then run teacher
    diagnosis and the 5D reference assessment independently.

    失败分离：作答保存 → 教师诊断（本地+AI 审查）→ 五维参考评价。
    五维评分失败不丢失答案、不影响教师反馈的查看与讨论；重试不重复累计成绩
    （同一会话同一作答版本的评分只保留一份）。
    """
    require_shenlun_ai(db)
    sess = db.execute(
        '''SELECT s.*, m.title, m.materials_json, m.question_stem, m.reference_answer, m.max_words
           FROM shenlun_sessions s
           JOIN shenlun_materials m ON m.id=s.material_id
           WHERE s.id=?''',
        (session_id,),
    ).fetchone()

    if not sess:
        raise HTTPException(404, '申论会话不存在')
    if not final_answer.strip():
        raise HTTPException(400, '作答内容不能为空')

    first_draft = sess['first_draft'] or final_answer
    rev_diff = compute_revision_diff(first_draft, final_answer)
    now_iso = datetime.now(timezone.utc).isoformat()
    ahash = answer_hash(final_answer)

    # 1) 先可靠保存本次作答与版本（先于任何外部模型调用）：
    #    五维评分或审查失败都不会丢失答案，诊断/评分/追问都绑定该版本。
    db.execute(
        '''UPDATE shenlun_sessions
           SET first_draft=?, final_answer=?, revision_diff=?, status='completed', completed_at=?
           WHERE id=?''',
        (first_draft, final_answer, rev_diff, now_iso, session_id),
    )
    db.commit()

    mark_submitted(db, session_id)
    db.commit()
    # 2) 教师诊断两阶段：本地疑点检测落库（零模型调用，绝不阻塞主流程），
    #    再做 AI 受约束语义审查 + 程序核验。审查失败时诊断仍以"疑点待确认"形态可用。
    teacher_diagnosis = run_teacher_diagnosis(db, sess, final_answer)
    db.commit()
    try:
        await apply_semantic_review(db, session_id, final_answer)
        db.commit()
        if teacher_diagnosis is not None:
            refreshed = get_latest_teacher_diagnosis(db, session_id)
            if refreshed is not None:
                teacher_diagnosis = refreshed
    except Exception:
        db.rollback()  # 审查失败不阻塞主提交，诊断保持 pending 状态可查

    materials_list = json.loads(sess['materials_json'])
    mat_content = '\n\n'.join(f"【{m['title']}】\n{m['content']}" for m in materials_list)

    # 3) 五维参考评价（AI 生成，非官方阅卷）。失败不影响已保存的作答与教师反馈。
    assessment_payload: dict | None = None
    assessment_error = ''
    task_5d_key = (session_id, ahash)
    if task_5d_key in _in_progress_assessments:
        assessment_error = '五维参考评价正在处理中，请稍候查看。'
    else:
        try:
            # 重试去重：同一会话同一作答版本已有评分则直接复用，不重复累计成绩
            existing = db.execute(
                '''SELECT * FROM shenlun_assessments
                   WHERE session_id=? AND assessment_stage='final_answer' AND answer_hash=?
                   ORDER BY created_at DESC, id DESC LIMIT 1''',
                (session_id, ahash),
            ).fetchone()
            if existing is not None:
                assessment_payload = {
                    'coverage': existing['coverage'], 'abstraction': existing['abstraction'],
                    'precision': existing['precision'], 'structure': existing['structure'],
                    'conciseness': existing['conciseness'], 'overall_score': existing['overall_score'],
                    'missing_points': json.loads(existing['missing_points_json']),
                    'redundant_points': json.loads(existing['redundant_points_json']),
                    'weak_abstractions': json.loads(existing['weak_abstractions_json']),
                    'wording_issues': json.loads(existing['wording_issues_json']),
                    'next_action': existing['next_action'],
                }
            else:
                _in_progress_assessments.add(task_5d_key)
                try:
                    messages = [
                        Message(
                            role='system',
                            content=(
                                '你是申论批改的参考评价助手（AI 生成，非官方阅卷结论）。\n'
                                '严格职责：依据参考采分要点进行【五维结构化诊断评分】，指出学生的遗漏点与逻辑缺陷。\n'
                                '严谨要求：\n'
                                '1. 必须返回符合严格 JSON Schema 的评分结构，禁止输出一大段空洞的散文式客套。\n'
                                '2. 严禁直接替用户重写整篇满分答案；给出具体的采分盲区与修改动作指引。\n'
                                '3. 五个维度得分（0.0 ~ 1.0）：\n'
                                '   - coverage: 要点覆盖度（材料核心事实与采分词是否全面齐全）\n'
                                '   - abstraction: 概括抽象度（是否跳出材料口语，提炼出规范化政务动词/概念）\n'
                                '   - precision: 表述精准度（信息转述是否精准无偏差）\n'
                                '   - structure: 结构条理性（是否分类归纳、分条列项、主谓清晰）\n'
                                '   - conciseness: 语言精炼度（是否剔除无意义副词细节，控制在规定字数内）\n'
                                '4. overall_score: 综合百分制折算得分（0 ~ 100）。'
                            ),
                        ),
                        Message(
                            role='user',
                            content=(
                                f'【给定资料】：\n{mat_content}\n\n'
                                f'【作答题目】：{sess["question_stem"]}（限字数：{sess["max_words"]} 字）\n'
                                f'【参考采分要点】：\n{sess["reference_answer"]}\n\n'
                                f'【考生作答初稿】：\n{first_draft}\n\n'
                                f'【考生修改终稿】：\n{final_answer}\n\n'
                                '请对考生的终稿进行五维诊断评分。'
                            ),
                        ),
                    ]

                    gateway = get_model_gateway()
                    res = await gateway.generate(
                        task_type='shenlun_assessment',
                        messages=messages,
                        schema=ShenlunAssessmentOutput,
                        model_policy='STRONG',
                    )
                    assessment: ShenlunAssessmentOutput = res.data

                    # 串版防护：评分等待期间用户重新提交（会话作答已变化）→ 不保存本结果
                    sess_now = db.execute(
                        'SELECT final_answer FROM shenlun_sessions WHERE id=?', (session_id,)
                    ).fetchone()
                    if sess_now is None or answer_hash(sess_now['final_answer'] or '') != ahash:
                        assessment_error = '评分期间作答已更新，本结果未保存；请以最新一次提交为准。'
                    else:
                        aid = str(uuid4())
                        db.execute(
                            '''INSERT INTO shenlun_assessments
                               (id, session_id, assessment_stage, coverage, abstraction, precision, structure,
                                conciseness, overall_score, missing_points_json, redundant_points_json,
                                weak_abstractions_json, wording_issues_json, next_action, created_at, answer_hash)
                               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (
                                aid, session_id, 'final_answer',
                                assessment.coverage, assessment.abstraction, assessment.precision,
                                assessment.structure, assessment.conciseness, assessment.overall_score,
                                json.dumps(assessment.missing_points, ensure_ascii=False),
                                json.dumps(assessment.redundant_points, ensure_ascii=False),
                                json.dumps(assessment.weak_abstractions, ensure_ascii=False),
                                json.dumps(assessment.wording_issues, ensure_ascii=False),
                                assessment.next_action, now_iso, ahash,
                            ),
                        )
                        # Rebuild Shenlun Learner Model deterministically from all historical assessments
                        rebuild_shenlun_mastery(db)
                        assessment_payload = assessment.model_dump()
                finally:
                    _in_progress_assessments.discard(task_5d_key)
        except Exception as exc:
            assessment_error = f'五维参考评价暂不可用（{type(exc).__name__}），答案与教师反馈已保存，可稍后重试。'

    db.commit()

    point_trace = await assess_point_trace(db, session_id, final_answer, assessment_payload)
    return {
        'session_id': session_id,
        'status': 'completed',
        'first_draft': first_draft,
        'final_answer': final_answer,
        'revision_diff': rev_diff,
        'assessment': assessment_payload,
        'assessment_error': assessment_error,
        'teacher_diagnosis': teacher_diagnosis,
        'reference_answer': sess['reference_answer'],  # unlocked after submission
        'guidance': get_guidance(db, session_id),
        'point_trace': point_trace,
    }


def rebuild_shenlun_mastery(db):
    """Deterministic projection rebuilding shenlun_mastery_state from raw immutable shenlun_assessments.
    
    Source of truth: shenlun_assessments table.
    Deterministic Policy:
      - Initial state: 0.5 (count = 0)
      - Bayesian evidence updating: score = (0.5 * 1.0 + sum(dim_scores)) / (1.0 + N)
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    # Reset baseline
    db.execute('DELETE FROM shenlun_mastery_state')
    db.execute(
        '''INSERT INTO shenlun_mastery_state (skill_key, skill_name, score, evaluation_count, updated_at) VALUES
           ('information_extraction', '材料信息提取', 0.5, 0, ?),
           ('information_synthesis', '同类要点合并', 0.5, 0, ?),
           ('abstraction', '宏观抽象提升', 0.5, 0, ?),
           ('language_conciseness', '语言精炼压缩', 0.5, 0, ?),
           ('structure_organization', '论述结构组织', 0.5, 0, ?)''',
        (now_iso, now_iso, now_iso, now_iso, now_iso),
    )

    rows = db.execute(
        '''SELECT coverage, abstraction, precision, structure, conciseness, created_at
           FROM shenlun_assessments
           ORDER BY created_at ASC, id ASC'''
    ).fetchall()
    if not rows:
        return

    n = len(rows)
    dim_sums = {
        'information_extraction': sum(r['coverage'] for r in rows),
        'information_synthesis': sum(r['precision'] for r in rows),
        'abstraction': sum(r['abstraction'] for r in rows),
        'language_conciseness': sum(r['conciseness'] for r in rows),
        'structure_organization': sum(r['structure'] for r in rows),
    }

    for skill_key, total_score in dim_sums.items():
        score = (0.5 * 1.0 + total_score) / (1.0 + n)
        db.execute(
            '''UPDATE shenlun_mastery_state
               SET score=?, evaluation_count=?, updated_at=?
               WHERE skill_key=?''',
            (round(score, 4), n, now_iso, skill_key),
        )


def get_shenlun_mastery_model(db) -> list[dict[str, Any]]:
    """Return all dimensions of the Shenlun Learner Model."""
    rows = db.execute(
        'SELECT skill_key, skill_name, score, evaluation_count, updated_at FROM shenlun_mastery_state ORDER BY skill_key'
    ).fetchall()
    return [dict(r) for r in rows]


def latest_assessment(db, session_id, answer):
    if not answer:
        return None
    row = db.execute("SELECT * FROM shenlun_assessments WHERE session_id=? AND answer_hash=? AND assessment_stage='final_answer' ORDER BY created_at DESC,id DESC LIMIT 1",
                     (session_id, answer_hash(answer))).fetchone()
    if not row:
        return None
    data = {key: row[key] for key in ('coverage', 'abstraction', 'precision', 'structure', 'conciseness', 'overall_score', 'next_action')}
    for key in ('missing_points', 'redundant_points', 'weak_abstractions', 'wording_issues'):
        data[key] = json.loads(row[key + '_json'])
    return data


def list_shenlun_materials(db) -> list[dict]:
    """列出题库中全部申论试题概要及解析状态。"""
    rows = db.execute(
        '''SELECT id, title, exam_year, question_stem, max_words,
                  length(materials_json) as mat_len,
                  length(reference_answer) as ans_len
           FROM shenlun_materials
           ORDER BY exam_year DESC, id ASC'''
    ).fetchall()
    return [
        {
            'id': r['id'],
            'title': r['title'],
            'exam_year': r['exam_year'],
            'question_stem': r['question_stem'],
            'max_words': r['max_words'],
            'has_reference_answer': bool(r['ans_len'] and r['ans_len'] > 20),
        }
        for r in rows
    ]


def get_shenlun_material_detail(db, material_id: str) -> dict:
    """获取单道申论试题的完整材料、题干与官方参考解析。"""
    row = db.execute('SELECT * FROM shenlun_materials WHERE id=?', (material_id,)).fetchone()
    if not row:
        raise HTTPException(404, '试题不存在')
    d = dict(row)
    d['materials'] = json.loads(d.pop('materials_json'))
    unlocked = db.execute('SELECT 1 FROM shenlun_sessions WHERE material_id=? AND final_answer IS NOT NULL AND length(trim(final_answer))>0 LIMIT 1', (material_id,)).fetchone()
    if not unlocked:
        d['reference_answer'] = ''
    d['reference_unlocked'] = bool(unlocked)
    return d

