"""Daily practice progress from existing learning records (Beijing calendar days)."""
from datetime import datetime, timedelta, timezone
import json
import re

BEIJING = timezone(timedelta(hours=8))
SHENLUN_DAILY_TARGET = 3


def small_question_ids(db):
    """Conservative screening of existing prompts; do not treat answer sections as tasks."""
    result = set()
    for row in db.execute('SELECT id,max_words,question_stem,materials_json FROM shenlun_materials'):
        stem = row['question_stem'].strip()
        if not (0 < row['max_words'] <= 600) or len(stem) < 40 or '参考答案' in stem[:40]:
            continue
        if not re.search('要求|请|根据|给定|结合', stem):
            continue
        materials = json.loads(row['materials_json'])
        if isinstance(materials, list) and any(isinstance(m, dict) and str(m.get('content') or '').strip() for m in materials):
            result.add(row['id'])
    return result


def completed_small_question_ids(db, date):
    eligible = small_question_ids(db)
    return {row[0] for row in db.execute(
        """SELECT DISTINCT material_id FROM shenlun_sessions
           WHERE status='completed' AND length(trim(COALESCE(final_answer,'')))>0
             AND date(completed_at,'+8 hours')=?""", (date,),
    )} & eligible


def today():
    return datetime.now(BEIJING).date().isoformat()


def shenlun_daily_task(db, target_date=None):
    date = target_date or today()
    candidates = small_question_ids(db)
    completed_ids = completed_small_question_ids(db, date)
    completed = len(completed_ids)
    return {
        'date': date, 'target': SHENLUN_DAILY_TARGET, 'completed': completed,
        'remaining': max(0, SHENLUN_DAILY_TARGET-completed),
        'progress_percent': min(100, round(completed/SHENLUN_DAILY_TARGET*100, 1)),
        'available': bool(candidates), 'candidate_count': len(candidates),
        'next_available': bool(candidates-completed_ids),
    }


def daily_goal(db):
    date = today()
    cols = {r[1] for r in db.execute('PRAGMA table_info(attempts)')}
    valid = 'AND valid_for_stats=1' if 'valid_for_stats' in cols else ''
    row = db.execute(
        f"""SELECT COUNT(*) AS total,
            COALESCE(SUM(mode IN ('PRACTICE','EXAM')),0) AS practice,
            COALESCE(SUM(mode='REVIEW'),0) AS review
            FROM attempts WHERE submitted_at IS NOT NULL
              AND date(submitted_at,'+8 hours')=? {valid}""", (date,),
    ).fetchone()
    completed = row['total']
    return {
        'date': date, 'target': 500, 'completed': completed,
        'practice_count': row['practice'], 'review_count': row['review'],
        'progress_percent': min(100.0, round(completed/500*100, 1)),
        'remaining': max(0, 500-completed),
        'shenlun': shenlun_daily_task(db, date),
    }
