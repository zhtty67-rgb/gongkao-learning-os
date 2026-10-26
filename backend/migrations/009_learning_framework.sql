PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

-- 1. Create learning_frameworks table
CREATE TABLE IF NOT EXISTS learning_frameworks (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT,
  version TEXT NOT NULL DEFAULT '1',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived')),
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Seed default learning framework
INSERT OR IGNORE INTO learning_frameworks (id, code, name, description, version, status, metadata_json, created_at, updated_at)
VALUES (
  'gongkao-learning-v1',
  'gongkao-learning-v1',
  '公考核心学习框架',
  '公务员录用考试行测与申论学习技能框架',
  '1.0',
  'active',
  '{"domain":"gongkao"}',
  strftime('%Y-%m-%dT%H:%M:%fZ','now'),
  strftime('%Y-%m-%dT%H:%M:%fZ','now')
);

-- 2. Create learning_skills table (The single authoritative LearningSkill entity)
CREATE TABLE IF NOT EXISTS learning_skills (
  id TEXT PRIMARY KEY REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
  framework_id TEXT NOT NULL REFERENCES learning_frameworks(id) ON DELETE CASCADE,
  code TEXT NOT NULL UNIQUE,
  parent_id TEXT REFERENCES learning_skills(id) ON DELETE CASCADE,
  knowledge_node_code TEXT,
  name TEXT NOT NULL,
  canonical_name TEXT,
  skill_type TEXT NOT NULL DEFAULT 'skill',
  description TEXT,
  difficulty_band TEXT NOT NULL DEFAULT 'medium',
  mastery_threshold REAL NOT NULL DEFAULT 0.8,
  sort_order INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'active',
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Trigger to automatically populate learning_skills when a knowledge_node is inserted
CREATE TRIGGER IF NOT EXISTS trg_knowledge_nodes_to_learning_skills
AFTER INSERT ON knowledge_nodes
FOR EACH ROW
BEGIN
  INSERT OR IGNORE INTO learning_skills (
    id, framework_id, code, parent_id, knowledge_node_code,
    name, canonical_name, skill_type, description, difficulty_band,
    mastery_threshold, sort_order, status, metadata_json, created_at, updated_at
  )
  VALUES (
    NEW.id,
    'gongkao-learning-v1',
    'gongkao.learning.' || NEW.id,
    NEW.parent_id,
    CASE
      WHEN NEW.id = 'growth' THEN 'gongkao.xingce.data_analysis.growth_rate'
      WHEN NEW.id = 'logic' THEN 'gongkao.xingce.reasoning.conditional_logic'
      WHEN NEW.id = 'work' THEN 'gongkao.xingce.quantitative.work_problem'
      ELSE 'gongkao.xingce.' || NEW.id
    END,
    NEW.name,
    NEW.name,
    NEW.node_type,
    NULL,
    'medium',
    0.8,
    0,
    'active',
    '{}',
    strftime('%Y-%m-%dT%H:%M:%fZ','now'),
    strftime('%Y-%m-%dT%H:%M:%fZ','now')
  );
END;

-- Backfill existing knowledge_nodes into learning_skills
INSERT OR IGNORE INTO learning_skills (
  id, framework_id, code, parent_id, knowledge_node_code,
  name, canonical_name, skill_type, description, difficulty_band,
  mastery_threshold, sort_order, status, metadata_json, created_at, updated_at
)
SELECT kn.id,
       'gongkao-learning-v1',
       'gongkao.learning.' || kn.id,
       kn.parent_id,
       CASE
         WHEN kn.id = 'growth' THEN 'gongkao.xingce.data_analysis.growth_rate'
         WHEN kn.id = 'logic' THEN 'gongkao.xingce.reasoning.conditional_logic'
         WHEN kn.id = 'work' THEN 'gongkao.xingce.quantitative.work_problem'
         ELSE 'gongkao.xingce.' || kn.id
       END,
       kn.name,
       kn.name,
       kn.node_type,
       NULL,
       'medium',
       0.8,
       0,
       'active',
       '{}',
       strftime('%Y-%m-%dT%H:%M:%fZ','now'),
       strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM knowledge_nodes kn;

-- 3. Create learning_objectives table
CREATE TABLE IF NOT EXISTS learning_objectives (
  id TEXT PRIMARY KEY,
  learning_skill_id TEXT NOT NULL REFERENCES learning_skills(id) ON DELETE CASCADE,
  code TEXT NOT NULL UNIQUE,
  description TEXT NOT NULL,
  objective_type TEXT NOT NULL DEFAULT 'mastery' CHECK(objective_type IN ('mastery', 'accuracy', 'speed', 'independence')),
  target_value REAL NOT NULL DEFAULT 0.8,
  sort_order INTEGER NOT NULL DEFAULT 0,
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  created_at TEXT NOT NULL
);

-- 4. Create learning_relations table (pedagogic relations between skills)
CREATE TABLE IF NOT EXISTS learning_relations (
  id TEXT PRIMARY KEY,
  framework_id TEXT NOT NULL REFERENCES learning_frameworks(id) ON DELETE CASCADE,
  source_skill_id TEXT NOT NULL REFERENCES learning_skills(id) ON DELETE CASCADE,
  relation_type TEXT NOT NULL CHECK(relation_type IN ('prerequisite', 'recommended_next', 'remediation', 'reinforces', 'alternative_path')),
  target_skill_id TEXT NOT NULL REFERENCES learning_skills(id) ON DELETE CASCADE,
  weight REAL NOT NULL DEFAULT 1.0 CHECK(weight > 0),
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  created_at TEXT NOT NULL,
  UNIQUE(framework_id, source_skill_id, relation_type, target_skill_id)
);

-- 5. Create question_skill_bindings table (multi-skill per question)
CREATE TABLE IF NOT EXISTS question_skill_bindings (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  learning_skill_id TEXT NOT NULL REFERENCES learning_skills(id) ON DELETE CASCADE,
  knowledge_node_code TEXT,
  role TEXT NOT NULL DEFAULT 'primary' CHECK(role IN ('primary', 'secondary', 'supporting')),
  weight REAL NOT NULL DEFAULT 1.0 CHECK(weight > 0),
  provenance TEXT NOT NULL DEFAULT 'migrated',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'needs_review')),
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  created_at TEXT NOT NULL,
  UNIQUE(question_id, learning_skill_id, role)
);

