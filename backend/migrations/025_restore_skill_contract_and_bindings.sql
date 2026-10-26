PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

-- 1. Drop old triggers that could interfere with table alterations
DROP TRIGGER IF EXISTS trg_qkm_to_question_skill_bindings;
DROP TRIGGER IF EXISTS trg_knowledge_nodes_to_learning_skills;

-- 2. Recreate learning_skills without foreign key to knowledge_nodes
DROP TABLE IF EXISTS learning_skills_old;
ALTER TABLE learning_skills RENAME TO learning_skills_old;

CREATE TABLE learning_skills (
  id TEXT PRIMARY KEY,
  framework_id TEXT NOT NULL DEFAULT 'gongkao-learning-v1',
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
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

INSERT OR REPLACE INTO learning_skills
  (id, framework_id, code, parent_id, knowledge_node_code, name, canonical_name,
   skill_type, description, difficulty_band, mastery_threshold, sort_order,
   status, metadata_json, created_at, updated_at)
SELECT id, 'gongkao-learning-v1', code, NULL, knowledge_node_code, name, name,
       'skill', NULL, 'medium', 0.8, 0, 'active', '{}',
       strftime('%Y-%m-%dT%H:%M:%fZ','now'), strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM (
  SELECT 'analogy' id, 'gongkao.learning.analogy' code, 'gongkao.xingce.reasoning.analogy' knowledge_node_code, '类比概念关系匹配' name UNION ALL
  SELECT 'definition', 'gongkao.learning.definition', 'gongkao.xingce.reasoning.definition', '定义要件匹配' UNION ALL
  SELECT 'graphic_position', 'gongkao.learning.graphic_position', 'gongkao.xingce.reasoning.graphic.position', '图形位置平移旋转' UNION ALL
  SELECT 'growth', 'gongkao.learning.growth', 'gongkao.xingce.data_analysis.growth_rate', '增长率' UNION ALL
  SELECT 'history', 'gongkao.learning.history', 'gongkao.xingce.general.history', '历史人文典故溯源' UNION ALL
  SELECT 'journey', 'gongkao.learning.journey', 'gongkao.xingce.quantitative.journey', '行程与相遇模型' UNION ALL
  SELECT 'law', 'gongkao.learning.law', 'gongkao.xingce.general.law', '法律规则分析与适用' UNION ALL
  SELECT 'logic', 'gongkao.learning.logic', 'gongkao.xingce.reasoning.conditional_logic', '充分条件假言推理' UNION ALL
  SELECT 'logic_fill', 'gongkao.learning.logic_fill', 'gongkao.xingce.verbal.logic_fill', '选词逻辑填空' UNION ALL
  SELECT 'main_idea', 'gongkao.learning.main_idea', 'gongkao.xingce.verbal.main_idea', '主旨主线概括' UNION ALL
  SELECT 'politics', 'gongkao.learning.politics', 'gongkao.xingce.general.politics', '政治政策常识识别' UNION ALL
  SELECT 'profit', 'gongkao.learning.profit', 'gongkao.xingce.quantitative.profit_problem', '经济利润折扣计算' UNION ALL
  SELECT 'scaling', 'gongkao.learning.scaling', 'gongkao.xingce.data_analysis.calculation.scaling', '放缩法速算' UNION ALL
  SELECT 'science', 'gongkao.learning.science', 'gongkao.xingce.general.science', '科技常识分析' UNION ALL
  SELECT 'tail_digit', 'gongkao.learning.tail_digit', 'gongkao.xingce.data_analysis.calculation.tail_digit', '尾数法速算' UNION ALL
  SELECT 'two_period', 'gongkao.learning.two_period', 'gongkao.xingce.data_analysis.proportion.two_period', '两期比重分析' UNION ALL
  SELECT 'work', 'gongkao.learning.work', 'gongkao.xingce.quantitative.work_problem', '工程问题合作效率'
);

-- Preserve any other existing learning skills
INSERT OR IGNORE INTO learning_skills
SELECT * FROM learning_skills_old;

-- 3. Recreate learning_relations with FK to learning_skills(id)
DROP TABLE IF EXISTS learning_relations_old;
ALTER TABLE learning_relations RENAME TO learning_relations_old;

CREATE TABLE learning_relations (
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

INSERT INTO learning_relations
SELECT * FROM learning_relations_old
WHERE source_skill_id IN (SELECT id FROM learning_skills)
  AND target_skill_id IN (SELECT id FROM learning_skills);

DROP TABLE learning_relations_old;

-- 4. Recreate question_skill_bindings with FK to learning_skills(id)
DROP TABLE IF EXISTS question_skill_bindings_old;
ALTER TABLE question_skill_bindings RENAME TO question_skill_bindings_old;

CREATE TABLE question_skill_bindings (
  id TEXT PRIMARY KEY,
  question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
  learning_skill_id TEXT REFERENCES learning_skills(id) ON DELETE CASCADE,
  knowledge_node_code TEXT,
  role TEXT NOT NULL DEFAULT 'primary' CHECK(role IN ('primary', 'secondary', 'supporting')),
  weight REAL NOT NULL DEFAULT 1.0 CHECK(weight > 0),
  provenance TEXT NOT NULL DEFAULT 'migrated',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'needs_review')),
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  created_at TEXT NOT NULL,
  UNIQUE(question_id, learning_skill_id, role)
);

