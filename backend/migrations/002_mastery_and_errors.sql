BEGIN IMMEDIATE;

CREATE TABLE mastery_evidence (
 attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
 knowledge_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
 success_evidence REAL NOT NULL CHECK(success_evidence >= 0),
 failure_evidence REAL NOT NULL CHECK(failure_evidence >= 0),
 time_ratio REAL NOT NULL CHECK(time_ratio >= 0),
 timed INTEGER NOT NULL CHECK(timed IN (0,1)),
 created_at TEXT NOT NULL,
 PRIMARY KEY(attempt_id, knowledge_node_id),
 CHECK((success_evidence > 0 AND failure_evidence = 0) OR (failure_evidence > 0 AND success_evidence = 0))
);

CREATE TABLE mastery_state (
 knowledge_node_id TEXT PRIMARY KEY REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
 mastery_score REAL NOT NULL CHECK(mastery_score BETWEEN 0 AND 1),
 evidence_positive REAL NOT NULL CHECK(evidence_positive >= 0),
 evidence_negative REAL NOT NULL CHECK(evidence_negative >= 0),
 attempt_count INTEGER NOT NULL CHECK(attempt_count >= 0),
 recent_accuracy REAL,
 timed_accuracy REAL,
 avg_time_ratio REAL,
 hint_dependency REAL NOT NULL CHECK(hint_dependency BETWEEN 0 AND 1),
 transfer_score REAL,
 last_practiced_at TEXT,
 updated_at TEXT NOT NULL
);

CREATE TABLE error_events (
 id TEXT PRIMARY KEY,
 attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
 error_type TEXT NOT NULL CHECK(error_type IN (
   'knowledge_gap','conceptual_error','method_selection','reading_error',
   'calculation_error','time_pressure','careless_error','transfer_failure','unknown'
 )),
 ai_confidence REAL CHECK(ai_confidence BETWEEN 0 AND 1),
 explanation TEXT NOT NULL DEFAULT '',
 source TEXT NOT NULL DEFAULT 'USER' CHECK(source = 'USER'),
 supersedes_id TEXT REFERENCES error_events(id),
 created_at TEXT NOT NULL
);

CREATE INDEX error_events_attempt_created ON error_events(attempt_id, created_at DESC);
CREATE INDEX mastery_evidence_node ON mastery_evidence(knowledge_node_id);
INSERT INTO schema_migrations VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
