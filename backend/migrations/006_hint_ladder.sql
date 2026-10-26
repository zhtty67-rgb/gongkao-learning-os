PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

CREATE TABLE attempts_new (
 id TEXT PRIMARY KEY,
 question_id TEXT NOT NULL,
 session_id TEXT NOT NULL,
 started_at TEXT NOT NULL,
 submitted_at TEXT,
 elapsed_ms INTEGER CHECK(elapsed_ms >= 0),
 selected_answer TEXT CHECK(selected_answer IN ('A','B','C','D')),
 correct INTEGER CHECK(correct IN (0,1)),
 confidence REAL CHECK(confidence IN (0.2,0.4,0.6,0.8,1.0)),
 hint_level INTEGER NOT NULL DEFAULT 0 CHECK(hint_level IN (0,1,2,3,4)),
 attempt_number INTEGER NOT NULL DEFAULT 1 CHECK(attempt_number = 1),
 changed_answer INTEGER NOT NULL DEFAULT 0 CHECK(changed_answer IN (0,1)),
 mode TEXT NOT NULL DEFAULT 'PRACTICE' CHECK(mode IN ('PRACTICE','REVIEW')),
 FOREIGN KEY(session_id,question_id) REFERENCES session_questions(session_id,question_id),
 UNIQUE(session_id,question_id),
 CHECK((submitted_at IS NULL AND selected_answer IS NULL AND correct IS NULL AND confidence IS NULL AND elapsed_ms IS NULL)
 OR (submitted_at IS NOT NULL AND selected_answer IS NOT NULL AND correct IS NOT NULL AND confidence IS NOT NULL AND elapsed_ms IS NOT NULL))
);

INSERT INTO attempts_new
 SELECT id,question_id,session_id,started_at,submitted_at,elapsed_ms,selected_answer,
        correct,confidence,hint_level,attempt_number,changed_answer,mode
 FROM attempts;

DROP TABLE attempts;
ALTER TABLE attempts_new RENAME TO attempts;

CREATE UNIQUE INDEX one_pending_attempt ON attempts(session_id) WHERE submitted_at IS NULL;

-- Also reconstruct mastery_evidence to permit Level 4 zero success evidence (0, 0)
CREATE TABLE mastery_evidence_new (
 attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
 knowledge_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
 success_evidence REAL NOT NULL CHECK(success_evidence >= 0),
 failure_evidence REAL NOT NULL CHECK(failure_evidence >= 0),
 time_ratio REAL NOT NULL CHECK(time_ratio >= 0),
 timed INTEGER NOT NULL CHECK(timed IN (0,1)),
 created_at TEXT NOT NULL,
 PRIMARY KEY(attempt_id, knowledge_node_id),
 CHECK((success_evidence > 0 AND failure_evidence = 0)
    OR (failure_evidence > 0 AND success_evidence = 0)
    OR (success_evidence = 0 AND failure_evidence = 0))
);

INSERT INTO mastery_evidence_new SELECT * FROM mastery_evidence;
DROP TABLE mastery_evidence;
ALTER TABLE mastery_evidence_new RENAME TO mastery_evidence;

INSERT INTO schema_migrations VALUES (6, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
PRAGMA foreign_keys=ON;
