import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Literal
import uuid
from uuid import uuid4

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Query, File, UploadFile, Form, BackgroundTasks, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai.schemas import GatewayError

from .db import connect, default_path, migrate, ROOT
from .adaptive_router import teaching_router
from .domain.analytics import ERROR_LABELS, dashboard, get_credibility_audit, latest_error_cte
from .domain.attempt_verdict import correct_expr, correction_note
from .domain.exposure import record_exposure
from .domain.assessor import generate_diagnosis
from .domain.notes import (
    NoteVersionConflictError,
    create_or_update_note,
    delete_note,
    get_note_by_id,
    list_user_notes,
    _UNSET,
)
from .domain.interactive_assessor import (
    apply_user_diagnosis_feedback,
    continue_interactive_review,
    generate_step_by_step_explanation,
    get_interactive_review_detail,
    get_user_review_preference,
    initiate_interactive_diagnosis,
    set_review_cause,
    set_user_review_preference,
)
from .domain.guided_teacher_review import get_guided_review, guided_review_turn
from .domain.calibration import calculate_calibration
from .domain.cat import (
    estimate_ability_theta,
    select_cat_question,
    should_stop_cat,
    theta_to_ability_band,
    theta_to_percentile,
)
from .domain.exam import (
    compose_practice_questions,
    compose_real_exam_questions,
    require_ai_allowed,
    start_mock_exam,
    submit_exam_paper,
)
from .domain.importer.schemas import (
    BatchPublishInput,
    ParsedDocument,
    ReclassifyInput,
    ReviewDecisionInput,
    ValidationStatus,
)
from .domain.importer.service import QuestionImportService
from .domain.learning_framework import (
    get_attempt_error_location,
    get_knowledge_map_summary,
    get_learning_framework,
    get_learning_skill_tree,
    get_question_learning_map,
    rebuild_error_overlay,
    rebuild_learning_stage,
    record_error_event,
)
from .domain.mastery import overall_mastery, rebuild_mastery
from .domain.daily_goal import daily_goal
from .domain.planner import generate_daily_plan
from .domain.module_teacher_service import ModuleTeacherService
from .domain.node_teacher_chat import node_teacher_context, answer_node_teacher
from .domain.question_selection import POLICY_VERSION, select_questions
from .domain.question_sources import source_catalog, find_references, resolve_reference, source_context
from .domain.review import due_reviews, rebuild_reviews
from .domain.shenlun import (
    get_shenlun_mastery_model,
    get_shenlun_material_detail,
    list_shenlun_materials,
    save_shenlun_draft,
    start_shenlun_session,
    submit_shenlun_assessment,
)
from .domain.shenlun_guidance import GuideInput, get_guidance, guide_turn, get_point_trace, require_shenlun_ai, assess_point_trace
try:
    from .domain.shenlun_teacher import (
        answer_teacher_followup,
        get_latest_teacher_diagnosis,
        get_teacher_followups,
    )
except ImportError:
    answer_teacher_followup = None
    get_latest_teacher_diagnosis = None
    get_teacher_followups = None
from .domain.tutor import generate_explanation, generate_hint, get_attempt_followups, answer_followup
from .knowledge import (
    audit_retrieval_quality,
    filter_candidate_evidences,
    get_knowledge_provider,
    KnowledgeHubProvider,
    KnowledgeProviderError,
)
from . import settings_service
from time import perf_counter
from .schemas import (
    AdaptiveSessionInput,
    Answer,
    CreateImportJobInput,
    DailyPlanInput,
    ErrorEventInput,
    HintRequest,
    KnowledgeRetrieveInput,
    ProcessImportJobInput,
    QuestionSkillBindInput,
    ShenlunDraftInput,
    ShenlunSessionInput,
    ShenlunSubmitInput,
    StartExamInput,
    StructuredErrorInput,
    InteractiveDiagnosisFeedbackInput,
    InteractiveReviewChatInput,
    SetReviewCauseInput,
    UpdateReviewPreferenceInput,
)


class CreateNoteInput(BaseModel):
    note_id: str | None = None
    expected_version: int | None = None
    note_type: Literal['question', 'knowledge_node', 'dialogue_clipping', 'shenlun_summary'] = 'question'
    content: str | None = None
    title: str | None = None
    question_id: str | None = None
    attempt_id: str | None = None
    knowledge_node_id: str | None = None
    knowledge_node_code: str | None = None
    module: str | None = None
    source_type: Literal['manual', 'review_ai_message', 'review_user_message', 'shenlun_dimension'] = 'manual'
    source_message_id: str | None = None
    source_quote: str | None = None
    metadata: dict[str, Any] | None = None


class ClipReviewMessageInput(BaseModel):
    message_content: str
    source_message_id: str | None = None
    turn_type: str = "review_chat"
    message_role: Literal["user", "assistant"] = "assistant"
    title: str | None = None


class AssociateNodeInput(BaseModel):
    knowledge_node_id: str | None = None
    expected_version: int | None = None


class ManualQuestionInput(BaseModel):
    module: str
    knowledge_node_id: str
    stem: str
    options: dict[str, str]
    answer: Literal['A', 'B', 'C', 'D']
    explanation: str
    source: str = '手动录入'
    year: int | None = None
    difficulty: float = 0.6
    estimated_seconds: int = 60


class UpdateQuestionInput(BaseModel):
    answer: Literal['A', 'B', 'C', 'D'] | None = None
    explanation: str | None = None
    stem: str | None = None
    options: dict[str, str] | None = None
    knowledge_node_id: str | None = None


class BatchAnswersInput(BaseModel):
    answers: dict[str, str]


class GroupAnswerItem(BaseModel):
    question_id: str
    attempt_id: str | None = None
    selected_answer: str | None = None
    confidence: float | None = None
    changed_answer: bool = False
    elapsed_ms: int | None = None


class GroupSubmitInput(BaseModel):
    answers: list[GroupAnswerItem]
    total_elapsed_ms: int = 0
    paused_ms: int = 0


class NodeTeacherTurn(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=8000)


