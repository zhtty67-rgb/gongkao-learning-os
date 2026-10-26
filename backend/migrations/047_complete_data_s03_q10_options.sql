-- 原题本第14页有A/B/C/D四组图；旧固定800像素切片遗漏C、D。
-- 仅更换作答图引用，保留题目ID、答案与学习历史。
BEGIN IMMEDIATE;
UPDATE questions
SET stem_assets_json='["/assets/questions/hs600-data-s03-q10_options_complete_20261016.png"]'
WHERE id='hs600-data-s03-q10'
  AND stem_assets_json='["/assets/questions/hs600-data-s03-q10_options.png"]';
INSERT OR IGNORE INTO schema_migrations(version,applied_at)
VALUES(47,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
