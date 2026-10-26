PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

-- 1. 扩展 attempts 表：来源、有效性、计时可信度与曝光状态
ALTER TABLE attempts ADD COLUMN source_type TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(source_type IN ('REAL_STUDY', 'AUTO_TEST', 'DEMO', 'IMPORT', 'UNKNOWN'));
ALTER TABLE attempts ADD COLUMN valid_for_stats INTEGER NOT NULL DEFAULT 1 CHECK(valid_for_stats IN (0, 1));
ALTER TABLE attempts ADD COLUMN timing_valid INTEGER NOT NULL DEFAULT 1 CHECK(timing_valid IN (0, 1));
ALTER TABLE attempts ADD COLUMN raw_elapsed_ms INTEGER;
ALTER TABLE attempts ADD COLUMN paused_ms INTEGER NOT NULL DEFAULT 0;
ALTER TABLE attempts ADD COLUMN audit_note TEXT;
ALTER TABLE attempts ADD COLUMN exposure_state TEXT NOT NULL DEFAULT 'UNKNOWN' CHECK(exposure_state IN ('UNKNOWN', 'NO_ASSISTANCE', 'ASSISTED'));

-- 2. 对历史作答记录进行计时可信度初始化审计
-- 规则：耗时不足 1 秒（elapsed_ms < 1000）或耗时过长（> 4小时，即 14400000 毫秒）的，标记 timing_valid = 0，并在 audit_note 中明确注明原因
-- 注意：正误记录保留，valid_for_stats 保持为 1，不删除不改写历史耗时与答案，耗时异常不自动剔除正确性记录
UPDATE attempts
SET timing_valid = 0,
    audit_note = '历史异常快速作答(<1s)，标记计时不可信，保留正误记录'
WHERE elapsed_ms IS NOT NULL AND elapsed_ms < 1000;

UPDATE attempts
SET timing_valid = 0,
    audit_note = '历史作答耗时异常偏长(>4h)，标记计时不可信，保留正误记录'
WHERE elapsed_ms IS NOT NULL AND elapsed_ms > 14400000;

-- 3. 新建辅助曝光记录表 exposure_logs
CREATE TABLE IF NOT EXISTS exposure_logs (
    id TEXT PRIMARY KEY,
    attempt_id TEXT REFERENCES attempts(id) ON DELETE SET NULL,
    question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
    session_id TEXT REFERENCES sessions(id) ON DELETE SET NULL,
    exposure_type TEXT NOT NULL CHECK(exposure_type IN ('HINT', 'EXPLANATION', 'ANSWER', 'AI_TUTOR')),
    stage TEXT NOT NULL CHECK(stage IN ('PRE_SUBMISSION', 'POST_SUBMISSION')),
    source_action TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    exposed_at TEXT NOT NULL,
    dedup_key TEXT UNIQUE
);

CREATE INDEX IF NOT EXISTS idx_exposure_logs_question ON exposure_logs(question_id);
CREATE INDEX IF NOT EXISTS idx_exposure_logs_attempt ON exposure_logs(attempt_id);
CREATE INDEX IF NOT EXISTS idx_exposure_logs_session ON exposure_logs(session_id);

INSERT OR IGNORE INTO schema_migrations VALUES (16, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
