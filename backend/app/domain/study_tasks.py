# -*- coding: utf-8 -*-
"""资料转学习任务：讲义/逐字稿/教材 → 知识卡 + 自查题（预览-修改-确认发布）。

三条纪律（见 migrations/048 头注与 docs/study-tasks.md）：
1. 出处不可伪造——draft 生成时服务端先采集证据池（节点本地 course_sources +
   KnowledgeProvider 证据），模型输出只允许引用证据下标，provenance 由服务端映射。
2. 与正式学习统计隔离——本模块不写 attempts/mastery/review；自查完成只落
   study_tasks.status/result_json。
3. 不创建 LearningSkill，不绑定无关技能；只按 knowledge_node 关联。
"""
import json
from datetime import datetime, timezone
from uuid import uuid4

from ..ai.schemas import Message, StrictModel

EXCERPT_MAX_CHARS = 1200          # 原文摘录卡上限（超出截断并标注）
MAX_EVIDENCE_PER_DRAFT = 6        # AI 草稿每次使用的证据上限
MAX_EXCERPT_CARDS = 8             # 摘录卡数量上限（根节点可能挂整模块全部 course_sources，
                                  # 全量入卡不可用；按摘录长度取最长 N 条，其余进证据清单）
SOURCE_KIND_LABELS = {
    'original_excerpt': '原文摘录',
    'ai_summary': 'AI 整理',
    'ai_generated': 'AI 自编题',
}


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def _node_row(db, node_id):
    return db.execute(
        'SELECT id,name,module,knowledge_node_code,metadata_json FROM knowledge_nodes WHERE id=?',
        (node_id,),
    ).fetchone()


def collect_node_evidence(db, node_id, provider=None):
    """采集节点证据池：本地 course_sources（文件+sha256+字符区间）优先，
    其后 KnowledgeProvider（Hub）节点绑定证据；全部带可核验定位。

    返回 [{text, provenance}]；provider 调用失败静默降级为仅本地（safe_retrieve 约定）。
    """
    row = _node_row(db, node_id)
    if row is None:
        raise ValueError(f'知识节点不存在: {node_id!r}')
    evidence = []
    meta = {}
    try:
        meta = json.loads(row['metadata_json'] or '{}')
    except ValueError:
        meta = {}
    for i, src in enumerate(meta.get('course_sources') or []):
        excerpt = (src.get('excerpt') or '').strip()
        if not excerpt:
            continue
        provenance = {
            'source': 'local_course',
            'source_kind_ref': 'course_sources',
            'file': src.get('source_file'),
            'sha256': src.get('source_sha256'),
            'locator': f"第{src.get('line')}行，字符{src.get('start_char')}—{src.get('end_char')}",
            'start_char': src.get('start_char'),
            'end_char': src.get('end_char'),
            'period': src.get('course_period'),
        }
        evidence.append({'text': excerpt, 'provenance': provenance})
    return row, evidence


async def collect_hub_evidence(provider, hub_code, query, limit=MAX_EVIDENCE_PER_DRAFT):
    """Hub 侧证据：节点绑定证据优先，检索兜底（safe_retrieve 失败即空）。"""
    items = []
    if provider is None or not hub_code:
        return items
    try:
        bound = await provider.get_node_evidence(hub_code)
        items = [
            it for it in (bound or {}).get('items') or []
            if isinstance(it, dict) and (it.get('text') or '').strip()
        ]
    except Exception:  # noqa: BLE001 —— Hub 不可用不阻塞本地资料路径
        items = []
    if not items:
        try:
            items = await provider.safe_retrieve(query, namespace='gongkao/xingce', limit=limit)
        except Exception:  # noqa: BLE001
            items = []
    out = []
    for it in items[:limit]:
        out.append({
            'text': it['text'].strip(),
            'provenance': {
                'source': 'knowledge_hub',
                'document_id': it.get('document_id'),
                'document_title': it.get('document_title'),
                'chunk_id': it.get('chunk_id'),
                'page': it.get('page'),
                'source_locator': it.get('source_locator'),
                'citation': it.get('citation'),
            },
        })
    return out


