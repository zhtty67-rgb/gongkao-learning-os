"""资料转学习任务 API（additive surface，与 adaptive_router 同款挂载模式）。"""
from fastapi import APIRouter
from fastapi import HTTPException
from pydantic import BaseModel, Field

from .ai import get_model_gateway
from .db import connect
from .domain import study_tasks as tasks
from .domain.exam import require_ai_allowed
from .knowledge import get_knowledge_provider


class GenerateInput(BaseModel):
    node_id: str
    excerpt_only: bool = False


class TaskPatchInput(BaseModel):
    title: str | None = None
    content: str | None = None
    detail: dict | None = None


class AnswerInput(BaseModel):
    answer: str
    understood: bool | None = Field(default=None, description='自评：是否已理解（可选）')


class SkipInput(BaseModel):
    reason: str | None = None


def study_router(path):
    router = APIRouter(prefix='/api/study', tags=['Study Tasks'])

    @router.get('/sets')
    def list_sets(node_id: str | None = None, status: str | None = None):
        with connect(path) as db:
            return {'sets': tasks.list_sets(db, node_id=node_id, status=status)}

    @router.get('/sets/{set_id}')
    def get_set(set_id: str):
        try:
            with connect(path) as db:
                return tasks.get_set(db, set_id)
        except ValueError as exc:
            raise HTTPException(404, str(exc))

    @router.post('/sets/generate')
    async def generate(body: GenerateInput):
        """从考点资料生成学习任务草稿。excerpt_only=True 走零模型路径（仅原文摘录）。"""
        with connect(path) as db:
            if not body.excerpt_only:
                try:
                    require_ai_allowed(db)
                except Exception as exc:  # noqa: BLE001 —— 考试锁等门禁以统一文案透出
                    raise HTTPException(423, str(exc))
            if body.excerpt_only:
                result = tasks.generate_excerpt_only_draft(db, body.node_id)
            else:
                provider = get_knowledge_provider()
                gateway = get_model_gateway()
                result = await tasks.generate_draft(db, body.node_id, provider, gateway)
        # 生成成功与否以响应体 status 字段区分（ok / model_unavailable / no_evidence）
        return result

    @router.patch('/tasks/{task_id}')
    def patch_task(task_id: str, body: TaskPatchInput):
        with connect(path) as db:
            try:
                tasks.update_task(db, task_id, title=body.title,
                                  content=body.content, detail=body.detail)
            except ValueError as exc:
                raise HTTPException(409, str(exc))
        return {'updated': task_id}

    @router.delete('/tasks/{task_id}')
    def delete_task(task_id: str):
        with connect(path) as db:
            try:
                tasks.delete_task(db, task_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc))
        return {'deleted': task_id}

    @router.post('/sets/{set_id}/publish')
    def publish(set_id: str):
        with connect(path) as db:
            try:
                return tasks.publish_set(db, set_id)
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    @router.post('/sets/{set_id}/archive')
    def archive(set_id: str):
        with connect(path) as db:
            try:
                return tasks.archive_set(db, set_id)
            except ValueError as exc:
                raise HTTPException(404, str(exc))

    @router.post('/tasks/{task_id}/answer')
    def answer(task_id: str, body: AnswerInput):
        with connect(path) as db:
            try:
                return tasks.answer_task(db, task_id, answer=body.answer,
                                         understood=body.understood)
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    @router.post('/tasks/{task_id}/skip')
    def skip(task_id: str, body: SkipInput):
        with connect(path) as db:
            try:
                return tasks.skip_task(db, task_id, reason=body.reason)
            except ValueError as exc:
                raise HTTPException(409, str(exc))

    @router.get('/nodes/{node_id}/summary')
    def node_summary(node_id: str):
        with connect(path) as db:
            return {'sets': tasks.node_task_summary(db, node_id)}

    return router
