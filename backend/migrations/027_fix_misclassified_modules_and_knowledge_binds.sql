-- Migration 027: fix misclassified question modules, then re-align knowledge map and
-- skill bindings for exactly the affected questions.
--
-- Background (audit 2026-10-01, D:\gong\audit-session-c-20261001):
--   71 questions were imported into the wrong module column. Migration 025 rebuilds
--   question_skill_bindings / question_knowledge_map FROM questions.module, so with wrong
--   modules its output is wrong for these questions. This migration runs AFTER 025 in the
--   normal numeric order and (1) corrects the module column, then (2) re-aligns the
--   binding rows and (3) converges the knowledge-map rows for exactly the affected
--   questions -- i.e. "fix module first, rebuild bindings second" holds for every touched
--   question under the verified release order:
--       data repair -> backend.app.db.migrate() -> repair_skill_contracts_and_bindings.py
--
--   Every ID below was individually verified against the original exam papers (Jiangsu
--   A/B/C 2016-2022 PDF section boundaries) and/or the full stem content. No keyword
--   auto-classification was used to build these lists.
--
--   Fine-grained mappings that are already correct are NOT touched: in particular the
--   LongFei 500 (lf500-*) graphic questions keep their two-row parent+child knowledge-map
--   rows and all same-module mappings stay as 025 left them.
--
-- Idempotent & convergent: every statement is a deterministic UPDATE / DELETE+INSERT-OR-IGNORE
-- guarded by explicit id lists; re-running after application startup is safe and idempotent.
--
-- NOTE on ordering inside this file: bindings are re-aligned BEFORE the knowledge-map
-- convergence so the LF1 trigger (AFTER INSERT ON question_knowledge_map) finds the
-- corrected binding already in place and becomes a no-op.

BEGIN IMMEDIATE;

-- ============================================================
-- Part 1: module column corrections (71 questions, verified)
-- ============================================================

-- 1a. Word-analogy questions misfiled as 图形推理 (44) -> 类比推理
--     Verified against paper section boundaries: e.g. 2022C q66-75, 2021C q66-75,
--     2016C q66-73 are the 类比推理 sections; stems are two-blank word analogies.
UPDATE questions SET module = '类比推理'
WHERE id IN (
  'js-2016-a-q077',
  'js-2016-a-q078',
  'js-2016-b-q077',
  'js-2016-b-q078',
  'js-2016-c-q072',
  'js-2016-c-q073',
  'js-2017-a-q077',
  'js-2017-a-q078',
  'js-2017-b-q077',
  'js-2017-b-q078',
  'js-2017-c-q077',
  'js-2017-c-q078',
  'js-2018-a-q072',
  'js-2018-a-q073',
  'js-2018-b-q072',
  'js-2018-b-q073',
  'js-2018-c-q072',
  'js-2018-c-q073',
  'js-2019-a-q072',
  'js-2019-a-q073',
  'js-2019-b-q072',
  'js-2019-b-q073',
  'js-2019-c-q072',
  'js-2019-c-q073',
  'js-2020-a-q072',
  'js-2020-a-q073',
  'js-2020-b-q072',
  'js-2020-b-q073',
  'js-2020-c-q072',
  'js-2020-c-q073',
  'js-2021-a-q074',
  'js-2021-a-q075',
  'js-2021-b-q074',
  'js-2021-b-q075',
  'js-2021-c-q074',
  'js-2021-c-q075',
  'js-2022-a-q075',
  'js-2022-a-q076',
  'js-2022-a-q077',
  'js-2022-b-q073',
  'js-2022-b-q074',
  'js-2022-b-q075',
  'js-2022-c-q073',
  'js-2022-c-q075');

