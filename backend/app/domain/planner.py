"""Daily Planner: Generates balanced daily study plans (35% review, 35% weakness, 20% new, 10% maintenance)."""
from datetime import datetime, timezone
import json
from typing import Any

from .mastery import overall_mastery
from .review import due_reviews


def calculate_quotas(total_items: int) -> dict[str, int]:
    """Deterministically allocate integer quotas summing exactly to total_items."""
    if total_items <= 0:
        return {'review': 0, 'weakness': 0, 'new': 0, 'maintenance': 0}
    if total_items == 1:
        return {'review': 1, 'weakness': 0, 'new': 0, 'maintenance': 0}
    if total_items == 2:
        return {'review': 1, 'weakness': 1, 'new': 0, 'maintenance': 0}
    if total_items == 3:
        return {'review': 1, 'weakness': 1, 'new': 1, 'maintenance': 0}

    q_review = int(round(total_items * 0.35))
    q_weakness = int(round(total_items * 0.35))
    q_new = int(round(total_items * 0.20))
    q_maint = total_items - (q_review + q_weakness + q_new)
    if q_maint < 0:
        q_maint = 0

    return {
        'review': q_review,
        'weakness': q_weakness,
        'new': q_new,
        'maintenance': q_maint,
    }


def generate_daily_plan(db, target_date: str | None = None, total_items: int = 10) -> dict[str, Any]:
    """Assemble deterministic daily study plan conforming to SPEC Section 15.
    
    Guarantees:
      1. Strictly no duplicate questions across buckets.
      2. Deterministic order and quotas.
      3. Graceful fallback when certain buckets have insufficient candidates.
      4. Never errors when candidate pool is smaller than requested total.
      5. Stable on extreme total_items (1, 3, 7, 10, 20).
    """
    total_items = max(1, total_items)
    as_of_dt = datetime.now(timezone.utc)
    plan_date = target_date or as_of_dt.strftime('%Y-%m-%d')

    # Check if plan already exists for today
    existing = db.execute('SELECT * FROM daily_plans WHERE plan_date=?', (plan_date,)).fetchone()
    if existing:
        return {
            'plan_date': plan_date,
            'allocation': json.loads(existing['allocation_json']),
            'items': json.loads(existing['items_json']),
            'reused': True,
        }

    quotas = calculate_quotas(total_items)
    selected_ids: set[str] = set()
    plan_items: list[dict[str, Any]] = []

    # Helper to add item safely
    def try_add(qid: str, category: str, cat_label: str, reason: str) -> bool:
        if len(plan_items) >= total_items:
            return False
        if qid in selected_ids:
            return False
        selected_ids.add(qid)
        plan_items.append({
            'question_id': qid,
            'category': category,
            'category_label': cat_label,
            'reason': reason,
        })
        return True

    # 1. Due Review (35%)
    if quotas['review'] > 0 and len(plan_items) < total_items:
        due_cards = due_reviews(db, as_of_dt, limit=quotas['review'])
        for card in due_cards:
            try_add(
                card['question_id'],
                'REVIEW',
                '到期复习 (35%)',
                f"FSRS 记忆临界点到了，已复习 {card['review_count']} 次",
            )

    # 2. Weakest Mastery (35%)
    if quotas['weakness'] > 0 and len(plan_items) < total_items:
        weak_rows = db.execute(
            '''SELECT DISTINCT q.id, kn.name node_name, ms.mastery_score
               FROM questions q
               JOIN question_knowledge_map qkm ON qkm.question_id=q.id
               JOIN knowledge_nodes kn ON kn.id=qkm.knowledge_node_id
               JOIN mastery_state ms ON ms.knowledge_node_id=kn.id
               WHERE q.is_verified = 1
               ORDER BY ms.mastery_score ASC, q.id ASC'''
        ).fetchall()
        for row in weak_rows:
            if sum(1 for p in plan_items if p['category'] == 'WEAKNESS') >= quotas['weakness']:
                break
            try_add(
                row['id'],
                'WEAKNESS',
                '重点攻坚 (35%)',
                f"薄弱考点【{row['node_name']}】掌握度仅 {int(row['mastery_score'] * 100)}%",
            )

    # 3. New Knowledge (20%)
    if quotas['new'] > 0 and len(plan_items) < total_items:
        cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
        valid_filter = "AND valid_for_stats = 1" if 'valid_for_stats' in cols else ""
        practiced_qids = {r[0] for r in db.execute(f'SELECT DISTINCT question_id FROM attempts WHERE submitted_at IS NOT NULL {valid_filter}')}
        new_rows = db.execute(
            '''SELECT id, module FROM questions WHERE is_verified = 1 ORDER BY id ASC'''
        ).fetchall()
        for row in new_rows:
            if row['id'] in practiced_qids:
                continue
            if sum(1 for p in plan_items if p['category'] == 'NEW_CONTENT') >= quotas['new']:
                break
            try_add(
                row['id'],
                'NEW_CONTENT',
                '新知拓展 (20%)',
                f"未接触过的【{row['module']}】题库新题",
            )

    # 4. Maintenance (10%) & Graceful Fallback
    # If quotas from above were unfilled due to candidate scarcity, backfill from remaining questions
    fallback_rows = db.execute(
        '''SELECT id, module FROM questions WHERE is_verified = 1 ORDER BY id ASC'''
    ).fetchall()
    for row in fallback_rows:
        if len(plan_items) >= total_items:
            break
        try_add(
            row['id'],
            'MAINTENANCE',
            '巩固保持 (10%)',
            f"【{row['module']}】保持手感与题型熟练度",
        )

    allocation = {
        'review_count': sum(1 for p in plan_items if p['category'] == 'REVIEW'),
        'weakness_count': sum(1 for p in plan_items if p['category'] == 'WEAKNESS'),
        'new_count': sum(1 for p in plan_items if p['category'] == 'NEW_CONTENT'),
        'maintenance_count': sum(1 for p in plan_items if p['category'] == 'MAINTENANCE'),
        'total': len(plan_items),
        'requested_total': total_items,
    }

    # Save to db
    db.execute(
        '''INSERT INTO daily_plans (plan_date, allocation_json, items_json, created_at)
           VALUES (?,?,?,?)''',
        (
            plan_date,
            json.dumps(allocation, ensure_ascii=False),
            json.dumps(plan_items, ensure_ascii=False),
            as_of_dt.isoformat(),
        ),
    )
    db.commit()

    return {
        'plan_date': plan_date,
        'allocation': allocation,
        'items': plan_items,
        'reused': False,
    }
