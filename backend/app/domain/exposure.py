"""Domain module for tracking assistance exposure and credibility."""
import json
import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_exposure(
    db,
    *,
    question_id: str,
    attempt_id: str | None = None,
    session_id: str | None = None,
    exposure_type: str,  # 'HINT' | 'EXPLANATION' | 'ANSWER' | 'AI_TUTOR'
    stage: str,          # 'PRE_SUBMISSION' | 'POST_SUBMISSION'
    source_action: str,  # 'QUIZ_HINT' | 'SUBMIT_REVIEW' | 'AI_EXPLAIN' | 'EXAM_REVIEW'
    details: dict | None = None,
) -> bool:
    """
    Record an assistance exposure event with idempotency / deduplication.
    Returns True if a new exposure was recorded, False if deduplicated.
    """
    details_str = json.dumps(details or {}, ensure_ascii=False)
    timestamp = now_iso()

    # Deduplication key prevents rapid refreshes / repeated clicks from inflating counts
    if attempt_id:
        sub_key = str(details.get('hint_level', '')) if details else ''
        dedup_key = f"{attempt_id}:{exposure_type}:{stage}:{sub_key}"
    elif session_id:
        dedup_key = f"{session_id}:{question_id}:{exposure_type}:{stage}"
    else:
        dedup_key = f"{question_id}:{exposure_type}:{stage}:{timestamp[:16]}"

    cur = db.execute(
        '''INSERT OR IGNORE INTO exposure_logs 
           (id, attempt_id, question_id, session_id, exposure_type, stage, source_action, details_json, exposed_at, dedup_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        (str(uuid.uuid4()), attempt_id, question_id, session_id, exposure_type, stage, source_action, details_str, timestamp, dedup_key)
    )
    inserted = (cur.rowcount > 0)

    # If this is pre-submission assistance on an active attempt, update attempt exposure_state to ASSISTED
    if stage == 'PRE_SUBMISSION' and attempt_id:
        db.execute(
            "UPDATE attempts SET exposure_state = 'ASSISTED' WHERE id = ? AND submitted_at IS NULL",
            (attempt_id,)
        )

    return inserted


def get_attempt_exposures(db, attempt_id: str) -> list[dict]:
    """Retrieve all exposure events for a given attempt."""
    rows = db.execute(
        '''SELECT id, attempt_id, question_id, session_id, exposure_type, stage, source_action, details_json, exposed_at
           FROM exposure_logs
           WHERE attempt_id = ?
           ORDER BY exposed_at ASC''',
        (attempt_id,)
    ).fetchall()
    return [dict(r) for r in rows]
