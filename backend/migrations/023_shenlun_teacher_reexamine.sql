BEGIN IMMEDIATE;

-- Objection / re-examination support for the shenlun teacher workbench.
-- followups.kind distinguishes ordinary questions from diagnosis objections;
-- shenlun_target_revisions is the append-only version log for per-target
-- maintain/adjust/withdraw decisions. Diagnosis rows themselves stay immutable:
-- the effective state is derived at read time by folding revisions on top.

ALTER TABLE shenlun_teacher_followups ADD COLUMN kind TEXT NOT NULL DEFAULT 'question';
ALTER TABLE shenlun_teacher_followups ADD COLUMN target_key TEXT NOT NULL DEFAULT '';

CREATE TABLE shenlun_target_revisions (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES shenlun_sessions(id) ON DELETE CASCADE,
 teacher_id TEXT NOT NULL,
 diagnosis_id TEXT NOT NULL,
 target_key TEXT NOT NULL,
 action TEXT NOT NULL CHECK(action IN ('maintain','adjust','withdraw')),
 reason TEXT NOT NULL DEFAULT '',
 revised_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(revised_json)),
 source TEXT NOT NULL DEFAULT 'ai' CHECK(source IN ('ai','user')),
 created_at TEXT NOT NULL
);

CREATE INDEX idx_shenlun_target_revisions
 ON shenlun_target_revisions(diagnosis_id, target_key, created_at);

INSERT INTO schema_migrations VALUES (23, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
