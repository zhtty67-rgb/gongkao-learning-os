PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

-- Migration 020: Unified Interactive Review across all modules with full conversation persistence
-- 1. Extend attempt_followups to associate with question_id, turn_type, execution status, and structured metadata
ALTER TABLE attempt_followups ADD COLUMN question_id TEXT REFERENCES questions(id) ON DELETE CASCADE;
ALTER TABLE attempt_followups ADD COLUMN turn_type TEXT NOT NULL DEFAULT 'free_chat';
ALTER TABLE attempt_followups ADD COLUMN status TEXT NOT NULL DEFAULT 'completed';
ALTER TABLE attempt_followups ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';

-- Backfill question_id for legacy followups using existing attempt relations
UPDATE attempt_followups
SET question_id = (SELECT question_id FROM attempts WHERE attempts.id = attempt_followups.attempt_id)
WHERE question_id IS NULL;

CREATE INDEX IF NOT EXISTS idx_attempt_followups_qid ON attempt_followups(question_id);

-- 2. Extend interactive_diagnoses with review summary and latest message timestamp for fast queries in error log and framework tree
ALTER TABLE interactive_diagnoses ADD COLUMN summary TEXT;
ALTER TABLE interactive_diagnoses ADD COLUMN last_message_at TEXT;

INSERT OR IGNORE INTO schema_migrations VALUES (20, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