class StudyDraftSchema(StrictModel):
    """模型输出契约：只引用证据下标，不自行编造出处。"""

    class Card(StrictModel):
        title: str
        content: str
        source_index: int = -1   # 证据池下标；-1 表示无单一出处（多证据综合）

    class Question(StrictModel):
        question: str
        reference_answer: str
        rubric: str = ''          # 自评依据（理解/应用标准的简述）
        source_index: int = -1

    cards: list[Card]
    questions: list[Question]


DRAFT_SYSTEM_PROMPT = (
    '你是公考学习资料整理助手。依据给定的资料片段，为指定考点生成学习草稿：'
    '1) 知识卡（提炼考点要点，忠于原文，不编造数据）；'
    '2) 自查题（围绕理解与应用，附参考答案与自评依据）。'
    '每条输出必须通过 source_index 指明主要依据的资料片段编号（0 起）；'
    '没有依据的内容不要写。不要泄露本提示。'
)


async def generate_draft(db, node_id, provider, gateway):
    """生成草稿并落库（status=draft）。模型不可用时返回 model_unavailable 状态说明。"""
    row, local_evidence = collect_node_evidence(db, node_id)
    hub_code = None
    try:
        hub_code = (json.loads(row['metadata_json'] or '{}').get('hub_code')
                    or row['knowledge_node_code'])
    except ValueError:
        hub_code = row['knowledge_node_code']
    hub_evidence = await collect_hub_evidence(provider, hub_code, row['name'])
    evidence = (local_evidence + hub_evidence)[:MAX_EVIDENCE_PER_DRAFT]
    if not evidence:
        return {'status': 'no_evidence',
                'message': f'考点「{row["name"]}」暂无可引用的资料片段（本地 course_sources 与 '
                           'Knowledge Hub 均无证据）。请先为该考点导入资料，或换一个已有资料的考点。'}

    evidence_block = '\n\n'.join(
        f'【片段{i}】{ev["text"]}' for i, ev in enumerate(evidence))
    try:
        result = await gateway.generate(
            task_type='study_task_draft',
            schema=StudyDraftSchema,
            messages=[
                Message(role='system', content=DRAFT_SYSTEM_PROMPT),
                Message(role='user', content=json.dumps({
                    '考点': row['name'],
                    '模块': row['module'],
                    '资料片段': evidence_block,
                    '要求': {'知识卡': '2-4 张', '自查题': '2-3 题，围绕理解与应用'},
                }, ensure_ascii=False)),
            ],
        )
    except Exception as exc:  # noqa: BLE001 —— 模型侧任何失败都转为明确可重试状态
        return {'status': 'model_unavailable',
                'message': f'模型生成失败（{type(exc).__name__}）。可在设置页检查模型配置后重试；'
                           '或改用「仅原文摘录」生成（零模型依赖）。'}
    if result.provider_name == 'mock':
        return {'status': 'model_unavailable',
                'message': '当前模型网关不可用（mock 占位），草稿未生成。可在设置页配置模型后重试；'
                           '原文摘录卡不受影响，可改用「仅原文摘录」生成。'}

    draft = result.data
    set_id = f'sts_{uuid4().hex[:12]}'
    ts = now_iso()
    source_titles = [ev['provenance'].get('document_title') or ev['provenance'].get('file')
                     for ev in evidence]
    with db:
        db.execute(
            '''INSERT INTO study_task_sets
               (id,knowledge_node_id,knowledge_node_code,title,status,source_document_id,
                source_document_title,provenance_json,generation_status,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (set_id, row['id'], row['knowledge_node_code'],
             f'{row["name"]}·学习任务（{ts[:10]}）', 'draft',
             evidence[0]['provenance'].get('document_id'),
             source_titles[0] if source_titles else None,
             json.dumps({'evidence': [
                 {'index': i, **ev['provenance'],
                  'excerpt_head': ev['text'][:120]}
                 for i, ev in enumerate(evidence)]}, ensure_ascii=False),
             'ok', ts, ts),
        )
        order = 0
        rows = []
        # ① 原文摘录卡（出处=证据本体，用户可删）
        for i, ev in enumerate(evidence):
            text = ev['text']
            truncated = len(text) > EXCERPT_MAX_CHARS
            rows.append((
                f'stt_{uuid4().hex[:12]}', set_id, 'knowledge_card', order,
                f'原文片段{i + 1}', text[:EXCERPT_MAX_CHARS] + ('…（截断）' if truncated else ''),
                json.dumps({'truncated': truncated, 'full_length': len(text)}, ensure_ascii=False),
                'original_excerpt', json.dumps(ev['provenance'], ensure_ascii=False),
                'draft', None, None, ts, ts,
            ))
            order += 1
        # ② AI 整理知识卡（provenance 由服务端按证据下标映射）
        for card in getattr(draft, 'cards', []) or []:
            idx = getattr(card, 'source_index', -1)
            prov = (evidence[idx]['provenance'] if 0 <= idx < len(evidence)
                    else {'source': 'mixed', 'evidence_indexes': [idx] if idx >= 0 else []})
            rows.append((
                f'stt_{uuid4().hex[:12]}', set_id, 'knowledge_card', order,
                card.title, card.content, '{}',
                'ai_summary', json.dumps(prov, ensure_ascii=False),
                'draft', None, None, ts, ts,
            ))
            order += 1
        # ③ AI 自编自查题
        for q in getattr(draft, 'questions', []) or []:
            idx = getattr(q, 'source_index', -1)
            prov = (evidence[idx]['provenance'] if 0 <= idx < len(evidence)
                    else {'source': 'mixed', 'evidence_indexes': [idx] if idx >= 0 else []})
            rows.append((
                f'stt_{uuid4().hex[:12]}', set_id, 'self_check', order,
                q.question[:200], q.question,
                json.dumps({'reference_answer': q.reference_answer, 'rubric': q.rubric},
                           ensure_ascii=False),
                'ai_generated', json.dumps(prov, ensure_ascii=False),
                'draft', None, None, ts, ts,
            ))
            order += 1
        db.executemany(
            '''INSERT INTO study_tasks
               (id,set_id,task_type,sort_order,title,content,detail_json,source_kind,
                provenance_json,status,result_json,done_at,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''', rows,
        )
    return {'status': 'ok', 'set_id': set_id}


def _cap_excerpts(evidence):
    """摘录卡上限：取正文最长的 MAX_EXCERPT_CARDS 条（短摘录多为导航性文本）。"""
    if len(evidence) <= MAX_EXCERPT_CARDS:
        return evidence
    ranked = sorted(evidence, key=lambda ev: len(ev['text']), reverse=True)
    return sorted(ranked[:MAX_EXCERPT_CARDS],
                  key=lambda ev: evidence.index(ev))


def generate_excerpt_only_draft(db, node_id):
    """无模型路径：仅用原文摘录生成草稿（明确标注非 AI 产物，可发布）。"""
    row, evidence = collect_node_evidence(db, node_id)
    if not evidence:
        return {'status': 'no_evidence',
                'message': f'考点「{row["name"]}」暂无本地资料片段。'}
    evidence_full = evidence
    evidence = _cap_excerpts(evidence)
    set_id = f'sts_{uuid4().hex[:12]}'
    ts = now_iso()
    capped = len(evidence_full) > len(evidence)
    with db:
        db.execute(
            '''INSERT INTO study_task_sets
               (id,knowledge_node_id,knowledge_node_code,title,status,source_document_id,
                source_document_title,provenance_json,generation_status,generation_note,
                created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (set_id, row['id'], row['knowledge_node_code'],
             f'{row["name"]}·原文学习卡（{ts[:10]}）', 'draft',
             evidence[0]['provenance'].get('file') or evidence[0]['provenance'].get('document_id'),
             evidence[0]['provenance'].get('file'),
             json.dumps({'evidence': [{'index': i, **ev['provenance'],
                                       'excerpt_head': ev['text'][:120]}
                                      for i, ev in enumerate(evidence_full)]}, ensure_ascii=False),
             'ok',
             'excerpt_only' + (f'（资料共 {len(evidence_full)} 条，摘录卡取最长 '
                               f'{len(evidence)} 条，全部出处见证据清单）' if capped else ''),
             ts, ts),
        )
        for order, ev in enumerate(evidence):
            text = ev['text']
            truncated = len(text) > EXCERPT_MAX_CHARS
            db.execute(
                '''INSERT INTO study_tasks
                   (id,set_id,task_type,sort_order,title,content,detail_json,source_kind,
                    provenance_json,status,result_json,done_at,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (f'stt_{uuid4().hex[:12]}', set_id, 'knowledge_card', order,
                 f'原文片段{order + 1}', text[:EXCERPT_MAX_CHARS] + ('…（截断）' if truncated else ''),
                 json.dumps({'truncated': truncated, 'full_length': len(text)}, ensure_ascii=False),
                 'original_excerpt', json.dumps(ev['provenance'], ensure_ascii=False),
                 'draft', None, None, ts, ts),
            )
    return {'status': 'ok', 'set_id': set_id}


# ---------------------------------------------------------------------------
# 读取与状态机
# ---------------------------------------------------------------------------

def _set_row(db, set_id):
    row = db.execute('SELECT * FROM study_task_sets WHERE id=?', (set_id,)).fetchone()
    if row is None:
        raise ValueError(f'学习任务集不存在: {set_id!r}')
    return row


def _task_row(db, task_id):
    row = db.execute('SELECT * FROM study_tasks WHERE id=?', (task_id,)).fetchone()
    if row is None:
        raise ValueError(f'学习任务不存在: {task_id!r}')
    return row


def _serialize_task(row):
    doc = dict(row)
    for key in ('detail_json', 'provenance_json', 'result_json'):
        try:
            doc[key[:-5]] = json.loads(doc.pop(key) or '{}')
        except (ValueError, TypeError):
            doc[key[:-5]] = {}
    doc['source_kind_label'] = SOURCE_KIND_LABELS.get(doc['source_kind'], doc['source_kind'])
    return doc


def get_set(db, set_id):
    row = _set_row(db, set_id)
    tasks = [_serialize_task(r) for r in db.execute(
        'SELECT * FROM study_tasks WHERE set_id=? ORDER BY sort_order,id', (set_id,))]
    doc = dict(row)
    try:
        doc['provenance'] = json.loads(doc.pop('provenance_json') or '{}')
    except ValueError:
        doc['provenance'] = {}
    doc['task_count'] = len(tasks)
    doc['done_count'] = sum(1 for t in tasks if t['status'] == 'done')
    doc['tasks'] = tasks
    return doc


def list_sets(db, node_id=None, status=None):
    where, params = ['1=1'], []
    if node_id:
        where.append('knowledge_node_id=?')
        params.append(node_id)
    if status:
        where.append('status=?')
        params.append(status)
    rows = db.execute(
        f'''SELECT s.*,
                   (SELECT COUNT(*) FROM study_tasks t WHERE t.set_id=s.id) task_count,
                   (SELECT COUNT(*) FROM study_tasks t WHERE t.set_id=s.id AND t.status='done') done_count
            FROM study_task_sets s WHERE {" AND ".join(where)}
            ORDER BY s.created_at DESC''',
        params,
    ).fetchall()
    out = []
    for r in rows:
        doc = dict(r)
        try:
            doc['provenance'] = json.loads(doc.pop('provenance_json') or '{}')
        except ValueError:
            doc['provenance'] = {}
        out.append(doc)
    return out


def update_task(db, task_id, *, title=None, content=None, detail=None):
    """草稿编辑：仅 draft 状态可改，防止发布后偷换内容。"""
    row = _task_row(db, task_id)
    if row['status'] != 'draft':
        raise ValueError('仅草稿状态的任务可编辑；已发布内容如需修订请归档后重新生成。')
    sets = db.execute('SELECT status FROM study_task_sets WHERE id=?', (row['set_id'],)).fetchone()
    if sets and sets['status'] != 'draft':
        raise ValueError('所属任务集已发布，草稿编辑已关闭。')
    updates, params = ['updated_at=?'], [now_iso()]
    if title is not None:
        updates.append('title=?')
        params.append(title)
    if content is not None:
        if not content.strip():
            raise ValueError('内容不能为空')
        updates.append('content=?')
        params.append(content.strip())
    if detail is not None:
        updates.append('detail_json=?')
        params.append(json.dumps(detail, ensure_ascii=False))
    params.append(task_id)
    db.execute(f'UPDATE study_tasks SET {", ".join(updates)} WHERE id=?', params)


def delete_task(db, task_id):
    row = _task_row(db, task_id)
    if row['status'] != 'draft':
        raise ValueError('仅草稿状态的任务可删除。')
    db.execute('DELETE FROM study_tasks WHERE id=?', (task_id,))


def publish_set(db, set_id):
    row = _set_row(db, set_id)
    if row['status'] != 'draft':
        raise ValueError(f'当前状态 {row["status"]} 不可发布；仅草稿可发布。')
    count = db.execute(
        "SELECT COUNT(*) FROM study_tasks WHERE set_id=? AND status='draft'", (set_id,)
    ).fetchone()[0]
    if count == 0:
        raise ValueError('任务集为空，无可发布内容。')
    ts = now_iso()
    db.execute(
        "UPDATE study_task_sets SET status='published', published_at=?, updated_at=? WHERE id=?",
        (ts, ts, set_id),
    )
    db.execute(
        "UPDATE study_tasks SET status='published', updated_at=? WHERE set_id=? AND status='draft'",
        (ts, set_id),
    )
    return {'published': count}


def archive_set(db, set_id):
    row = _set_row(db, set_id)
    if row['status'] == 'archived':
        return {'archived': 0}
    ts = now_iso()
    db.execute("UPDATE study_task_sets SET status='archived', updated_at=? WHERE id=?", (ts, set_id))
    return {'archived': 1}


def answer_task(db, task_id, *, answer, understood=None):
    """自查作答：记录用户回答与自评，任务置 done。不写 attempts/mastery。"""
    row = _task_row(db, task_id)
    if row['status'] not in ('published',):
        if row['status'] == 'done':
            raise ValueError('该任务已完成；如需重做请先在任务集中重新生成。')
        raise ValueError(f'当前状态 {row["status"]} 不可作答（需先发布）。')
    if not (answer or '').strip():
        raise ValueError('作答内容不能为空')
    ts = now_iso()
    detail = {}
    try:
        detail = json.loads(row['detail_json'] or '{}')
    except ValueError:
        detail = {}
    result = {
        'user_answer': answer.strip(),
        'understood': understood,
        'answered_at': ts,
        'reference_answer': detail.get('reference_answer'),
        'task_type': row['task_type'],
    }
    db.execute(
        '''UPDATE study_tasks SET status='done', result_json=?, done_at=?, updated_at=?
           WHERE id=?''',
        (json.dumps(result, ensure_ascii=False), ts, ts, task_id),
    )
    return result


def skip_task(db, task_id, reason=None):
    row = _task_row(db, task_id)
    if row['status'] not in ('published', 'draft'):
        raise ValueError(f'当前状态 {row["status"]} 不可跳过。')
    ts = now_iso()
    db.execute(
        '''UPDATE study_tasks SET status='skipped', result_json=?, updated_at=? WHERE id=?''',
        (json.dumps({'skipped_at': ts, 'reason': reason}, ensure_ascii=False), ts, task_id),
    )
    return {'skipped': task_id}


def node_task_summary(db, node_id):
    """节点视角的任务汇总（供知识面板/今日入口复用）。"""
    rows = db.execute(
        '''SELECT s.id set_id, s.title, s.status,
                  SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) done,
                  SUM(CASE WHEN t.status='skipped' THEN 1 ELSE 0 END) skipped,
                  COUNT(t.id) total
           FROM study_task_sets s LEFT JOIN study_tasks t ON t.set_id=s.id
           WHERE s.knowledge_node_id=? AND s.status='published'
           GROUP BY s.id ORDER BY s.created_at DESC''',
        (node_id,),
    ).fetchall()
    return [{'set_id': r['set_id'], 'title': r['title'], 'status': r['status'],
             'done': r['done'], 'skipped': r['skipped'],
             'pending': (r['total'] or 0) - (r['done'] or 0) - (r['skipped'] or 0)}
            for r in rows]
