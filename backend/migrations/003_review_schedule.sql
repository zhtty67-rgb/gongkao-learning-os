BEGIN IMMEDIATE;

CREATE TABLE review_cards (
 question_id TEXT PRIMARY KEY REFERENCES questions(id) ON DELETE CASCADE,
 card_id INTEGER NOT NULL UNIQUE,
 state INTEGER NOT NULL CHECK(state IN (1,2,3)),
 step INTEGER,
 stability REAL,
 difficulty REAL,
 due TEXT NOT NULL,
 last_review TEXT,
 review_count INTEGER NOT NULL CHECK(review_count >= 0),
 lapse_count INTEGER NOT NULL CHECK(lapse_count >= 0),
 updated_at TEXT NOT NULL
);

CREATE TABLE review_events (
 id TEXT PRIMARY KEY,
 attempt_id TEXT NOT NULL UNIQUE REFERENCES attempts(id) ON DELETE CASCADE,
 question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
 rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 4),
 rating_reason TEXT NOT NULL CHECK(rating_reason IN (
   'incorrect','hint_used','over_time','low_confidence',
   'fast_high_confidence','standard_correct'
 )),
 reviewed_at TEXT NOT NULL,
 elapsed_ms INTEGER NOT NULL CHECK(elapsed_ms >= 0),
 state_before INTEGER NOT NULL CHECK(state_before IN (1,2,3)),
 state_after INTEGER NOT NULL CHECK(state_after IN (1,2,3)),
 due_before TEXT NOT NULL,
 due_after TEXT NOT NULL,
 stability_after REAL,
 difficulty_after REAL,
 created_at TEXT NOT NULL
);

CREATE INDEX review_cards_due ON review_cards(due);
CREATE INDEX review_events_question_reviewed ON review_events(question_id, reviewed_at);
INSERT INTO schema_migrations VALUES (3, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
