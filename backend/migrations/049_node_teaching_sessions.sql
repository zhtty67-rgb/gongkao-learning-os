BEGIN IMMEDIATE;

-- Migration 049: 长期教学记录（节点锚定教学对话跨会话持久化）
-- 补齐 node_teacher_chat（答疑/自查/费曼/专项/苏格拉底）的服务端落库——
-- 此前仅前端 sessionStorage（8 轮回传），换会话即丢。
-- 纪律：本表只存教学对话与教学沉淀；不写 attempts/mastery（与 048 同一隔离原则）。

CREATE TABLE IF NOT EXISTS node_teaching_sessions (
    id TEXT PRIMARY KEY,
    knowledge_node_id TEXT NOT NULL REFERENCES knowledge_nodes(id) ON DELETE CASCADE,
    mode TEXT NOT NULL CHECK(mode IN ('qa','self_check','feynman','breakthrough','concept','socratic')),
    status TEXT NOT NULL CHECK(status IN ('active','closed')) DEFAULT 'active',
    title TEXT,
    created_at TEXT NOT NULL,
    last_message_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS node_teaching_turns (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES node_teaching_sessions(id) ON DELETE CASCADE,
    seq INTEGER NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('user','assistant')),
    content TEXT NOT NULL,
    phase TEXT,
    status TEXT NOT NULL CHECK(status IN ('completed','failed')) DEFAULT 'completed',
    meta_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(meta_json)),
    created_at TEXT NOT NULL,
    UNIQUE(session_id, seq)
);

CREATE INDEX IF NOT EXISTS idx_nts_node ON node_teaching_sessions(knowledge_node_id, mode, status);
CREATE INDEX IF NOT EXISTS idx_ntt_session ON node_teaching_turns(session_id, seq);

INSERT OR IGNORE INTO schema_migrations(version,applied_at)
VALUES(49,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
