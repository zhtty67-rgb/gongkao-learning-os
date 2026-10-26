-- Migration 034: allow formal empty-answer submission and three-tier confidence values.
--
-- Two coupled semantics changes, both backward compatible with existing rows:
-- 1. Empty-answer submission (未作答/不会). Previously the table-level CHECK required
--    selected_answer IS NOT NULL for every submitted attempt, so a learner could not
--    formally submit "I don't know" without fabricating an option. Now a submitted
--    attempt keeps selected_answer NULL with correct=0 (never counted as correct),
--    while submitted attempts with a real option keep correct in (0,1).
-- 2. Three-tier confidence (纯蒙题/半猜/有信心 → 0.2/0.5/0.9). The five legacy values
--    (0.2/0.4/0.6/0.8/1.0) remain valid so historical records stay readable as-is.
--
-- Unsubmitted attempts keep the original invariant: NULL answer/correct/confidence/elapsed.

PRAGMA foreign_keys=OFF;

CREATE TABLE attempts_new (
 id TEXT PRIMARY KEY,
 question_id TEXT NOT NULL,
 session_id TEXT NOT NULL,
 started_at TEXT NOT NULL,
 submitted_at TEXT,
 elapsed_ms INTEGER CHECK(elapsed_ms >= 0),
 selected_answer TEXT CHECK(selected_answer IS NULL OR selected_answer IN ('A','B','C','D')),
 correct INTEGER CHECK(correct IN (0,1)),
 confidence REAL CHECK(confidence IS NULL OR confidence IN (0.2,0.4,0.5,0.6,0.8,0.9,1.0)),
 hint_level INTEGER NOT NULL DEFAULT 0 CHECK(hint_level IN (0,1,2,3,4)),
 attempt_number INTEGER NOT NULL DEFAULT 1 CHECK(attempt_number = 1),
 changed_answer INTEGER NOT NULL DEFAULT 0 CHECK(changed_answer IN (0,1)),
 mode TEXT NOT NULL DEFAULT 'PRACTICE' CHECK(mode IN ('PRACTICE','REVIEW','EXAM')),
 source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('REAL_STUDY', 'AUTO_TEST', 'DEMO', 'IMPORT', 'UNKNOWN')),
 valid_for_stats INTEGER NOT NULL DEFAULT 1 CHECK(valid_for_stats IN (0, 1)),
 timing_valid INTEGER NOT NULL DEFAULT 1 CHECK(timing_valid IN (0, 1)),
 raw_elapsed_ms INTEGER,
 paused_ms INTEGER NOT NULL DEFAULT 0,
 audit_note TEXT,
 exposure_state TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(exposure_state IN ('UNKNOWN', 'NO_ASSISTANCE', 'ASSISTED')),
 is_time_estimated INTEGER NOT NULL DEFAULT 0 CHECK(is_time_estimated IN (0, 1)),
 time_estimation_method TEXT,
 corrected_correct INTEGER,
 correction_basis TEXT,
 answer_key_fingerprint TEXT,
 corrected_at TEXT,
 FOREIGN KEY(session_id,question_id) REFERENCES session_questions(session_id,question_id),
 UNIQUE(session_id,question_id),
 CHECK(
   (submitted_at IS NULL AND selected_answer IS NULL AND correct IS NULL AND confidence IS NULL AND elapsed_ms IS NULL)
   OR
   (submitted_at IS NOT NULL AND correct IS NOT NULL AND elapsed_ms IS NOT NULL
      AND (selected_answer IN ('A','B','C','D') OR (selected_answer IS NULL AND correct = 0)))
 )
);

INSERT INTO attempts_new SELECT * FROM attempts;
DROP TABLE attempts;
ALTER TABLE attempts_new RENAME TO attempts;
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_attempt ON attempts(session_id) WHERE submitted_at IS NULL;

PRAGMA foreign_keys=ON;

INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (34, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
