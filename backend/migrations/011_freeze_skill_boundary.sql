PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

-- Knowledge nodes and trainable skills have separate ownership boundaries.
-- Importing or otherwise creating a new knowledge node must not expand LF1.
DROP TRIGGER IF EXISTS trg_knowledge_nodes_to_learning_skills;
DROP TRIGGER IF EXISTS trg_qkm_to_question_skill_bindings;

-- Freeze the 17 approved LF1 skills explicitly so a fresh database has the
-- same framework without relying on runtime inference from knowledge nodes.
INSERT OR IGNORE INTO knowledge_nodes
  (id, parent_id, subject, module, name, node_type, weight, exam_priority)
VALUES
  ('analogy', NULL, '行测', '判断推理', '类比概念关系匹配', 'skill', 1.0, 1.0),
  ('definition', NULL, '行测', '判断推理', '定义要件匹配', 'skill', 1.0, 1.0),
  ('graphic_position', NULL, '行测', '判断推理', '图形位置平移旋转', 'skill', 1.0, 1.0),
  ('growth', NULL, '行测', '资料分析', '增长率', 'skill', 1.0, 1.0),
  ('history', NULL, '行测', '常识判断', '历史人文典故溯源', 'skill', 1.0, 1.0),
  ('journey', NULL, '行测', '数量关系', '行程与相遇模型', 'skill', 1.0, 1.0),
  ('law', NULL, '行测', '常识判断', '法律规则分析与适用', 'skill', 1.0, 1.0),
  ('logic', NULL, '行测', '判断推理', '充分条件推理', 'skill', 1.0, 1.0),
  ('logic_fill', NULL, '行测', '言语理解与表达', '选词逻辑填空', 'skill', 1.0, 1.0),
  ('main_idea', NULL, '行测', '言语理解与表达', '主旨主线概括', 'skill', 1.0, 1.0),
  ('politics', NULL, '行测', '常识判断', '政治政策常识识别', 'skill', 1.0, 1.0),
  ('profit', NULL, '行测', '数量关系', '经济利润折扣计算', 'skill', 1.0, 1.0),
  ('scaling', NULL, '行测', '资料分析', '放缩法速算', 'skill', 1.0, 1.0),
  ('science', NULL, '行测', '常识判断', '科技常识分析', 'skill', 1.0, 1.0),
  ('tail_digit', NULL, '行测', '资料分析', '尾数法速算', 'skill', 1.0, 1.0),
  ('two_period', NULL, '行测', '资料分析', '两期比重分析', 'skill', 1.0, 1.0),
  ('work', NULL, '行测', '数量关系', '工程问题', 'skill', 1.0, 1.0);

INSERT OR IGNORE INTO learning_skills
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

-- Legacy question maps may still be written by core learning flows. Mirror a
-- binding only when that node is already an approved LearningSkill.
CREATE TRIGGER trg_qkm_to_question_skill_bindings
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

INSERT INTO schema_migrations VALUES (11, strftime('%Y-%m-%dT%H:%M:%fZ','now'));

COMMIT;
PRAGMA foreign_keys=ON;