-- Partial unique index strictly guaranteeing single active primary binding per question
CREATE UNIQUE INDEX IF NOT EXISTS uq_qsb_single_active_primary
ON question_skill_bindings(question_id)
WHERE role = 'primary' AND status = 'active';

-- 4. Recreate error_skill_bindings with FK to learning_skills(id)
DROP TABLE IF EXISTS error_skill_bindings_old;
ALTER TABLE error_skill_bindings RENAME TO error_skill_bindings_old;

CREATE TABLE error_skill_bindings (
  id TEXT PRIMARY KEY,
  error_event_id TEXT NOT NULL REFERENCES error_events(id) ON DELETE CASCADE,
  learning_skill_id TEXT REFERENCES learning_skills(id) ON DELETE CASCADE,
  knowledge_node_code TEXT,
  role TEXT NOT NULL DEFAULT 'primary' CHECK(role IN ('primary', 'contributing', 'prerequisite_gap')),
  weight REAL NOT NULL DEFAULT 1.0 CHECK(weight > 0),
  provenance TEXT NOT NULL DEFAULT 'deterministic',
  confidence REAL DEFAULT 1.0 CHECK(confidence BETWEEN 0 AND 1),
  created_at TEXT NOT NULL,
  UNIQUE(error_event_id, learning_skill_id, role)
);

