-- Preserve stable IDs/bindings while distinguishing a topic from its sole leaf.
BEGIN IMMEDIATE;
UPDATE knowledge_nodes
SET name='总体国家安全观的课程要点'
WHERE id='political_theory.thought.security.topic_23' AND name='总体国家安全观';
INSERT OR IGNORE INTO schema_migrations(version,applied_at)
VALUES(39,strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
