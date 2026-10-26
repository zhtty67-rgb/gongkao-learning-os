"""名师讲题工具：本地确定性检索为默认，LLM 讲题须显式 opt-in。

- 默认路径：``ModuleTeacherService.get_teacher_context_for_review`` —— 毫秒级
  纯本地检索（教师规则/纠偏案例），自带W 老师/花生言语越界门禁，零外部成本。
- ``use_llm=true``：HTTP 代理到运行中的后端 ``POST /api/module-teachers/{tid}/explain``
  （走应用模型网关，产生 LLM 成本）。后端离线时不静默降级，明确报错并附 hint。
"""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from ..db import default_path
from ..domain.module_teacher_service import ModuleTeacherService

DEFAULT_API_BASE = 'http://127.0.0.1:8000'

_service = None


def _get_service():
    global _service
    if _service is None:
        _service = ModuleTeacherService()
    return _service


def api_base():
    return os.environ.get('GONGKAO_API_BASE', DEFAULT_API_BASE).rstrip('/')


def _load_question(db_path, question_id):
    """只读加载题面（与 queries.ro_connect 同一 URI 口径）。"""
    import sqlite3
    from urllib.parse import quote
    target = Path(db_path or default_path())
    uri = 'file:' + quote(target.resolve().as_posix(), safe='/:') + '?mode=ro'
    con = sqlite3.connect(uri, uri=True, timeout=15)
    con.row_factory = sqlite3.Row
    try:
        row = con.execute(
            '''SELECT id,stem,options_json,answer,explanation,module FROM questions WHERE id=?''',
            (question_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f'题目不存在: {question_id!r}')
        return dict(row)
    finally:
        con.close()


def ask_teacher(question_id=None, stem=None, module=None, use_llm=False, db_path=None):
    """讲题入口。返回统一形状：teacher 定位 + 方法参考（+ 可选 LLM 讲题）。"""
    service = _get_service()
    options = {}
    answer = ''
    explanation = ''
    figure_description = ''
    if question_id:
        q = _load_question(db_path, question_id)
        stem = stem or q['stem']
        module = module or q['module']
        try:
            options = json.loads(q['options_json'] or '{}')
        except ValueError:
            options = {}
        answer = q['answer'] or ''
        explanation = q['explanation'] or ''
    if not stem:
        raise ValueError('必须提供 question_id 或 stem（题面文本）')
    if not module:
        raise ValueError('必须能确定模块（module 或 question_id 推断）')

    context = service.get_teacher_context_for_review(module, stem, explanation=explanation)
    if context is None:
        raise ValueError(f'模块 {module!r} 没有已接入的独立教师模型')

    result = {
        'teacher_id': context.get('teacher_id'),
        'teacher_name': context.get('teacher_name'),
        'module': context.get('module'),
        'answer_status': 'method_reference_only',
        'policies': context.get('policies', []),
        'critique': context.get('critique'),
        'signature_advice': context.get('signature_advice'),
    }
    if context.get('out_of_scope_rejected'):
        result['answer_status'] = 'out_of_scope_rejected'
        result['rejection_reason'] = context.get('rejection_reason')
        return result

    if use_llm:
        payload = {
            'stem': stem,
            'options': options,
            'answer': answer,
            'explanation': explanation,
            'figure_description': figure_description,
        }
        try:
            result['llm_explanation'] = _proxy_explain(context['teacher_id'], payload)
            result['answer_status'] = 'llm_explained'
        except Exception as exc:  # noqa: BLE001 —— 代理失败回本地参考并明确说明
            result['answer_status'] = 'llm_unavailable'
            result['llm_error'] = str(exc)
            result['hint'] = (
                f'后端未在 {api_base()} 运行或讲题接口异常；本地方法参考仍可用。'
                '需要完整 LLM 讲题请先启动后端（scripts/start-backend.ps1）。'
            )
    return result


def _proxy_explain(teacher_id, payload, timeout=120):
    url = f"{api_base()}/api/module-teachers/{teacher_id}/explain"
    req = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json'}, method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))
