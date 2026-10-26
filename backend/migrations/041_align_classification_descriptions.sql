-- Align descriptions after taxonomy moves; retain IDs, sources and all bindings.
BEGIN IMMEDIATE;
UPDATE knowledge_nodes SET description='倍数、整除与数字特性；合作完工已归入独立工程问题分支。' WHERE id='quant_divisibility_work';
UPDATE knowledge_nodes SET description='相遇、追及、往返、流水行船与火车过桥等行程模型；比赛题已归入独立比赛问题分支。' WHERE id='quant_competition_journey';
UPDATE knowledge_nodes SET description='近义反义、成语含义与引申象征等语义关系；集合范畴关系单独归类。' WHERE id='analogy_semantic_category';
UPDATE knowledge_nodes SET description='辨析材料与制成品等原材料对应关系；物理化学变化作为二级辨析方法单独展示。' WHERE id='analogy_material_physical_chemical';
UPDATE knowledge_nodes SET description='支持论证、前提假设与解释说明，沿用本机教师课程组织。' WHERE id='logic_support_premise';
UPDATE knowledge_nodes SET description='传统文化中的选官制度、教育学校、艺术工艺与节日节气。' WHERE id='cs_l3_7_b0b67a';
UPDATE knowledge_nodes SET description='传统织锦刺绣与工艺艺术；节日节气单独归传统文化分支。' WHERE id='cs_l5_47_2a1cbb';
UPDATE knowledge_nodes SET description='民法基本原则、主体与法律行为，及物权、合同等课程知识。' WHERE id='cs_l3_15_cc8dc8';
UPDATE knowledge_nodes SET description='刑法总则、犯罪与刑罚；行政法单独归类。' WHERE id='cs_l3_16_3e9395';
UPDATE knowledge_nodes SET description='先秦分封、宗法、井田、礼乐与生产文化等相关制度和知识。' WHERE module='常识判断' AND name='先秦政治经济与文化';
UPDATE knowledge_nodes SET description='基期A、现期B、增长率R、增长量X及其相互计算关系；速算分配方法归计算技巧。' WHERE id='da_abrx';
UPDATE knowledge_nodes SET description='资料分析的混合增长率与加权平均，包含十字交叉和线段方法；区别于数量关系的纯溶液题。' WHERE id='da_salt_mixture';
INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(41,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
