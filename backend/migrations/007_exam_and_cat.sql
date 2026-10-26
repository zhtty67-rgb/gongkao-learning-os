PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

-- 1. Reconstruct sessions to support EXAM mode
CREATE TABLE sessions_new (
 id TEXT PRIMARY KEY,
 mode TEXT NOT NULL DEFAULT 'PRACTICE' CHECK(mode IN ('PRACTICE','REVIEW','EXAM')),
 started_at TEXT NOT NULL,
 completed_at TEXT,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed'))
);

INSERT INTO sessions_new SELECT id,mode,started_at,completed_at,status FROM sessions;

-- 2. Reconstruct attempts to support EXAM mode
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
 hint_level INTEGER NOT NULL DEFAULT 0 CHECK(hint_level IN (0,1,2,3,4)),
 attempt_number INTEGER NOT NULL DEFAULT 1 CHECK(attempt_number = 1),
 changed_answer INTEGER NOT NULL DEFAULT 0 CHECK(changed_answer IN (0,1)),
 mode TEXT NOT NULL DEFAULT 'PRACTICE' CHECK(mode IN ('PRACTICE','REVIEW','EXAM')),
 FOREIGN KEY(session_id,question_id) REFERENCES session_questions(session_id,question_id),
 UNIQUE(session_id,question_id),
 CHECK((submitted_at IS NULL AND selected_answer IS NULL AND correct IS NULL AND confidence IS NULL AND elapsed_ms IS NULL)
 OR (submitted_at IS NOT NULL AND selected_answer IS NOT NULL AND correct IS NOT NULL AND confidence IS NOT NULL AND elapsed_ms IS NOT NULL))
);

INSERT INTO attempts_new
 SELECT id,question_id,session_id,started_at,submitted_at,elapsed_ms,selected_answer,
        correct,confidence,hint_level,attempt_number,changed_answer,mode
 FROM attempts;

DROP TABLE attempts;
DROP TABLE sessions;

ALTER TABLE sessions_new RENAME TO sessions;
ALTER TABLE attempts_new RENAME TO attempts;

CREATE UNIQUE INDEX one_pending_attempt ON attempts(session_id) WHERE submitted_at IS NULL;

-- 3. Exam metadata and records
CREATE TABLE exam_records (
 session_id TEXT PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
 exam_type TEXT NOT NULL CHECK(exam_type IN ('MOCK','CAT')),
 time_limit_seconds INTEGER NOT NULL CHECK(time_limit_seconds > 0),
 total_questions INTEGER NOT NULL CHECK(total_questions > 0),
 earned_score REAL,
 max_score REAL NOT NULL,
 ability_theta REAL,
 standard_error REAL,
 completed_at TEXT,
 created_at TEXT NOT NULL
);

-- 4. Daily plans table
CREATE TABLE daily_plans (
 plan_date TEXT PRIMARY KEY,
 session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
 allocation_json TEXT NOT NULL CHECK(json_valid(allocation_json)),
 items_json TEXT NOT NULL CHECK(json_valid(items_json)),
 created_at TEXT NOT NULL
);

INSERT INTO schema_migrations VALUES (7, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
PRAGMA foreign_keys=ON;