-- 1b. Definition-judgement questions misfiled as 逻辑判断 (23, all 2016 papers) -> 定义判断
--     Verified against paper: 2016 A/B/C 判断推理 ends with a contiguous 定义判断 block;
--     e.g. 2016C q96-105 are all "X，指……" definition questions in the original paper.
UPDATE questions SET module = '定义判断'
WHERE id IN (
  'js-2016-a-q102',
  'js-2016-a-q103',
  'js-2016-a-q104',
  'js-2016-a-q105',
  'js-2016-a-q107',
  'js-2016-a-q111',
  'js-2016-a-q112',
  'js-2016-a-q114',
  'js-2016-a-q115',
  'js-2016-b-q101',
  'js-2016-b-q105',
  'js-2016-b-q108',
  'js-2016-b-q112',
  'js-2016-b-q113',
  'js-2016-b-q114',
  'js-2016-c-q096',
  'js-2016-c-q099',
  'js-2016-c-q101',
  'js-2016-c-q102',
  'js-2016-c-q103',
  'js-2016-c-q104',
  'js-2016-c-q106',
  'js-2016-c-q107');

-- 1c. Quantitative questions misfiled as 言语理解 (4) -> 数量关系
--     Verified against paper: 2022A 第三部分数量关系 = q48-67 (q53/54/55 are 碳排放计算、
--     概率、定积分几何), 2022C 第三部分数量关系 starts at q46 (number sequence).
UPDATE questions SET module = '数量关系'
WHERE id IN (
  'js-2022-a-q053',
  'js-2022-a-q054',
  'js-2022-a-q055',
  'js-2022-c-q046');

