PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

CREATE TABLE sessions_new (
 id TEXT PRIMARY KEY,
 mode TEXT NOT NULL DEFAULT 'PRACTICE' CHECK(mode IN ('PRACTICE','REVIEW')),
 started_at TEXT NOT NULL,
 completed_at TEXT,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed'))
);

CREATE TABLE session_questions_new (
 session_id TEXT NOT NULL REFERENCES sessions(id),
 question_id TEXT NOT NULL REFERENCES questions(id),
 position INTEGER NOT NULL CHECK(position >= 0),
 PRIMARY KEY(session_id,question_id),
 UNIQUE(session_id,position)
);

CREATE TABLE attempts_new (
 id TEXT PRIMARY KEY,
 question_id TEXT NOT NULL,
 session_id TEXT NOT NULL,
 started_at TEXT NOT NULL,
 submitted_at TEXT,
 elapsed_ms INTEGER CHECK(elapsed_ms >= 0),
 selected_answer TEXT CHECK(selected_answer IN ('A','B','C','D')),
 correct INTEGER CHECK(correct IN (0,1)),
 confidence REAL CHECK(confidence IN (0.2,0.4,0.6,0.8,1.0)),
 hint_level INTEGER NOT NULL DEFAULT 0 CHECK(hint_level = 0),
 attempt_number INTEGER NOT NULL DEFAULT 1 CHECK(attempt_number = 1),
 changed_answer INTEGER NOT NULL DEFAULT 0 CHECK(changed_answer IN (0,1)),
 mode TEXT NOT NULL DEFAULT 'PRACTICE' CHECK(mode IN ('PRACTICE','REVIEW')),
 FOREIGN KEY(session_id,question_id) REFERENCES session_questions(session_id,question_id),
 UNIQUE(session_id,question_id),
 CHECK((submitted_at IS NULL AND selected_answer IS NULL AND correct IS NULL AND confidence IS NULL AND elapsed_ms IS NULL)
 OR (submitted_at IS NOT NULL AND selected_answer IS NOT NULL AND correct IS NOT NULL AND confidence IS NOT NULL AND elapsed_ms IS NOT NULL))
);

INSERT INTO sessions_new SELECT id,mode,started_at,completed_at,status FROM sessions;
INSERT INTO session_questions_new SELECT session_id,question_id,position FROM session_questions;
INSERT INTO attempts_new
 SELECT id,question_id,session_id,started_at,submitted_at,elapsed_ms,selected_answer,
        correct,confidence,hint_level,attempt_number,changed_answer,mode
 FROM attempts;

DROP TABLE attempts;
DROP TABLE session_questions;
DROP TABLE sessions;

ALTER TABLE sessions_new RENAME TO sessions;
ALTER TABLE session_questions_new RENAME TO session_questions;
ALTER TABLE attempts_new RENAME TO attempts;

CREATE UNIQUE INDEX one_pending_attempt ON attempts(session_id) WHERE submitted_at IS NULL;

ALTER TABLE review_events
 ADD COLUMN scheduler_version TEXT NOT NULL DEFAULT 'py-fsrs-6.3.2';
ALTER TABLE review_events
 ADD COLUMN rating_policy_version TEXT NOT NULL DEFAULT 'gongkao-auto-rating-v1';

INSERT INTO schema_migrations VALUES (4, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
PRAGMA foreign_keys=ON;
