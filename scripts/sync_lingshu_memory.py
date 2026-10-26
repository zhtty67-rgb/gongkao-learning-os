"""公考学习状态 ↔ 灵枢脑（dsh-memory）认知图同步。

方向纪律：
- 正向（默认，公考→脑）：只写脑端 md，绝不写公考库。
- 反向（--backsync，脑→公考）：**只写 user_notes 一张表**（dialogue_clipping，
  经 domain/notes.create_or_update_note），绝不碰 attempts/mastery/review——
  学习状态本体永远以公考库为唯一真源。

写入一律走 MCP 工具（cg op=write），内容按 CCG 六要素模板构造（实证：缺任
一行即 REJECT，六行齐 ACCEPT）。

层映射（recorder 令牌权限面）：
- structural  知识树骨架（模块根 + 二级节点）
- knowledge   考点掌握态（仅 attempt_count>0 的节点；增量：上次同步后有新作答）
- contextual  作答/错因摘要（水位 [last, now] 区间一条）

幂等语义：条目带快照日期与稳定 tag（gongkao:node:<code>）；重复同步同一节点
会产生新条目（生效条件声明「以最新同步为准」，由脑端遗忘/整并机制收敛）。

安全推进：--memory-root 指向 scratch 先行；--dry-run 只构造不连接；
真实脑根（~/.lingshu/memory）写入前需人工确认。

用法：
  python scripts/sync_lingshu_memory.py --dry-run
  python scripts/sync_lingshu_memory.py --memory-root work/lingshu-scratch/probe2
  python scripts/sync_lingshu_memory.py                  # 真实脑根（会写入）
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.db import default_path                      # noqa: E402
from backend.app.gongkao_mcp.queries import ro_connect       # noqa: E402
from backend.app.lingshu_bridge.client import memory_root    # noqa: E402

STATE_FILE = ROOT / 'data' / 'lingshu_sync_state.json'
SYNC_TAG_PREFIX = 'gongkao:'


def _fmt_ts(dt):
    return dt.astimezone(timezone.utc).strftime('%Y-%m-%d')


def _verdict_expr():
    return "COALESCE(a.corrected_correct, a.correct)"


def collect_structural(db):
    """知识树骨架：模块根与二级节点。"""
    rows = db.execute(
        '''SELECT kn.id,kn.parent_id,kn.name,kn.module,kn.node_type,
                  kn.knowledge_node_code,COUNT(c.id) child_count
           FROM knowledge_nodes kn
           LEFT JOIN knowledge_nodes c ON c.parent_id=kn.id
           WHERE kn.parent_id IS NULL
              OR kn.parent_id IN (SELECT id FROM knowledge_nodes WHERE parent_id IS NULL)
           GROUP BY kn.id ORDER BY kn.parent_id NULLS FIRST,kn.id'''.replace('NULLS FIRST', 'IS NULL DESC'),
    ).fetchall()
    entries = []
    for r in rows:
        is_root = r['parent_id'] is None
        code = r['knowledge_node_code'] or r['id']
        title = f"公考知识树·{'模块' if is_root else '分支'}·{r['name']}（{code}）"
        entries.append({
            'layer': 'structural',
            'title': title,
            'tag': f'{SYNC_TAG_PREFIX}node:{code}',
            'importance': 0.7 if is_root else 0.5,
            'body': (
                f"{'所属行测/申论大模块' if is_root else '模块下的二级分支'}：{r['name']}"
                f"（module={r['module']}，node_type={r['node_type']}），"
                f"下辖 {r['child_count']} 个直接子节点。"
                f"全部考点与题目绑定见公考系统知识树（GET /api/learning-framework）。"
            ),
        })
    return entries


def collect_knowledge(db, since_iso=None):
    """考点掌握态：有作答记录的节点；增量时仅取水位后有新作答的节点。"""
    params = []
    extra = ''
    if since_iso:
        extra = '''AND ms.knowledge_node_id IN (
            SELECT qkm.knowledge_node_id FROM attempts a
            JOIN question_knowledge_map qkm ON qkm.question_id=a.question_id
            WHERE a.submitted_at > ? {stats_filter})'''
        extra = extra.format(stats_filter=_stats_filter(db))
        params.append(since_iso)
    rows = db.execute(
        f'''SELECT kn.id,kn.name,kn.module,kn.knowledge_node_code,
                   ms.mastery_score,ms.evidence_positive,ms.evidence_negative,
                   ms.attempt_count,ms.recent_accuracy,ms.avg_time_ratio,
                   ms.hint_dependency,ms.last_practiced_at
           FROM knowledge_nodes kn JOIN mastery_state ms ON ms.knowledge_node_id=kn.id
           WHERE ms.attempt_count > 0 {extra}
           ORDER BY ms.mastery_score''',
        params,
    ).fetchall()
    entries = []
    for r in rows:
        code = r['knowledge_node_code'] or r['id']
        snapshot = _fmt_ts(datetime.now(timezone.utc))
        entries.append({
            'layer': 'knowledge',
            'title': f'公考掌握度·{r["name"]}（{code}）',
            'tag': f'{SYNC_TAG_PREFIX}node:{code}',
            'importance': 0.6 if (r['mastery_score'] or 1) < 0.5 else 0.4,
            'body': (
                f"{r['name']}（module={r['module']}）掌握度 "
                f"{round(r['mastery_score'], 3)}（Beta 后验：正证据 {r['evidence_positive']} / "
                f"负证据 {r['evidence_negative']}，{r['attempt_count']} 次作答），"
                f"近期正确率 {r['recent_accuracy']}，平均用时比 {r['avg_time_ratio']}，"
                f"提示依赖 {r['hint_dependency']}，最近练习 {r['last_practiced_at']}。"
            ),
            'snapshot': snapshot,
        })
    return entries


def _stats_filter(db, alias='a'):
    """与 dashboard/mastery 同口径：valid_for_stats 列存在时只统计正式作答。"""
    cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
    return f'AND {alias}.valid_for_stats=1' if 'valid_for_stats' in cols else ''


def collect_contextual(db, since_iso):
    """水位区间作答/错因摘要（一条）。"""
    end = datetime.now(timezone.utc)
    stats = _stats_filter(db)
    rows = db.execute(
        f'''SELECT kn.module,
                   COUNT(*) n, SUM({_verdict_expr()}) correct,
                   AVG(a.elapsed_ms) avg_ms
           FROM attempts a
           JOIN questions q ON q.id=a.question_id
           LEFT JOIN question_knowledge_map qkm ON qkm.question_id=a.question_id
           LEFT JOIN knowledge_nodes kn ON kn.id=qkm.knowledge_node_id
           WHERE a.submitted_at > ? AND a.submitted_at <= ? {stats}
           GROUP BY kn.module ORDER BY n DESC''',
        (since_iso or '1970-01-01', end.isoformat()),
    ).fetchall()
    errors = db.execute(
        f'''SELECT e.error_type, COUNT(DISTINCT e.attempt_id) n
           FROM error_events e JOIN attempts a ON a.id=e.attempt_id
           WHERE a.submitted_at > ? AND a.submitted_at <= ? AND e.error_type IS NOT NULL {stats}
           GROUP BY e.error_type ORDER BY n DESC''',
        (since_iso or '1970-01-01', end.isoformat()),
    ).fetchall()
    total = sum(r['n'] for r in rows)
    correct = sum(r['correct'] or 0 for r in rows)
    if total == 0:
        return []
    module_txt = '；'.join(
        f"{r['module'] or '未映射'} {r['n']}题对{r['correct'] or 0}" for r in rows[:8])
    error_txt = '、'.join(f"{r['error_type']}×{r['n']}" for r in errors[:6]) or '无新增错因记录'
    return [{
        'layer': 'contextual',
        'title': f'公考作答摘要 {since_iso or "全史"} → {_fmt_ts(end)}',
        'tag': f'{SYNC_TAG_PREFIX}digest:{_fmt_ts(end)}',
        'importance': 0.35,
        'body': (
            f'水位区间内正式作答 {total} 题，正确 {correct}（{round(correct / total, 3) if total else "-"}）。'
            f'分模块：{module_txt}。新增错因：{error_txt}。'
            f'明细见公考系统 gk_recent_attempts / gk_wrong_book（MCP 网关）。'
        ),
    }]


def six_element_entry(entry):
    """CCG 六要素模板（实证缺失任一行即 REJECT）。"""
    snapshot = entry.get('snapshot', _fmt_ts(datetime.now(timezone.utc)))
    return (
        f"# 功能名：{entry['title']}\n"
        f"# 生效条件：数据来自公考学习系统只读投影，快照日期 {snapshot}；仅描述本人学习状态\n"
        f"# 子功能：无（状态条目）\n"
        f"# 执行：读取公考库 gongkao.db 同名表/视图即得同源数据；或经公考 MCP 网关对应工具查询\n"
        f"# 验证方式：与公考系统对应 API 读数一致（mastery_state 为 attempts 的确定性重放）\n"
        f"# 不适用条件：公考库重建投影或更新一次同步后，本条即过期，以最新同步为准\n"
        f"\n{entry['body']}"
    )


def load_state():
    if STATE_FILE.is_file():
        try:
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
        except ValueError:
            pass
    return {}


# =========================================================================
# 反向同步（脑 → 公考 user_notes）
# =========================================================================

# 默认只导 agent 精炼记忆层；contextual 默认排除——DSH 的 dsh-memory-hook 会把
# 每条用户消息原样落入 contextual，整层导入等于把聊天记录灌进笔记。
BACKSYNC_DEFAULT_LAYERS = ('knowledge', 'self')
ECHO_TAG = 'gongkao:source:gongkao'       # 正向镜像的稳定标记
ECHO_MARKER = '数据来自公考学习系统'        # 六要素「生效条件」行内的镜像特征（tags 丢失时的兜底）

BACKSYNC_IMPORT_ORIGIN = 'lingshu_brain'


def read_brain_index(root):
    """白箱直读 _index.json（脑端为可读白箱设计；只读不锁）。"""
    path = Path(root) / '_index.json'
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8')).get('nodes') or {}
    except ValueError:
        return {}


def parse_node_file(path):
    """frontmatter（行级 key: <JSON值>）与正文分离；解析失败按空元数据处理。"""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except OSError:
        return {}, ''
    if text.startswith('---'):
        rest = text[4:]
        if '\n---\n' in rest:
            fm_text, content = rest.split('\n---\n', 1)
            fm = {}
            for line in fm_text.splitlines():
                key, sep, raw = line.partition(':')
                if not sep:
                    continue
                raw = raw.strip()
                try:
                    fm[key.strip()] = json.loads(raw)
                except ValueError:
                    fm[key.strip()] = raw
            return fm, content.strip()
    return {}, text.strip()


def collect_backsync(root, state, layers=BACKSYNC_DEFAULT_LAYERS, max_import=100):
    """枚举可回流的脑节点：层白名单 + 回声过滤 + 水位增量 + 已导映射。"""
    back = state.get('backsync') or {}
    imported = back.get('imported') or {}
    watermark = float(back.get('last_created_at') or 0)
    candidates = []
    for nid, meta in read_brain_index(root).items():
        if len(candidates) >= max_import:
            break
        if not isinstance(meta, dict):
            continue
        layer = meta.get('layer') or (meta.get('path') or '').split('/')[0]
        if layer not in layers:
            continue
        tags = meta.get('tags') or []
        if ECHO_TAG in tags or nid in imported:
            continue
        fm, content = parse_node_file(Path(root) / (meta.get('path') or ''))
        if not content or ECHO_MARKER in content:
            continue
        created_at = float(fm.get('created_at') or 0)
        if created_at <= watermark:
            continue
        kn_code = next((t[len('gongkao:node:'):] for t in tags
                        if isinstance(t, str) and t.startswith('gongkao:node:')), None)
        first_line = content.splitlines()[0]
        if first_line.startswith('# 功能名：'):
            title = first_line[len('# 功能名：'):].strip()
        elif first_line.startswith('# '):
            title = first_line[2:].strip()
        else:
            title = content[:40]
        candidates.append({
            'node_id': nid, 'layer': layer, 'tags': tags, 'created_at': created_at,
            'content': content, 'title': title, 'knowledge_node_code': kn_code,
        })
    candidates.sort(key=lambda e: e['created_at'])
    return candidates


def run_backsync(db_path, root, state, layers, max_import, dry_run=False):
    """执行回流：候选 → user_notes(dialogue_clipping)，幂等（映射 + source_message_id 双保险）。"""
    from backend.app.db import connect
    from backend.app.domain.notes import create_or_update_note

    candidates = collect_backsync(root, state, layers=layers, max_import=max_import)
    back = state.setdefault('backsync', {})
    imported = back.setdefault('imported', {})

    print(f'反向同步候选：{len(candidates)} 条（层 {list(layers)}，'
          f'水位 {back.get("last_created_at") or "0"}，已导 {len(imported)}）')
    for entry in candidates[:3]:
        print(f'  样例[{entry["node_id"]}] {entry["title"][:50]}')
    if dry_run or not candidates:
        if not dry_run:
            print('无可回流条目；状态文件未变更。')
        return 0

    created = skipped = 0
    with connect(db_path) as db:
        module_cache = {}
        for entry in candidates:
            # 双保险①：状态映射已在 collect 过滤；②：库里按 source_message_id 复原映射
            existing = db.execute(
                'SELECT id FROM user_notes WHERE source_message_id=? AND user_id=?',
                (entry['node_id'], 'default_user'),
            ).fetchone()
            if existing:
                imported[entry['node_id']] = existing['id']
                skipped += 1
                continue
            module = None
            if entry['knowledge_node_code'] and entry['knowledge_node_code'] not in module_cache:
                row = db.execute(
                    'SELECT module FROM knowledge_nodes WHERE knowledge_node_code=?',
                    (entry['knowledge_node_code'],),
                ).fetchone()
                module_cache[entry['knowledge_node_code']] = row['module'] if row else None
            if entry['knowledge_node_code']:
                module = module_cache.get(entry['knowledge_node_code'])
            note = create_or_update_note(
                db,
                note_type='dialogue_clipping',
                content=entry['content'],
                title=entry['title'][:200] or None,
                knowledge_node_code=entry['knowledge_node_code'],
                module=module,
                source_type='manual',  # CHECK 约束无 lingshu 值；溯源在 metadata 与 source_message_id
                source_message_id=entry['node_id'],
                metadata={
                    'origin': BACKSYNC_IMPORT_ORIGIN,
                    'brain_node_id': entry['node_id'],
                    'brain_layer': entry['layer'],
                    'brain_tags': entry['tags'],
                    'brain_created_at': entry['created_at'],
                },
            )
            imported[entry['node_id']] = note['id']
            created += 1
    back['last_created_at'] = max(float(back.get('last_created_at') or 0),
                                  max(e['created_at'] for e in candidates))
    back['last_run'] = datetime.now(timezone.utc).isoformat()
    save_state(state)
    print(f'回流完成：新建 {created} 条笔记，复原映射 {skipped} 条；'
          f'水位推进至 {back["last_created_at"]}')
    return 0


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--db', default=None, help='gongkao.db 路径（默认 data/gongkao.db，只读）')
    ap.add_argument('--memory-root', default=os.environ.get('LINGSHU_MEMORY_ROOT'),
                    help='脑端 MDCG_ROOT（默认 ~/.lingshu/memory；测试指向 scratch）')
    ap.add_argument('--layers', default='structural,knowledge,contextual',
                    help='正向要同步的层（逗号分隔）')
    ap.add_argument('--backsync', action='store_true',
                    help='反向同步：脑端 agent 原生记忆 → 公考 user_notes（只写这一张表）')
    ap.add_argument('--backsync-layers', default=','.join(BACKSYNC_DEFAULT_LAYERS),
                    help='反向允许回流的层（默认 knowledge,self；contextual 为 dsh-hook 原始消息流默认排除）')
    ap.add_argument('--max-import', type=int, default=100,
                    help='反向单次最大导入条数')
    ap.add_argument('--dry-run', action='store_true', help='只构造与打印，不连接脑端')
    ap.add_argument('--full', action='store_true', help='忽略水位，全量同步')
    ap.add_argument('--max-per-layer', type=int, default=200, help='每层写入上限')
    ap.add_argument('--sample', type=int, default=1, help='打印样条数')
    args = ap.parse_args(argv)

    layers = [x.strip() for x in args.layers.split(',') if x.strip()]
    unknown = set(layers) - {'structural', 'knowledge', 'contextual'}
    if unknown:
        ap.error(f'未知层: {unknown}（可选 structural/knowledge/contextual）')

    state = load_state()
    if args.backsync:
        layers = tuple(x.strip() for x in args.backsync_layers.split(',') if x.strip())
        allowed = {'knowledge', 'self', 'contextual', 'structural', 'anchor'}
        unknown_back = set(layers) - allowed
        if unknown_back:
            ap.error(f'未知反向层: {unknown_back}（可选 {sorted(allowed)}）')
        if 'anchor' in layers:
            ap.error('anchor 层为脑端核心身份（不可遗忘），不允许回流')
        return run_backsync(args.db or str(default_path()), args.memory_root or memory_root(),
                            state, layers, args.max_import, dry_run=args.dry_run)

    since_iso = None if args.full else state.get('last_attempt_submitted_at')
    with ro_connect(args.db) as db:
        stats = _stats_filter(db)
        latest = db.execute(
            f'SELECT MAX(submitted_at) FROM attempts a WHERE a.submitted_at IS NOT NULL {stats}'
        ).fetchone()[0]
        plan = {}
        if 'structural' in layers:
            plan['structural'] = collect_structural(db)
        if 'knowledge' in layers:
            plan['knowledge'] = collect_knowledge(db, since_iso)
        if 'contextual' in layers:
            plan['contextual'] = collect_contextual(db, since_iso)

    print(f'同步计划（水位 {"全量" if args.full else since_iso or "全量（首次）"}）：')
    for layer in layers:
        rows = plan.get(layer, [])[:args.max_per_layer]
        print(f'  {layer}: {len(rows)} 条')
        for entry in rows[:args.sample]:
            print(f'    样例[{entry["title"]}] {entry["body"][:120]}')

    if args.dry_run:
        print('dry-run：未连接脑端，未写入。')
        return 0

    from backend.app.lingshu_bridge.client import BrainClient
    client = BrainClient(root=args.memory_root)
    try:
        results = {}
        for layer in layers:
            ok, fail = 0, []
            for entry in plan.get(layer, [])[:args.max_per_layer]:
                try:
                    resp = client.cg('write', content=six_element_entry(entry),
                                     content_kind='text', layer=layer,
                                     tags=[entry['tag'], f'{SYNC_TAG_PREFIX}source:gongkao'],
                                     importance_hint=entry.get('importance', 0.4))
                    if resp.get('ok') and resp.get('committed'):
                        ok += 1
                    else:
                        verdict = (resp.get('verdict') or {}).get('state')
                        fail.append(f'{entry["title"]}: {verdict or resp.get("error", "unknown")}')
                except Exception as exc:  # noqa: BLE001 —— 单条失败不中断整层
                    fail.append(f'{entry["title"]}: {type(exc).__name__}: {exc}')
            results[layer] = {'ok': ok, 'failed': fail}
            print(f'  {layer}: 写入 {ok} 成功' + (f'，{len(fail)} 失败' if fail else ''))
            for f in fail[:5]:
                print(f'    ✗ {f}')
        state['synced_at'] = datetime.now(timezone.utc).isoformat()
        state['last_results'] = {k: v['ok'] for k, v in results.items()}
        total_failed = sum(len(v['failed']) for v in results.values())
        if total_failed == 0:
            state['last_attempt_submitted_at'] = latest or state.get('last_attempt_submitted_at')
            print(f'水位推进至 {state["last_attempt_submitted_at"]}；状态文件 {STATE_FILE}')
        else:
            # 失败不推进水位：下次同步仍会覆盖本次区间，避免漏同步
            print(f'⚠ {total_failed} 条写入失败，水位不推进（保持 '
                  f'{state.get("last_attempt_submitted_at")}）；排查后重跑')
        save_state(state)
    finally:
        client.close()
    return 0 if total_failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
