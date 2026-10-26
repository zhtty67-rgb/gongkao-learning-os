"""只读查询层：网关全部数据访问走 ``file:...?mode=ro`` URI。

口径复用既有确定性投影（``domain/mastery.py``、``domain/review.py``、
``domain/analytics.py``），不另立第二套判据。
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from ..db import default_path
from ..domain.mastery import overall_mastery  # 纯标准库投影

# analytics 家族（dashboard/latest_error_cte）惰性导入：其依赖链拉 fastapi
# （venv-only），脑镜像同步器在系统 python 下运行时不需要。

STEM_EXCERPT_LEN = 160


@contextmanager
def ro_connect(path=None):
    """只读打开 gongkao.db；URI 模式保证物理只读（写语句直接报错）。"""
    target = Path(path or default_path())
    uri = 'file:' + quote(target.resolve().as_posix(), safe='/:') + '?mode=ro'
    db = sqlite3.connect(uri, uri=True, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        yield db
    finally:
        db.close()


def _cols(db, table):
    return [c[1] for c in db.execute(f'PRAGMA table_info({table})').fetchall()]


def _stem_excerpt(text):
    text = (text or '').strip()
    return text if len(text) <= STEM_EXCERPT_LEN else text[:STEM_EXCERPT_LEN] + '…'


def _verdict_expr(db):
    cols = _cols(db, 'attempts')
    if 'corrected_correct' in cols:
        return "COALESCE(a.corrected_correct, a.correct)"
    return 'a.correct'


def overall(db):
    """学习概览：总览指标 + 模块掌握度卷积 + 到期复习数。"""
    from ..domain.analytics import dashboard
    now_iso = datetime.now(timezone.utc).isoformat()
    summary = dashboard(db, overall_mastery(db))
    modules = [dict(row) for row in db.execute(
        '''SELECT kn.module,
                  COUNT(*) node_count,
                  SUM(CASE WHEN ms.attempt_count>0 THEN 1 ELSE 0 END) practiced_nodes,
                  AVG(ms.mastery_score) avg_mastery
           FROM knowledge_nodes kn JOIN mastery_state ms ON ms.knowledge_node_id=kn.id
           GROUP BY kn.module ORDER BY avg_mastery'''
    )]
    due = db.execute('SELECT COUNT(*) FROM review_cards WHERE due<=?', (now_iso,)).fetchone()[0]
    bank = db.execute('SELECT COUNT(*) FROM questions').fetchone()[0]
    return {
        'metrics': summary['metrics'],
        'daily_goal': summary['daily_goal'],
        'weakest': summary['weakest'],
        'recommendation': summary['recommendation'],
        'module_rollup': [
            {
                'module': m['module'],
                'avg_mastery': round(m['avg_mastery'], 4) if m['avg_mastery'] is not None else None,
                'practiced_nodes': m['practiced_nodes'],
                'node_count': m['node_count'],
            } for m in modules
        ],
        'due_review_count': due,
        'question_bank_size': bank,
    }


def _node_where(db, selector):
    """节点定位：knowledge_node_code 优先，列存在时再匹配 code/id（列感知，新旧库兼容）。"""
    cols = _cols(db, 'knowledge_nodes')
    clauses, params = ['kn.knowledge_node_code=?'], [selector]
    if 'code' in cols:
        clauses.append('kn.code=?')
        params.append(selector)
    clauses.append('kn.id=?')
    params.append(selector)
    return '(' + ' OR '.join(clauses) + ')', params


def mastery_detail(db, module=None, node=None, limit=50):
    """掌握度明细：可按模块过滤或定位单节点。"""
    where, params = ['1=1'], []
    if module:
        where.append('kn.module=?')
        params.append(module)
    if node:
        clause, node_params = _node_where(db, node)
        where.append(clause)
        params.extend(node_params)
    rows = db.execute(
        f'''SELECT kn.id node_id,kn.name,kn.module,kn.knowledge_node_code,
                   ms.mastery_score,ms.attempt_count,ms.evidence_positive,ms.evidence_negative,
                   ms.recent_accuracy,ms.avg_time_ratio,ms.hint_dependency,ms.last_practiced_at
           FROM knowledge_nodes kn JOIN mastery_state ms ON ms.knowledge_node_id=kn.id
           WHERE {' AND '.join(where)}
           ORDER BY CASE WHEN ms.attempt_count>0 THEN 0 ELSE 1 END, ms.mastery_score, kn.name
           LIMIT ?''',
        [*params, limit],
    ).fetchall()
    return {'count': len(rows), 'nodes': [dict(r) for r in rows]}


def knowledge_tree(db, module=None, depth=2):
    """知识树骨架：按 parent_id 组装到指定深度。"""
    where, params = ['1=1'], []
    if module:
        where.append('kn.module=?')
        params.append(module)
    rows = db.execute(
        f'''SELECT kn.id,kn.parent_id,kn.name,kn.module,kn.node_type,kn.subject,
                   kn.knowledge_node_code,ms.mastery_score,ms.attempt_count
           FROM knowledge_nodes kn
           LEFT JOIN mastery_state ms ON ms.knowledge_node_id=kn.id
           WHERE {' AND '.join(where)}
           ORDER BY kn.parent_id,kn.id''',
        params,
    ).fetchall()
    by_parent = {}
    for r in rows:
        by_parent.setdefault(r['parent_id'], []).append(dict(r))

    def build(node, level):
        entry = {
            'id': node['id'], 'name': node['name'], 'module': node['module'],
            'node_type': node['node_type'], 'knowledge_node_code': node['knowledge_node_code'],
            'mastery_score': round(node['mastery_score'], 4) if node['mastery_score'] is not None else None,
            'attempt_count': node['attempt_count'],
        }
        if level < depth:
            entry['children'] = [
                build(child, level + 1) for child in by_parent.get(node['id'], [])
            ]
        return entry

    roots = [build(n, 1) for n in by_parent.get(None, [])]
    return {'depth': depth, 'module': module, 'root_count': len(roots), 'roots': roots}


def node_detail(db, node):
    """单节点深览：掌握度、绑题数、错因分布、最近作答。"""
    clause, params = _node_where(db, node)
    row = db.execute(
        f'''SELECT kn.* FROM knowledge_nodes kn WHERE {clause} LIMIT 1''', params,
    ).fetchone()
    if row is None:
        raise KeyError(f'知识节点不存在: {node!r}')
    detail = dict(row)
    if 'metadata_json' in detail and isinstance(detail.get('metadata_json'), str):
        try:
            detail['metadata'] = json.loads(detail['metadata_json']) if detail['metadata_json'] else {}
        except ValueError:
            detail['metadata'] = {}
        detail.pop('metadata_json', None)
    node_id = row['id']
    joined = db.execute(
        '''SELECT mastery_score,attempt_count,evidence_positive,evidence_negative,
                  recent_accuracy,avg_time_ratio,hint_dependency,last_practiced_at
           FROM mastery_state WHERE knowledge_node_id=?''', (node_id,),
    ).fetchone()
    detail['mastery'] = dict(joined) if joined else None
    detail['bound_question_count'] = db.execute(
        'SELECT COUNT(*) FROM question_knowledge_map WHERE knowledge_node_id=?', (node_id,),
    ).fetchone()[0]
    errors = db.execute(
        '''SELECT e.error_type, COUNT(*) n
           FROM error_events e
           JOIN question_knowledge_map qkm ON qkm.question_id=e.question_id
           WHERE qkm.knowledge_node_id=? AND e.error_type IS NOT NULL
           GROUP BY e.error_type ORDER BY n DESC''', (node_id,),
    ).fetchall()
    detail['error_breakdown'] = [{'error_type': r['error_type'], 'count': r['n']} for r in errors]
    recent = db.execute(
        f'''SELECT a.id,a.question_id,a.submitted_at,a.elapsed_ms,a.confidence,a.hint_level,
                   {_verdict_expr(db)} AS correct, q.stem
           FROM attempts a JOIN questions q ON q.id=a.question_id
           JOIN question_knowledge_map qkm ON qkm.question_id=a.question_id
           WHERE qkm.knowledge_node_id=? AND a.submitted_at IS NOT NULL
           ORDER BY a.submitted_at DESC,a.id DESC LIMIT 5''', (node_id,),
    ).fetchall()
    detail['recent_attempts'] = [
        {**{k: r[k] for k in r.keys() if k != 'stem'}, 'stem_excerpt': _stem_excerpt(r['stem'])}
        for r in recent
    ]
    return detail


def recent_attempts(db, limit=20, session_id=None, module=None, only_wrong=False):
    """最近作答流：含信心与提示层级。"""
    where, params = ['a.submitted_at IS NOT NULL'], []
    if session_id:
        where.append('a.session_id=?')
        params.append(session_id)
    if module:
        where.append('q.module=?')
        params.append(module)
    if only_wrong:
        where.append(f'{_verdict_expr(db)}=0')
    rows = db.execute(
        f'''SELECT a.id,a.question_id,a.session_id,a.submitted_at,a.elapsed_ms,a.confidence,
                   a.hint_level,a.mode,{_verdict_expr(db)} AS correct,q.module,q.stem
           FROM attempts a JOIN questions q ON q.id=a.question_id
           WHERE {' AND '.join(where)}
           ORDER BY a.submitted_at DESC,a.id DESC LIMIT ?''',
        [*params, limit],
    ).fetchall()
    return {
        'count': len(rows),
        'attempts': [
            {**{k: r[k] for k in r.keys() if k != 'stem'}, 'stem_excerpt': _stem_excerpt(r['stem'])}
            for r in rows
        ],
    }


def wrong_book(db, module=None, limit=20):
    """错题本：全局错因分布 + 最近错题事件（口径同 /api/analytics/errors）。"""
    from ..domain.analytics import latest_error_cte
    where, params = ['re.rn=1'], []
    if module:
        where.append('q.module=?')
        params.append(module)
    where_sql = ' AND '.join(where)
    breakdown_rows = db.execute(
        latest_error_cte() +
        f''' SELECT re.error_type, COUNT(*) n
             FROM ranked_errors re
             JOIN attempts a ON a.id=re.attempt_id JOIN questions q ON q.id=a.question_id
             WHERE {where_sql} AND re.error_type IS NOT NULL
             GROUP BY re.error_type ORDER BY n DESC''',
        params,
    ).fetchall()
    events = db.execute(
        latest_error_cte() +
        f''' SELECT re.id,re.attempt_id,re.error_type,re.error_subtype,re.explanation,
                    re.created_at,q.id question_id,q.module,q.stem,a.confidence
             FROM ranked_errors re
             JOIN attempts a ON a.id=re.attempt_id JOIN questions q ON q.id=a.question_id
             WHERE {where_sql}
             ORDER BY re.created_at DESC LIMIT ?''',
        [*params, limit],
    ).fetchall()
    total_wrong = db.execute(
        f'''SELECT COUNT(*) FROM attempts a JOIN questions q ON q.id=a.question_id
            WHERE a.submitted_at IS NOT NULL AND {_verdict_expr(db)}=0'''
        + (' AND q.module=?' if module else ''),
        params,
    ).fetchone()[0]
    return {
        'total_wrong': total_wrong,
        'breakdown': [{'error_type': r['error_type'], 'count': r['n']} for r in breakdown_rows],
        'count': len(events),
        'events': [
            {**{k: r[k] for k in r.keys() if k != 'stem'}, 'stem_excerpt': _stem_excerpt(r['stem'])}
            for r in events
        ],
    }


def due_list(db, limit=20):
    """FSRS 到期复习卡片（口径复用 domain/review.due_reviews）。

    due_reviews 惰性导入：它拉 fsrs 包（venv-only），脑镜像同步器在系统
    python 下运行时不需要这个依赖。
    """
    from ..domain.review import due_reviews
    as_of = datetime.now(timezone.utc)
    rows = due_reviews(db, as_of, limit)
    return {
        'as_of': as_of.isoformat(),
        'count': len(rows),
        'items': [
            {
                'question_id': r['question_id'],
                'due': r['due'],
                'state': r['state'],
                'stability': r['stability'],
                'difficulty': r['difficulty'],
                'review_count': r['review_count'],
                'lapse_count': r['lapse_count'],
                'module': r['module'],
                'subject': r['subject'],
                'year': r['year'],
                'source': r['source'],
                'difficulty_question': r['question_difficulty'],
                'stem_excerpt': _stem_excerpt(r['stem']),
            } for r in rows
        ],
    }


def notes(db, node=None, question_id=None, module=None, limit=20):
    """个人笔记检索（user_notes，只读）。"""
    cols = _cols(db, 'user_notes')
    where, params = ['1=1'], []
    if node:
        where.append('(knowledge_node_code=? OR knowledge_node_id=?)')
        params.extend([node, node])
    if question_id:
        where.append('question_id=?')
        params.append(question_id)
    if module:
        where.append('module=?')
        params.append(module)
    order = 'updated_at DESC' if 'updated_at' in cols else 'rowid DESC'
    rows = db.execute(
        f'''SELECT * FROM user_notes WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ?''',
        [*params, limit],
    ).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        content = item.get('content') or ''
        item['content_excerpt'] = content if len(content) <= 400 else content[:400] + '…'
        items.append(item)
    return {'count': len(items), 'notes': items}
