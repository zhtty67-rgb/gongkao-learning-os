BEGIN IMMEDIATE;

-- Review pipeline columns for teacher diagnoses.
-- review_status: 'legacy' = rows written before this migration existed;
--                'pending'  = local suspicions persisted, AI review not yet applied;
--                'reviewed' = AI semantic review applied and program-verified;
--                'unavailable' = AI review could not run / output unusable (honest degradation).
ALTER TABLE shenlun_teacher_diagnoses ADD COLUMN suspicions_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE shenlun_teacher_diagnoses ADD COLUMN evidence_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE shenlun_teacher_diagnoses ADD COLUMN ai_review_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE shenlun_teacher_diagnoses ADD COLUMN review_status TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE shenlun_teacher_diagnoses ADD COLUMN answer_hash TEXT NOT NULL DEFAULT '';

INSERT INTO schema_migrations VALUES (22, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
