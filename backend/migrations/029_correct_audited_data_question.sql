-- Individually verified by options and statistical explanation in the embedded
-- teacher audit: this question compares quarterly production, not conditional logic.
-- Preserve answers, attempts, explanations and mastery; do not invent a fine skill.
BEGIN IMMEDIATE;
UPDATE questions SET module = '资料分析'
WHERE id = 'js-2019-c-q115' AND module = '逻辑判断'
  AND options_json LIKE '%乙烯%' AND options_json LIKE '%季度%';

UPDATE question_skill_bindings
SET learning_skill_id = NULL, knowledge_node_code = 'gongkao.xingce.data_analysis',
    status = 'needs_review', provenance = 'migrated',
    metadata_json = json_set(metadata_json, '$.module_corrected_by', 'migration_029')
WHERE question_id = 'js-2019-c-q115' AND role = 'primary'
  AND EXISTS (SELECT 1 FROM questions WHERE id = question_id AND module = '资料分析');

UPDATE question_skill_bindings SET status = 'inactive',
    metadata_json = json_set(metadata_json, '$.module_corrected_by', 'migration_029')
WHERE question_id = 'js-2019-c-q115' AND role <> 'primary'
  AND knowledge_node_code LIKE 'gongkao.xingce.reasoning.%'
  AND EXISTS (SELECT 1 FROM questions WHERE id = question_id AND module = '资料分析');

DELETE FROM question_knowledge_map
WHERE question_id = 'js-2019-c-q115'
  AND EXISTS (SELECT 1 FROM questions WHERE id = question_id AND module = '资料分析')
  AND knowledge_node_id IN (SELECT id FROM knowledge_nodes WHERE knowledge_node_code LIKE 'gongkao.xingce.reasoning.%' OR id = 'logic');

INSERT OR IGNORE INTO question_knowledge_map (question_id, knowledge_node_id, weight)
SELECT q.id, n.id, 1.0 FROM questions q JOIN knowledge_nodes n ON n.id = 'data_analysis'
WHERE q.id = 'js-2019-c-q115' AND q.module = '资料分析';

INSERT OR IGNORE INTO schema_migrations VALUES (29, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
