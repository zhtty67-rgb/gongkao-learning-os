-- Migration 033: split 立体图推 (spatial/3D graphic reasoning) out of 图形推理
-- into its own standalone module.
--
-- Background (2026-10-07):
--   图形推理 held 755 questions: 493 from the LongFei 平面图推500题 book plus 262
--   Jiangsu A/B/C real-exam papers. The spatial (3D) question family — 纸盒/多面体
--   外表面折叠 and 截面图(剖开) — lived inside 图形推理 while the knowledge tree
--   already had a dedicated spatial subtree (reasoning_graphic_spatial + 4 skills,
--   question_count=0) that no question was bound to. This migration promotes that
--   subtree to a standalone module named 立体图推 and moves exactly the 69 spatial
--   questions into it.
--
--   Every ID below was individually verified against the full stem text: 62 folding
--   stems ("...外表面，右边哪一项能由它折叠而成") and 7 cross-section stems
--   ("从任意角度/面剖开，...截面图"). Deliberately NOT moved:
--     - 71 拼合 questions: 66 平移拼合 + 5 黑白纸片拼合 are 平面拼合 (2D), stay in 图形推理;
--     - lf500-q314 (折纸裁剪, 2D fold-cut-unfold) stays with its 平面 book;
--     - 三视图 / 立体拼合 have zero questions in the bank; their nodes move with the
--       subtree so future imports land in the new module.
--
--   Binding semantics follow the frozen-17 LF1 skill contract (migration 011):
--     - question_knowledge_map rows move from the old module root (reasoning_graphic)
--       to the precise spatial skill node (folding / cross_section);
--     - graphic_position skill bindings are factually wrong for these questions and
--       are set to status='inactive' (audit trail preserved);
--     - the NULL-skill needs_review primary rows are re-pointed from the old module
--       root code to the new module root code;
--     - no new learning_skills contracts are created (17 stay frozen).
--
--   All statements are deterministic and idempotent: guarded by explicit id lists
--   and OR-IGNORE / NOT EXISTS. Release order remains
--       data repair -> backend.app.db.migrate() -> repair_skill_contracts_and_bindings.py
--   followed by rebuild_mastery / rebuild_reviews / rebuild_error_overlay.

BEGIN IMMEDIATE;

-- ============================================================
-- Part 1: module column (69 questions, individually verified)
-- ============================================================

-- 1a. 62 folding questions -> 立体图推
UPDATE questions SET module = '立体图推'
WHERE id IN (
  'js-2017-a-q087', 'js-2017-a-q088', 'js-2017-a-q089', 'js-2017-a-q090',
  'js-2017-b-q087', 'js-2017-b-q088', 'js-2017-b-q089', 'js-2017-b-q090',
  'js-2017-c-q088', 'js-2017-c-q089', 'js-2017-c-q090', 'js-2018-a-q085',
  'js-2018-a-q086', 'js-2018-a-q087', 'js-2018-a-q088', 'js-2018-b-q085',
  'js-2018-b-q086', 'js-2018-b-q087', 'js-2018-b-q088', 'js-2018-c-q085',
  'js-2018-c-q086', 'js-2018-c-q087', 'js-2018-c-q088', 'js-2019-a-q084',
  'js-2019-a-q085', 'js-2019-a-q086', 'js-2019-a-q087', 'js-2019-b-q084',
  'js-2019-b-q085', 'js-2019-b-q086', 'js-2019-b-q087', 'js-2019-c-q084',
  'js-2019-c-q085', 'js-2019-c-q086', 'js-2019-c-q087', 'js-2020-a-q084',
  'js-2020-a-q085', 'js-2020-a-q086', 'js-2020-a-q087', 'js-2020-b-q084',
  'js-2020-b-q085', 'js-2020-b-q086', 'js-2020-b-q087', 'js-2020-c-q084',
  'js-2020-c-q085', 'js-2020-c-q086', 'js-2020-c-q087', 'js-2021-a-q087',
  'js-2021-a-q088', 'js-2021-a-q089', 'js-2021-b-q087', 'js-2021-b-q088',
  'js-2021-b-q089', 'js-2021-c-q087', 'js-2021-c-q088', 'js-2021-c-q089',
  'js-2022-a-q089', 'js-2022-a-q090', 'js-2022-b-q087', 'js-2022-b-q088',
  'js-2022-c-q087', 'js-2022-c-q088'
);