-- 5. Recreate error_overlay with FK to learning_skills(id)
DROP TABLE IF EXISTS error_overlay;
CREATE TABLE error_overlay (
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

-- 6. Recreate learning_stages with FK to learning_skills(id)
DROP TABLE IF EXISTS learning_stages;
CREATE TABLE learning_stages (
  learning_skill_id TEXT PRIMARY KEY REFERENCES learning_skills(id) ON DELETE CASCADE,
  stage TEXT NOT NULL CHECK(stage IN ('UNSEEN','INTRODUCED','GUIDED_PRACTICE','INDEPENDENT_PRACTICE','MASTERED','MAINTENANCE')),
  mastery_score REAL NOT NULL DEFAULT 0.0,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  accuracy REAL DEFAULT 0.0,
  hint_dependency REAL DEFAULT 0.0,
  review_count INTEGER NOT NULL DEFAULT 0,
  last_updated_at TEXT NOT NULL
);

-- 7. Recreate learning_objectives with FK to learning_skills(id)
DROP TABLE IF EXISTS learning_objectives_old;
ALTER TABLE learning_objectives RENAME TO learning_objectives_old;
CREATE TABLE learning_objectives (
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
INSERT INTO learning_objectives SELECT * FROM learning_objectives_old
WHERE learning_skill_id IN (SELECT id FROM learning_skills);
DROP TABLE learning_objectives_old;

-- 8. Accurate Semantic Classification (Zero blind bulk-mapping)

-- A. Analogy (类比推理)
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'analogy', 'gongkao.xingce.reasoning.analogy', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '类比推理';

UPDATE question_knowledge_map
SET knowledge_node_id = 'analogy'
WHERE question_id IN (SELECT id FROM questions WHERE module = '类比推理');

-- B. Definition (定义判断)
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'definition', 'gongkao.xingce.reasoning.definition', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '定义判断';

UPDATE question_knowledge_map
SET knowledge_node_id = 'definition'
WHERE question_id IN (SELECT id FROM questions WHERE module = '定义判断');

-- C. Logic (逻辑判断) - Only conditional & deductive logic; other marked needs_review
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'logic', 'gongkao.xingce.reasoning.conditional_logic', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module = '逻辑判断'
  AND (
    q.explanation LIKE '%充分条件%' OR q.explanation LIKE '%必要条件%' OR q.explanation LIKE '%假言%'
    OR q.explanation LIKE '%充要%' OR q.explanation LIKE '%逆否%' OR q.explanation LIKE '%命题推理%'
    OR q.explanation LIKE '%真假推理%' OR q.explanation LIKE '%复言命题%'
    OR q.stem LIKE '%充分条件%' OR q.stem LIKE '%必要条件%' OR q.stem LIKE '%如果……那么%' OR q.stem LIKE '%只有……才%'
  );

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, NULL, 'gongkao.xingce.reasoning.logic', 'primary', 1.0, 'migrated', 'needs_review', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module = '逻辑判断'
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary');

UPDATE question_knowledge_map
SET knowledge_node_id = 'logic'
WHERE question_id IN (SELECT id FROM questions WHERE module = '逻辑判断');

-- D. Graphic (图形推理) - Only translation/rotation/movement; other marked needs_review
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'graphic_position', 'gongkao.xingce.reasoning.graphic.position', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module = '图形推理'
  AND (
    q.explanation LIKE '%平移%' OR q.explanation LIKE '%旋转%' OR q.explanation LIKE '%翻转%'
    OR q.explanation LIKE '%位置规律%' OR q.explanation LIKE '%顺时针%' OR q.explanation LIKE '%逆时针%'
  );

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, NULL, 'gongkao.xingce.reasoning.graphic', 'primary', 1.0, 'migrated', 'needs_review', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module = '图形推理'
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary');

-- E. Verbal (言语理解)
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'logic_fill', 'gongkao.xingce.verbal.logic_fill', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module IN ('言语理解', '言语理解与表达')
  AND (
    q.explanation LIKE '%选词%' OR q.explanation LIKE '%逻辑填空%' OR q.stem LIKE '%依次填入%'
    OR q.explanation LIKE '%第一空%' OR q.explanation LIKE '%第二空%'
  );

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'main_idea', 'gongkao.xingce.verbal.main_idea', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module IN ('言语理解', '言语理解与表达')
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary')
  AND (
    q.explanation LIKE '%中心理解%' OR q.explanation LIKE '%主旨概括%' OR q.explanation LIKE '%主旨大意%'
    OR q.explanation LIKE '%态度观点%' OR q.stem LIKE '%意在说明%' OR q.stem LIKE '%主要表明%'
    OR q.stem LIKE '%核心观点%' OR q.stem LIKE '%主旨%'
  );

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, NULL, 'gongkao.xingce.verbal', 'primary', 1.0, 'migrated', 'needs_review', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module IN ('言语理解', '言语理解与表达')
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary');

-- F. General (常识判断) - Explicit law, history, science, politics; NEVER default to politics
-- 1) Law
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'law', 'gongkao.xingce.general.law', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module = '常识判断'
  AND (
    q.explanation LIKE '%法律%' OR q.explanation LIKE '%宪法%' OR q.explanation LIKE '%刑法%'
    OR q.explanation LIKE '%民法%' OR q.explanation LIKE '%行政%' OR q.explanation LIKE '%诉讼%'
    OR q.explanation LIKE '%法条%' OR q.explanation LIKE '%法规%' OR q.explanation LIKE '%司法%'
    OR q.stem LIKE '%法律%' OR q.stem LIKE '%民法典%' OR q.stem LIKE '%刑法%' OR q.stem LIKE '%宪法%'
    OR q.stem LIKE '%行政处罚%' OR q.stem LIKE '%诉讼法%' OR q.stem LIKE '%合法%' OR q.stem LIKE '%违法%'
  );

-- 2) History
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'history', 'gongkao.xingce.general.history', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module = '常识判断'
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary')
  AND (
    q.explanation LIKE '%历史%' OR q.explanation LIKE '%人文%' OR q.explanation LIKE '%朝代%'
    OR q.explanation LIKE '%诗词%' OR q.explanation LIKE '%古文%' OR q.explanation LIKE '%典故%'
    OR q.stem LIKE '%朝代%' OR q.stem LIKE '%皇帝%' OR q.stem LIKE '%诗句%' OR q.stem LIKE '%史记%'
    OR q.stem LIKE '%唐代%' OR q.stem LIKE '%宋代%' OR q.stem LIKE '%战国%' OR q.stem LIKE '%文学常识%'
  );

