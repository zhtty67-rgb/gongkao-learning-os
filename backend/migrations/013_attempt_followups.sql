BEGIN IMMEDIATE;

-- AI Tutor Follow-up Q&A dialogue history associated with question attempts
CREATE TABLE IF NOT EXISTS attempt_followups (
 id TEXT PRIMARY KEY,
 attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
 role TEXT NOT NULL CHECK(role IN ('user', 'assistant')),
 content TEXT NOT NULL,
 created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_attempt_followups_attempt
 ON attempt_followups(attempt_id, created_at ASC);

INSERT INTO schema_migrations VALUES (13, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
