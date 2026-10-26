-- Migration 028: non-destructive attempt answer-key calibration.
--
-- The repair engine used to rewrite attempts.correct when the standard answer key changed.
-- That destroyed the historical fact of "what was judged at the time". From now on the
-- original judgment is immutable; a changed standard answer is recorded as a separate
-- correction on the attempt row:
--
--   corrected_correct        1/0 verdict under the CURRENT standard answer (NULL = never corrected)
--   correction_basis         human-readable reason (answer-key recalibration)
--   answer_key_fingerprint   stable short hash of (question_id, standard answer used)
--   corrected_at             ISO timestamp of the calibration
--
-- All statistics consumers read the effective verdict via
--   COALESCE(attempts.corrected_correct, attempts.correct)
-- so uncorrected attempts keep their original judgment and corrected ones use the
-- calibrated verdict. attempts.selected_answer and attempts.correct are never rewritten.

ALTER TABLE attempts ADD COLUMN corrected_correct INTEGER;
ALTER TABLE attempts ADD COLUMN correction_basis TEXT;
ALTER TABLE attempts ADD COLUMN answer_key_fingerprint TEXT;
ALTER TABLE attempts ADD COLUMN corrected_at TEXT;

INSERT OR REPLACE INTO schema_migrations (version, applied_at) VALUES (28, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
