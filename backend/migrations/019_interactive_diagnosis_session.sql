PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

-- Migration 019: Interactive, Corrigible Diagnosis Session with Provenance Tracking
CREATE TABLE IF NOT EXISTS interactive_diagnoses (
    id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK(status IN ('HYPOTHESIZED', 'CLARIFYING', 'CONFIRMED', 'CORRECTED', 'SKIPPED', 'INSUFFICIENT_INFO')),
    observed_facts_json TEXT NOT NULL DEFAULT '{}',
    hypotheses_json TEXT NOT NULL DEFAULT '[]',
    initial_inference_json TEXT NOT NULL DEFAULT '{}',
    clarification_question TEXT,
    clarification_options_json TEXT NOT NULL DEFAULT '[]',
    user_feedback_type TEXT CHECK(user_feedback_type IN ('CONFIRMED', 'CORRECTED', 'SKIPPED')),
    user_feedback_text TEXT,
    final_diagnosis_json TEXT,
    is_user_confirmed INTEGER NOT NULL DEFAULT 0 CHECK(is_user_confirmed IN (0, 1)),
    citation TEXT,
    suggested_action TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    dedup_key TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_interactive_diag_attempt ON interactive_diagnoses(attempt_id);
CREATE INDEX IF NOT EXISTS idx_interactive_diag_question ON interactive_diagnoses(question_id);

INSERT OR IGNORE INTO schema_migrations VALUES (19, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