-- ============================================================
-- Part 2: primary skill binding re-alignment (mirrors 025's per-module rules)
-- ============================================================

-- 2a. 类比推理 -> analogy, active (025 rule A)
UPDATE question_skill_bindings
SET learning_skill_id = 'analogy',
    knowledge_node_code = 'gongkao.xingce.reasoning.analogy',
    status = 'active',
    provenance = 'migrated',
    metadata_json = json_set(metadata_json, '$.module_corrected_by', 'migration_027')
WHERE question_id IN (
  'js-2016-a-q077',
  'js-2016-a-q078',
  'js-2016-b-q077',
  'js-2016-b-q078',
  'js-2016-c-q072',
  'js-2016-c-q073',
  'js-2017-a-q077',
  'js-2017-a-q078',
  'js-2017-b-q077',
  'js-2017-b-q078',
  'js-2017-c-q077',
  'js-2017-c-q078',
  'js-2018-a-q072',
  'js-2018-a-q073',
  'js-2018-b-q072',
  'js-2018-b-q073',
  'js-2018-c-q072',
  'js-2018-c-q073',
  'js-2019-a-q072',
  'js-2019-a-q073',
  'js-2019-b-q072',
  'js-2019-b-q073',
  'js-2019-c-q072',
  'js-2019-c-q073',
  'js-2020-a-q072',
  'js-2020-a-q073',
  'js-2020-b-q072',
  'js-2020-b-q073',
  'js-2020-c-q072',
  'js-2020-c-q073',
  'js-2021-a-q074',
  'js-2021-a-q075',
  'js-2021-b-q074',
  'js-2021-b-q075',
  'js-2021-c-q074',
  'js-2021-c-q075',
  'js-2022-a-q075',
  'js-2022-a-q076',
  'js-2022-a-q077',
  'js-2022-b-q073',
  'js-2022-b-q074',
  'js-2022-b-q075',
  'js-2022-c-q073',
  'js-2022-c-q075')
  AND role = 'primary';

-- 2b. 定义判断 -> definition, active (025 rule B)
UPDATE question_skill_bindings
SET learning_skill_id = 'definition',
    knowledge_node_code = 'gongkao.xingce.reasoning.definition',
    status = 'active',
    provenance = 'migrated',
    metadata_json = json_set(metadata_json, '$.module_corrected_by', 'migration_027')
WHERE question_id IN (
  'js-2016-a-q102',
  'js-2016-a-q103',
  'js-2016-a-q104',
  'js-2016-a-q105',
  'js-2016-a-q107',
  'js-2016-a-q111',
  'js-2016-a-q112',
  'js-2016-a-q114',
  'js-2016-a-q115',
  'js-2016-b-q101',
  'js-2016-b-q105',
  'js-2016-b-q108',
  'js-2016-b-q112',
  'js-2016-b-q113',
  'js-2016-b-q114',
  'js-2016-c-q096',
  'js-2016-c-q099',
  'js-2016-c-q101',
  'js-2016-c-q102',
  'js-2016-c-q103',
  'js-2016-c-q104',
  'js-2016-c-q106',
  'js-2016-c-q107')
  AND role = 'primary';

-- 2c. The 4 quantitative questions match none of 025's work/journey/profit keyword rules
--     (碳排放计算 / 概率 / 定积分 / 数列), so the faithful 025 outcome is needs_review with
--     no specific skill (025 rule G fallback).
UPDATE question_skill_bindings
SET learning_skill_id = NULL,
    knowledge_node_code = 'gongkao.xingce.quantitative',
    status = 'needs_review',
    provenance = 'migrated',
    metadata_json = json_set(metadata_json, '$.module_corrected_by', 'migration_027')
WHERE question_id IN (
  'js-2022-a-q053',
  'js-2022-a-q054',
  'js-2022-a-q055',
  'js-2022-c-q046')
  AND role = 'primary';

-- 2d. Safety net: if a touched question somehow has no primary binding row, create one
--     (same id convention as 025). INSERT OR IGNORE keeps this a no-op in the normal path.
INSERT OR IGNORE INTO question_skill_bindings
  (id, question_id, learning_skill_id, knowledge_node_code, role, weight, provenance, status, metadata_json, created_at)
SELECT 'qsb_' || q.id || '_primary', q.id,
       CASE WHEN q.module = '类比推理' THEN 'analogy'
            WHEN q.module = '定义判断' THEN 'definition'
            ELSE NULL END,
       CASE WHEN q.module = '类比推理' THEN 'gongkao.xingce.reasoning.analogy'
            WHEN q.module = '定义判断' THEN 'gongkao.xingce.reasoning.definition'
            WHEN q.module = '数量关系' THEN 'gongkao.xingce.quantitative'
            END,
       'primary', 1.0, 'migrated',
       CASE WHEN q.module IN ('类比推理', '定义判断') THEN 'active' ELSE 'needs_review' END,
       '{"module_corrected_by": "migration_027"}',
       strftime('%Y-%m-%dT%H:%M:%fZ','now')
FROM questions q
WHERE q.id IN (
  'js-2016-a-q077',
  'js-2016-a-q078',
  'js-2016-b-q077',
  'js-2016-b-q078',
  'js-2016-c-q072',
  'js-2016-c-q073',
  'js-2017-a-q077',
  'js-2017-a-q078',
  'js-2017-b-q077',
  'js-2017-b-q078',
  'js-2017-c-q077',
  'js-2017-c-q078',
  'js-2018-a-q072',
  'js-2018-a-q073',
  'js-2018-b-q072',
  'js-2018-b-q073',
  'js-2018-c-q072',
  'js-2018-c-q073',
  'js-2019-a-q072',
  'js-2019-a-q073',
  'js-2019-b-q072',
  'js-2019-b-q073',
  'js-2019-c-q072',
  'js-2019-c-q073',
  'js-2020-a-q072',
  'js-2020-a-q073',
  'js-2020-b-q072',
  'js-2020-b-q073',
  'js-2020-c-q072',
  'js-2020-c-q073',
  'js-2021-a-q074',
  'js-2021-a-q075',
  'js-2021-b-q074',
  'js-2021-b-q075',
  'js-2021-c-q074',
  'js-2021-c-q075',
  'js-2022-a-q075',
  'js-2022-a-q076',
  'js-2022-a-q077',
  'js-2022-b-q073',
  'js-2022-b-q074',
  'js-2022-b-q075',
  'js-2022-c-q073',
  'js-2022-c-q075',
  'js-2016-a-q102',
  'js-2016-a-q103',
  'js-2016-a-q104',
  'js-2016-a-q105',
  'js-2016-a-q107',
  'js-2016-a-q111',
  'js-2016-a-q112',
  'js-2016-a-q114',
  'js-2016-a-q115',
  'js-2016-b-q101',
  'js-2016-b-q105',
  'js-2016-b-q108',
  'js-2016-b-q112',
  'js-2016-b-q113',
  'js-2016-b-q114',
  'js-2016-c-q096',
  'js-2016-c-q099',
  'js-2016-c-q101',
  'js-2016-c-q102',
  'js-2016-c-q103',
  'js-2016-c-q104',
  'js-2016-c-q106',
  'js-2016-c-q107',
  'js-2022-a-q053',
  'js-2022-a-q054',
  'js-2022-a-q055',
  'js-2022-c-q046')
  AND q.module IN ('类比推理', '定义判断', '数量关系')
  AND NOT EXISTS (SELECT 1 FROM question_skill_bindings b WHERE b.question_id = q.id AND b.role = 'primary');

-- ============================================================
-- Part 3: knowledge map convergence (only the touched questions)
-- ============================================================

-- 3a. The 44 analogy questions were mapped to reasoning_graphic (same-module before the
--     module fix, so 025 left them). Converge to the analogy module root.
DELETE FROM question_knowledge_map
WHERE question_id IN (
  'js-2016-a-q077',
  'js-2016-a-q078',
  'js-2016-b-q077',
  'js-2016-b-q078',
  'js-2016-c-q072',
  'js-2016-c-q073',
  'js-2017-a-q077',
  'js-2017-a-q078',
  'js-2017-b-q077',
  'js-2017-b-q078',
  'js-2017-c-q077',
  'js-2017-c-q078',
  'js-2018-a-q072',
  'js-2018-a-q073',
  'js-2018-b-q072',
  'js-2018-b-q073',
  'js-2018-c-q072',
  'js-2018-c-q073',
  'js-2019-a-q072',
  'js-2019-a-q073',
  'js-2019-b-q072',
  'js-2019-b-q073',
  'js-2019-c-q072',
  'js-2019-c-q073',
  'js-2020-a-q072',
  'js-2020-a-q073',
  'js-2020-b-q072',
  'js-2020-b-q073',
  'js-2020-c-q072',
  'js-2020-c-q073',
  'js-2021-a-q074',
  'js-2021-a-q075',
  'js-2021-b-q074',
  'js-2021-b-q075',
  'js-2021-c-q074',
  'js-2021-c-q075',
  'js-2022-a-q075',
  'js-2022-a-q076',
  'js-2022-a-q077',
  'js-2022-b-q073',
  'js-2022-b-q074',
  'js-2022-b-q075',
  'js-2022-c-q073',
  'js-2022-c-q075')
  AND knowledge_node_id != 'analogy';

INSERT OR IGNORE INTO question_knowledge_map (question_id, knowledge_node_id, weight)
SELECT q.id, 'analogy', 1.0
FROM questions q
WHERE q.id IN (
  'js-2016-a-q077',
  'js-2016-a-q078',
  'js-2016-b-q077',
  'js-2016-b-q078',
  'js-2016-c-q072',
  'js-2016-c-q073',
  'js-2017-a-q077',
  'js-2017-a-q078',
  'js-2017-b-q077',
  'js-2017-b-q078',
  'js-2017-c-q077',
  'js-2017-c-q078',
  'js-2018-a-q072',
  'js-2018-a-q073',
  'js-2018-b-q072',
  'js-2018-b-q073',
  'js-2018-c-q072',
  'js-2018-c-q073',
  'js-2019-a-q072',
  'js-2019-a-q073',
  'js-2019-b-q072',
  'js-2019-b-q073',
  'js-2019-c-q072',
  'js-2019-c-q073',
  'js-2020-a-q072',
  'js-2020-a-q073',
  'js-2020-b-q072',
  'js-2020-b-q073',
  'js-2020-c-q072',
  'js-2020-c-q073',
  'js-2021-a-q074',
  'js-2021-a-q075',
  'js-2021-b-q074',
  'js-2021-b-q075',
  'js-2021-c-q074',
  'js-2021-c-q075',
  'js-2022-a-q075',
  'js-2022-a-q076',
  'js-2022-a-q077',
  'js-2022-b-q073',
  'js-2022-b-q074',
  'js-2022-b-q075',
  'js-2022-c-q073',
  'js-2022-c-q075')
  AND NOT EXISTS (SELECT 1 FROM question_knowledge_map m WHERE m.question_id = q.id);

-- 3b. The 23 definition questions were mapped to logic by 025 (module was 逻辑判断 at that
--     moment). Converge to the definition module root.
DELETE FROM question_knowledge_map
WHERE question_id IN (
  'js-2016-a-q102',
  'js-2016-a-q103',
  'js-2016-a-q104',
  'js-2016-a-q105',
  'js-2016-a-q107',
  'js-2016-a-q111',
  'js-2016-a-q112',
  'js-2016-a-q114',
  'js-2016-a-q115',
  'js-2016-b-q101',
  'js-2016-b-q105',
  'js-2016-b-q108',
  'js-2016-b-q112',
  'js-2016-b-q113',
  'js-2016-b-q114',
  'js-2016-c-q096',
  'js-2016-c-q099',
  'js-2016-c-q101',
  'js-2016-c-q102',
  'js-2016-c-q103',
  'js-2016-c-q104',
  'js-2016-c-q106',
  'js-2016-c-q107')
  AND knowledge_node_id != 'definition';

INSERT OR IGNORE INTO question_knowledge_map (question_id, knowledge_node_id, weight)
SELECT q.id, 'definition', 1.0
FROM questions q
WHERE q.id IN (
  'js-2016-a-q102',
  'js-2016-a-q103',
  'js-2016-a-q104',
  'js-2016-a-q105',
  'js-2016-a-q107',
  'js-2016-a-q111',
  'js-2016-a-q112',
  'js-2016-a-q114',
  'js-2016-a-q115',
  'js-2016-b-q101',
  'js-2016-b-q105',
  'js-2016-b-q108',
  'js-2016-b-q112',
  'js-2016-b-q113',
  'js-2016-b-q114',
  'js-2016-c-q096',
  'js-2016-c-q099',
  'js-2016-c-q101',
  'js-2016-c-q102',
  'js-2016-c-q103',
  'js-2016-c-q104',
  'js-2016-c-q106',
  'js-2016-c-q107')
  AND NOT EXISTS (SELECT 1 FROM question_knowledge_map m WHERE m.question_id = q.id);

-- 3c. The 4 quantitative questions were mapped to verbal (module was 言语理解 at that
--     moment; 025-G only rewrites verbal nodes of questions already in 数量关系).
DELETE FROM question_knowledge_map
WHERE question_id IN (
  'js-2022-a-q053',
  'js-2022-a-q054',
  'js-2022-a-q055',
  'js-2022-c-q046')
  AND knowledge_node_id != 'quantitative';

INSERT OR IGNORE INTO question_knowledge_map (question_id, knowledge_node_id, weight)
SELECT q.id, 'quantitative', 1.0
FROM questions q
WHERE q.id IN (
  'js-2022-a-q053',
  'js-2022-a-q054',
  'js-2022-a-q055',
  'js-2022-c-q046')
  AND NOT EXISTS (SELECT 1 FROM question_knowledge_map m WHERE m.question_id = q.id);

-- 3d. Residual cross-module binds: 资料分析 questions mapped to the analogy node (025-H
--     does not rewrite knowledge_map). Converge to the data_analysis module root.
DELETE FROM question_knowledge_map
WHERE question_id IN (
  'js-2016-c-q111',
  'js-2016-c-q113',
  'js-2016-c-q114',
  'js-2016-c-q115',
  'js-2017-c-q111',
  'js-2017-c-q115',
  'js-2021-c-q111',
  'js-2021-c-q112',
  'js-2021-c-q114',
  'js-2021-c-q115')
  AND knowledge_node_id != 'data_analysis';

INSERT OR IGNORE INTO question_knowledge_map (question_id, knowledge_node_id, weight)
SELECT q.id, 'data_analysis', 1.0
FROM questions q
WHERE q.id IN (
  'js-2016-c-q111',
  'js-2016-c-q113',
  'js-2016-c-q114',
  'js-2016-c-q115',
  'js-2017-c-q111',
  'js-2017-c-q115',
  'js-2021-c-q111',
  'js-2021-c-q112',
  'js-2021-c-q114',
  'js-2021-c-q115')
  AND NOT EXISTS (SELECT 1 FROM question_knowledge_map m WHERE m.question_id = q.id);

-- ============================================================
-- Part 4: record migration version
-- ============================================================
INSERT OR REPLACE INTO schema_migrations (version, applied_at)
VALUES (27, strftime('%Y-%m-%dT%H:%M:%fZ','now'));

COMMIT;
