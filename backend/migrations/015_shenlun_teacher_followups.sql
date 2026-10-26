BEGIN IMMEDIATE;

-- Per-teacher follow-up conversation for shenlun workbench diagnosis
CREATE TABLE shenlun_teacher_followups (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES shenlun_sessions(id) ON DELETE CASCADE,
 teacher_id TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('user','assistant')),
 content TEXT NOT NULL,
 citations_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(citations_json)),
 created_at TEXT NOT NULL
);

CREATE INDEX idx_shenlun_teacher_followups
 ON shenlun_teacher_followups(session_id, teacher_id, created_at);

INSERT INTO schema_migrations VALUES (15, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