-- 3) Science
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'science', 'gongkao.xingce.general.science', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module = '常识判断'
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary')
  AND (
    q.explanation LIKE '%科技%' OR q.explanation LIKE '%物理%' OR q.explanation LIKE '%化学%'
    OR q.explanation LIKE '%生物%' OR q.explanation LIKE '%地理%' OR q.explanation LIKE '%天文%'
    OR q.stem LIKE '%物理常识%' OR q.stem LIKE '%化学常识%' OR q.stem LIKE '%生物常识%' OR q.stem LIKE '%地理常识%'
    OR q.stem LIKE '%行星%' OR q.stem LIKE '%维生素%' OR q.stem LIKE '%光合作用%' OR q.stem LIKE '%热胀冷缩%'
  );

-- 4) Politics
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'politics', 'gongkao.xingce.general.politics', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module = '常识判断'
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary')
  AND (
    q.explanation LIKE '%时政%' OR q.explanation LIKE '%党建%' OR q.explanation LIKE '%政治%'
    OR q.explanation LIKE '%二十大%' OR q.explanation LIKE '%十九大%' OR q.explanation LIKE '%重要会议%'
    OR q.stem LIKE '%习近平%' OR q.stem LIKE '%新时代%' OR q.stem LIKE '%党的二十大%'
    OR q.stem LIKE '%政府工作报告%' OR q.stem LIKE '%中央经济工作会议%' OR q.stem LIKE '%中国共产党%'
  );

-- 5) Unmapped common knowledge -> needs_review
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, NULL, 'gongkao.xingce.general', 'primary', 1.0, 'migrated', 'needs_review', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.module = '常识判断'
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary');

-- G. Quantitative (数量关系)
UPDATE question_knowledge_map
SET knowledge_node_id = 'quantitative'
WHERE question_id IN (SELECT id FROM questions WHERE module = '数量关系') AND knowledge_node_id = 'verbal';

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'work', 'gongkao.xingce.quantitative.work_problem', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '数量关系' AND (q.explanation LIKE '%工程问题%' OR q.stem LIKE '%工程问题%' OR q.explanation LIKE '%合作完工%');

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'journey', 'gongkao.xingce.quantitative.journey', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '数量关系' AND (q.explanation LIKE '%行程问题%' OR q.stem LIKE '%行程问题%');

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'profit', 'gongkao.xingce.quantitative.profit_problem', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '数量关系' AND (q.explanation LIKE '%经济利润%' OR q.stem LIKE '%经济利润%');

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, NULL, 'gongkao.xingce.quantitative', 'primary', 1.0, 'migrated', 'needs_review', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '数量关系'
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary');

-- H. Data Analysis (资料分析)
INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'two_period', 'gongkao.xingce.data_analysis.proportion.two_period', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '资料分析' AND (q.explanation LIKE '%两期比重%' OR q.explanation LIKE '%比重类%' OR q.explanation LIKE '%基期比重%');

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'tail_digit', 'gongkao.xingce.data_analysis.calculation.tail_digit', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '资料分析' AND (q.explanation LIKE '%尾数法%' OR q.stem LIKE '%尾数法%');

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'scaling', 'gongkao.xingce.data_analysis.calculation.scaling', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '资料分析' AND (q.explanation LIKE '%放缩法%' OR q.stem LIKE '%放缩法%');

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, 'growth', 'gongkao.xingce.data_analysis.growth_rate', 'primary', 1.0, 'migrated', 'active', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '资料分析'
  AND (q.explanation LIKE '%增长率%' OR q.explanation LIKE '%增长量%' OR q.explanation LIKE '%ABRX%' OR q.explanation LIKE '%比较类%')
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary');

INSERT OR REPLACE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id, NULL, 'gongkao.xingce.data_analysis', 'primary', 1.0, 'migrated', 'needs_review', '{}', strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q WHERE q.module = '资料分析'
  AND q.id NOT IN (SELECT question_id FROM question_skill_bindings WHERE role='primary');