-- 1b. 7 cross-section questions -> 立体图推
UPDATE questions SET module = '立体图推'
WHERE id IN (
  'js-2019-a-q090', 'js-2019-b-q090', 'js-2019-c-q090', 'js-2020-a-q090',
  'js-2020-b-q090', 'js-2020-c-q090', 'js-2021-b-q090'
);

-- ============================================================
-- Part 2: knowledge tree — promote the spatial subtree to a module
-- ============================================================

-- 2a. reasoning_graphic_spatial becomes the 立体图推 module root.
--     id / knowledge_node_code stay stable (bindings and Hub evidence reference them).
UPDATE knowledge_nodes
SET parent_id = NULL,
    node_type = 'module',
    module = '立体图推',
    name = '立体图推'
WHERE id = 'reasoning_graphic_spatial';

-- 2b. The four spatial skills follow their root into the new module.
UPDATE knowledge_nodes
SET module = '立体图推'
WHERE id IN (
  'reasoning_graphic_spatial_assembly',
  'reasoning_graphic_spatial_cross_section',
  'reasoning_graphic_spatial_folding',
  'reasoning_graphic_spatial_three_views'
);

-- ============================================================
-- Part 3: skill bindings — re-align before knowledge-map convergence
--         (the LF1 trigger on question_knowledge_map must find corrected
--          bindings in place; for spatial nodes it is a no-op anyway)
-- ============================================================

-- 3a. graphic_position bindings are semantically wrong for spatial questions:
--     deactivate, keeping provenance/metadata as audit trail.
UPDATE question_skill_bindings
SET status = 'inactive'
WHERE status = 'active'
  AND learning_skill_id = 'graphic_position'
  AND question_id IN (
  'js-2017-a-q087', 'js-2017-a-q088', 'js-2017-a-q089', 'js-2017-a-q090',
  'js-2017-b-q087', 'js-2017-b-q088', 'js-2017-b-q089', 'js-2017-b-q090',
  'js-2017-c-q088', 'js-2017-c-q089', 'js-2017-c-q090', 'js-2018-a-q085',
  'js-2018-a-q086', 'js-2018-a-q087', 'js-2018-a-q088', 'js-2018-b-q085',
  'js-2018-b-q086', 'js-2018-b-q087', 'js-2018-b-q088', 'js-2018-c-q085',
  'js-2018-c-q086', 'js-2018-c-q087', 'js-2018-c-q088', 'js-2019-a-q084',
  'js-2019-a-q085', 'js-2019-a-q086', 'js-2019-a-q087', 'js-2019-b-q084',
  'js-2019-b-q085', 'js-2019-b-q086', 'js-2019-b-q087', 'js-2019-c-q084',
  'js-2019-c-q085', 'js-2019-c-q086', 'js-2019-c-q087', 'js-2020-a-q084',
  'js-2020-a-q085', 'js-2020-a-q086', 'js-2020-a-q087', 'js-2020-b-q084',
  'js-2020-b-q085', 'js-2020-b-q086', 'js-2020-b-q087', 'js-2020-c-q084',
  'js-2020-c-q085', 'js-2020-c-q086', 'js-2020-c-q087', 'js-2021-a-q087',
  'js-2021-a-q088', 'js-2021-a-q089', 'js-2021-b-q087', 'js-2021-b-q088',
  'js-2021-b-q089', 'js-2021-c-q087', 'js-2021-c-q088', 'js-2021-c-q089',
  'js-2022-a-q089', 'js-2022-a-q090', 'js-2022-b-q087', 'js-2022-b-q088',
  'js-2022-c-q087', 'js-2022-c-q088',
  'js-2019-a-q090', 'js-2019-b-q090', 'js-2019-c-q090', 'js-2020-a-q090',
  'js-2020-b-q090', 'js-2020-c-q090', 'js-2021-b-q090'
);

