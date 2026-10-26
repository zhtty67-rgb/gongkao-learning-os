"""Deterministic FSRS-6 scheduling projected from immutable attempts."""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid5, NAMESPACE_URL

from fsrs import Card, Rating, Scheduler


SCHEDULER_VERSION = 'py-fsrs-6.3.2'
RATING_POLICY_VERSION = 'gongkao-auto-rating-v1'


SCHEDULER = Scheduler(
    desired_retention=0.9,
    learning_steps=(),
    relearning_steps=(),
    maximum_interval=36500,
    enable_fuzzing=False,
)


def _card_id(question_id: str) -> int:
    return int.from_bytes(sha256(question_id.encode('utf-8')).digest()[:7], 'big')


def rating_for_attempt(attempt, estimated_seconds: int):
    """Map observed performance to FSRS without asking the learner for a rating."""
    if not attempt['correct']:
        return Rating.Again, 'incorrect'
    if attempt['hint_level'] > 0:
        return Rating.Hard, 'hint_used'
    timing_valid = dict(attempt).get('timing_valid', 1)
    if timing_valid and attempt['elapsed_ms'] > estimated_seconds * 1000:
        return Rating.Hard, 'over_time'
    conf = attempt['confidence'] if isinstance(attempt, dict) or hasattr(attempt, '__getitem__') else getattr(attempt, 'confidence', None)
    if conf is not None and conf <= 0.4:
        return Rating.Hard, 'low_confidence'
    if timing_valid and attempt['elapsed_ms'] <= estimated_seconds * 600 and conf is not None and conf >= 0.8:
        return Rating.Easy, 'fast_high_confidence'
    return Rating.Good, 'standard_correct'


def rebuild_reviews(db):
    """Replay submitted attempts into deterministic FSRS cards and event projections."""
    db.execute('DELETE FROM review_events')
    db.execute('DELETE FROM review_cards')
    cols = [c[1] for c in db.execute('PRAGMA table_info(attempts)').fetchall()]
    valid_filter = "AND a.valid_for_stats = 1" if 'valid_for_stats' in cols else ""
    attempts_raw = db.execute(
        f'''SELECT a.*,q.estimated_seconds
           FROM attempts a JOIN questions q ON q.id=a.question_id
           WHERE a.submitted_at IS NOT NULL {valid_filter}
           ORDER BY a.question_id,a.submitted_at,a.id'''
    ).fetchall()
    # FSRS replay uses the effective verdict: corrected attempts rate by the verdict under
    # the current standard answer while attempts.correct keeps the historical judgment.
    attempts = []
    for a in attempts_raw:
        d = dict(a)
        if d.get('corrected_correct') is not None:
            d['correct'] = d['corrected_correct']
        attempts.append(d)
    cards = {}
    counts = {}
    lapses = {}
    for attempt in attempts:
        question_id = attempt['question_id']
        reviewed_at = datetime.fromisoformat(attempt['submitted_at']).astimezone(timezone.utc)
        card = cards.get(question_id) or Card(card_id=_card_id(question_id), due=reviewed_at)
        rating, reason = rating_for_attempt(attempt, attempt['estimated_seconds'])
        state_before = card.state.value
        due_before = card.due.isoformat()
        had_prior_review = card.last_review is not None
        card, _ = SCHEDULER.review_card(
            card, rating, review_datetime=reviewed_at, review_duration=attempt['elapsed_ms'],
        )
        cards[question_id] = card
        counts[question_id] = counts.get(question_id, 0) + 1
        lapses[question_id] = lapses.get(question_id, 0) + int(had_prior_review and rating is Rating.Again)
        event_id = str(uuid5(NAMESPACE_URL, f'gongkao-review:{attempt["id"]}'))
        db.execute(
            '''INSERT INTO review_events
               (id,attempt_id,question_id,rating,rating_reason,reviewed_at,elapsed_ms,
                state_before,state_after,due_before,due_after,stability_after,difficulty_after,
                created_at,scheduler_version,rating_policy_version)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                event_id, attempt['id'], question_id, rating.value, reason, reviewed_at.isoformat(),
                attempt['elapsed_ms'], state_before, card.state.value, due_before, card.due.isoformat(),
                card.stability, card.difficulty, attempt['submitted_at'], SCHEDULER_VERSION,
                RATING_POLICY_VERSION,
            ),
        )
    updated_at = datetime.now(timezone.utc).isoformat()
    for question_id, card in cards.items():
        db.execute(
            '''INSERT INTO review_cards
               (question_id,card_id,state,step,stability,difficulty,due,last_review,
                review_count,lapse_count,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
            (
                question_id, card.card_id, card.state.value, card.step, card.stability, card.difficulty,
                card.due.isoformat(), card.last_review.isoformat() if card.last_review else None,
                counts[question_id], lapses[question_id], updated_at,
            ),
        )


def due_reviews(db, as_of=None, limit=25):
    as_of = (as_of or datetime.now(timezone.utc)).astimezone(timezone.utc)
    rows = db.execute(
        '''SELECT rc.question_id, rc.question_id AS id, rc.state,rc.stability,rc.difficulty,rc.due,rc.last_review,
                  rc.review_count,rc.lapse_count,q.source,q.year,q.exam_type,q.subject,q.module,
                  q.stem,q.options_json,q.difficulty question_difficulty,q.estimated_seconds,q.is_verified,
                  q.stem_assets_json,q.option_assets_json
           FROM review_cards rc JOIN questions q ON q.id=rc.question_id
           WHERE rc.due<=?
           ORDER BY rc.due,rc.question_id LIMIT ?''',
        (as_of.isoformat(), limit),
    ).fetchall()
    return rows
