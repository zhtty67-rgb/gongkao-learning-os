BEGIN IMMEDIATE;

CREATE TABLE session_question_selections (
 session_id TEXT NOT NULL,
 question_id TEXT NOT NULL,
 position INTEGER NOT NULL CHECK(position >= 0),
 policy_version TEXT NOT NULL,
 selection_score REAL NOT NULL,
 selection_reason TEXT NOT NULL,
 component_scores_json TEXT NOT NULL CHECK(json_valid(component_scores_json)),
 decided_at TEXT NOT NULL,
 PRIMARY KEY(session_id,question_id),
 UNIQUE(session_id,position),
 FOREIGN KEY(session_id,question_id)
   REFERENCES session_questions(session_id,question_id) ON DELETE CASCADE
);

CREATE INDEX session_question_selections_policy
 ON session_question_selections(policy_version,session_id,position);

INSERT INTO schema_migrations VALUES (5, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
