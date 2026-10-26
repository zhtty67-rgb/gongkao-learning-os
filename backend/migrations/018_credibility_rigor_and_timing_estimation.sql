PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

-- Migration 018: Credibility rigor, timing estimation flags, and exposure tracking integrity
-- 1. Explicitly distinguish measured elapsed time from distributed/estimated time
ALTER TABLE attempts ADD COLUMN is_time_estimated INTEGER NOT NULL DEFAULT 0 CHECK(is_time_estimated IN (0, 1));
ALTER TABLE attempts ADD COLUMN time_estimation_method TEXT;

INSERT OR IGNORE INTO schema_migrations VALUES (18, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
COMMIT;
