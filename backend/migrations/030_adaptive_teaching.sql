BEGIN IMMEDIATE;
-- Reuse learning_relations: source is the prerequisite, target depends on source.
CREATE TRIGGER prerequisite_no_cycle_insert BEFORE INSERT ON learning_relations
WHEN NEW.relation_type='prerequisite'
BEGIN
 SELECT RAISE(ABORT,'prerequisite cycle') WHERE NEW.source_skill_id=NEW.target_skill_id
 OR EXISTS (WITH RECURSIVE descendants(id) AS (
   SELECT target_skill_id FROM learning_relations WHERE relation_type='prerequisite' AND source_skill_id=NEW.target_skill_id
   UNION SELECT r.target_skill_id FROM learning_relations r JOIN descendants d ON r.source_skill_id=d.id WHERE r.relation_type='prerequisite'
 ) SELECT 1 FROM descendants WHERE id=NEW.source_skill_id);
END;
CREATE TRIGGER prerequisite_no_cycle_update BEFORE UPDATE ON learning_relations
WHEN NEW.relation_type='prerequisite'
BEGIN
 SELECT RAISE(ABORT,'prerequisite cycle') WHERE NEW.source_skill_id=NEW.target_skill_id
 OR EXISTS (WITH RECURSIVE descendants(id) AS (
   SELECT target_skill_id FROM learning_relations WHERE relation_type='prerequisite' AND source_skill_id=NEW.target_skill_id AND id!=OLD.id
   UNION SELECT r.target_skill_id FROM learning_relations r JOIN descendants d ON r.source_skill_id=d.id WHERE r.relation_type='prerequisite' AND r.id!=OLD.id
 ) SELECT 1 FROM descendants WHERE id=NEW.source_skill_id);
END;
-- Conservative curriculum seed: two-period proportions require growth-rate reasoning.
INSERT OR IGNORE INTO learning_relations(id,framework_id,source_skill_id,relation_type,target_skill_id,metadata_json,created_at)
VALUES('adaptive-growth-two-period','gongkao-learning-v1','growth','prerequisite','two_period',
 '{"basis":"两期比重公式依赖分子与分母增长率","curated":true}',strftime('%Y-%m-%dT%H:%M:%fZ','now'));
CREATE TABLE adaptive_teaching_sessions (
 session_id TEXT PRIMARY KEY REFERENCES sessions(id),
 goal_skill_id TEXT NOT NULL REFERENCES learning_skills(id),
 goal TEXT NOT NULL,
 phase TEXT NOT NULL CHECK(phase IN ('PROBE','PLAN','TEACH_NODE','CHECK','UPDATE','COMPLETE')),
 revision INTEGER NOT NULL DEFAULT 0,
 state_json TEXT NOT NULL CHECK(json_valid(state_json)),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE adaptive_teaching_events (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES adaptive_teaching_sessions(session_id),
 request_id TEXT NOT NULL,
 revision INTEGER NOT NULL,
 phase TEXT NOT NULL,
 attempt_id TEXT REFERENCES attempts(id),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 created_at TEXT NOT NULL,
 UNIQUE(session_id,request_id), UNIQUE(session_id,revision)
);
CREATE INDEX adaptive_events_attempt ON adaptive_teaching_events(attempt_id);
INSERT INTO schema_migrations VALUES(30,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
