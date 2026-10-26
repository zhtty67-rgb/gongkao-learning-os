PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

-- Migration 021: Unified Review Preferences and Integrated Error Cause Attribution
-- 1. Extend interactive_diagnoses to store unified cause attribution and change history
ALTER TABLE interactive_diagnoses ADD COLUMN selected_error_type TEXT;
ALTER TABLE interactive_diagnoses ADD COLUMN cause_source TEXT DEFAULT 'PENDING';
ALTER TABLE interactive_diagnoses ADD COLUMN cause_history_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE interactive_diagnoses ADD COLUMN client_request_id TEXT;

CREATE INDEX IF NOT EXISTS idx_interactive_diag_err_type ON interactive_diagnoses(selected_error_type);

-- 2. Create user review preferences table for persistent review preference mode
CREATE TABLE IF NOT EXISTS user_review_preferences (
    user_id TEXT PRIMARY KEY DEFAULT 'default_user',
    preference_mode TEXT NOT NULL DEFAULT 'MANUAL' CHECK(preference_mode IN ('AUTO_ASK', 'MANUAL', 'EXPLANATION_ONLY')),
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO user_review_preferences (user_id, preference_mode, updated_at)
VALUES ('default_user', 'MANUAL', strftime('%Y-%m-%dT%H:%M:%fZ','now'));

INSERT OR IGNORE INTO schema_migrations VALUES (21, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