class NodeTeacherInput(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    mode: Literal['concept', 'breakthrough', 'qa', 'self_check', 'feynman'] = 'concept'
    history: list[NodeTeacherTurn] = Field(default_factory=list, max_length=8)
    phase: Literal['hint', 'explain', 'direct', 'transfer', 'check_transfer'] | None = None


class GuidedReviewInput(BaseModel):
    action: Literal['thought', 'dont_know', 'retry', 'hint', 'direct', 'full', 'transfer', 'check_transfer', 'followup', 'ask']
    message: str = Field(default='', max_length=2000)
    answer: str = Field(default='', max_length=10)
    request_id: str = Field(min_length=1, max_length=100)


class FollowUpInput(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    diagnosis: dict[str, Any] | None = None


class ShenlunTeacherFollowUpInput(BaseModel):
    """申论教师追问输入：question 必填；user_attribution 为用户自己的最终错因归属（可选）；
    intent 显式声明意图（question=答疑 / objection=复核诊断），auto=按关键词启发式判断。"""
    question: str = Field(min_length=1, max_length=1000)
    user_attribution: str = Field(default='', max_length=1000)
    intent: str = Field(default='auto', pattern='^(auto|question|objection)$')




def now():
    return datetime.now(timezone.utc).isoformat()


def require_session(db, sid):
    row = db.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
    if row is None:
        raise HTTPException(404, '训练会话不存在')
    return dict(row)


def pending_view(db, row):
    question = dict(db.execute('SELECT id,source,year,exam_type,subject,module,stem,options_json,difficulty,estimated_seconds,is_verified,stem_assets_json,option_assets_json,passage_id FROM questions WHERE id=?', (row['question_id'],)).fetchone())
    question['options'] = json.loads(question.pop('options_json'))
    original_source = source_context(db, row['session_id'], row['question_id'])
    if original_source:
        question['source'] = original_source['source'] + ' · ' + original_source['source_locator']
        question['source_reference_id'] = original_source['reference_id']
    question['is_verified'] = bool(question['is_verified'])
    stem_raw = question.pop('stem_assets_json', '[]') or '[]'
    opt_raw = question.pop('option_assets_json', '{}') or '{}'
    question['stem_assets'] = json.loads(stem_raw) if isinstance(stem_raw, str) else stem_raw
    question['option_assets'] = json.loads(opt_raw) if isinstance(opt_raw, str) else opt_raw
    passage_id = question.pop('passage_id', None)
    question['passage'] = None
    if passage_id:
        p_row = db.execute('SELECT id,content,assets_json FROM question_passages WHERE id=?', (passage_id,)).fetchone()
        if p_row:
            question['passage'] = {
                'id': p_row['id'],
                'content': p_row['content'],
                'assets': json.loads(p_row['assets_json'] or '[]'),
            }
    selection = selection_view(db, row['session_id'], row['question_id'])
    return {
        'done': False, 'attempt_id': row['id'], 'mode': row['mode'],
        'started_at': row['started_at'], 'server_now': now(), 'question': question,
        'selection': selection,
    }


def result_view(db, row):
    result = dict(row)
    result['correct'] = bool(result['correct'])
    result['changed_answer'] = bool(result['changed_answer'])
    question = dict(db.execute('SELECT stem,options_json,answer,explanation,stem_assets_json,option_assets_json,module,ai_explanation_json,passage_id FROM questions WHERE id=?', (row['question_id'],)).fetchone())
    opt_raw = question.pop('options_json', '{}') or '{}'
    result['options'] = json.loads(opt_raw) if isinstance(opt_raw, str) else opt_raw
    stem_raw = question.pop('stem_assets_json', '[]') or '[]'
    opt_assets_raw = question.pop('option_assets_json', '{}') or '{}'
    result['stem_assets'] = json.loads(stem_raw) if isinstance(stem_raw, str) else stem_raw
    result['option_assets'] = json.loads(opt_assets_raw) if isinstance(opt_assets_raw, str) else opt_assets_raw
    ai_raw = question.pop('ai_explanation_json', None)
    result['ai_explanation'] = json.loads(ai_raw) if ai_raw else None
    passage_id = question.pop('passage_id', None)
    result['passage'] = None
    if passage_id:
        p_row = db.execute('SELECT id,content,assets_json FROM question_passages WHERE id=?', (passage_id,)).fetchone()
        if p_row:
            result['passage'] = {
                'id': p_row['id'],
                'content': p_row['content'],
                'assets': json.loads(p_row['assets_json'] or '[]'),
            }
    result.update(question)
    error = db.execute(
        'SELECT id,error_type,explanation,source,created_at FROM error_events WHERE attempt_id=? ORDER BY created_at DESC,id DESC LIMIT 1',
        (row['id'],),
    ).fetchone()
    result['error_event'] = dict(error) if error else None
    schedule = db.execute(
        '''SELECT re.rating,re.rating_reason,re.scheduler_version,re.rating_policy_version,
                  rc.state,rc.due,rc.review_count,rc.lapse_count
           FROM review_events re JOIN review_cards rc ON rc.question_id=re.question_id
           WHERE re.attempt_id=?''',
        (row['id'],),
    ).fetchone()
    result['review_schedule'] = dict(schedule) if schedule else None
    result['selection'] = selection_view(db, row['session_id'], row['question_id'])
    return result


def selection_view(db, session_id, question_id):
    row = db.execute(
        '''SELECT position,policy_version,selection_score,selection_reason,
                  component_scores_json,decided_at
           FROM session_question_selections WHERE session_id=? AND question_id=?''',
        (session_id, question_id),
    ).fetchone()
    if row is None:
        return None
    value = dict(row)
    value['component_scores'] = json.loads(value.pop('component_scores_json'))
    return value


def create_session_snapshot(db, question_ids, mode):
    sid = str(uuid4())
    db.execute('INSERT INTO sessions(id,mode,started_at) VALUES (?,?,?)', (sid, mode, now()))
    db.executemany(
        'INSERT INTO session_questions VALUES (?,?,?)',
        [(sid, question_id, index) for index, question_id in enumerate(question_ids)],
    )
    return sid


def active_review_session(db):
    row = db.execute(
        '''SELECT s.id,s.mode,s.started_at,s.status,COUNT(sq.question_id) total,
                  COUNT(CASE WHEN a.submitted_at IS NOT NULL THEN 1 END) answered
           FROM sessions s
           JOIN session_questions sq ON sq.session_id=s.id
           LEFT JOIN attempts a ON a.session_id=s.id AND a.question_id=sq.question_id
           WHERE s.mode='REVIEW' AND s.status='active'
           GROUP BY s.id
           ORDER BY s.started_at DESC,s.id DESC LIMIT 1'''
    ).fetchone()
    return dict(row) if row else None


def create_app(db_path=None):
    path = db_path if db_path is not None else default_path()

    @asynccontextmanager
    async def lifespan(app):
        if not settings_service.is_pytest_context():
            # 应用保存的系统设置（AI 网关与知识检索），设置页保存后重启仍生效。
            try:
                settings_service.apply_saved_settings()
            except Exception:
                logger.exception('应用系统设置失败，回退到默认配置')
        migrate(path)
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            rebuild_mastery(db)
            rebuild_reviews(db)
        yield

    app = FastAPI(title='公考 Learning OS · Phase 3B', lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=['*'],
        allow_credentials=True,
        allow_methods=['*'],
        allow_headers=['*'],
    )

    # ------------------------------------------------------------------
    # Optional shared-token lock for AI-spending endpoints (opt-in).
    # Set env var GONGKAO_AI_TOKEN to enable; when unset, behaviour is
    # identical to before. The frontend sends it as `X-Study-Token`.
    # ------------------------------------------------------------------
    ai_token = os.environ.get('GONGKAO_AI_TOKEN')

    def _is_ai_spending_path(p: str) -> bool:
        return (
            p.startswith('/api/teaching/')
            or p == '/api/knowledge/retrieve'
            or p == '/api/shenlun/submit'
            or (p.startswith('/api/shenlun/') and p.endswith('/guidance'))
            or (p.startswith('/api/shenlun/') and p.endswith('/point-trace'))
            or p.endswith(('/hint', '/diagnose', '/explain', '/followup', '/process', '/reclassify'))
        )

    @app.middleware('http')
    async def ai_token_guard(request: Request, call_next):
        if ai_token and request.method != 'OPTIONS' and _is_ai_spending_path(request.url.path):
            if request.headers.get('x-study-token') != ai_token:
                return JSONResponse(
                    status_code=401,
                    content={'detail': '该功能已启用口令保护，请在前端 localStorage 设置 study_token 后重试。'},
                )
        return await call_next(request)

    assets_dir = ROOT / 'data' / 'assets'
    assets_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.exception_handler(GatewayError)
    async def gateway_error_handler(request: Request, exc: GatewayError):
        return JSONResponse(
            status_code=502,
            content={'detail': f'AI 服务暂时不可用，请稍后重试。（{type(exc).__name__}）'},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        messages = []
        for e in exc.errors():
            loc = '.'.join(str(part) for part in e.get('loc', []))
            messages.append(f'{loc}: {e["msg"]}')
        return JSONResponse(
            status_code=422,
            content={'detail': '请求参数有误：' + '；'.join(messages)},
        )

    @app.middleware('http')
    async def no_cache(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get('/api/network/info')
    def network_info():
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
        except Exception:
            ip = '127.0.0.1'
        finally:
            s.close()
        return {
            'lan_ip': ip,
            'frontend_port': 3000,
            'backend_port': 8000,
            'quiz_url': f'http://{ip}:3000/quiz',
            'home_url': f'http://{ip}:3000',
        }

    @app.get('/api/health')
    def health():
        with connect(path) as db:
            return {'status': 'ok', 'questions': db.execute('SELECT COUNT(*) FROM questions').fetchone()[0]}

    @app.get('/api/quiz/modules')
    def quiz_modules():
        with connect(path) as db:
            counts_by_module = dict(
                db.execute("SELECT module, COUNT(*) FROM questions GROUP BY module").fetchall()
            )
            unpracticed_by_module = dict(
                db.execute(
                    """
                    SELECT q.module, COUNT(*) FROM questions q
                    WHERE q.id NOT IN (SELECT DISTINCT question_id FROM attempts WHERE submitted_at IS NOT NULL)
                    GROUP BY q.module
                    """
                ).fetchall()
            )

            total_all = sum(counts_by_module.values())
            unpracticed_all = sum(unpracticed_by_module.values())

            reasoning_submodules = ["判断推理", "图形推理", "立体图推", "逻辑判断", "定义判断", "类比推理"]
            reasoning_total = sum(counts_by_module.get(m, 0) for m in reasoning_submodules)
            reasoning_unpracticed = sum(unpracticed_by_module.get(m, 0) for m in reasoning_submodules)

            modules_list = [
                {
                    "id": "ALL",
                    "name": "全部模块",
                    "total": total_all,
                    "unpracticed": unpracticed_all,
                },
                {
                    "id": "言语理解",
                    "name": "言语理解与表达",
                    "total": counts_by_module.get("言语理解", 0),
                    "unpracticed": unpracticed_by_module.get("言语理解", 0),
                },
                {
                    "id": "判断推理",
                    "name": "判断推理 (综合)",
                    "total": reasoning_total,
                    "unpracticed": reasoning_unpracticed,
                    "submodules": [
                        {
                            "id": "图形推理",
                            "name": "图形推理",
                            "total": counts_by_module.get("图形推理", 0),
                            "unpracticed": unpracticed_by_module.get("图形推理", 0),
                        },
                        {
                            "id": "立体图推",
                            "name": "立体图推",
                            "total": counts_by_module.get("立体图推", 0),
                            "unpracticed": unpracticed_by_module.get("立体图推", 0),
                        },
                        {
                            "id": "逻辑判断",
                            "name": "逻辑判断",
                            "total": counts_by_module.get("逻辑判断", 0),
                            "unpracticed": unpracticed_by_module.get("逻辑判断", 0),
                        },
                        {
                            "id": "定义判断",
                            "name": "定义判断",
                            "total": counts_by_module.get("定义判断", 0),
                            "unpracticed": unpracticed_by_module.get("定义判断", 0),
                        },
                        {
                            "id": "类比推理",
                            "name": "类比推理",
                            "total": counts_by_module.get("类比推理", 0),
                            "unpracticed": unpracticed_by_module.get("类比推理", 0),
                        },
                    ],
                },
                {
                    "id": "资料分析",
                    "name": "资料分析",
                    "total": counts_by_module.get("资料分析", 0),
                    "unpracticed": unpracticed_by_module.get("资料分析", 0),
                },
                {
                    "id": "数量关系",
                    "name": "数量关系",
                    "total": counts_by_module.get("数量关系", 0),
                    "unpracticed": unpracticed_by_module.get("数量关系", 0),
                },
                {
                    "id": "政治理论",
                    "name": "政治理论",
                    "total": counts_by_module.get("政治理论", 0),
                    "unpracticed": unpracticed_by_module.get("政治理论", 0),
                },
                {
                    "id": "常识判断",
                    "name": "常识判断",
                    "total": counts_by_module.get("常识判断", 0),
                    "unpracticed": unpracticed_by_module.get("常识判断", 0),
                },
            ]
            return {"modules": modules_list, "total": total_all}

    @app.get('/api/question-sources')
    def question_sources_catalog():
        with connect(path) as db:
            return source_catalog(db)

    @app.get('/api/question-sources/questions')
    def question_source_questions(source: str | None = None, set_number: int | None = Query(None, ge=1),
                                  question_number: int | None = Query(None, ge=1), search: str = '',
                                  offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        with connect(path) as db:
            items = find_references(db, source, set_number, question_number, search)
            return {'total': len(items), 'items': items[offset:offset + limit]}

    @app.post('/api/question-sources/practice', status_code=201)
    def practice_question_source(body: dict):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            if isinstance(body.get('reference_id'), str):
                selected = [resolve_reference(db, body['reference_id'])]
            elif isinstance(body.get('source'), str) and body['source'].strip():
                set_number = body.get('set_number')
                if set_number is not None and (type(set_number) is not int or set_number < 1):
                    raise HTTPException(422, '套号必须为正整数')
                selected = find_references(db, source=body['source'], set_number=set_number)
            else:
                raise HTTPException(422, '请选择具体来源或原题号')
            if not selected:
                raise HTTPException(404, '该来源暂无题目')
            reference_count = len(selected)
            unique = {}
            for item in selected:
                unique.setdefault(item['question_id'], item)
            selected = list(unique.values())
            if len(selected) > 200:
                raise HTTPException(422, '请先选择一套练习，或单独练习某道题')
            sid = create_session_snapshot(db, [a['question_id'] for a in selected], 'PRACTICE')
            db.executemany('INSERT INTO session_question_sources(session_id,question_id,reference_id,source,source_locator) VALUES(?,?,?,?,?)',
                           [(sid, a['question_id'], a['reference_id'], a['source'], a['source_locator']) for a in selected])
            return {'id': sid, 'total': len(selected), 'source_reference_count': reference_count}

    @app.post('/api/quiz/session', status_code=201)
    def start(body: dict | None = None):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            node_id = body.get('node_id') if body else None
            size = int(body.get('size', 50)) if body and body.get('size') else 50
            module = body.get('module') if body else None
            total_in_db = db.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
            if total_in_db == 0:
                raise HTTPException(409, '题库为空，请先运行题库导入脚本')

            if node_id:
                subnodes = [r[0] for r in db.execute(
                    '''WITH RECURSIVE sub(id) AS (
                        SELECT id FROM knowledge_nodes WHERE id = ?
                        UNION ALL
                        SELECT kn.id FROM knowledge_nodes kn JOIN sub s ON kn.parent_id = s.id
                    ) SELECT id FROM sub''', (node_id,)
                ).fetchall()]
                placeholders = ','.join(['?'] * len(subnodes))
                questions = db.execute(
                    f'''SELECT DISTINCT q.id FROM questions q
                       JOIN question_knowledge_map qkm ON qkm.question_id = q.id
                       WHERE qkm.knowledge_node_id IN ({placeholders})
                       ORDER BY q.id''', subnodes
                ).fetchall()
                if not questions:
                    raise HTTPException(409, '题库为空，请先运行题库导入脚本')
                effective_size = min(max(int(size), 5), 100) if size else 20
                question_ids = [q['id'] for q in questions[:effective_size]]
            else:
                question_ids = compose_practice_questions(db, module=module, total_count=size)

            sid = create_session_snapshot(db, question_ids, 'PRACTICE')
            return {'id': sid, 'total': len(question_ids)}

    @app.get('/api/review/status')
    def review_status():
        with connect(path) as db:
            as_of = now()
            due_count = db.execute('SELECT COUNT(*) FROM review_cards WHERE due<=?', (as_of,)).fetchone()[0]
            return {'as_of': as_of, 'due_count': due_count, 'active_session': active_review_session(db)}

    @app.post('/api/review/session', status_code=201)
    def start_review():
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            active = active_review_session(db)
            if active:
                return {'id': active['id'], 'total': active['total'], 'reused': True}
            as_of = datetime.now(timezone.utc)
            due = due_reviews(db, as_of, 25)
            if not due:
                return {'id': None, 'total': 0, 'reused': False}
            sid = create_session_snapshot(db, [row['question_id'] for row in due], 'REVIEW')
            return {'id': sid, 'total': len(due), 'reused': False}

    @app.post('/api/practice/adaptive/session', status_code=201)
    def start_adaptive(body: AdaptiveSessionInput):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            decided = datetime.now(timezone.utc)
            selections = select_questions(db, body.limit, decided)
            if not selections:
                raise HTTPException(409, '题库为空，请先运行题库导入脚本')
            sid = create_session_snapshot(db, [item['question_id'] for item in selections], 'PRACTICE')
            db.executemany(
                '''INSERT INTO session_question_selections
                   (session_id,question_id,position,policy_version,selection_score,
                    selection_reason,component_scores_json,decided_at)
                   VALUES (?,?,?,?,?,?,?,?)''',
                [(
                    sid, item['question_id'], item['position'], POLICY_VERSION,
                    item['selection_score'], item['selection_reason'],
                    json.dumps(item['component_scores'], ensure_ascii=False, sort_keys=True),
                    decided.isoformat(),
                ) for item in selections],
            )
            return {'id': sid, 'total': len(selections), 'policy_version': POLICY_VERSION}

    @app.get('/api/practice/adaptive/{sid}/audit')
    def adaptive_audit(sid: str):
        with connect(path) as db:
            require_session(db, sid)
            items = []
            for row in db.execute(
                '''SELECT question_id,position,policy_version,selection_score,selection_reason,
                          component_scores_json,decided_at
                   FROM session_question_selections WHERE session_id=? ORDER BY position''',
                (sid,),
            ):
                item = dict(row)
                item['component_scores'] = json.loads(item.pop('component_scores_json'))
                items.append(item)
            return {'session_id': sid, 'policy_version': POLICY_VERSION, 'items': items}

    @app.get('/api/quiz/current')
    def current_practice_session():
        """跨设备统一的“当前训练”：最近一次有作答活动的进行中 PRACTICE 会话。

        与复习流程的 active_review_session 同构；从未作答的会话按开始时间参与排序。
        """
        with connect(path) as db:
            row = db.execute(
                '''SELECT s.id,s.mode,s.started_at,s.status,COUNT(sq.question_id) total,
                          COUNT(CASE WHEN a.submitted_at IS NOT NULL THEN 1 END) answered
                   FROM sessions s
                   JOIN session_questions sq ON sq.session_id=s.id
                   LEFT JOIN attempts a ON a.session_id=s.id AND a.question_id=sq.question_id
                   WHERE s.mode='PRACTICE' AND s.status='active'
                   GROUP BY s.id
                   ORDER BY COALESCE(MAX(COALESCE(a.submitted_at,a.started_at)),s.started_at) DESC,s.id DESC
                   LIMIT 1'''
            ).fetchone()
            return dict(row) if row else None

    @app.get('/api/quiz/{sid}')
    def session(sid: str):
        with connect(path) as db:
            db.execute('BEGIN')
            state = require_session(db, sid)
            state['total'] = db.execute('SELECT COUNT(*) FROM session_questions WHERE session_id=?', (sid,)).fetchone()[0]
            state['answered'] = db.execute('SELECT COUNT(*) FROM attempts WHERE session_id=? AND submitted_at IS NOT NULL', (sid,)).fetchone()[0]
            pending = db.execute('SELECT * FROM attempts WHERE session_id=? AND submitted_at IS NULL', (sid,)).fetchone()
            latest = db.execute('SELECT * FROM attempts WHERE session_id=? AND submitted_at IS NOT NULL ORDER BY submitted_at DESC LIMIT 1', (sid,)).fetchone()
            state['current'] = pending_view(db, pending) if pending else None
            state['latest_result'] = result_view(db, latest) if latest else None
            return state

    @app.get('/api/quiz/{sid}/answered')
    def answered_questions(sid: str):
        """All submitted attempts of this session in question order, for in-session review."""
        with connect(path) as db:
            db.execute('BEGIN')
            require_session(db, sid)
            rows = db.execute(
                '''SELECT a.*, sq.position AS sheet_position FROM attempts a
                   JOIN session_questions sq ON sq.session_id=a.session_id AND sq.question_id=a.question_id
                   WHERE a.session_id=? AND a.submitted_at IS NOT NULL
                   ORDER BY sq.position''', (sid,)).fetchall()
            answered = []
            for row in rows:
                item = result_view(db, row)
                item['position'] = row['sheet_position']
                item.pop('sheet_position', None)
                answered.append(item)
            return {'answered': answered}

    # Kept compatible with the agreed v0.1 API. No prefetching; always no-store.
    @app.get('/api/quiz/{sid}/next')
    def next_question(sid: str):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            state = require_session(db, sid)
            if state['status'] == 'completed':
                return {'done': True}
            pending = db.execute('SELECT * FROM attempts WHERE session_id=? AND submitted_at IS NULL', (sid,)).fetchone()
            if pending:
                return pending_view(db, pending)
            question = db.execute('SELECT sq.question_id FROM session_questions sq LEFT JOIN attempts a ON a.session_id=sq.session_id AND a.question_id=sq.question_id WHERE sq.session_id=? AND a.id IS NULL ORDER BY sq.position LIMIT 1', (sid,)).fetchone()
            if question is None:
                return {'done': True}
            aid = str(uuid4())
            cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
            is_test = (os.environ.get('GONGKAO_ENV') == 'test')
            source_type = 'AUTO_TEST' if is_test else 'REAL_STUDY'
            valid_for_stats = 0 if is_test else 1

            if 'source_type' in cols:
                extra_cols = ['source_type', 'valid_for_stats', 'exposure_state']
                extra_vals = [source_type, valid_for_stats, 'UNKNOWN']
                if 'is_time_estimated' in cols:
                    extra_cols.extend(['is_time_estimated', 'time_estimation_method'])
                    extra_vals.extend([0, 'SERVER_MEASURED'])
                c_str = ','.join(['id', 'question_id', 'session_id', 'started_at', 'mode'] + extra_cols)
                p_str = ','.join(['?'] * (5 + len(extra_cols)))
                db.execute(
                    f'INSERT INTO attempts({c_str}) VALUES ({p_str})',
                    (aid, question['question_id'], sid, now(), state['mode'], *extra_vals),
                )
            else:
                db.execute(
                    'INSERT INTO attempts(id,question_id,session_id,started_at,mode) VALUES (?,?,?,?,?)',
                    (aid, question['question_id'], sid, now(), state['mode']),
                )
            return pending_view(db, db.execute('SELECT * FROM attempts WHERE id=?', (aid,)).fetchone())

    @app.post('/api/quiz/{sid}/answer')
    def submit(sid: str, body: Answer):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            require_session(db, sid)
            attempt = db.execute('SELECT * FROM attempts WHERE id=? AND session_id=?', (body.attempt_id, sid)).fetchone()
            if attempt is None:
                raise HTTPException(404, '本会话中不存在该作答')
            if attempt['submitted_at'] is not None:
                attempt_conf = attempt['confidence']
                if (attempt['selected_answer'], bool(attempt['changed_answer']), attempt_conf) != (body.selected_answer, body.changed_answer, body.confidence):
                    raise HTTPException(409, '该题已提交，不能覆盖原始作答')
                return result_view(db, attempt)
            submitted = now()
            raw_elapsed = max(0, int((datetime.fromisoformat(submitted) - datetime.fromisoformat(attempt['started_at'])).total_seconds() * 1000))
            client_paused = getattr(body, 'paused_ms', 0) or 0
            if attempt['mode'] == 'EXAM':
                paused_ms = 0
            elif 0 <= client_paused < raw_elapsed:
                paused_ms = client_paused
            else:
                paused_ms = 0
            elapsed = max(0, raw_elapsed - paused_ms)
            timing_valid = 1 if (1000 <= elapsed <= 14400000) else 0
            audit_note = None
            if elapsed < 1000:
                audit_note = '异常快速作答(<1s)，标记计时不可信，保留正误记录'
            elif elapsed > 14400000:
                audit_note = '作答耗时异常偏长(>4h)，标记计时不可信，保留正误记录'
            elif client_paused != paused_ms and client_paused > 0:
                audit_note = '客户端暂停时长不合规，未予扣减'

            answer = db.execute('SELECT answer FROM questions WHERE id=?', (attempt['question_id'],)).fetchone()[0]
            effective_confidence = body.confidence

            # 两类空答案严格区分：
            # - 未用提示的首次空答案提交＝正式提交：保留空答案、判未答对，照常计入统计与复习调度；
            # - 提示后空答案提交＝跳过教学重答：提交事实保留（结束本题作答），但不新增正式答错记录，
            #   不改变首次成绩（排除出正式统计与复习调度，与引导复盘“跳过重答”同语义）。
            unanswered = body.selected_answer is None
            hint_level = attempt['hint_level'] if 'hint_level' in attempt.keys() else 0
            skip_formal = False
            if unanswered:
                if hint_level > 0:
                    skip_formal = True
                    audit_note = '提示后未作答：跳过教学重答，不计入正式统计，不改变首次成绩'
                else:
                    audit_note = '未作答（不会）：主动提交空答案，按未作答计入正式统计'

            cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
            if 'timing_valid' in cols:
                att_dict = dict(attempt)
                curr_src = att_dict.get('source_type', 'UNKNOWN')
                new_src = curr_src  # 严格保持原有 source_type，不自动升级

                curr_exp = att_dict.get('exposure_state', 'UNKNOWN')
                if curr_exp == 'ASSISTED':
                    new_exp = 'ASSISTED'
                elif curr_src in ('REAL_STUDY', 'AUTO_TEST'):
                    new_exp = 'NO_ASSISTANCE'
                else:
                    new_exp = 'UNKNOWN'  # 缺少全监控依据的历史记录保持 UNKNOWN

                curr_valid = att_dict.get('valid_for_stats', 1)
                # 提示后空答案仅把原本有效的记录降为不计入统计；AUTO_TEST 等本就排除的保持不变。
                new_valid = 0 if (skip_formal and curr_valid == 1) else curr_valid

                extra_update = ""
                extra_params = []
                if 'is_time_estimated' in cols:
                    extra_update = ", is_time_estimated=?, time_estimation_method=?"
                    extra_params = [0, 'SERVER_MEASURED']

                db.execute(
                    f'''UPDATE attempts 
                       SET submitted_at=?,elapsed_ms=?,raw_elapsed_ms=?,paused_ms=?,timing_valid=?,audit_note=?,source_type=?,exposure_state=?,selected_answer=?,correct=?,confidence=?,changed_answer=?,valid_for_stats=? {extra_update}
                       WHERE id=?''',
                    (submitted, elapsed, raw_elapsed, paused_ms, timing_valid, audit_note, new_src, new_exp, body.selected_answer, int(body.selected_answer == answer), effective_confidence, body.changed_answer, new_valid, *extra_params, body.attempt_id)
                )
            else:
                db.execute('UPDATE attempts SET submitted_at=?,elapsed_ms=?,selected_answer=?,correct=?,confidence=?,changed_answer=? WHERE id=?', (submitted, elapsed, body.selected_answer, int(body.selected_answer == answer), effective_confidence, body.changed_answer, body.attempt_id))

            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if 'exposure_logs' in tables:
                record_exposure(
                    db,
                    attempt_id=body.attempt_id,
                    question_id=attempt['question_id'],
                    session_id=sid,
                    exposure_type='EXPLANATION',
                    stage='POST_SUBMISSION',
                    source_action='SUBMIT_REVIEW',
                    details={}
                )

            total = db.execute('SELECT COUNT(*) FROM session_questions WHERE session_id=?', (sid,)).fetchone()[0]
            count = db.execute('SELECT COUNT(*) FROM attempts WHERE session_id=? AND submitted_at IS NOT NULL', (sid,)).fetchone()[0]
            if count == total:
                db.execute("UPDATE sessions SET status='completed',completed_at=? WHERE id=?", (submitted, sid))
            rebuild_mastery(db)
            rebuild_reviews(db)
            return result_view(db, db.execute('SELECT * FROM attempts WHERE id=?', (body.attempt_id,)).fetchone())

    @app.get('/api/quiz/{sid}/group')
    def get_quiz_group(sid: str, group_idx: int | None = None):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            state = require_session(db, sid)

            rows = db.execute('''
                SELECT sq.position, sq.question_id, q.passage_id, q.module
                FROM session_questions sq
                JOIN questions q ON q.id = sq.question_id
                WHERE sq.session_id = ?
                ORDER BY sq.position ASC
            ''', (sid,)).fetchall()

            if not rows:
                raise HTTPException(404, '该会话无题目')

            groups = []
            curr_g = None
            for r in rows:
                pid = r['passage_id']
                should_break = (
                    curr_g is None or
                    (pid is not None and curr_g['passage_id'] != pid) or
                    (pid is None and len(curr_g['question_ids']) >= 5) or
                    (curr_g['passage_id'] is None and pid is not None)
                )
                if should_break:
                    curr_g = {
                        'passage_id': pid,
                        'question_ids': [],
                    }
                    groups.append(curr_g)
                curr_g['question_ids'].append(r['question_id'])

            total_groups = len(groups)

            selected_idx = 0
            if group_idx is not None and 1 <= group_idx <= total_groups:
                selected_idx = group_idx - 1
            else:
                found_unsubmitted = False
                for idx, g in enumerate(groups):
                    qids = g['question_ids']
                    placeholders = ','.join(['?'] * len(qids))
                    submitted_cnt = db.execute(f'''
                        SELECT count(*) FROM attempts
                        WHERE session_id = ? AND question_id IN ({placeholders}) AND submitted_at IS NOT NULL
                    ''', (sid, *qids)).fetchone()[0]
                    if submitted_cnt < len(qids):
                        selected_idx = idx
                        found_unsubmitted = True
                        break
                if not found_unsubmitted:
                    selected_idx = total_groups - 1

            target_group = groups[selected_idx]
            group_questions = []

            # Check if there is an existing pending attempt in this session
            existing_pending = db.execute('SELECT * FROM attempts WHERE session_id = ? AND submitted_at IS NULL', (sid,)).fetchone()

            for qid in target_group['question_ids']:
                att = db.execute(
                    'SELECT * FROM attempts WHERE session_id = ? AND question_id = ?',
                    (sid, qid)
                ).fetchone()

                if att is None and existing_pending is None:
                    aid = str(uuid4())
                    db.execute(
                        'INSERT INTO attempts(id, question_id, session_id, started_at, mode) VALUES (?, ?, ?, ?, ?)',
                        (aid, qid, sid, now(), state['mode'])
                    )
                    att = db.execute('SELECT * FROM attempts WHERE id = ?', (aid,)).fetchone()
                    existing_pending = att

                if att is not None and att['submitted_at'] is not None:
                    res = result_view(db, att)
                    q_view = dict(res)
                    q_view['attempt_id'] = att['id']
                    q_view['submitted'] = True
                    q_view['question_id'] = att['question_id']
                    q_view['question'] = {
                        'id': att['question_id'],
                        'stem': res['stem'],
                        'options': res['options'],
                        'stem_assets': res.get('stem_assets', []),
                        'option_assets': res.get('option_assets', {}),
                        'module': res.get('module', '资料分析'),
                        'source': res.get('source', ''),
                        'estimated_seconds': res.get('estimated_seconds', 60),
                        'passage': res.get('passage'),
                    }
                elif att is not None:
                    pending = pending_view(db, att)
                    q_view = {
                        'attempt_id': att['id'],
                        'question_id': att['question_id'],
                        'submitted': False,
                        'question': pending['question'],
                        'started_at': pending['started_at'],
                        'selection': pending.get('selection'),
                    }
                else:
                    q_row = dict(db.execute('SELECT id,source,year,exam_type,subject,module,stem,options_json,difficulty,estimated_seconds,is_verified,stem_assets_json,option_assets_json,passage_id FROM questions WHERE id=?', (qid,)).fetchone())
                    q_row['options'] = json.loads(q_row.pop('options_json'))
                    original_source = source_context(db, sid, qid)
                    if original_source:
                        q_row['source'] = original_source['source'] + ' · ' + original_source['source_locator']
                        q_row['source_reference_id'] = original_source['reference_id']
                    q_row['is_verified'] = bool(q_row['is_verified'])
                    stem_raw = q_row.pop('stem_assets_json', '[]') or '[]'
                    opt_raw = q_row.pop('option_assets_json', '{}') or '{}'
                    q_row['stem_assets'] = json.loads(stem_raw) if isinstance(stem_raw, str) else stem_raw
                    q_row['option_assets'] = json.loads(opt_raw) if isinstance(opt_raw, str) else opt_raw
                    q_row['passage'] = None
                    q_view = {
                        'attempt_id': None,
                        'question_id': qid,
                        'submitted': False,
                        'question': q_row,
                        'started_at': now(),
                        'selection': None,
                    }
                group_questions.append(q_view)

            passage_obj = None
            pid = target_group['passage_id']
            if pid:
                p_row = db.execute('SELECT id, content, assets_json FROM question_passages WHERE id = ?', (pid,)).fetchone()
                if p_row:
                    passage_obj = {
                        'id': p_row['id'],
                        'content': p_row['content'],
                        'assets': json.loads(p_row['assets_json'] or '[]'),
                    }

            is_group_settled = all(q.get('submitted') for q in group_questions)
            summary = None
            if is_group_settled:
                total_in_grp = len(group_questions)
                correct_in_grp = sum(1 for q in group_questions if q.get('correct'))
                elapsed_in_grp = sum(q.get('elapsed_ms', 0) for q in group_questions)
                summary = {
                    'total': total_in_grp,
                    'correct_count': correct_in_grp,
                    'accuracy_percent': round(correct_in_grp / total_in_grp * 100, 1) if total_in_grp > 0 else 0,
                    'total_elapsed_ms': elapsed_in_grp,
                    'avg_elapsed_ms': round(elapsed_in_grp / total_in_grp) if total_in_grp > 0 else 0,
                    'is_all_correct': correct_in_grp == total_in_grp,
                }

            session_total = db.execute('SELECT COUNT(*) FROM session_questions WHERE session_id=?', (sid,)).fetchone()[0]
            session_answered = db.execute('SELECT COUNT(*) FROM attempts WHERE session_id=? AND submitted_at IS NOT NULL', (sid,)).fetchone()[0]
            all_completed = session_answered >= session_total

            return {
                'session_id': sid,
                'group_index': selected_idx + 1,
                'total_groups': total_groups,
                'passage': passage_obj,
                'questions': group_questions,
                'is_group_settled': is_group_settled,
                'summary': summary,
                'all_completed': all_completed,
                'has_next_group': (selected_idx + 1) < total_groups,
                'session_total': session_total,
                'session_answered': session_answered,
                'started_at': group_questions[0].get('started_at') or now(),
                'server_now': now(),
            }

    @app.post('/api/quiz/{sid}/group-answer')
    def submit_group(sid: str, body: GroupSubmitInput):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            require_session(db, sid)
            submitted = now()

            if not body.answers:
                raise HTTPException(400, '提交内容不能为空')

            n_answers = len(body.answers)
            sess_mode = db.execute('SELECT mode FROM sessions WHERE id=?', (sid,)).fetchone()['mode']
            client_paused = (body.paused_ms or 0)
            actual_paused = 0 if sess_mode == 'EXAM' else (client_paused if (0 <= client_paused < body.total_elapsed_ms) else 0)
            net_elapsed = max(0, body.total_elapsed_ms - actual_paused)
            distributed_elapsed = (net_elapsed // n_answers) if n_answers > 0 else 0

            cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
            has_cred = 'timing_valid' in cols
            has_est = 'is_time_estimated' in cols
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            has_exposure = 'exposure_logs' in tables

            is_test = (os.environ.get('GONGKAO_ENV') == 'test')
            default_source = 'AUTO_TEST' if is_test else 'REAL_STUDY'
            default_valid = 0 if is_test else 1

            results = []
            for item in body.answers:
                qid = item.question_id
                att = db.execute('SELECT * FROM attempts WHERE session_id=? AND question_id=?', (sid, qid)).fetchone()

                sel = item.selected_answer.strip().upper() if item.selected_answer else None
                if item.elapsed_ms is not None:
                    item_elapsed = item.elapsed_ms
                    is_time_estimated = 0
                    time_estimation_method = 'CLIENT_MEASURED'
                    timing_note = None
                else:
                    item_elapsed = distributed_elapsed
                    is_time_estimated = 1
                    time_estimation_method = 'EQUAL_SPLIT'
                    timing_note = '材料组均分估算耗时'

                timing_valid = 1 if (1000 <= item_elapsed <= 14400000) else 0
                audit_note = timing_note
                if item_elapsed < 1000:
                    audit_note = '异常快速作答(<1s)，标记计时不可信，保留正误记录'
                elif item_elapsed > 14400000:
                    audit_note = '作答耗时异常偏长(>4h)，标记计时不可信，保留正误记录'

                answer = db.execute('SELECT answer FROM questions WHERE id=?', (qid,)).fetchone()[0]
                is_correct = (sel == answer) if sel else False
                effective_item_conf = item.confidence

                # 组内空答案与单题口径一致：未用提示＝正式未作答（计入统计）；
                # 提示后空答案＝跳过教学重答，不计入正式统计（组题界面无提示入口，此处为口径一致的防御处理）。
                skip_item_formal = False
                if sel is None:
                    item_hint = att['hint_level'] if (att is not None and 'hint_level' in att.keys()) else 0
                    if item_hint > 0:
                        skip_item_formal = True
                        audit_note = '提示后未作答：跳过教学重答，不计入正式统计，不改变首次成绩'
                    else:
                        audit_note = '未作答（不会）：主动提交空答案，按未作答计入正式统计' + (f'；{timing_note}' if timing_note else '')

                if att is None:
                    aid = str(uuid4())
                    item_valid = 0 if skip_item_formal else default_valid
                    if has_cred:
                        extra_cols = ['is_time_estimated', 'time_estimation_method'] if has_est else []
                        extra_vals = [is_time_estimated, time_estimation_method] if has_est else []
                        c_str = ','.join(['id', 'question_id', 'session_id', 'started_at', 'submitted_at', 'elapsed_ms', 'raw_elapsed_ms', 'paused_ms', 'timing_valid', 'audit_note', 'source_type', 'valid_for_stats', 'exposure_state', 'selected_answer', 'correct', 'confidence', 'mode'] + extra_cols)
                        p_str = ','.join(['?'] * (17 + len(extra_cols)))
                        db.execute(
                            f'INSERT INTO attempts({c_str}) VALUES ({p_str})',
                            (aid, qid, sid, submitted, submitted, item_elapsed, item_elapsed, 0, timing_valid, audit_note, default_source, item_valid, 'NO_ASSISTANCE', sel, is_correct, effective_item_conf, sess_mode, *extra_vals)
                        )
                    else:
                        db.execute(
                            '''INSERT INTO attempts(id, question_id, session_id, started_at, submitted_at, elapsed_ms, selected_answer, correct, confidence, mode)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                            (aid, qid, sid, submitted, submitted, item_elapsed, sel, is_correct, effective_item_conf, sess_mode)
                        )
                    updated_att = db.execute('SELECT * FROM attempts WHERE id=?', (aid,)).fetchone()
                else:
                    if att['submitted_at'] is None:
                        if has_cred:
                            att_dict = dict(att)
                            curr_src = att_dict.get('source_type', 'UNKNOWN')
                            new_src = curr_src  # 严格保持原有 source_type，不自动升级
                            curr_exp = att_dict.get('exposure_state', 'UNKNOWN')
                            if curr_exp == 'ASSISTED':
                                new_exp = 'ASSISTED'
                            elif curr_src in ('REAL_STUDY', 'AUTO_TEST'):
                                new_exp = 'NO_ASSISTANCE'
                            else:
                                new_exp = 'UNKNOWN'

                            curr_valid = att_dict.get('valid_for_stats', 1)
                            new_valid = 0 if (skip_item_formal and curr_valid == 1) else curr_valid

                            extra_update = ", is_time_estimated=?, time_estimation_method=?" if has_est else ""
                            extra_vals = [is_time_estimated, time_estimation_method] if has_est else []

                            db.execute(
                                f'''UPDATE attempts
                                   SET submitted_at=?, elapsed_ms=?, raw_elapsed_ms=?, paused_ms=?, timing_valid=?, audit_note=?, source_type=?, exposure_state=?, selected_answer=?, correct=?, confidence=?, changed_answer=?, valid_for_stats=? {extra_update}
                                   WHERE id=?''',
                                (submitted, item_elapsed, item_elapsed, 0, timing_valid, audit_note, new_src, new_exp, sel, is_correct, effective_item_conf, item.changed_answer, new_valid, *extra_vals, att['id'])
                            )
                        else:
                            db.execute(
                                '''UPDATE attempts
                                   SET submitted_at=?, elapsed_ms=?, selected_answer=?, correct=?, confidence=?, changed_answer=?
                                   WHERE id=?''',
                                (submitted, item_elapsed, sel, is_correct, effective_item_conf, item.changed_answer, att['id'])
                            )
                    updated_att = db.execute('SELECT * FROM attempts WHERE id=?', (att['id'],)).fetchone()

                if has_exposure:
                    record_exposure(
                        db,
                        attempt_id=updated_att['id'],
                        question_id=qid,
                        session_id=sid,
                        exposure_type='EXPLANATION',
                        stage='POST_SUBMISSION',
                        source_action='SUBMIT_REVIEW',
                        details={}
                    )

                results.append(result_view(db, updated_att))

            total = db.execute('SELECT COUNT(*) FROM session_questions WHERE session_id=?', (sid,)).fetchone()[0]
            count = db.execute('SELECT COUNT(*) FROM attempts WHERE session_id=? AND submitted_at IS NOT NULL', (sid,)).fetchone()[0]
            if count == total:
                db.execute("UPDATE sessions SET status='completed', completed_at=? WHERE id=?", (submitted, sid))

            rebuild_mastery(db)
            rebuild_reviews(db)

            correct_count = sum(1 for r in results if r['correct'])
            summary = {
                'total': n_answers,
                'correct_count': correct_count,
                'accuracy_percent': round(correct_count / n_answers * 100, 1) if n_answers > 0 else 0,
                'total_elapsed_ms': body.total_elapsed_ms,
                'avg_elapsed_ms': round(body.total_elapsed_ms / n_answers) if n_answers > 0 else 0,
                'is_all_correct': correct_count == n_answers,
            }

            return {
                'session_id': sid,
                'summary': summary,
                'results': results,
                'has_next_group': count < total,
                'session_completed': count == total,
                'total_answered': count,
                'total_questions': total,
            }

    @app.post('/api/attempts/{attempt_id}/error', status_code=201)
    def record_error(attempt_id: str, body: ErrorEventInput):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            attempt = db.execute('SELECT * FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            if attempt is None or attempt['submitted_at'] is None:
                raise HTTPException(404, '已提交的作答不存在')
            if attempt['correct']:
                raise HTTPException(409, '正确作答不记录错因')
            explanation = body.explanation.strip()
            latest = db.execute(
                'SELECT * FROM error_events WHERE attempt_id=? ORDER BY created_at DESC,id DESC LIMIT 1',
                (attempt_id,),
            ).fetchone()
            if latest and latest['error_type'] == body.error_type and latest['explanation'] == explanation:
                return dict(latest)
            event_id = str(uuid4())
            created = now()
            db.execute(
                '''INSERT INTO error_events
                   (id,attempt_id,question_id,error_type,explanation,source,diagnosis_source,supersedes_id,occurred_at,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)''',
                (event_id, attempt_id, attempt['question_id'], body.error_type, explanation, 'USER', 'user_confirmed', latest['id'] if latest else None, created, created),
            )
            # Associate default error skill binding based on primary question skill
            primary_skill = db.execute(
                '''SELECT qsb.learning_skill_id, qsb.knowledge_node_code
                   FROM question_skill_bindings qsb
                   JOIN learning_skills ls ON ls.id = qsb.learning_skill_id
                   WHERE qsb.question_id=? AND qsb.role='primary' LIMIT 1''',
                (attempt['question_id'],)
            ).fetchone()
            if primary_skill is None:
                primary_skill = db.execute(
                    '''SELECT qkm.knowledge_node_id AS learning_skill_id, ls.knowledge_node_code
                       FROM question_knowledge_map qkm
                       JOIN learning_skills ls ON ls.id=qkm.knowledge_node_id
                       WHERE qkm.question_id=? LIMIT 1''',
                    (attempt['question_id'],)
                ).fetchone()
            if primary_skill is None:
                # Questions bound to knowledge nodes outside the frozen LF1 skill
                # contracts (e.g. 立体图推) still deserve a code-level error binding.
                kn_row = db.execute(
                    '''SELECT kn.knowledge_node_code
                       FROM question_knowledge_map qkm
                       JOIN knowledge_nodes kn ON kn.id = qkm.knowledge_node_id
                       WHERE qkm.question_id=? AND kn.knowledge_node_code IS NOT NULL
                       LIMIT 1''',
                    (attempt['question_id'],)
                ).fetchone()
                if kn_row:
                    primary_skill = {
                        'learning_skill_id': None,
                        'knowledge_node_code': kn_row['knowledge_node_code'],
                    }
            if primary_skill is None:
                q_row = db.execute('SELECT module FROM questions WHERE id=?', (attempt['question_id'],)).fetchone()
                mod = q_row['module'] if q_row else None
                fallback_skill_map = {
                    '图形推理': 'graphic_position',
                    '定义判断': 'definition',
                    '类比推理': 'analogy',
                    '逻辑判断': 'logic',
                    '判断推理': 'logic',
                    '资料分析': 'growth',
                    '数量关系': 'work',
                    '言语理解': 'main_idea',
                    '言语理解与表达': 'main_idea',
                    '政治理论': 'politics',
                    '常识判断': 'politics',
                }
                fallback_skill_id = fallback_skill_map.get(mod, 'logic')
                skill_row = db.execute('SELECT id, knowledge_node_code FROM learning_skills WHERE id=?', (fallback_skill_id,)).fetchone()
                if skill_row:
                    primary_skill = {
                        'learning_skill_id': skill_row['id'],
                        'knowledge_node_code': skill_row['knowledge_node_code'],
                    }

            if primary_skill:
                esb_id = f"esb_{event_id}_{primary_skill['learning_skill_id']}_primary"
                db.execute(
                    '''INSERT OR IGNORE INTO error_skill_bindings
                       (id, error_event_id, learning_skill_id, knowledge_node_code, role, weight, provenance, confidence, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)''',
                    (esb_id, event_id, primary_skill['learning_skill_id'], primary_skill['knowledge_node_code'], 'primary', 1.0, 'user_confirmed', 1.0, created),
                )

            return dict(db.execute('SELECT * FROM error_events WHERE id=?', (event_id,)).fetchone())

    @app.get('/api/mastery')
    def mastery():
        with connect(path) as db:
            verdict = correct_expr(db)
            nodes = [dict(row) for row in db.execute(
                f'''SELECT kn.*,ms.mastery_score,ms.evidence_positive,ms.evidence_negative,
                          ms.attempt_count,ms.recent_accuracy,ms.timed_accuracy,ms.avg_time_ratio,
                          ms.hint_dependency,ms.transfer_score,ms.last_practiced_at,
                          COALESCE(qc.cnt, 0) AS direct_question_count,
                          COALESCE(qstats.practiced_count, 0) AS practiced_question_count,
                          COALESCE(qstats.error_count, 0) AS error_question_count,
                          COALESCE(stq.subtree_question_count, 0) AS subtree_question_count
                   FROM knowledge_nodes kn
                   JOIN mastery_state ms ON ms.knowledge_node_id=kn.id
                   LEFT JOIN (
                       SELECT knowledge_node_id, COUNT(DISTINCT question_id) AS cnt
                       FROM question_knowledge_map
                       GROUP BY knowledge_node_id
                   ) qc ON qc.knowledge_node_id=kn.id
                   LEFT JOIN (
                       SELECT qkm.knowledge_node_id,
                              COUNT(DISTINCT CASE WHEN a.submitted_at IS NOT NULL THEN qkm.question_id END) AS practiced_count,
                              COUNT(DISTINCT CASE WHEN a.submitted_at IS NOT NULL AND {verdict} = 0 THEN qkm.question_id END) AS error_count
                       FROM question_knowledge_map qkm
                       LEFT JOIN attempts a ON a.question_id = qkm.question_id
                       GROUP BY qkm.knowledge_node_id
                   ) qstats ON qstats.knowledge_node_id=kn.id
                   LEFT JOIN (
                       WITH RECURSIVE subtree(root_id, node_id) AS (
                           SELECT id, id FROM knowledge_nodes
                           UNION ALL
                           SELECT subtree.root_id, kn.id FROM knowledge_nodes kn JOIN subtree ON kn.parent_id = subtree.node_id
                       )
                       SELECT subtree.root_id AS knowledge_node_id,
                              COUNT(DISTINCT qkm.question_id) AS subtree_question_count
                       FROM subtree
                       JOIN question_knowledge_map qkm ON qkm.knowledge_node_id = subtree.node_id
                       GROUP BY subtree.root_id
                   ) stq ON stq.knowledge_node_id=kn.id
                   ORDER BY kn.subject,kn.module,kn.parent_id,kn.name'''
            )]
            return {'overall': overall_mastery(db), 'nodes': nodes}

    @app.get('/api/knowledge-nodes/{node_id}/questions')
    def knowledge_node_questions(node_id: str):
        with connect(path) as db:
            rows = db.execute(
                '''SELECT q.id, q.stem, q.module, q.difficulty, q.answer, q.explanation,
                          COALESCE(att_summary.attempt_count, 0) AS attempt_count,
                          att_summary.last_attempt_id,
                          att_summary.last_correct,
                          att_summary.last_submitted_at,
                          att_summary.last_selected_answer,
                          idg.status AS review_status,
                          idg.summary AS review_summary,
                          idg.user_feedback_text AS review_user_self_report,
                          idg.is_user_confirmed AS review_is_user_confirmed
                   FROM question_knowledge_map qkm
                   JOIN questions q ON q.id = qkm.question_id
                   LEFT JOIN (
                       SELECT a.question_id,
                              COUNT(*) AS attempt_count,
                              (SELECT id FROM attempts WHERE question_id=a.question_id AND submitted_at IS NOT NULL ORDER BY submitted_at DESC, id DESC LIMIT 1) AS last_attempt_id,
                              (SELECT correct FROM attempts WHERE question_id=a.question_id AND submitted_at IS NOT NULL ORDER BY submitted_at DESC, id DESC LIMIT 1) AS last_correct,
                              (SELECT submitted_at FROM attempts WHERE question_id=a.question_id AND submitted_at IS NOT NULL ORDER BY submitted_at DESC, id DESC LIMIT 1) AS last_submitted_at,
                              (SELECT selected_answer FROM attempts WHERE question_id=a.question_id AND submitted_at IS NOT NULL ORDER BY submitted_at DESC, id DESC LIMIT 1) AS last_selected_answer
                       FROM attempts a
                       WHERE a.submitted_at IS NOT NULL
                       GROUP BY a.question_id
                   ) att_summary ON att_summary.question_id = q.id
                   LEFT JOIN interactive_diagnoses idg ON idg.attempt_id = att_summary.last_attempt_id
                   WHERE qkm.knowledge_node_id = ?
                   ORDER BY q.id''',
                (node_id,),
            ).fetchall()
            items = []
            for r in rows:
                item = dict(r)
                item['last_correct'] = bool(item['last_correct']) if item['last_correct'] is not None else None
                item['has_review'] = bool(item.get('review_status'))
                item['review_is_user_confirmed'] = bool(item.get('review_is_user_confirmed')) if item.get('review_is_user_confirmed') is not None else False
                items.append(item)
            return {'node_id': node_id, 'total': len(items), 'questions': items}

    @app.get('/api/knowledge-nodes/{node_id}/evidence')
    async def knowledge_node_evidence(node_id: str):
        """Formal node-evidence bindings from the Knowledge Hub (read-only).

        Uses the existing knowledge_node_code mapping; never free-text
        retrieval masquerading as bindings. States:
        - ok + count>0          正式绑定资料
        - ok + count=0          已查询但无绑定
        - unmapped              节点无编码或 Hub 端无此节点
        - 503/502               Hub 不可用/响应异常（可重试）
        """
        with connect(path) as db:
            row = db.execute(
                'SELECT knowledge_node_code, metadata_json FROM knowledge_nodes WHERE id=?', (node_id,)
            ).fetchone()
        if row is None:
            raise HTTPException(404, '知识节点不存在')
        from .domain.politics_course_tree import course_evidence
        local_items = course_evidence(row['metadata_json'], node_id)
        if local_items:
            return {'status': 'ok', 'count': len(local_items), 'items': local_items,
                    'knowledge_node_code': row['knowledge_node_code'], 'source': 'local_course_reference'}
        code = (row['knowledge_node_code'] or '').strip()
        if not code:
            return {
                'status': 'unmapped',
                'message': '该考点尚未映射到知识中心节点',
                'count': 0,
                'items': [],
            }
        try:
            provider = get_knowledge_provider()
            result = await provider.get_node_evidence(code)
        except KnowledgeProviderError as exc:
            raise HTTPException(503, f'知识中心暂时无法访问：{exc}')
        if result.get('status') == 'unmapped':
            return {
                'status': 'unmapped',
                'message': '该考点尚未在知识中心建立节点映射',
                'count': 0,
                'items': [],
            }
        return {
            'status': 'ok',
            'count': result.get('count', 0),
            'items': result.get('items', []),
            'knowledge_node_code': code,
        }

    @app.get('/api/knowledge-nodes/{node_id}/teacher-chat')
    def teacher_node_context(node_id: str):
        with connect(path) as db:
            return node_teacher_context(db, node_id)

    @app.post('/api/knowledge-nodes/{node_id}/teacher-chat')
    async def teacher_node_answer(node_id: str, body: NodeTeacherInput):
        with connect(path) as db:
            active_exam = db.execute("SELECT id FROM sessions WHERE mode='EXAM' AND status='active' LIMIT 1").fetchone()
            require_ai_allowed(db, session_id=active_exam['id'] if active_exam else None)
            return await answer_node_teacher(db,node_id,body.message,body.mode,[turn.model_dump() for turn in body.history],phase=body.phase)

    @app.get('/api/dashboard')
    def dashboard_view():
        with connect(path) as db:
            return dashboard(db, overall_mastery(db))

    @app.get('/api/audit/stats')
    def get_audit_stats():
        with connect(path) as db:
            return get_credibility_audit(db)

    @app.get('/api/daily-goal')
    def api_daily_goal():
        with connect(path) as db:
            return daily_goal(db)

    @app.get('/api/analytics/errors')
    def errors():
        with connect(path) as db:
            rows = [dict(row) for row in db.execute(
                latest_error_cte() +
                ''' SELECT re.id,re.attempt_id,re.error_type,re.explanation,re.source,re.created_at,
                           q.id question_id,q.stem,q.module,a.confidence,a.elapsed_ms,
                           idg.status AS review_status, idg.summary AS review_summary,
                           idg.is_user_confirmed AS review_is_user_confirmed
                    FROM ranked_errors re
                    JOIN attempts a ON a.id=re.attempt_id JOIN questions q ON q.id=a.question_id
                    LEFT JOIN interactive_diagnoses idg ON idg.attempt_id = re.attempt_id
                    WHERE re.rn=1 ORDER BY re.created_at DESC'''
            )]
            breakdown = {key: 0 for key in ERROR_LABELS}
            for row in rows:
                if row['error_type'] in breakdown:
                    breakdown[row['error_type']] += 1
                row['error_label'] = ERROR_LABELS.get(row['error_type'], '未知错误')
                row['has_review'] = bool(row.get('review_status'))
                row['review_is_user_confirmed'] = bool(row.get('review_is_user_confirmed')) if row.get('review_is_user_confirmed') is not None else False
            wrong = db.execute('SELECT COUNT(*) FROM attempts WHERE submitted_at IS NOT NULL AND correct=0').fetchone()[0]
            return {
                'events': rows,
                'breakdown': [{'error_type': key, 'label': label, 'count': breakdown[key]} for key, label in ERROR_LABELS.items()],
                'undiagnosed_count': wrong - len(rows),
            }

    @app.get('/api/review/due')
    def reviews_due(limit: int = Query(default=25, ge=1, le=100)):
        with connect(path) as db:
            as_of = now()
            items = []
            for row in due_reviews(db, datetime.fromisoformat(as_of), limit):
                item = dict(row)
                item['options'] = json.loads(item.pop('options_json'))
                item['is_verified'] = bool(item['is_verified'])
                stem_raw = item.pop('stem_assets_json', '[]') or '[]'
                opt_raw = item.pop('option_assets_json', '{}') or '{}'
                item['stem_assets'] = json.loads(stem_raw) if isinstance(stem_raw, str) else stem_raw
                item['option_assets'] = json.loads(opt_raw) if isinstance(opt_raw, str) else opt_raw
                items.append(item)
            return {'as_of': as_of, 'count': len(items), 'items': items}

    @app.get('/api/knowledge/health')
    async def knowledge_health(
        probe: bool = False,
        query: str = '工程问题已知时间设工作总量',
        namespace: str = 'gongkao/xingce/quantitative',
    ):
        raw_mode = os.environ.get('KNOWLEDGE_PROVIDER')
        result: dict = {
            'configured_mode': raw_mode or '(default)',
            'probe_requested': bool(probe),
        }
        try:
            provider = get_knowledge_provider()
        except ValueError as exc:
            result.update({
                'status': 'unavailable',
                'provider': 'unknown',
                'message': f'知识 Provider 配置错误：{exc}',
            })
            return result
        health = await provider.health_check()
        result.update(health.model_dump())

        if probe:
            import time as _time
            # Readiness probe uses a generous timeout: the Hub's first dense query
            # warms up its embedding model (seconds), which must not be reported as
            # an outage. Runtime tutoring flows keep their own short isolation bound.
            if isinstance(provider, KnowledgeHubProvider):
                provider = KnowledgeHubProvider(
                    base_url=provider.base_url,
                    api_key=provider.api_key,
                    timeout_seconds=max(provider.timeout_seconds, 12.0),
                )
            probe_result: dict = {'query': query, 'namespace': namespace}
            start = _time.perf_counter()
            try:
                raw_evidences = await provider.retrieve(query=query, namespace=namespace, limit=3)
                elapsed = round((_time.perf_counter() - start) * 1000.0, 2)
                # Apply content adequacy and topical relevance
                valid_candidates = filter_candidate_evidences(raw_evidences, query, module='数量关系')
                if valid_candidates:
                    probe_status = 'ok'
                elif raw_evidences:
                    probe_status = 'inadequate_content'
                else:
                    probe_status = 'empty'

                probe_result.update({
                    'status': probe_status,
                    'latency_ms': elapsed,
                    'raw_count': len(raw_evidences),
                    'count': len(valid_candidates),
                    'top_evidence': (
                        valid_candidates[0].model_dump() if valid_candidates else None
                    ),
                })
            except Exception as exc:
                elapsed = round((_time.perf_counter() - start) * 1000.0, 2)
                probe_result.update({
                    'status': 'unavailable',
                    'latency_ms': elapsed,
                    'count': 0,
                    'error': str(exc)[:300],
                })
            result['probe'] = probe_result
        return result

    @app.get('/api/knowledge/quality')
    async def knowledge_quality_audit():
        """On-demand deep quality audit endpoint verifying positive, negative, and title-only guards."""
        try:
            provider = get_knowledge_provider()
        except ValueError as exc:
            return {'status': 'unavailable', 'quality_status': 'fail', 'error': str(exc)}
        if isinstance(provider, KnowledgeHubProvider):
            provider = KnowledgeHubProvider(
                base_url=provider.base_url,
                api_key=provider.api_key,
                timeout_seconds=max(provider.timeout_seconds, 15.0),
            )
        audit_res = await audit_retrieval_quality(provider)
        return {
            'provider': provider.provider_name,
            **audit_res,
        }

    @app.post('/api/knowledge/retrieve')
    async def knowledge_retrieve(body: KnowledgeRetrieveInput):
        with connect(path) as db:
            if body.filters and 'session_id' in body.filters:
                require_ai_allowed(db, session_id=str(body.filters['session_id']))
        provider = get_knowledge_provider()
        evidences = await provider.retrieve(body.query, body.namespace, body.filters, body.limit)
        return {'query': body.query, 'namespace': body.namespace, 'items': [e.model_dump() for e in evidences]}

    @app.post('/api/quiz/{sid}/hint')
    async def get_hint(sid: str, body: HintRequest):
        with connect(path) as db:
            require_session(db, sid)
            attempt = db.execute('SELECT * FROM attempts WHERE id=? AND session_id=?', (body.attempt_id, sid)).fetchone()
            if attempt is None:
                raise HTTPException(404, '本会话中不存在该待提示作答')
            require_ai_allowed(db, session_id=sid, attempt_id=body.attempt_id)
            hint = await generate_hint(db, body.attempt_id, body.requested_level)
            tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            if 'exposure_logs' in tables:
                record_exposure(
                    db,
                    attempt_id=body.attempt_id,
                    question_id=attempt['question_id'],
                    session_id=sid,
                    exposure_type='HINT',
                    stage='PRE_SUBMISSION',
                    source_action='QUIZ_HINT',
                    details={'hint_level': body.requested_level},
                )
            return hint.model_dump()

    @app.api_route('/api/attempts/{attempt_id}/diagnose', methods=['GET', 'POST'])
    async def diagnose_error(attempt_id: str):
        with connect(path) as db:
            require_ai_allowed(db, attempt_id=attempt_id)
            diag = await generate_diagnosis(db, attempt_id)
            return diag.model_dump()

    @app.get('/api/user/review-preference')
    def get_review_pref():
        with connect(path) as db:
            return {'preference_mode': get_user_review_preference(db)}

    @app.post('/api/user/review-preference')
    def update_review_pref(body: UpdateReviewPreferenceInput):
        with connect(path) as db:
            mode = set_user_review_preference(db, mode=body.preference_mode)
            return {'preference_mode': mode}

    @app.get('/api/attempts/{attempt_id}/review-diagnosis')
    def get_review_diagnosis(attempt_id: str):
        """Strictly read-only GET: returns review details if exists, or NOT_STARTED payload without creating DB rows or calling AI."""
        with connect(path) as db:
            return get_interactive_review_detail(db, attempt_id)

    @app.get('/api/attempts/{attempt_id}/guided-review')
    def get_teacher_guided_review(attempt_id: str):
        with connect(path) as db:
            return get_guided_review(db, attempt_id)

    @app.post('/api/attempts/{attempt_id}/guided-review')
    async def post_teacher_guided_review(attempt_id: str, body: GuidedReviewInput):
        with connect(path) as db:
            require_ai_allowed(db, attempt_id=attempt_id)
            return await guided_review_turn(db, attempt_id, body.action, body.message, body.answer, body.request_id)

    @app.post('/api/attempts/{attempt_id}/review-diagnosis')
    async def start_review_diagnosis(attempt_id: str):
        """Explicitly initiates review via POST; idempotent if already initiated."""
        with connect(path) as db:
            require_ai_allowed(db, attempt_id=attempt_id)
            return await initiate_interactive_diagnosis(db, attempt_id)

    @app.post('/api/attempts/{attempt_id}/review-cause')
    def post_review_cause(attempt_id: str, body: SetReviewCauseInput):
        """Path 2: User directly selects known cause without calling AI."""
        with connect(path) as db:
            return set_review_cause(
                db,
                attempt_id=attempt_id,
                error_type=body.error_type,
                explanation=body.explanation,
                source='USER_DIRECT',
                stage_code=body.stage_code,
                knowledge_node_id=body.knowledge_node_id,
                supplementary_cause=body.supplementary_cause,
            )

    @app.post('/api/attempts/{attempt_id}/review-feedback')
    async def post_review_diagnosis_feedback(attempt_id: str, body: InteractiveDiagnosisFeedbackInput):
        with connect(path) as db:
            require_ai_allowed(db, attempt_id=attempt_id)
            return await apply_user_diagnosis_feedback(
                db,
                attempt_id=attempt_id,
                feedback_type=body.feedback_type,
                selected_hypothesis_id=body.selected_hypothesis_id,
                user_text=body.user_text,
            )

    @app.post('/api/attempts/{attempt_id}/review-chat')
    async def post_review_chat(attempt_id: str, body: InteractiveReviewChatInput):
        with connect(path) as db:
            require_ai_allowed(db, attempt_id=attempt_id)
            return await continue_interactive_review(
                db,
                attempt_id=attempt_id,
                message=body.message,
                client_request_id=body.client_request_id,
            )

    @app.get('/api/questions/{question_id}/review-history')
    def get_question_review_history(question_id: str):
        with connect(path) as db:
            rows = db.execute(
                f'''SELECT a.id AS attempt_id, a.question_id, a.submitted_at, a.selected_answer,
                          a.correct, {correct_expr(db)} AS effective_correct,
                          a.corrected_correct, a.correction_basis,
                          a.confidence, a.elapsed_ms,
                          idg.status AS review_status, idg.summary AS review_summary,
                          idg.is_user_confirmed, idg.user_feedback_text, idg.last_message_at,
                          COALESCE((SELECT COUNT(*) FROM attempt_followups WHERE attempt_id = a.id), 0) AS message_count
                   FROM attempts a
                   LEFT JOIN interactive_diagnoses idg ON idg.attempt_id = a.id
                   WHERE a.question_id = ? AND a.submitted_at IS NOT NULL
                   ORDER BY a.submitted_at DESC, a.id DESC''',
                (question_id,),
            ).fetchall()
            history = []
            for r in rows:
                item = dict(r)
                item['correct'] = bool(item['correct'])
                if item.get('corrected_correct') is not None:
                    item['correction_note'] = correction_note(item['correct'], item['corrected_correct'])
                    item['effective_correct'] = bool(item['effective_correct'])
                item['has_review'] = bool(item.get('review_status'))
                item['is_user_confirmed'] = bool(item.get('is_user_confirmed')) if item.get('is_user_confirmed') is not None else False
                history.append(item)
            return {'question_id': question_id, 'attempts': history}

    @app.api_route('/api/attempts/{attempt_id}/explain', methods=['GET', 'POST'])
    async def explain_attempt(attempt_id: str):
        with connect(path) as db:
            require_ai_allowed(db, attempt_id=attempt_id)
            detail = await generate_step_by_step_explanation(db, attempt_id)
            att = db.execute('SELECT question_id, session_id FROM attempts WHERE id=?', (attempt_id,)).fetchone()
            if att:
                tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
                if 'exposure_logs' in tables:
                    record_exposure(
                        db,
                        attempt_id=attempt_id,
                        question_id=att['question_id'],
                        session_id=att['session_id'] if 'session_id' in att.keys() else None,
                        exposure_type='EXPLANATION',
                        stage='POST_SUBMISSION',
                        source_action='AI_EXPLAIN',
                        details={},
                    )
            if isinstance(detail, dict):
                # Backward-compatibility fields for legacy callers/tests expecting TutorExplanationOutput
                step_msg = next((m for m in detail.get("messages", []) if m.get("turn_type") == "step_by_step_explanation"), None)
                step_meta = {}
                if step_msg and step_msg.get("metadata_json"):
                    try:
                        raw_meta = step_msg["metadata_json"]
                        step_meta = json.loads(raw_meta) if isinstance(raw_meta, str) else raw_meta
                    except Exception:
                        pass
                detail.setdefault("summary", detail.get("summary") or "分步精讲已生成")
                detail.setdefault("core_concept", step_meta.get("knowledge_node") or detail.get("summary") or "核心考点")
                detail.setdefault("recommended_action", step_meta.get("attempt_check_point") or "对照教材原解析核对步骤")
            return detail

    @app.get('/api/attempts/{attempt_id}/followups')
    def list_attempt_followups(attempt_id: str):
        with connect(path) as db:
            require_ai_allowed(db, attempt_id=attempt_id)
            messages = get_attempt_followups(db, attempt_id)
            return {'attempt_id': attempt_id, 'messages': messages}

    @app.post('/api/attempts/{attempt_id}/followup')
    async def create_attempt_followup(attempt_id: str, body: FollowUpInput):
        with connect(path) as db:
            require_ai_allowed(db, attempt_id=attempt_id)
            reply = await answer_followup(db, attempt_id, body.question, diagnosis=body.diagnosis)
            return reply

    @app.post('/api/exam/start', status_code=201)
    def exam_start(body: StartExamInput):
        with connect(path) as db:
            return start_mock_exam(db, body.time_limit_seconds, body.question_count)

    @app.post('/api/exam/{sid}/submit')
    def exam_submit(sid: str):
        with connect(path) as db:
            return submit_exam_paper(db, sid)

    @app.post('/api/cat/session', status_code=201)
    def cat_start():
        with connect(path) as db:
            return start_mock_exam(db, time_limit_seconds=3600)

    @app.get('/api/cat/{sid}/status')
    def cat_status(sid: str):
        with connect(path) as db:
            sess = require_session(db, sid)
            attempts = db.execute(
                f'''SELECT {correct_expr(db)} AS correct, q.difficulty FROM attempts a
                   JOIN questions q ON q.id=a.question_id
                   WHERE a.session_id=? AND a.submitted_at IS NOT NULL''',
                (sid,),
            ).fetchall()
            resp_list = [(float(r['difficulty']), int(r['correct'])) for r in attempts]
            theta, se = estimate_ability_theta(resp_list)
            is_stopped = should_stop_cat(len(resp_list), se)
            band_info = theta_to_ability_band(theta)
            return {
                'session_id': sid,
                'answered_count': len(resp_list),
                'ability_theta': theta,
                'standard_error': se,
                'ability_band': band_info['ability_band'],
                'assumed_distribution_percentile': band_info['assumed_distribution_percentile'],
                'percentile': band_info['assumed_distribution_percentile'],
                'normalized_score': band_info['normalized_score'],
                'is_terminated': is_stopped or (sess['status'] == 'completed'),
            }

    @app.get('/api/plan/today')
    def get_today_plan(total: int = Query(default=10, ge=1, le=50)):
        with connect(path) as db:
            return generate_daily_plan(db, total_items=total)

    @app.post('/api/plan/today/session', status_code=201)
    def start_plan_session(body: DailyPlanInput):
        with connect(path) as db:
            plan = generate_daily_plan(db, total_items=body.total_items)
            qids = [it['question_id'] for it in plan['items']]
            if not qids:
                raise HTTPException(409, '今日计划无可用题目')
            sid = create_session_snapshot(db, qids, 'PRACTICE')
            db.execute('UPDATE daily_plans SET session_id=? WHERE plan_date=?', (sid, plan['plan_date']))
            db.commit()
            return {'session_id': sid, 'plan_date': plan['plan_date'], 'total': len(qids)}

    @app.get('/api/analytics/calibration')
    def calibration_analytics():
        with connect(path) as db:
            return calculate_calibration(db)

    @app.post('/api/shenlun/session', status_code=201)
    def shenlun_start(body: ShenlunSessionInput):
        with connect(path) as db:
            if body.daily:
                db.execute('BEGIN IMMEDIATE')
            return start_shenlun_session(db, body.material_id, daily=body.daily, next_task=body.next_task)

    @app.post('/api/shenlun/draft')
    def shenlun_draft(body: ShenlunDraftInput):
        with connect(path) as db:
            return save_shenlun_draft(db, body.session_id, body.draft_text, body.notes)

    @app.get('/api/shenlun/{session_id}/guidance')
    def shenlun_guidance(session_id: str):
        with connect(path) as db:
            return get_guidance(db, session_id)

    @app.post('/api/shenlun/{session_id}/guidance')
    async def shenlun_guidance_turn(session_id: str, body: GuideInput):
        with connect(path) as db:
            return await guide_turn(db, session_id, body)

    @app.get('/api/shenlun/{session_id}/point-trace')
    def shenlun_point_trace(session_id: str):
        with connect(path) as db:
            return {'point_trace': get_point_trace(db, session_id)}

    @app.post('/api/shenlun/{session_id}/point-trace')
    async def retry_shenlun_point_trace(session_id: str):
        with connect(path) as db:
            require_shenlun_ai(db)
            row = db.execute('SELECT final_answer FROM shenlun_sessions WHERE id=?', (session_id,)).fetchone()
            if row is None:
                raise HTTPException(404, '申论会话不存在')
            if not row['final_answer']:
                raise HTTPException(409, '请先提交作答')
            return {'point_trace': await assess_point_trace(db, session_id, row['final_answer'], retry=True)}

    @app.post('/api/shenlun/submit')
    async def shenlun_submit(body: ShenlunSubmitInput):
        with connect(path) as db:
            return await submit_shenlun_assessment(db, body.session_id, body.final_answer)

    @app.get('/api/shenlun/mastery')
    def shenlun_mastery():
        with connect(path) as db:
            return {'skills': get_shenlun_mastery_model(db)}

    @app.get('/api/shenlun/materials')
    def shenlun_materials_list():
        with connect(path) as db:
            return {'materials': list_shenlun_materials(db)}

    @app.get('/api/shenlun/materials/{material_id}')
    def shenlun_material_detail(material_id: str):
        with connect(path) as db:
            return get_shenlun_material_detail(db, material_id)

    @app.get('/api/shenlun/teacher/{session_id}')
    def shenlun_teacher_diagnosis(session_id: str):
        if get_latest_teacher_diagnosis is None:
            raise HTTPException(501, '申论本地教师诊断引擎未就绪')
        with connect(path) as db:
            return {'diagnosis': get_latest_teacher_diagnosis(db, session_id)}

    @app.get('/api/shenlun/{session_id}/teacher/{teacher_id}/followups')
    def list_shenlun_teacher_followups(session_id: str, teacher_id: str):
        if get_teacher_followups is None:
            raise HTTPException(501, '申论本地教师诊断引擎未就绪')
        with connect(path) as db:
            return {'messages': get_teacher_followups(db, session_id, teacher_id)}

    @app.post('/api/shenlun/{session_id}/teacher/{teacher_id}/followup')
    async def create_shenlun_teacher_followup(session_id: str, teacher_id: str, body: ShenlunTeacherFollowUpInput):
        if answer_teacher_followup is None:
            raise HTTPException(501, '申论本地教师诊断引擎未就绪')
        with connect(path) as db:
            require_shenlun_ai(db)
            try:
                reply = await answer_teacher_followup(db, session_id, teacher_id, body.question, body.user_attribution, body.intent)
            except ValueError as exc:
                raise HTTPException(400, str(exc))
            return reply

    # =========================================================================
    # Four Module Teachers: 逻辑判断、定义判断、数量关系、资料分析名师智能体
    # =========================================================================
    module_teacher_service = ModuleTeacherService()

    @app.get('/api/module-teachers')
    def api_list_module_teachers():
        return module_teacher_service.list_teachers()

    @app.get('/api/module-teachers/{teacher_id}/profile')
    def api_get_module_teacher_profile(teacher_id: str):
        try:
            return module_teacher_service.get_teacher_profile(teacher_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @app.post('/api/module-teachers/{teacher_id}/explain')
    async def api_explain_with_module_teacher(teacher_id: str, payload: dict):
        try:
            return await module_teacher_service.explain_current_question(teacher_id, payload)
        except ValueError as exc:
            status_code = 404 if teacher_id not in module_teacher_service._config.get("teachers", {}) else 422
            raise HTTPException(status_code, str(exc))
        except Exception as exc:
            raise HTTPException(500, f"名师讲题引擎调用异常: {exc}")

    # =========================================================================
    # Phase LF1: Learning Framework, Skill Tree & Error Overlay Endpoints
    # =========================================================================

    @app.get('/api/learning-framework')
    def api_get_learning_framework():
        with connect(path) as db:
            return get_learning_framework(db)

    @app.get('/api/learning-skills/tree')
    def api_get_learning_skill_tree():
        with connect(path) as db:
            return {'tree': get_learning_skill_tree(db)}

    @app.get('/api/learning-skills/{skill_id_or_code}')
    def api_get_learning_skill(skill_id_or_code: str):
        with connect(path) as db:
            row = db.execute(
                '''SELECT * FROM learning_skills WHERE id=? OR code=?''',
                (skill_id_or_code, skill_id_or_code),
            ).fetchone()
            if row is None:
                raise HTTPException(404, f"学习技能 '{skill_id_or_code}' 不存在")
            return dict(row)

    @app.get('/api/questions/{question_id}/learning-map')
    def api_get_question_learning_map(question_id: str):
        with connect(path) as db:
            return get_question_learning_map(db, question_id)

    @app.post('/api/questions/{question_id}/skills', status_code=201)
    def api_bind_question_skill(question_id: str, body: QuestionSkillBindInput):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            q = db.execute('SELECT id FROM questions WHERE id=?', (question_id,)).fetchone()
            if q is None:
                raise HTTPException(404, f"题目 '{question_id}' 不存在")
            skill = db.execute('SELECT id, knowledge_node_code FROM learning_skills WHERE id=? OR code=?', (body.skill_id, body.skill_id)).fetchone()
            if skill is None:
                raise HTTPException(404, f"学习技能 '{body.skill_id}' 不存在")

            binding_id = f"qsb_{question_id}_{skill['id']}_{body.role}"
            now_iso = now()
            db.execute(
                '''INSERT INTO question_skill_bindings
                   (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(question_id, learning_skill_id, role) DO UPDATE SET
                     weight=excluded.weight,
                     status=excluded.status''',
                (binding_id, question_id, skill['id'], skill['knowledge_node_code'], body.role, body.weight, 'manual', 'active', '{}', now_iso)
            )
            db.commit()
            return {'status': 'bound', 'binding_id': binding_id}

    @app.post('/api/questions', status_code=201)
    def api_create_question(body: ManualQuestionInput):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            qid = f"manual_q_{uuid4().hex[:10]}"
            options_json = json.dumps(body.options, ensure_ascii=False)
            content_fp = hashlib.sha256(f"{body.source}:{qid}:{body.stem}:{options_json}".encode('utf-8')).hexdigest()
            subject = '申论' if body.module == '申论' else '行测'
            db.execute(
                '''INSERT INTO questions (
                    id, source, year, exam_type, subject, module, stem, options_json,
                    difficulty, answer, explanation, estimated_seconds, is_verified,
                    stem_assets_json, option_assets_json, source_locator, content_fingerprint
                ) VALUES (?, ?, ?, '专项练习', ?, ?, ?, ?, ?, ?, ?, ?, 1, '[]', '{}', '手动录入', ?)''',
                (
                    qid, body.source, body.year or 2026, subject, body.module,
                    body.stem, options_json, body.difficulty, body.answer,
                    body.explanation, body.estimated_seconds, content_fp
                )
            )

            # Map to knowledge node
            db.execute(
                '''INSERT OR REPLACE INTO question_knowledge_map (question_id, knowledge_node_id, weight)
                   VALUES (?, ?, 1.0)''',
                (qid, body.knowledge_node_id)
            )

            # Skill binding
            ls = db.execute(
                '''SELECT id, knowledge_node_code FROM learning_skills
                   WHERE id = ? OR knowledge_node_code = (SELECT knowledge_node_code FROM knowledge_nodes WHERE id = ?)''',
                (body.knowledge_node_id, body.knowledge_node_id)
            ).fetchone()

            if ls is None:
                fallback_id = 'graphic_position' if '图形' in body.module else 'growth'
                ls = db.execute('SELECT id, knowledge_node_code FROM learning_skills WHERE id = ?', (fallback_id,)).fetchone()

            if ls:
                binding_id = f"qsb_{qid}_{ls['id']}_primary"
                db.execute(
                    '''INSERT INTO question_skill_bindings
                       (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (binding_id, qid, ls['id'], ls['knowledge_node_code'], 'primary', 1.0, 'manual', 'active', '{}', now())
                )

            rebuild_mastery(db)
            return {'status': 'created', 'id': qid}

    @app.patch('/api/questions/{question_id}')
    def api_update_question(question_id: str, body: UpdateQuestionInput):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            q = db.execute('SELECT * FROM questions WHERE id = ?', (question_id,)).fetchone()
            if not q:
                raise HTTPException(404, f"题目 '{question_id}' 不存在")

            if body.answer:
                db.execute('UPDATE questions SET answer = ? WHERE id = ?', (body.answer, question_id))
            if body.explanation is not None:
                db.execute('UPDATE questions SET explanation = ? WHERE id = ?', (body.explanation, question_id))
            if body.stem is not None:
                db.execute('UPDATE questions SET stem = ? WHERE id = ?', (body.stem, question_id))
            if body.options is not None:
                db.execute('UPDATE questions SET options_json = ? WHERE id = ?', (json.dumps(body.options, ensure_ascii=False), question_id))
            if body.knowledge_node_id:
                db.execute(
                    '''INSERT OR REPLACE INTO question_knowledge_map (question_id, knowledge_node_id, weight)
                       VALUES (?, ?, 1.0)''',
                    (question_id, body.knowledge_node_id)
                )

            rebuild_mastery(db)
            rebuild_reviews(db)
            return {'status': 'updated', 'id': question_id}


    @app.get('/api/attempts/{attempt_id}/error-location')
    async def api_get_attempt_error_location(attempt_id: str):
        with connect(path) as db:
            return await get_attempt_error_location(db, attempt_id)

    @app.post('/api/attempts/{attempt_id}/error-structured', status_code=201)
    def api_record_structured_error(attempt_id: str, body: StructuredErrorInput):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            event = record_error_event(
                db,
                attempt_id=attempt_id,
                error_type=body.error_type,
                error_subtype=body.error_subtype,
                actual_error_skill_id=body.actual_error_skill_id,
                diagnosis_source=body.diagnosis_source,
                diagnosis_confidence=body.diagnosis_confidence,
                explanation=body.explanation,
            )
            db.commit()
            return event

    @app.get('/api/learning-skills/{skill_id_or_code}/errors')
    def api_get_skill_errors(skill_id_or_code: str):
        with connect(path) as db:
            skill = db.execute('SELECT id, name, knowledge_node_code FROM learning_skills WHERE id=? OR code=?', (skill_id_or_code, skill_id_or_code)).fetchone()
            if skill is None:
                raise HTTPException(404, f"技能 '{skill_id_or_code}' 不存在")
            rebuild_error_overlay(db, specific_skill_id=skill['id'])
            rebuild_learning_stage(db, specific_skill_id=skill['id'])
            overlay = db.execute('SELECT * FROM error_overlay WHERE learning_skill_id=?', (skill['id'],)).fetchone()
            events = db.execute(
                '''SELECT ee.*, esb.role, esb.provenance
                   FROM error_events ee
                   JOIN error_skill_bindings esb ON esb.error_event_id=ee.id
                   WHERE esb.learning_skill_id=?
                   ORDER BY ee.occurred_at DESC''',
                (skill['id'],)
            ).fetchall()
            return {
                'skill_id': skill['id'],
                'skill_name': skill['name'],
                'knowledge_node_code': skill['knowledge_node_code'],
                'overlay': dict(overlay) if overlay else None,
                'error_events': [dict(e) for e in events],
            }

    @app.get('/api/knowledge-nodes/{node_code:path}/error-summary')
    def api_get_knowledge_node_error_summary(node_code: str):
        with connect(path) as db:
            rebuild_error_overlay(db)
            rows = db.execute(
                '''SELECT eo.*, ls.name AS skill_name
                   FROM error_overlay eo
                   JOIN learning_skills ls ON ls.id=eo.learning_skill_id
                   WHERE eo.knowledge_node_code=? OR ls.knowledge_node_code=?''',
                (node_code, node_code)
            ).fetchall()
            total_attempts = sum(r['attempt_count'] for r in rows)
            total_wrongs = sum(r['wrong_count'] for r in rows)
            total_high_conf = sum(r['high_confidence_error_count'] for r in rows)
            return {
                'knowledge_node_code': node_code,
                'skills_count': len(rows),
                'total_attempts': total_attempts,
                'total_wrong_count': total_wrongs,
                'high_confidence_errors': total_high_conf,
                'skills': [dict(r) for r in rows],
            }

    @app.get('/api/learning-map/summary')
    def api_get_learning_map_summary():
        with connect(path) as db:
            return get_knowledge_map_summary(db)

    @app.post('/api/projections/rebuild')
    def api_rebuild_projections():
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            rebuild_error_overlay(db)
            rebuild_learning_stage(db)
            db.commit()
            return {'status': 'ok', 'rebuilt': ['error_overlay', 'learning_stages']}

    # =========================================================================
    # Phase QI1: Question Bank Importer, Review Queue & Publish Gate Endpoints
    # =========================================================================

    @app.post('/api/importer/jobs', status_code=201)
    def api_create_import_job(body: CreateImportJobInput):
        with connect(path) as db:
            service = QuestionImportService(db)
            meta = dict(body.metadata or {})
            if body.answer_document_id:
                meta['answer_document_id'] = body.answer_document_id
            if body.answer_document_version_id:
                meta['answer_document_version_id'] = body.answer_document_version_id
            return service.create_job(
                source_document_id=body.source_document_id,
                source_document_version_id=body.source_document_version_id,
                filename=body.filename,
                metadata=meta,
            )

    @app.get('/api/importer/jobs')
    def api_list_import_jobs(limit: int = Query(default=50, ge=1, le=100)):
        with connect(path) as db:
            service = QuestionImportService(db)
            return {'jobs': service.list_jobs(limit=limit)}

    @app.get('/api/importer/jobs/{job_id}')
    def api_get_import_job(job_id: str):
        with connect(path) as db:
            service = QuestionImportService(db)
            try:
                return service.get_job(job_id)
            except ValueError as e:
                raise HTTPException(404, str(e))

    @app.delete('/api/importer/jobs/{job_id}')
    def api_delete_import_job(job_id: str):
        with connect(path) as db:
            db.execute('DELETE FROM question_import_drafts WHERE job_id=?', (job_id,))
            db.execute('DELETE FROM question_import_jobs WHERE id=?', (job_id,))
            db.commit()
            return {'status': 'deleted', 'id': job_id}

    @app.post('/api/importer/jobs/{job_id}/batch-answers')
    def api_batch_answers(job_id: str, body: BatchAnswersInput):
        with connect(path) as db:
            db.execute('BEGIN IMMEDIATE')
            job = db.execute('SELECT * FROM question_import_jobs WHERE id = ?', (job_id,)).fetchone()
            if not job:
                raise HTTPException(404, f"导入任务 '{job_id}' 不存在")

            updated_count = 0
            for k, v in body.answers.items():
                ans = v.strip().upper()
                if ans not in ('A', 'B', 'C', 'D'):
                    continue
                try:
                    q_num = int(k)
                except ValueError:
                    continue

                draft = db.execute(
                    'SELECT id FROM question_import_drafts WHERE job_id = ? AND question_number = ?',
                    (job_id, q_num)
                ).fetchone()
                if draft:
                    db.execute(
                        '''UPDATE question_import_drafts
                           SET answer = ?, answer_matched = 1, answer_source = 'human_batch',
                               validation_status = 'READY_TO_PUBLISH'
                           WHERE id = ?''',
                        (ans, draft['id'])
                    )
                    updated_count += 1

            # Recompute job stats
            total = db.execute('SELECT count(*) FROM question_import_drafts WHERE job_id = ?', (job_id,)).fetchone()[0]
            validated = db.execute('SELECT count(*) FROM question_import_drafts WHERE job_id = ? AND answer_matched = 1', (job_id,)).fetchone()[0]
            needs_rev = db.execute("SELECT count(*) FROM question_import_drafts WHERE job_id = ? AND validation_status = 'NEEDS_REVIEW'", (job_id,)).fetchone()[0]
            auto_acc = db.execute("SELECT count(*) FROM question_import_drafts WHERE job_id = ? AND validation_status = 'AUTO_ACCEPTED'", (job_id,)).fetchone()[0]
            ready_pub = db.execute("SELECT count(*) FROM question_import_drafts WHERE job_id = ? AND validation_status = 'READY_TO_PUBLISH'", (job_id,)).fetchone()[0]

            new_status = 'needs_review' if needs_rev > 0 else 'ready_to_publish' if (validated > 0 or ready_pub > 0) else job['status']
            db.execute(
                '''UPDATE question_import_jobs
                   SET status = ?, total_candidates = ?, validated_questions = ?,
                       needs_review = ?, auto_accepted_count = ?, updated_at = ?
                   WHERE id = ?''',
                (new_status, total, validated, needs_rev, auto_acc, now(), job_id)
            )
            db.commit()

            return {'status': 'ok', 'updated_count': updated_count}


    @app.post('/api/importer/jobs/{job_id}/process')
    async def api_process_import_job(job_id: str, body: ProcessImportJobInput):
        with connect(path) as db:
            service = QuestionImportService(db)
            try:
                job = service.get_job(job_id)
            except ValueError as e:
                raise HTTPException(404, str(e))

            if body.parsed_document is not None:
                parsed_doc = ParsedDocument.model_validate(body.parsed_document)
            else:
                from .knowledge import KnowledgeHubProvider, KnowledgeProviderError
                provider = KnowledgeHubProvider()
                try:
                    raw = await provider.get_parsed_document(
                        job.source_document_id, job.source_document_version_id
                    )
                except KnowledgeProviderError as exc:
                    raise HTTPException(502, str(exc)) from exc
                parsed_doc = ParsedDocument.model_validate(raw)

            answer_parsed_doc = None
            if getattr(body, 'answer_parsed_document', None) is not None:
                answer_parsed_doc = ParsedDocument.model_validate(body.answer_parsed_document)
            elif (job.metadata or {}).get('answer_document_id'):
                from .knowledge import KnowledgeHubProvider, KnowledgeProviderError
                ans_doc_id = job.metadata['answer_document_id']
                ans_ver_id = job.metadata.get('answer_document_version_id')
                provider = KnowledgeHubProvider()
                try:
                    raw_ans = await provider.get_parsed_document(ans_doc_id, ans_ver_id)
                    answer_parsed_doc = ParsedDocument.model_validate(raw_ans)
                except KnowledgeProviderError as exc:
                    logger.warning("failed_to_fetch_answer_parsed_doc: %s", exc)

            return await service.process_job(job_id, parsed_doc, answer_parsed_doc=answer_parsed_doc)

    async def _run_async_import_pipeline(
        db_path,
        job_id: str,
        q_filename: str,
        q_bytes: bytes,
        a_filename: str | None,
        a_bytes: bytes | None,
        title: str | None,
    ):
        from .knowledge import KnowledgeHubProvider
        from .domain.importer.schemas import JobStatus, utc_now_iso
        provider = KnowledgeHubProvider()

        with connect(db_path) as db:
            db.execute(
                "UPDATE question_import_jobs SET status=?, stage=?, updated_at=? WHERE id=?",
                (JobStatus.QUEUED.value, 'uploading_to_hub', utc_now_iso(), job_id),
            )
            db.commit()

        try:
            # 1. Upload Question PDF to Knowledge Hub
            q_res = await provider.import_document(
                filename=q_filename,
                content=q_bytes,
                namespace='gongkao/xingce',
                title=title or q_filename,
                wait=True,
            )
            q_doc_id = q_res['document_id']
            q_ver_id = q_res['document_version_id']

            # 2. Upload optional Answer PDF
            a_doc_id = None
            a_ver_id = None
            if a_bytes is not None:
                a_res = await provider.import_document(
                    filename=a_filename or 'answer.pdf',
                    content=a_bytes,
                    namespace='gongkao/xingce',
                    title=(title or '') + ' 答案解析',
                    wait=True,
                )
                a_doc_id = a_res['document_id']
                a_ver_id = a_res['document_version_id']

            # 3. Update job source document IDs
            with connect(db_path) as db:
                meta = {'title': title}
                if a_doc_id:
                    meta['answer_document_id'] = a_doc_id
                    meta['answer_document_version_id'] = a_ver_id
                db.execute(
                    "UPDATE question_import_jobs SET source_document_id=?, source_document_version_id=?, metadata_json=?, updated_at=? WHERE id=?",
                    (q_doc_id, q_ver_id, json.dumps(meta, ensure_ascii=False), utc_now_iso(), job_id),
                )
                db.commit()

            # 4. Fetch parsed documents and process job
            raw_q = await provider.get_parsed_document(q_doc_id, q_ver_id)
            q_parsed = ParsedDocument.model_validate(raw_q)

            a_parsed = None
            if a_doc_id:
                try:
                    raw_a = await provider.get_parsed_document(a_doc_id, a_ver_id)
                    a_parsed = ParsedDocument.model_validate(raw_a)
                except Exception as exc:
                    logger.warning("Failed to get parsed Answer PDF: %s", exc)

            with connect(db_path) as db:
                service = QuestionImportService(db)
                await service.process_job(job_id, q_parsed, answer_parsed_doc=a_parsed)

        except Exception as exc:
            logger.exception("Background import pipeline failed for job %s: %s", job_id, exc)
            with connect(db_path) as db:
                db.execute(
                    "UPDATE question_import_jobs SET status=?, stage='failed', error=?, updated_at=? WHERE id=?",
                    (JobStatus.FAILED.value, str(exc), utc_now_iso(), job_id),
                )
                db.commit()

    @app.post('/api/importer/upload', status_code=status.HTTP_202_ACCEPTED)
    async def api_upload_import_files(
        background_tasks: BackgroundTasks,
        question_file: UploadFile = File(...),
        answer_file: UploadFile | None = File(default=None),
        title: str | None = Form(default=None),
    ):
        q_bytes = await question_file.read()
        q_filename = question_file.filename or 'question.pdf'
        a_bytes = await answer_file.read() if answer_file is not None else None
        a_filename = answer_file.filename if answer_file is not None else None

        with connect(path) as db:
            service = QuestionImportService(db)
            job = service.create_job(
                source_document_id=f"pending_{uuid4().hex[:8]}",
                filename=q_filename,
                metadata={'title': title, 'stage': 'uploading'},
            )

        background_tasks.add_task(
            _run_async_import_pipeline,
            path,
            job.id,
            q_filename,
            q_bytes,
            a_filename,
            a_bytes,
            title,
        )

        return {
            'job_id': job.id,
            'status': 'queued',
            'stage': 'uploading',
            'filename': q_filename,
            'message': 'Import job queued successfully',
        }

    @app.get('/api/importer/jobs/{job_id}/review')
    def api_get_review_queue(
        job_id: str,
        status: ValidationStatus | None = Query(default=None),
        reason: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
    ):
        with connect(path) as db:
            service = QuestionImportService(db)
            items = service.get_review_items(
                job_id=job_id,
                status_filter=status,
                reason_filter=reason,
                limit=limit,
                offset=offset,
            )
            return {'items': items, 'count': len(items)}

    @app.get('/api/importer/drafts/{draft_id}')
    def api_get_draft(draft_id: str):
        with connect(path) as db:
            service = QuestionImportService(db)
            try:
                return service.get_draft(draft_id)
            except ValueError as e:
                raise HTTPException(404, str(e))

    @app.post('/api/importer/drafts/{draft_id}/review')
    def api_review_draft(draft_id: str, body: ReviewDecisionInput):
        with connect(path) as db:
            service = QuestionImportService(db)
            try:
                return service.apply_review_decision(draft_id, body)
            except ValueError as e:
                raise HTTPException(400, str(e))

    @app.post('/api/importer/jobs/{job_id}/publish')
    def api_publish_drafts(job_id: str, body: BatchPublishInput):
        with connect(path) as db:
            service = QuestionImportService(db)
            try:
                return service.publish_drafts(job_id, body.draft_ids)
            except ValueError as e:
                raise HTTPException(400, str(e))

    @app.post('/api/importer/jobs/{job_id}/reclassify')
    async def api_reclassify_drafts(job_id: str, body: ReclassifyInput):
        with connect(path) as db:
            service = QuestionImportService(db)
            try:
                return await service.reclassify_drafts(body)
            except ValueError as e:
                raise HTTPException(400, str(e))

    # =========================================================================
    # User Notes & Reflection Endpoints (我的笔记／感悟)
    # =========================================================================

    @app.get('/api/notes')
    def api_list_notes(
        question_id: str | None = None,
        attempt_id: str | None = None,
        knowledge_node_id: str | None = None,
        knowledge_node_code: str | None = None,
        module: str | None = None,
        note_type: str | None = None,
        query: str | None = None,
        limit: int = Query(default=50, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        include_shenlun: bool = True,
    ):
        with connect(path) as db:
            return list_user_notes(
                db,
                user_id="default_user",
                question_id=question_id,
                attempt_id=attempt_id,
                knowledge_node_id=knowledge_node_id,
                knowledge_node_code=knowledge_node_code,
                module=module,
                note_type=note_type,
                query=query,
                limit=limit,
                offset=offset,
                include_shenlun=include_shenlun,
            )

    @app.post('/api/notes', status_code=201)
    def api_create_or_update_note(body: CreateNoteInput):
        with connect(path) as db:
            try:
                title_val = body.title if "title" in body.model_fields_set else _UNSET
                kn_id_val = body.knowledge_node_id if "knowledge_node_id" in body.model_fields_set else _UNSET
                kn_code_val = body.knowledge_node_code if "knowledge_node_code" in body.model_fields_set else _UNSET
                module_val = body.module if "module" in body.model_fields_set else _UNSET
                meta_val = body.metadata if "metadata" in body.model_fields_set else _UNSET

                res = create_or_update_note(
                    db,
                    user_id="default_user",
                    note_id=body.note_id,
                    expected_version=body.expected_version,
                    note_type=body.note_type,
                    content=body.content,
                    title=title_val,
                    question_id=body.question_id,
                    attempt_id=body.attempt_id,
                    knowledge_node_id=kn_id_val,
                    knowledge_node_code=kn_code_val,
                    module=module_val,
                    source_type=body.source_type,
                    source_message_id=body.source_message_id,
                    source_quote=body.source_quote,
                    metadata=meta_val,
                )
                return res
            except NoteVersionConflictError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": str(exc),
                        "error_code": "VERSION_CONFLICT",
                        "expected_version": exc.expected_version,
                        "current_version": exc.current_version,
                        "current_note": exc.current_note,
                    },
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc))

    @app.get('/api/notes/{note_id}')
    def api_get_note(note_id: str):
        with connect(path) as db:
            try:
                return get_note_by_id(db, note_id, user_id="default_user")
            except ValueError as exc:
                raise HTTPException(404, str(exc))

    @app.delete('/api/notes/{note_id}')
    def api_delete_note(note_id: str):
        with connect(path) as db:
            ok = delete_note(db, note_id, user_id="default_user")
            if not ok:
                raise HTTPException(404, f"笔记 {note_id} 不存在或已被删除")
            return {"status": "deleted", "id": note_id}

    @app.post('/api/attempts/{attempt_id}/clip-message', status_code=201)
    def api_clip_review_message(attempt_id: str, body: ClipReviewMessageInput):
        """Bookmark a message from review dialogue into user personal notes with deduplication."""
        with connect(path) as db:
            att = db.execute("SELECT question_id FROM attempts WHERE id=?", (attempt_id,)).fetchone()
            if not att:
                raise HTTPException(404, f"作答 {attempt_id} 不存在")

            q_id = att["question_id"]
            src_type = "review_ai_message" if body.message_role == "assistant" else "review_user_message"
            msg_id = body.source_message_id or f"msg_{hash(body.message_content[:50])}"
            title = body.title or ("复盘解析收藏" if body.message_role == "assistant" else "我的复盘心得")

            res = create_or_update_note(
                db,
                user_id="default_user",
                note_type="dialogue_clipping",
                content=body.message_content,
                title=title,
                question_id=q_id,
                attempt_id=attempt_id,
                source_type=src_type,
                source_message_id=msg_id,
                source_quote=body.message_content[:150],
                metadata={"clipped_at": now(), "turn_type": body.turn_type},
            )
            return res

    @app.post('/api/notes/{note_id}/associate-node')
    def api_associate_note_with_node(note_id: str, body: AssociateNodeInput):
        with connect(path) as db:
            kn_id = body.knowledge_node_id
            kn_code = None
            if kn_id and kn_id not in ("", "CLEAR"):
                kn_row = db.execute("SELECT id, knowledge_node_code FROM knowledge_nodes WHERE id=?", (kn_id,)).fetchone()
                if not kn_row:
                    raise HTTPException(404, f"考点节点 {kn_id} 不存在")
                kn_code = kn_row["knowledge_node_code"]
            else:
                kn_id = None
                kn_code = None

            try:
                res = create_or_update_note(
                    db,
                    user_id="default_user",
                    note_id=note_id,
                    expected_version=body.expected_version,
                    knowledge_node_id=kn_id,
                    knowledge_node_code=kn_code,
                )
                return res
            except NoteVersionConflictError as exc:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": str(exc),
                        "error_code": "VERSION_CONFLICT",
                        "expected_version": exc.expected_version,
                        "current_version": exc.current_version,
                        "current_note": exc.current_note,
                    },
                )
            except ValueError as exc:
                raise HTTPException(400, str(exc))

    # ------------------------------------------------------------------
    # 系统设置（AI 模型网关 + 知识检索）：可视化配置入口，保存即热重载。
    # ------------------------------------------------------------------
    @app.get('/api/settings')
    def api_get_settings():
        return settings_service.settings_snapshot()

    @app.put('/api/settings')
    def api_put_settings(payload: dict[str, Any]):
        raw = settings_service.normalize_incoming(payload)
        try:
            incoming = settings_service.SystemSettings.model_validate(raw)
        except Exception as exc:
            raise HTTPException(422, f'设置格式有误：{exc}')
        merged = settings_service.merge_settings(settings_service.load_settings(), incoming)
        settings_service.save_settings(merged)
        settings_service.apply_knowledge_env(merged)
        settings_service.apply_saved_settings_gateway(merged)
        return settings_service.settings_snapshot()

    class AiTestRequest(BaseModel):
        policy: Literal['FAST', 'BALANCED', 'STRONG', 'fallback'] = 'BALANCED'
        override: dict[str, Any] | None = None

    @app.post('/api/settings/ai/test')
    async def api_test_ai(payload: AiTestRequest):
        override = None
        if payload.override:
            try:
                override = settings_service.PolicySettings.model_validate(
                    settings_service.normalize_incoming(
                        {'ai': {'policies': {'X': payload.override}}}
                    )['ai']['policies']['X']
                )
            except Exception as exc:
                raise HTTPException(422, f'测试参数有误：{exc}')
        try:
            config = settings_service.resolve_policy_config(payload.policy, override)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return await settings_service.test_ai_policy(config)

    class KnowledgeTestRequest(BaseModel):
        query: str = '工程问题已知时间设工作总量'

    @app.post('/api/settings/knowledge/test')
    async def api_test_knowledge(payload: KnowledgeTestRequest):
        try:
            provider = get_knowledge_provider()
        except ValueError as exc:
            return {'ok': False, 'message': f'知识 Provider 配置错误：{exc}'}
        health = await provider.health_check()
        result: dict[str, Any] = {'ok': health.status == 'healthy', **health.model_dump()}
        if health.status != 'healthy':
            result['message'] = health.message or f'知识检索当前不可用（{health.status}）'
            return result
        start = perf_counter()
        try:
            evidences = await provider.retrieve(
                query=payload.query, namespace='gongkao/xingce/quantitative', limit=3,
            )
            result['probe_ok'] = True
            result['probe_count'] = len(evidences)
            result['message'] = (
                f'连接正常，检索到 {len(evidences)} 条证据（耗时 {round((perf_counter() - start) * 1000)} ms）。'
            )
        except Exception as exc:
            result['probe_ok'] = False
            result['message'] = f'健康检查通过，但检索探测失败：{exc}'
        return result

    app.include_router(teaching_router(path))

    return app


app = create_app()
