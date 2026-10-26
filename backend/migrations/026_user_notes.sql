BEGIN IMMEDIATE;

-- Migration 026: User Personal Notes & Reflection System (我的笔记／感悟)
-- Stores personal thoughts, node notes, dialogue clippings, and shenlun reflection links.
-- Includes optimistic concurrency protection (version INTEGER NOT NULL DEFAULT 1).
-- Does NOT mutate ground truth textbook explanations, attempts, or mastery scores.

CREATE TABLE IF NOT EXISTS user_notes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL DEFAULT 'default_user',
    note_type TEXT NOT NULL CHECK(note_type IN ('question', 'knowledge_node', 'dialogue_clipping', 'shenlun_summary')),
    content TEXT NOT NULL,
    title TEXT,
    
    -- Question and attempt association
    question_id TEXT REFERENCES questions(id) ON DELETE SET NULL,
    attempt_id TEXT REFERENCES attempts(id) ON DELETE SET NULL,
    
    -- Knowledge tree node association
    knowledge_node_id TEXT REFERENCES knowledge_nodes(id) ON DELETE SET NULL,
    knowledge_node_code TEXT,
    module TEXT,
    
    -- Review dialogue clipping / source provenance
    source_type TEXT NOT NULL DEFAULT 'manual' CHECK(source_type IN ('manual', 'review_ai_message', 'review_user_message', 'shenlun_dimension')),
    source_message_id TEXT,
    source_quote TEXT,
    
    -- Shenlun practice linkage
    shenlun_session_id TEXT REFERENCES shenlun_sessions(id) ON DELETE CASCADE,
    shenlun_dimension TEXT,
    
    -- Optimistic concurrency version
    version INTEGER NOT NULL DEFAULT 1,
    
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_user_notes_user_type ON user_notes(user_id, note_type);
CREATE INDEX IF NOT EXISTS idx_user_notes_question ON user_notes(question_id);
CREATE INDEX IF NOT EXISTS idx_user_notes_attempt ON user_notes(attempt_id);
CREATE INDEX IF NOT EXISTS idx_user_notes_kn_node ON user_notes(knowledge_node_id);
CREATE INDEX IF NOT EXISTS idx_user_notes_source_msg ON user_notes(source_message_id);

INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (26, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
