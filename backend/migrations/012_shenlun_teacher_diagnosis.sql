BEGIN IMMEDIATE;

-- Teacher Feiyang local diagnosis records (immutable raw facts, one per submit attempt)
CREATE TABLE shenlun_teacher_diagnoses (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES shenlun_sessions(id) ON DELETE CASCADE,
 engine_version TEXT NOT NULL,
 teacher_name TEXT NOT NULL,
 question_type TEXT NOT NULL,
 training_targets_json TEXT NOT NULL CHECK(json_valid(training_targets_json)),
 followups_json TEXT NOT NULL CHECK(json_valid(followups_json)),
 strengths_json TEXT NOT NULL CHECK(json_valid(strengths_json)),
 matched_policies_json TEXT NOT NULL CHECK(json_valid(matched_policies_json)),
 similar_cases_json TEXT NOT NULL CHECK(json_valid(similar_cases_json)),
 coach_note TEXT NOT NULL,
 material_summary_json TEXT NOT NULL CHECK(json_valid(material_summary_json)),
 created_at TEXT NOT NULL
);

CREATE INDEX idx_shenlun_teacher_diagnoses_session
 ON shenlun_teacher_diagnoses(session_id, created_at DESC);

INSERT INTO schema_migrations VALUES (12, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
