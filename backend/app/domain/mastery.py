"""Deterministic, replayable mastery projections derived only from attempts."""
from datetime import datetime, timezone

from .attempt_verdict import correct_expr

HINT_SUCCESS_MULTIPLIERS = {
    0: 1.0,   # 独立做对
    1: 0.65,  # 一级提示后做对
    2: 0.45,  # 二级提示后做对
    3: 0.25,  # 三级提示后做对
    4: 0.0,   # 完整解析后做对（不增加正面掌握度证据）
}

# Editorial/context nodes can appear on the map without becoming mathematical
# mastery evidence. Existing nodes remain eligible unless explicitly opted out.
MASTERY_ELIGIBLE_SQL = """COALESCE(json_extract(
    CASE WHEN json_valid(kn.metadata_json) THEN kn.metadata_json ELSE '{}' END,
    '$.mastery_eligible'), 1) != 0"""


def rebuild_mastery(db):
    """Rebuild all projections. Raw attempts are the source of truth.

    The effective verdict (COALESCE(corrected_correct, correct)) is used so that
    answer-key corrections flow into mastery without rewriting history."""
    timestamp = datetime.now(timezone.utc).isoformat()
    db.execute('DELETE FROM mastery_evidence')
    db.execute('DELETE FROM mastery_state')
    cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
    valid_filter = "AND a.valid_for_stats = 1" if 'valid_for_stats' in cols else ""
    timing_expr = 'a.timing_valid' if 'timing_valid' in cols else '1'
    rows = db.execute(
        f'''SELECT a.id attempt_id,{correct_expr(db)} AS correct,a.elapsed_ms,a.hint_level,a.submitted_at,
                  q.estimated_seconds,qkm.knowledge_node_id,qkm.weight,{timing_expr} AS timing_valid
           FROM attempts a
           JOIN questions q ON q.id=a.question_id
           JOIN question_knowledge_map qkm ON qkm.question_id=a.question_id
           JOIN knowledge_nodes kn ON kn.id=qkm.knowledge_node_id
           WHERE a.submitted_at IS NOT NULL {valid_filter} AND {MASTERY_ELIGIBLE_SQL}
           ORDER BY a.submitted_at,a.id,qkm.knowledge_node_id'''
    ).fetchall()
    db.executemany(
        '''INSERT INTO mastery_evidence
           (attempt_id,knowledge_node_id,success_evidence,failure_evidence,time_ratio,timed,created_at)
           VALUES (?,?,?,?,?,?,?)''',
        [(
            row['attempt_id'], row['knowledge_node_id'],
            (row['weight'] * HINT_SUCCESS_MULTIPLIERS.get(row['hint_level'], 1.0)) if row['correct'] else 0,
            0 if row['correct'] else row['weight'],
            row['elapsed_ms'] / (row['estimated_seconds'] * 1000) if row['timing_valid'] else 0,
            int(bool(row['timing_valid']) and row['elapsed_ms'] <= row['estimated_seconds'] * 1000),
            row['submitted_at'],
        ) for row in rows],
    )
    nodes = db.execute('SELECT id FROM knowledge_nodes ORDER BY id').fetchall()
    for node in nodes:
        evidence = db.execute(
            f'''SELECT me.*,{correct_expr(db)} AS correct,a.hint_level,a.submitted_at,{timing_expr} AS timing_valid
               FROM mastery_evidence me JOIN attempts a ON a.id=me.attempt_id
               WHERE me.knowledge_node_id=? ORDER BY a.submitted_at DESC,a.id DESC''',
            (node['id'],),
        ).fetchall()
        positive = sum(row['success_evidence'] for row in evidence)
        negative = sum(row['failure_evidence'] for row in evidence)
        count = len(evidence)
        recent = evidence[:20]
        timed = [row for row in evidence if row['timed']]
        valid_times = [row for row in evidence if row['timing_valid']]
        db.execute(
            '''INSERT INTO mastery_state VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                node['id'], (1 + positive) / (2 + positive + negative), positive, negative, count,
                sum(row['correct'] for row in recent) / len(recent) if recent else None,
                sum(row['correct'] for row in timed) / len(timed) if timed else None,
                sum(row['time_ratio'] for row in valid_times) / len(valid_times) if valid_times else None,
                sum(row['hint_level'] > 0 for row in evidence) / count if count else 0,
                None, evidence[0]['submitted_at'] if evidence else None, timestamp,
            ),
        )


def overall_mastery(db):
    row = db.execute(
        f'''SELECT SUM(ms.mastery_score * kn.weight) weighted, SUM(kn.weight) total
           FROM mastery_state ms JOIN knowledge_nodes kn ON kn.id=ms.knowledge_node_id
           WHERE {MASTERY_ELIGIBLE_SQL}'''
    ).fetchone()
    return row['weighted'] / row['total'] if row and row['total'] else 0.5