-- I. Preserve existing valid bindings, secondary/supporting roles, and unmapped bindings with trace
INSERT OR IGNORE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT
  old.id,
  old.question_id,
  CASE
    WHEN old.learning_skill_id IN (SELECT id FROM learning_skills) THEN old.learning_skill_id
    ELSE NULL
  END,
  old.knowledge_node_code,
  CASE
    WHEN old.role = 'primary' AND EXISTS (
      SELECT 1 FROM question_skill_bindings cur WHERE cur.question_id = old.question_id AND cur.role = 'primary'
    ) THEN 'supporting'
    ELSE old.role
  END,
  old.weight,
  old.provenance,
  CASE
    WHEN old.learning_skill_id IN (SELECT id FROM learning_skills) THEN old.status
    ELSE 'needs_review'
  END,
  CASE
    WHEN old.learning_skill_id IN (SELECT id FROM learning_skills) THEN old.metadata_json
    ELSE json_set(old.metadata_json, '$.original_learning_skill_id', old.learning_skill_id)
  END,
  old.created_at
FROM question_skill_bindings_old old
WHERE NOT (
  -- Avoid inserting duplicate (question_id, learning_skill_id, role)
  EXISTS (
    SELECT 1 FROM question_skill_bindings cur
    WHERE cur.question_id = old.question_id
      AND cur.learning_skill_id = old.learning_skill_id
      AND cur.role = old.role
  )
  OR (
    -- Do not resurrect cross-module errors as secondary bindings (already traced in metadata)
    EXISTS (
      SELECT 1 FROM question_skill_bindings cur
      JOIN questions q ON q.id = cur.question_id
      WHERE cur.question_id = old.question_id
        AND cur.role = 'primary'
        AND (
          (q.module = '类比推理' AND old.learning_skill_id != 'analogy')
          OR (q.module = '定义判断' AND old.learning_skill_id != 'definition')
          OR (q.module = '常识判断' AND old.learning_skill_id = 'politics' AND cur.learning_skill_id IN ('law', 'history', 'science'))
        )
    )
  )
);

DROP TABLE question_skill_bindings_old;

-- 9. Restore error_skill_bindings
INSERT OR REPLACE INTO error_skill_bindings
  (id, error_event_id, learning_skill_id, knowledge_node_code, role, weight, provenance, confidence, created_at)
SELECT id, error_event_id,
       CASE
         WHEN learning_skill_id = 'quant_work_cooperation' THEN 'work'
         WHEN learning_skill_id = 'da_rate_general' THEN 'growth'
         WHEN learning_skill_id = 'verbal_logic_fill' THEN 'logic_fill'
         WHEN learning_skill_id = 'quantitative' AND error_event_id LIKE '%e7d5771d%' THEN 'journey'
         ELSE learning_skill_id
       END,
       knowledge_node_code, role, weight, provenance, confidence, created_at
FROM error_skill_bindings_old
WHERE learning_skill_id IN ('analogy','definition','graphic_position','growth','history','journey','law','logic','logic_fill','main_idea','politics','profit','scaling','science','tail_digit','two_period','work')
   OR learning_skill_id IN ('quant_work_cooperation', 'da_rate_general', 'verbal_logic_fill')
   OR (learning_skill_id = 'quantitative' AND error_event_id LIKE '%e7d5771d%');

DROP TABLE error_skill_bindings_old;
DROP TABLE IF EXISTS learning_skills_old;

-- 10. Recreate LF1 trigger on question_knowledge_map
CREATE TRIGGER IF NOT EXISTS trg_qkm_to_question_skill_bindings
AFTER INSERT ON question_knowledge_map
FOR EACH ROW
BEGIN
  INSERT OR IGNORE INTO question_skill_bindings (
    id, question_id, learning_skill_id, knowledge_node_code, role, weight,
    provenance, status, metadata_json, created_at
  )
  SELECT
    'qsb_' || NEW.question_id || '_' || ls.id || '_primary',
    NEW.question_id,
    ls.id,
    ls.knowledge_node_code,
    'primary',
    NEW.weight,
    'migrated',
    'active',
    '{}',
    strftime('%Y-%m-%dT%H:%M:%fZ','now')
  FROM learning_skills ls
  WHERE ls.id = NEW.knowledge_node_id;
END;

INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (25, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
PRAGMA foreign_keys=ON;