-- Trigger to automatically populate question_skill_bindings when question_knowledge_map is inserted
CREATE TRIGGER IF NOT EXISTS trg_qkm_to_question_skill_bindings
AFTER INSERT ON question_knowledge_map
FOR EACH ROW
BEGIN
  INSERT OR IGNORE INTO question_skill_bindings (
    id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at
  )
  VALUES (
    'qsb_' || NEW.question_id || '_' || NEW.knowledge_node_id || '_primary',
    NEW.question_id,
    NEW.knowledge_node_id,
    (SELECT knowledge_node_code FROM learning_skills WHERE id = NEW.knowledge_node_id),
    'primary',
    NEW.weight,
    'migrated',
    'active',
    '{}',
    strftime('%Y-%m-%dT%H:%M:%fZ','now')
  );
END;

-- Backfill question_skill_bindings from existing question_knowledge_map
INSERT OR IGNORE INTO question_skill_bindings (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || qkm.question_id || '_' || qkm.knowledge_node_id || '_primary',
       qkm.question_id,
       qkm.knowledge_node_id,
       ls.knowledge_node_code,
       'primary',
       qkm.weight,
       'migrated',
       'active',
       '{}',
       strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM question_knowledge_map qkm
LEFT JOIN learning_skills ls ON ls.id = qkm.knowledge_node_id;

-- 6. Reconstruct error_events with fixed error taxonomy, diagnosis source, and status
CREATE TABLE IF NOT EXISTS error_events_new (
  id TEXT PRIMARY KEY,
  attempt_id TEXT NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
  question_id TEXT REFERENCES questions(id) ON DELETE CASCADE,
  error_type TEXT NOT NULL CHECK(error_type IN (
    'knowledge_gap','concept_confusion','formula_selection','calculation_error',
    'condition_misread','reasoning_error','option_trap','time_pressure',
    'careless_error','uncertain_guess',
    'conceptual_error','method_selection','reading_error','transfer_failure','unknown'
  )),
  error_subtype TEXT,
  diagnosis_source TEXT NOT NULL DEFAULT 'deterministic' CHECK(diagnosis_source IN ('deterministic','assessor','user_confirmed','imported')),
  diagnosis_confidence REAL CHECK(diagnosis_confidence BETWEEN 0 AND 1),
  severity REAL DEFAULT 1.0,
  status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','improving','resolved','recurred')),
  explanation TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT 'USER' CHECK(source IN ('USER', 'ASSESSOR', 'SYSTEM')),
  ai_confidence REAL CHECK(ai_confidence BETWEEN 0 AND 1),
  occurred_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
  resolved_at TEXT,
  supersedes_id TEXT REFERENCES error_events_new(id),
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

-- Migrate existing rows from error_events
INSERT INTO error_events_new (id, attempt_id, question_id, error_type, diagnosis_source, diagnosis_confidence, explanation, source, ai_confidence, occurred_at, created_at)
SELECT e.id,
       e.attempt_id,
       a.question_id,
       e.error_type,
       CASE WHEN e.source = 'USER' THEN 'user_confirmed' ELSE 'assessor' END,
       e.ai_confidence,
       e.explanation,
       e.source,
       e.ai_confidence,
       e.created_at,
       e.created_at
FROM error_events e
LEFT JOIN attempts a ON a.id = e.attempt_id;

DROP TABLE error_events;
ALTER TABLE error_events_new RENAME TO error_events;

CREATE INDEX IF NOT EXISTS error_events_attempt_created ON error_events(attempt_id, created_at DESC);
CREATE INDEX IF NOT EXISTS error_events_question ON error_events(question_id);
CREATE INDEX IF NOT EXISTS error_events_status ON error_events(status);

-- 7. Create error_skill_bindings table (Actual Error Skill mapping)
CREATE TABLE IF NOT EXISTS error_skill_bindings (
  id TEXT PRIMARY KEY,
  error_event_id TEXT NOT NULL REFERENCES error_events(id) ON DELETE CASCADE,
  learning_skill_id TEXT NOT NULL REFERENCES learning_skills(id) ON DELETE CASCADE,
  knowledge_node_code TEXT,
  role TEXT NOT NULL DEFAULT 'primary' CHECK(role IN ('primary', 'contributing', 'prerequisite_gap')),
  weight REAL NOT NULL DEFAULT 1.0 CHECK(weight > 0),
  provenance TEXT NOT NULL DEFAULT 'deterministic',
  confidence REAL DEFAULT 1.0 CHECK(confidence BETWEEN 0 AND 1),
  created_at TEXT NOT NULL,
  UNIQUE(error_event_id, learning_skill_id, role)
);

-- Backfill initial error_skill_bindings for existing error_events using question's primary skill
INSERT OR IGNORE INTO error_skill_bindings (id, error_event_id, learning_skill_id, knowledge_node_code, role, weight, provenance, confidence, created_at)
SELECT 'esb_' || ee.id || '_' || qsb.learning_skill_id || '_primary',
       ee.id,
       qsb.learning_skill_id,
       qsb.knowledge_node_code,
       'primary',
       1.0,
       'migrated_default',
       1.0,
       ee.created_at
FROM error_events ee
JOIN question_skill_bindings qsb ON qsb.question_id = ee.question_id AND qsb.role = 'primary';

-- 8. Create error_overlay projection table
CREATE TABLE IF NOT EXISTS error_overlay (
  learning_skill_id TEXT PRIMARY KEY REFERENCES learning_skills(id) ON DELETE CASCADE,
  knowledge_node_code TEXT,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  wrong_count INTEGER NOT NULL DEFAULT 0,
  error_rate REAL NOT NULL DEFAULT 0.0,
  recent_error_count INTEGER NOT NULL DEFAULT 0,
  recurrence_count INTEGER NOT NULL DEFAULT 0,
  high_confidence_error_count INTEGER NOT NULL DEFAULT 0,
  dominant_error_type TEXT,
  open_error_count INTEGER NOT NULL DEFAULT 0,
  resolved_error_count INTEGER NOT NULL DEFAULT 0,
  last_error_at TEXT,
  updated_at TEXT NOT NULL
);

-- 9. Create learning_stages projection table
CREATE TABLE IF NOT EXISTS learning_stages (
  learning_skill_id TEXT PRIMARY KEY REFERENCES learning_skills(id) ON DELETE CASCADE,
  stage TEXT NOT NULL CHECK(stage IN ('UNSEEN','INTRODUCED','GUIDED_PRACTICE','INDEPENDENT_PRACTICE','MASTERED','MAINTENANCE')),
  mastery_score REAL NOT NULL DEFAULT 0.0,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  accuracy REAL DEFAULT 0.0,
  hint_dependency REAL DEFAULT 0.0,
  review_count INTEGER NOT NULL DEFAULT 0,
  last_updated_at TEXT NOT NULL
);

-- Record migration version
INSERT INTO schema_migrations VALUES (9, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
PRAGMA foreign_keys=ON;