-- 3b. The NULL-skill needs_review primary rows re-point from the old graphic
--     module root code to the new 立体图推 module root code.
UPDATE question_skill_bindings
SET knowledge_node_code = 'gongkao.xingce.reasoning.graphic.spatial'
WHERE learning_skill_id IS NULL
  AND knowledge_node_code = 'gongkao.xingce.reasoning.graphic'
  AND status = 'needs_review'
  AND question_id IN (
  'js-2017-a-q087', 'js-2017-a-q088', 'js-2017-a-q089', 'js-2017-a-q090',
  'js-2017-b-q087', 'js-2017-b-q088', 'js-2017-b-q089', 'js-2017-b-q090',
  'js-2017-c-q088', 'js-2017-c-q089', 'js-2017-c-q090', 'js-2018-a-q085',
  'js-2018-a-q086', 'js-2018-a-q087', 'js-2018-a-q088', 'js-2018-b-q085',
  'js-2018-b-q086', 'js-2018-b-q087', 'js-2018-b-q088', 'js-2018-c-q085',
  'js-2018-c-q086', 'js-2018-c-q087', 'js-2018-c-q088', 'js-2019-a-q084',
  'js-2019-a-q085', 'js-2019-a-q086', 'js-2019-a-q087', 'js-2019-b-q084',
  'js-2019-b-q085', 'js-2019-b-q086', 'js-2019-b-q087', 'js-2019-c-q084',
  'js-2019-c-q085', 'js-2019-c-q086', 'js-2019-c-q087', 'js-2020-a-q084',
  'js-2020-a-q085', 'js-2020-a-q086', 'js-2020-a-q087', 'js-2020-b-q084',
  'js-2020-b-q085', 'js-2020-b-q086', 'js-2020-b-q087', 'js-2020-c-q084',
  'js-2020-c-q085', 'js-2020-c-q086', 'js-2020-c-q087', 'js-2021-a-q087',
  'js-2021-a-q088', 'js-2021-a-q089', 'js-2021-b-q087', 'js-2021-b-q088',
  'js-2021-b-q089', 'js-2021-c-q087', 'js-2021-c-q088', 'js-2021-c-q089',
  'js-2022-a-q089', 'js-2022-a-q090', 'js-2022-b-q087', 'js-2022-b-q088',
  'js-2022-c-q087', 'js-2022-c-q088',
  'js-2019-a-q090', 'js-2019-b-q090', 'js-2019-c-q090', 'js-2020-a-q090',
  'js-2020-b-q090', 'js-2020-c-q090', 'js-2021-b-q090'
);

-- ============================================================
-- Part 4: knowledge map convergence (only the touched questions)
-- ============================================================

-- 4a. Drop the old module-root bindings (all 69 were bound to reasoning_graphic).
DELETE FROM question_knowledge_map
WHERE knowledge_node_id = 'reasoning_graphic'
  AND question_id IN (
  'js-2017-a-q087', 'js-2017-a-q088', 'js-2017-a-q089', 'js-2017-a-q090',
  'js-2017-b-q087', 'js-2017-b-q088', 'js-2017-b-q089', 'js-2017-b-q090',
  'js-2017-c-q088', 'js-2017-c-q089', 'js-2017-c-q090', 'js-2018-a-q085',
  'js-2018-a-q086', 'js-2018-a-q087', 'js-2018-a-q088', 'js-2018-b-q085',
  'js-2018-b-q086', 'js-2018-b-q087', 'js-2018-b-q088', 'js-2018-c-q085',
  'js-2018-c-q086', 'js-2018-c-q087', 'js-2018-c-q088', 'js-2019-a-q084',
  'js-2019-a-q085', 'js-2019-a-q086', 'js-2019-a-q087', 'js-2019-b-q084',
  'js-2019-b-q085', 'js-2019-b-q086', 'js-2019-b-q087', 'js-2019-c-q084',
  'js-2019-c-q085', 'js-2019-c-q086', 'js-2019-c-q087', 'js-2020-a-q084',
  'js-2020-a-q085', 'js-2020-a-q086', 'js-2020-a-q087', 'js-2020-b-q084',
  'js-2020-b-q085', 'js-2020-b-q086', 'js-2020-b-q087', 'js-2020-c-q084',
  'js-2020-c-q085', 'js-2020-c-q086', 'js-2020-c-q087', 'js-2021-a-q087',
  'js-2021-a-q088', 'js-2021-a-q089', 'js-2021-b-q087', 'js-2021-b-q088',
  'js-2021-b-q089', 'js-2021-c-q087', 'js-2021-c-q088', 'js-2021-c-q089',
  'js-2022-a-q089', 'js-2022-a-q090', 'js-2022-b-q087', 'js-2022-b-q088',
  'js-2022-c-q087', 'js-2022-c-q088',
  'js-2019-a-q090', 'js-2019-b-q090', 'js-2019-c-q090', 'js-2020-a-q090',
  'js-2020-b-q090', 'js-2020-c-q090', 'js-2021-b-q090'
);

