-- 044: 六题语义与原图复核后的知识树关联；保留题目内容、技能与学习记录。
BEGIN IMMEDIATE;
INSERT OR IGNORE INTO question_knowledge_map SELECT 'js-2022-a-q065','quant_permutation',1 FROM questions WHERE id='js-2022-a-q065' AND EXISTS(SELECT 1 FROM knowledge_nodes WHERE id='quant_permutation');
INSERT OR IGNORE INTO question_knowledge_map SELECT 'js-2022-a-q066','quant_competition',1 FROM questions WHERE id='js-2022-a-q066' AND EXISTS(SELECT 1 FROM knowledge_nodes WHERE id='quant_competition');
INSERT OR IGNORE INTO question_knowledge_map SELECT 'js-2022-a-q067','quant_geometry',1 FROM questions WHERE id='js-2022-a-q067' AND EXISTS(SELECT 1 FROM knowledge_nodes WHERE id='quant_geometry');
INSERT OR IGNORE INTO question_knowledge_map SELECT 'js-2022-b-q060','quant_geometry',1 FROM questions WHERE id='js-2022-b-q060' AND EXISTS(SELECT 1 FROM knowledge_nodes WHERE id='quant_geometry');
INSERT OR IGNORE INTO question_knowledge_map SELECT 'js-2022-b-q062','quant_geometry',1 FROM questions WHERE id='js-2022-b-q062' AND EXISTS(SELECT 1 FROM knowledge_nodes WHERE id='quant_geometry');
INSERT OR IGNORE INTO question_knowledge_map SELECT 'js-2022-b-q065','quant_geometry',1 FROM questions WHERE id='js-2022-b-q065' AND EXISTS(SELECT 1 FROM knowledge_nodes WHERE id='quant_geometry');
INSERT OR IGNORE INTO schema_migrations VALUES(44,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
