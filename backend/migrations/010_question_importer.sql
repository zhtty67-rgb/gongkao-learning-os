PRAGMA foreign_keys=OFF;
BEGIN IMMEDIATE;

-- 1. Create question_passages table
CREATE TABLE IF NOT EXISTS question_passages (
  id TEXT PRIMARY KEY,
  source_document_id TEXT,
  source_document_version_id TEXT,
  source_page_start INTEGER,
  source_page_end INTEGER,
  source_locator TEXT,
  content TEXT NOT NULL,
  assets_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(assets_json)),
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  created_at TEXT NOT NULL
);

-- 2. Create question_import_jobs table
CREATE TABLE IF NOT EXISTS question_import_jobs (
  id TEXT PRIMARY KEY,
  source_document_id TEXT NOT NULL,
  source_document_version_id TEXT,
  filename TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL CHECK(status IN ('queued', 'extracting', 'matching_answers', 'classifying', 'validating', 'needs_review', 'ready_to_publish', 'publishing', 'completed', 'failed')),
  stage TEXT NOT NULL DEFAULT 'queued',
  total_candidates INTEGER NOT NULL DEFAULT 0,
  parsed_questions INTEGER NOT NULL DEFAULT 0,
  validated_questions INTEGER NOT NULL DEFAULT 0,
  needs_review INTEGER NOT NULL DEFAULT 0,
  published_questions INTEGER NOT NULL DEFAULT 0,
  failed_questions INTEGER NOT NULL DEFAULT 0,
  auto_accepted_count INTEGER NOT NULL DEFAULT 0,
  review_reasons_summary TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(review_reasons_summary)),
  error TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 3. Create question_import_drafts table
CREATE TABLE IF NOT EXISTS question_import_drafts (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES question_import_jobs(id) ON DELETE CASCADE,
  question_number INTEGER NOT NULL,
  raw_question_number_str TEXT,
  passage_id TEXT REFERENCES question_passages(id) ON DELETE SET NULL,
  passage_text TEXT,
  subject TEXT NOT NULL DEFAULT '行测',
  module TEXT NOT NULL DEFAULT '资料分析',
  module_source TEXT NOT NULL DEFAULT 'heading_rule',
  stem TEXT NOT NULL,
  stem_assets_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(stem_assets_json)),
  options_json TEXT NOT NULL CHECK(json_valid(options_json)),
  option_assets_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(option_assets_json)),
  answer TEXT CHECK(answer IS NULL OR answer IN ('A','B','C','D')),
  answer_source TEXT,
  answer_matched INTEGER NOT NULL DEFAULT 0 CHECK(answer_matched IN (0,1)),
  explanation TEXT NOT NULL DEFAULT '',
  explanation_source TEXT,
  knowledge_node_id TEXT,
  knowledge_node_code TEXT,
  knowledge_confidence REAL DEFAULT 0.0,
  knowledge_candidates_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(knowledge_candidates_json)),
  skill_id TEXT,
  skill_code TEXT,
  skill_confidence REAL DEFAULT 0.0,
  skill_candidates_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(skill_candidates_json)),
  skill_bindings_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(skill_bindings_json)),
  classification_provenance_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(classification_provenance_json)),
  validation_status TEXT NOT NULL DEFAULT 'PENDING' CHECK(validation_status IN ('PENDING', 'AUTO_ACCEPTED', 'ACCEPTED_WITH_AUDIT', 'NEEDS_REVIEW', 'READY_TO_PUBLISH', 'PUBLISHED', 'REJECTED')),
  review_reasons_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(review_reasons_json)),
  source_document_id TEXT NOT NULL,
  source_document_version_id TEXT,
  source_page INTEGER,
  source_block_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_block_ids_json)),
  source_locator TEXT,
  content_fingerprint TEXT NOT NULL,
  published_question_id TEXT REFERENCES questions(id) ON DELETE SET NULL,
  reviewed_by TEXT,
  reviewed_at TEXT,
  review_comment TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- 4. Add columns to questions table if not already present
ALTER TABLE questions ADD COLUMN passage_id TEXT REFERENCES question_passages(id) ON DELETE SET NULL;
ALTER TABLE questions ADD COLUMN stem_assets_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(stem_assets_json));
ALTER TABLE questions ADD COLUMN option_assets_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(option_assets_json));
ALTER TABLE questions ADD COLUMN source_document_id TEXT;
ALTER TABLE questions ADD COLUMN source_document_version_id TEXT;
ALTER TABLE questions ADD COLUMN source_page INTEGER;
ALTER TABLE questions ADD COLUMN source_block_ids_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(source_block_ids_json));
ALTER TABLE questions ADD COLUMN source_locator TEXT;
ALTER TABLE questions ADD COLUMN content_fingerprint TEXT;

-- 5. Indexes
CREATE INDEX IF NOT EXISTS idx_qij_status ON question_import_jobs(status);
CREATE INDEX IF NOT EXISTS idx_qid_job_status ON question_import_drafts(job_id, validation_status);
CREATE INDEX IF NOT EXISTS idx_qid_fingerprint ON question_import_drafts(content_fingerprint);
CREATE INDEX IF NOT EXISTS idx_questions_fingerprint ON questions(content_fingerprint);
CREATE INDEX IF NOT EXISTS idx_questions_source_doc ON questions(source_document_id);
CREATE INDEX IF NOT EXISTS idx_questions_passage ON questions(passage_id);

-- 6. Record migration
INSERT INTO schema_migrations VALUES (10, strftime('%Y-%m-%dT%H:%M:%fZ','now'));

COMMIT;
PRAGMA foreign_keys=ON;
