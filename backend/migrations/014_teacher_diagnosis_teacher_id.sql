BEGIN IMMEDIATE;

-- Multi-teacher support: tag each diagnosis row with its teacher id
ALTER TABLE shenlun_teacher_diagnoses ADD COLUMN teacher_id TEXT NOT NULL DEFAULT '';

-- Backfill: all existing rows were produced by the feiyang engine
UPDATE shenlun_teacher_diagnoses SET teacher_id = 'teacher_feiyang' WHERE teacher_id = '';

INSERT INTO schema_migrations VALUES (14, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
