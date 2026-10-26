BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge_nodes (
 id TEXT PRIMARY KEY, parent_id TEXT REFERENCES knowledge_nodes(id),
 subject TEXT NOT NULL, module TEXT NOT NULL, name TEXT NOT NULL, node_type TEXT NOT NULL,
 weight REAL NOT NULL CHECK(weight > 0), exam_priority REAL NOT NULL CHECK(exam_priority >= 0)
);
CREATE TABLE IF NOT EXISTS questions (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, year INTEGER, exam_type TEXT NOT NULL,
 subject TEXT NOT NULL CHECK(subject = '行测'), module TEXT NOT NULL, stem TEXT NOT NULL,
 options_json TEXT NOT NULL CHECK(json_valid(options_json)),
 difficulty REAL NOT NULL CHECK(difficulty BETWEEN 0 AND 1),
 answer TEXT NOT NULL CHECK(answer IN ('A','B','C','D')), explanation TEXT NOT NULL,
 estimated_seconds INTEGER NOT NULL CHECK(estimated_seconds > 0),
 is_verified INTEGER NOT NULL CHECK(is_verified IN (0,1))
);
CREATE TABLE IF NOT EXISTS question_knowledge_map (
 question_id TEXT NOT NULL REFERENCES questions(id), knowledge_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id),
 weight REAL NOT NULL CHECK(weight > 0), PRIMARY KEY(question_id,knowledge_node_id)
);
CREATE TABLE IF NOT EXISTS sessions (
 id TEXT PRIMARY KEY, mode TEXT NOT NULL DEFAULT 'PRACTICE' CHECK(mode = 'PRACTICE'),
 started_at TEXT NOT NULL, completed_at TEXT,
 status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','completed'))
);
CREATE TABLE IF NOT EXISTS session_questions (
 session_id TEXT NOT NULL REFERENCES sessions(id), question_id TEXT NOT NULL REFERENCES questions(id),
 position INTEGER NOT NULL CHECK(position >= 0),
 PRIMARY KEY(session_id,question_id), UNIQUE(session_id,position)
);
CREATE TABLE IF NOT EXISTS attempts (
 id TEXT PRIMARY KEY, question_id TEXT NOT NULL, session_id TEXT NOT NULL,
 started_at TEXT NOT NULL, submitted_at TEXT, elapsed_ms INTEGER CHECK(elapsed_ms >= 0),
 selected_answer TEXT CHECK(selected_answer IN ('A','B','C','D')), correct INTEGER CHECK(correct IN (0,1)),
 confidence REAL CHECK(confidence IN (0.2,0.4,0.6,0.8,1.0)),
 hint_level INTEGER NOT NULL DEFAULT 0 CHECK(hint_level = 0),
 attempt_number INTEGER NOT NULL DEFAULT 1 CHECK(attempt_number = 1),
 changed_answer INTEGER NOT NULL DEFAULT 0 CHECK(changed_answer IN (0,1)),
 mode TEXT NOT NULL DEFAULT 'PRACTICE' CHECK(mode = 'PRACTICE'),
 FOREIGN KEY(session_id,question_id) REFERENCES session_questions(session_id,question_id),
 UNIQUE(session_id,question_id),
 CHECK((submitted_at IS NULL AND selected_answer IS NULL AND correct IS NULL AND confidence IS NULL AND elapsed_ms IS NULL)
 OR (submitted_at IS NOT NULL AND selected_answer IS NOT NULL AND correct IS NOT NULL AND confidence IS NOT NULL AND elapsed_ms IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_attempt ON attempts(session_id) WHERE submitted_at IS NULL;
INSERT OR IGNORE INTO schema_migrations VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
