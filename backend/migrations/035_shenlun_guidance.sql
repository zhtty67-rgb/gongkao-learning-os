BEGIN IMMEDIATE;
-- Additive: legacy sessions/assessments and their immutable answer versions stay intact.
CREATE TABLE shenlun_guidance (
 session_id TEXT PRIMARY KEY REFERENCES shenlun_sessions(id) ON DELETE CASCADE,
 stage TEXT NOT NULL DEFAULT '审题' CHECK(stage IN ('审题','阅读提炼','组织答案','点评修改')),
 revision INTEGER NOT NULL DEFAULT 0,
 state_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(state_json))
);
CREATE TABLE shenlun_point_reports (
 session_id TEXT NOT NULL REFERENCES shenlun_sessions(id) ON DELETE CASCADE,
 version_key TEXT NOT NULL,
 answer_text TEXT NOT NULL,
 report_json TEXT NOT NULL CHECK(json_valid(report_json)),
 PRIMARY KEY(session_id, version_key)
);
INSERT INTO schema_migrations VALUES (35, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
