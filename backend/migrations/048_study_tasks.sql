BEGIN IMMEDIATE;

-- Migration 048: 资料转学习任务（Study Task Sets）
-- 讲义/逐字稿/教材 → 知识卡 + 自查题 + 学习任务。三个不变量：
-- 1. 溯源不可伪造：provenance_json 只能引用采集到的证据池（原文出处由服务端
--    从证据映射写入，模型输出仅指证据下标）；source_kind 区分原文/AI整理/AI自编。
-- 2. 与正式学习统计隔离：本表体系不写 attempts/mastery/review —— 自查完成只落
--    本表状态与 result_json，理解验证依赖后续正式作答。
-- 3. 不自动创建 LearningSkill：仅通过 knowledge_node_id/code 关联既有知识树。

CREATE TABLE IF NOT EXISTS study_task_sets (
    id TEXT PRIMARY KEY,
    knowledge_node_id TEXT REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    knowledge_node_code TEXT,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('draft','published','archived')) DEFAULT 'draft',
    source_document_id TEXT,
    source_document_title TEXT,
    provenance_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(provenance_json)),
    generation_status TEXT NOT NULL DEFAULT 'ok' CHECK(generation_status IN ('ok','model_unavailable')),
    generation_note TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS study_tasks (
    id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL REFERENCES study_task_sets(id) ON DELETE CASCADE,
    task_type TEXT NOT NULL CHECK(task_type IN ('knowledge_card','self_check')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    title TEXT,
    content TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(detail_json)),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('original_excerpt','ai_summary','ai_generated')),
    provenance_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(provenance_json)),
    status TEXT NOT NULL CHECK(status IN ('draft','published','done','skipped')) DEFAULT 'draft',
    result_json TEXT CHECK(result_json IS NULL OR json_valid(result_json)),
    done_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_study_tasks_set ON study_tasks(set_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_study_task_sets_node ON study_task_sets(knowledge_node_id, status);

INSERT OR IGNORE INTO schema_migrations(version,applied_at)
VALUES(48,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
