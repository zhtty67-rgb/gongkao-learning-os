BEGIN IMMEDIATE;

-- 作答版本存储（最小兼容）：
-- 1) 教师诊断行自带其对应版本的作答文本，使历史诊断可真实复核原句（不伪造还原）；
-- 2) 五维评分绑定作答版本指纹，用于重试去重与串版防护。
ALTER TABLE shenlun_teacher_diagnoses ADD COLUMN answer_text TEXT NOT NULL DEFAULT '';
ALTER TABLE shenlun_assessments ADD COLUMN answer_hash TEXT NOT NULL DEFAULT '';

INSERT INTO schema_migrations VALUES (24, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