-- 4b. 62 folding questions -> 多面体折叠 skill node.
INSERT OR IGNORE INTO question_knowledge_map (question_id, knowledge_node_id, weight)
SELECT q.id, 'reasoning_graphic_spatial_folding', 1.0
FROM questions q
WHERE q.module = '立体图推'
  AND q.stem LIKE '%折叠%'
  AND q.id IN (
  'js-2017-a-q087', 'js-2017-a-q088', 'js-2017-a-q089', 'js-2017-a-q090',
  'js-2017-b-q087', 'js-2017-b-q088', 'js-2017-b-q089', 'js-2017-b-q090',
  'js-2017-c-q088', 'js-2017-c-q089', 'js-2017-c-q090', 'js-2018-a-q085',
  'js-2018-a-q086', 'js-2018-a-q087', 'js-2018-a-q088', 'js-2018-b-q085',
  'js-2018-b-q086', 'js-2018-b-q087', 'js-2018-b-q088', 'js-2018-c-q085',
  'js-2018-c-q086', 'js-2018-c-q087', 'js-2018-c-q088', 'js-2019-a-q084',
  'js-2019-a-q085', 'js-2019-a-q086', 'js-2019-a-q087', 'js-2019-b-q084',
  'js-2019-b-q085', 'js-2019-b-q086', 'js-2019-b-q087', 'js-2019-c-q084',
  'js-2019-c-q085', 'js-2019-c-q086', 'js-2019-c-q087', 'js-2020-a-q084',
  'js-2020-a-q085', 'js-2020-a-q086', 'js-2020-a-q087', 'js-2020-b-q084',
  'js-2020-b-q085', 'js-2020-b-q086', 'js-2020-b-q087', 'js-2020-c-q084',
  'js-2020-c-q085', 'js-2020-c-q086', 'js-2020-c-q087', 'js-2021-a-q087',
  'js-2021-a-q088', 'js-2021-a-q089', 'js-2021-b-q087', 'js-2021-b-q088',
  'js-2021-b-q089', 'js-2021-c-q087', 'js-2021-c-q088', 'js-2021-c-q089',
  'js-2022-a-q089', 'js-2022-a-q090', 'js-2022-b-q087', 'js-2022-b-q088',
  'js-2022-c-q087', 'js-2022-c-q088'
);

-- 4c. 7 cross-section questions -> 截面图 skill node.
INSERT OR IGNORE INTO question_knowledge_map (question_id, knowledge_node_id, weight)
SELECT q.id, 'reasoning_graphic_spatial_cross_section', 1.0
FROM questions q
WHERE q.module = '立体图推'
  AND q.id IN (
  'js-2019-a-q090', 'js-2019-b-q090', 'js-2019-c-q090', 'js-2020-a-q090',
  'js-2020-b-q090', 'js-2020-c-q090', 'js-2021-b-q090'
);

-- 4d. Guard: every moved question must carry exactly one spatial binding.
--     (No-op on a healthy run; assertion-style repair if a row was missed.)
INSERT OR IGNORE INTO question_knowledge_map (question_id, knowledge_node_id, weight)
SELECT q.id, 'reasoning_graphic_spatial', 1.0
FROM questions q
WHERE q.module = '立体图推'
  AND NOT EXISTS (
    SELECT 1 FROM question_knowledge_map m WHERE m.question_id = q.id
  );

-- ============================================================
-- Part 5: record migration version
-- ============================================================
INSERT OR REPLACE INTO schema_migrations (version, applied_at)
VALUES (33, strftime('%Y-%m-%dT%H:%M:%fZ','now'));

COMMIT;
