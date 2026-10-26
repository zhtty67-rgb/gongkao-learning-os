"""Import Job Service for Question Bank Importer (QI1).

Orchestrates:
- Import job lifecycle (queued -> extracting -> matching_answers -> classifying -> validating -> completed).
- Staging in question_import_drafts (Draft vs Formal Question separation).
- Human review queue operations (accept, modify, reject).
- Strict Publish Gate (no uncertain answers published into gradable questions).
- Provenance preservation and idempotent re-import.
- Reclassification for unmapped/low-confidence drafts.
"""
from __future__ import annotations

import json
import logging
from typing import Any
from uuid import uuid4
import sqlite3

from ...ai.gateway import ModelGateway
from .classifier import QuestionClassifier
from .extractor import CANONICAL_MODULES, QuestionExtractor
from .matcher import AnswerMatcher
from .schemas import (
    BatchPublishInput,
    ClassificationProvenance,
    DraftQuestionDTO,
    ImportJobDTO,
    JobStatus,
    ParsedDocument,
    PublishResultDTO,
    ReclassifyInput,
    ReclassifyResultDTO,
    ReviewDecisionInput,
    ReviewItemDTO,
    ReviewReason,
    SkillBindingItem,
    ValidationStatus,
    utc_now_iso,
)

logger = logging.getLogger(__name__)



def _iter_asset_refs(stem_assets: Any, option_assets: Any) -> list[Any]:
    """Collect every asset reference from stem/option asset structures defensively."""
    refs: list[Any] = []
    if isinstance(stem_assets, list):
        refs.extend(stem_assets)
    if isinstance(option_assets, dict):
        for v in option_assets.values():
            if isinstance(v, list):
                refs.extend(v)
            else:
                refs.append(v)
    return refs


class QuestionImportService:
    """Core domain service managing the question import lifecycle."""

    def __init__(self, db: sqlite3.Connection, gateway: ModelGateway | None = None):
        self.db = db
        self.gateway = gateway or ModelGateway()
        self.classifier = QuestionClassifier(db, self.gateway)

    # =========================================================================
    # Job Lifecycle
    # =========================================================================

    def create_job(
        self,
        source_document_id: str,
        source_document_version_id: str | None = None,
        filename: str = '',
        metadata: dict[str, Any] | None = None,
    ) -> ImportJobDTO:
        job_id = f"qij_{uuid4().hex[:12]}"
        now = utc_now_iso()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)

        self.db.execute(
            "INSERT INTO question_import_jobs ("
            "  id, source_document_id, source_document_version_id, filename,"
            "  status, stage, total_candidates, parsed_questions, validated_questions,"
            "  needs_review, published_questions, failed_questions, auto_accepted_count,"
            "  review_reasons_summary, metadata_json, created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, 0, '{}', ?, ?, ?)",
            (job_id, source_document_id, source_document_version_id, filename,
             JobStatus.QUEUED.value, 'queued', meta_json, now, now),
        )
        self.db.commit()
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> ImportJobDTO:
        row = self.db.execute("SELECT * FROM question_import_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise ValueError(f"Job not found: {job_id}")
        return ImportJobDTO(
            id=row["id"],
            source_document_id=row["source_document_id"],
            source_document_version_id=row["source_document_version_id"],
            filename=row["filename"],
            status=JobStatus(row["status"]),
            stage=row["stage"],
            total_candidates=row["total_candidates"],
            parsed_questions=row["parsed_questions"],
            validated_questions=row["validated_questions"],
            needs_review=row["needs_review"],
            published_questions=row["published_questions"],
            failed_questions=row["failed_questions"],
            auto_accepted_count=row["auto_accepted_count"],
            review_reasons_summary=json.loads(row["review_reasons_summary"]),
            error=row["error"],
            metadata=json.loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_jobs(self, limit: int = 50) -> list[ImportJobDTO]:
        rows = self.db.execute(
            "SELECT * FROM question_import_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
            ImportJobDTO(
                id=r["id"],
                source_document_id=r["source_document_id"],
                source_document_version_id=r["source_document_version_id"],
                filename=r["filename"],
                status=JobStatus(r["status"]),
                stage=r["stage"],
                total_candidates=r["total_candidates"],
                parsed_questions=r["parsed_questions"],
                validated_questions=r["validated_questions"],
                needs_review=r["needs_review"],
                published_questions=r["published_questions"],
                failed_questions=r["failed_questions"],
                auto_accepted_count=r["auto_accepted_count"],
                review_reasons_summary=json.loads(r["review_reasons_summary"]),
                error=r["error"],
                metadata=json.loads(r["metadata_json"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    async def process_job(
        self,
        job_id: str,
        parsed_doc: ParsedDocument,
        answer_parsed_doc: ParsedDocument | None = None,
    ) -> ImportJobDTO:
        """Executes full import pipeline from ParsedDocument into draft staging."""
        now = utc_now_iso()
        self.db.execute(
            "UPDATE question_import_jobs SET status=?, stage=?, updated_at=? WHERE id=?",
            (JobStatus.EXTRACTING.value, 'extracting', now, job_id),
        )
        self.db.commit()

        try:
            # 1. Extraction
            extractor = QuestionExtractor(parsed_doc)
            ext_res = extractor.extract()

            all_answer_keys = list(ext_res.answer_keys)
            all_explanations = list(ext_res.explanations)

            # If separate answer/explanation PDF is provided, extract and merge
            if answer_parsed_doc is not None:
                ans_extractor = QuestionExtractor(answer_parsed_doc)
                ans_res = ans_extractor.extract()
                all_answer_keys.extend(ans_res.answer_keys)
                all_explanations.extend(ans_res.explanations)

            # Save passages to DB
            for p in ext_res.passages:
                self.db.execute(
                    "INSERT OR REPLACE INTO question_passages ("
                    "  id, source_document_id, source_document_version_id, source_page_start, source_page_end,"
                    "  source_locator, content, assets_json, metadata_json, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        p.id, p.source_document_id, p.source_document_version_id,
                        p.source_page_start, p.source_page_end, p.source_locator,
                        p.content, json.dumps(p.assets, ensure_ascii=False),
                        json.dumps(p.metadata, ensure_ascii=False), now,
                    ),
                )

            # 2. Matching Answers
            self.db.execute(
                "UPDATE question_import_jobs SET status=?, stage=?, updated_at=? WHERE id=?",
                (JobStatus.MATCHING_ANSWERS.value, 'matching_answers', utc_now_iso(), job_id),
            )
            self.db.commit()

            matcher = AnswerMatcher(all_answer_keys, all_explanations)
            match_results = matcher.match_all(ext_res.questions)
            match_by_qnum = {m.question_number: m for m in match_results}

            # 3. Classifying and Staging Drafts
            self.db.execute(
                "UPDATE question_import_jobs SET status=?, stage=?, updated_at=? WHERE id=?",
                (JobStatus.CLASSIFYING.value, 'classifying', utc_now_iso(), job_id),
            )
            self.db.commit()

            review_reasons_counts: dict[str, int] = {}
            auto_accepted = 0
            needs_review = 0
            validated = 0

            for q in ext_res.questions:
                m_res = match_by_qnum.get(q.question_number)
                has_critical_error = bool(m_res and any(
                    r in (ReviewReason.ANSWER_MISSING, ReviewReason.ANSWER_CONFLICT, ReviewReason.OPTION_PARSE_FAILED)
                    for r in m_res.review_reasons
                ))

                explanation_text = m_res.explanation if m_res else q.inline_explanation or ''
                class_res = await self.classifier.classify(
                    module=q.module,
                    stem=q.stem,
                    options=q.options,
                    explanation=explanation_text,
                    has_critical_error=has_critical_error,
                )

                # Combine review reasons
                all_reasons = []
                if m_res:
                    all_reasons.extend(m_res.review_reasons)
                all_reasons.extend(class_res.added_review_reasons)

                seen_r = set()
                deduped_reasons = []
                for r in all_reasons:
                    r_str = r.value if isinstance(r, ReviewReason) else str(r)
                    if r_str not in seen_r:
                        seen_r.add(r_str)
                        deduped_reasons.append(r_str)
                        review_reasons_counts[r_str] = review_reasons_counts.get(r_str, 0) + 1

                val_status = class_res.validation_status
                if deduped_reasons:
                    val_status = ValidationStatus.NEEDS_REVIEW

                if val_status == ValidationStatus.AUTO_ACCEPTED:
                    auto_accepted += 1
                    validated += 1
                elif val_status == ValidationStatus.ACCEPTED_WITH_AUDIT:
                    validated += 1
                elif val_status == ValidationStatus.NEEDS_REVIEW:
                    needs_review += 1

                draft_id = f"qid_{uuid4().hex[:12]}"
                resolved_ans = m_res.answer if m_res else q.inline_answer
                ans_source = m_res.answer_source if m_res else 'unresolved'
                ans_matched = m_res.answer_matched if m_res else 0
                exp_source = m_res.explanation_source if m_res else 'none'

                self.db.execute(
                    "INSERT OR REPLACE INTO question_import_drafts ("
                    "  id, job_id, question_number, raw_question_number_str, passage_id, passage_text,"
                    "  subject, module, module_source, stem, stem_assets_json, options_json, option_assets_json,"
                    "  answer, answer_source, answer_matched, explanation, explanation_source,"
                    "  knowledge_node_id, knowledge_node_code, knowledge_confidence, knowledge_candidates_json,"
                    "  skill_id, skill_code, skill_confidence, skill_candidates_json, skill_bindings_json,"
                    "  classification_provenance_json, validation_status, review_reasons_json,"
                    "  source_document_id, source_document_version_id, source_page, source_block_ids_json,"
                    "  source_locator, content_fingerprint, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        draft_id,
                        job_id,
                        q.question_number,
                        q.raw_question_number_str,
                        q.passage_id,
                        q.passage_text,
                        q.subject,
                        q.module,
                        q.module_source,
                        q.stem,
                        json.dumps(q.stem_assets, ensure_ascii=False),
                        json.dumps(q.options, ensure_ascii=False),
                        json.dumps(q.option_assets, ensure_ascii=False),
                        resolved_ans,
                        ans_source,
                        ans_matched,
                        explanation_text,
                        exp_source,
                        class_res.knowledge_node_id,
                        class_res.knowledge_node_code,
                        class_res.knowledge_confidence,
                        json.dumps(class_res.knowledge_candidates, ensure_ascii=False),
                        class_res.skill_id,
                        class_res.skill_code,
                        class_res.skill_confidence,
                        json.dumps(class_res.skill_candidates, ensure_ascii=False),
                        json.dumps([b.model_dump() for b in class_res.skill_bindings], ensure_ascii=False),
                        json.dumps(class_res.provenance.model_dump(), ensure_ascii=False),
                        val_status.value,
                        json.dumps(deduped_reasons, ensure_ascii=False),
                        q.source_document_id,
                        q.source_document_version_id,
                        q.source_page,
                        json.dumps(q.source_block_ids, ensure_ascii=False),
                        q.source_locator,
                        q.content_fingerprint,
                        now,
                        now,
                    ),
                )

            # 4. Finalize Job Status
            final_status = JobStatus.NEEDS_REVIEW if needs_review > 0 else JobStatus.READY_TO_PUBLISH
            final_stage = 'validated'
            self.db.execute(
                "UPDATE question_import_jobs SET "
                "  status=?, stage=?, total_candidates=?, parsed_questions=?, validated_questions=?,"
                "  needs_review=?, auto_accepted_count=?, review_reasons_summary=?, updated_at=? "
                "WHERE id=?",
                (
                    final_status.value,
                    final_stage,
                    len(ext_res.questions),
                    len(ext_res.questions),
                    validated,
                    needs_review,
                    auto_accepted,
                    json.dumps(review_reasons_counts, ensure_ascii=False),
                    utc_now_iso(),
                    job_id,
                ),
            )
            self.db.commit()
            return self.get_job(job_id)

        except Exception as exc:
            logger.exception("Failed processing import job %s: %s", job_id, exc)
            self.db.execute(
                "UPDATE question_import_jobs SET status=?, stage='failed', error=?, updated_at=? WHERE id=?",
                (JobStatus.FAILED.value, str(exc), utc_now_iso(), job_id),
            )
            self.db.commit()
            raise

    # =========================================================================
    # Review Queue Operations
    # =========================================================================

    def get_review_items(
        self,
        job_id: str,
        status_filter: ValidationStatus | None = None,
        reason_filter: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ReviewItemDTO]:
        conditions = ["job_id = ?"]
        params: list[Any] = [job_id]

        if status_filter:
            conditions.append("validation_status = ?")
            params.append(status_filter.value)
        else:
            # Default to showing items needing attention first
            pass

        if reason_filter:
            conditions.append("review_reasons_json LIKE ?")
            params.append(f"%{reason_filter}%")

        where_clause = " AND ".join(conditions)
        query = (
            f"SELECT * FROM question_import_drafts "
            f"WHERE {where_clause} "
            f"ORDER BY CASE WHEN validation_status='NEEDS_REVIEW' THEN 0 ELSE 1 END, question_number ASC "
            f"LIMIT ? OFFSET ?"
        )
        params.extend([limit, offset])

        rows = self.db.execute(query, tuple(params)).fetchall()
        items = []
        for r in rows:
            items.append(
                ReviewItemDTO(
                    draft_id=r["id"],
                    job_id=r["job_id"],
                    question_number=r["question_number"],
                    stem=r["stem"],
                    stem_assets=json.loads(r["stem_assets_json"]) if r["stem_assets_json"] else [],
                    options=json.loads(r["options_json"]) if r["options_json"] else {},
                    option_assets=json.loads(r["option_assets_json"]) if r["option_assets_json"] else {},
                    passage_text=r["passage_text"],
                    answer=r["answer"],
                    answer_source=r["answer_source"],
                    answer_matched=r["answer_matched"] or 0,
                    explanation=r["explanation"] or '',
                    module=r["module"],
                    suggested_knowledge_node_code=r["knowledge_node_code"],
                    suggested_skill_code=r["skill_code"],
                    confidence=r["knowledge_confidence"] or 0.0,
                    review_reasons=json.loads(r["review_reasons_json"]) if r["review_reasons_json"] else [],
                    source_page=r["source_page"],
                    source_locator=r["source_locator"],
                    validation_status=ValidationStatus(r["validation_status"]),
                )
            )
        return items

    def get_draft(self, draft_id: str) -> DraftQuestionDTO:
        r = self.db.execute("SELECT * FROM question_import_drafts WHERE id = ?", (draft_id,)).fetchone()
        if not r:
            raise ValueError(f"Draft not found: {draft_id}")
        return self._row_to_draft_dto(r)

    def apply_review_decision(
        self,
        draft_id: str,
        decision: ReviewDecisionInput,
        reviewer: str = 'human_reviewer',
    ) -> DraftQuestionDTO:
        draft = self.get_draft(draft_id)
        now = utc_now_iso()

        if decision.action == 'reject':
            self.db.execute(
                "UPDATE question_import_drafts SET "
                "  validation_status=?, reviewed_by=?, reviewed_at=?, review_comment=?, updated_at=? "
                "WHERE id=?",
                (ValidationStatus.REJECTED.value, reviewer, now, decision.comment, now, draft_id),
            )
        elif decision.action == 'accept':
            # Accept requires valid answer
            if not draft.answer:
                raise ValueError("Cannot accept question without an authoritative answer.")
            self.db.execute(
                "UPDATE question_import_drafts SET "
                "  validation_status=?, review_reasons_json='[]', reviewed_by=?, reviewed_at=?, review_comment=?, updated_at=? "
                "WHERE id=?",
                (ValidationStatus.READY_TO_PUBLISH.value, reviewer, now, decision.comment, now, draft_id),
            )
        elif decision.action == 'modify':
            # Apply user overrides
            ans = decision.answer or draft.answer
            if not ans or ans not in ('A', 'B', 'C', 'D'):
                raise ValueError("Modified answer must be one of A, B, C, D.")
            exp = decision.explanation if decision.explanation is not None else draft.explanation
            mod = decision.module or draft.module
            kn_code = decision.knowledge_node_code or draft.knowledge_node_code
            sk_code = decision.skill_code or draft.skill_code

            # Update skill bindings if skill_code changed
            skill_bindings = list(draft.skill_bindings)
            if sk_code:
                skill_bindings = [
                    SkillBindingItem(
                        learning_skill_id=sk_code,
                        skill_code=sk_code,
                        skill_name=sk_code,
                        knowledge_node_code=kn_code,
                        role="primary",
                        weight=1.0,
                    )
                ]

            self.db.execute(
                "UPDATE question_import_drafts SET "
                "  answer=?, answer_source='human_review', answer_matched=1, explanation=?,"
                "  module=?, knowledge_node_code=?, skill_code=?, skill_bindings_json=?,"
                "  validation_status=?, review_reasons_json='[]', reviewed_by=?, reviewed_at=?, review_comment=?, updated_at=? "
                "WHERE id=?",
                (
                    ans,
                    exp,
                    mod,
                    kn_code,
                    sk_code,
                    json.dumps([b.model_dump() for b in skill_bindings], ensure_ascii=False),
                    ValidationStatus.READY_TO_PUBLISH.value,
                    reviewer,
                    now,
                    decision.comment,
                    now,
                    draft_id,
                ),
            )

        self._refresh_job_counts(draft.job_id)
        self.db.commit()
        return self.get_draft(draft_id)

    # =========================================================================
    # Publish Gate
    # =========================================================================

    def publish_drafts(self, job_id: str, draft_ids: list[str] | None = None) -> PublishResultDTO:
        """Publishes validated drafts into the formal question bank (Publish Gate)."""
        job = self.get_job(job_id)
        now = utc_now_iso()

        query = (
            "SELECT * FROM question_import_drafts "
            "WHERE job_id = ? AND validation_status IN ('AUTO_ACCEPTED', 'ACCEPTED_WITH_AUDIT', 'READY_TO_PUBLISH')"
        )
        params: list[Any] = [job_id]
        if draft_ids:
            placeholders = ",".join("?" for _ in draft_ids)
            query += f" AND id IN ({placeholders})"
            params.extend(draft_ids)

        draft_rows = self.db.execute(query, tuple(params)).fetchall()

        published_ids: list[str] = []
        errors: list[dict[str, Any]] = []
        skipped_count = 0

        for r in draft_rows:
            did = r["id"]
            q_num = r["question_number"]
            stem = r["stem"].strip()
            options = json.loads(r["options_json"])
            ans = r["answer"]
            ans_matched = r["answer_matched"]
            ans_source = r["answer_source"]
            mod = r["module"]
            src_doc = r["source_document_id"]
            src_loc = r["source_locator"]
            fp = r["content_fingerprint"]

            # --- PUBLISH GATE VERIFICATION ---
            # 1. Stem valid
            if not stem:
                errors.append({"draft_id": did, "question_number": q_num, "error": "Stem is empty"})
                continue

            # 2. Options valid (at least A, B, C, D)
            if not all(k in options for k in ('A', 'B', 'C', 'D')):
                option_assets = json.loads(r["option_assets_json"])
                if not all(k in option_assets for k in ('A', 'B', 'C', 'D')):
                    errors.append({"draft_id": did, "question_number": q_num, "error": "Incomplete options"})
                    continue

            # 3. Answer authoritative & matched (NEVER MODEL GUESS)
            if not ans or ans not in ('A', 'B', 'C', 'D'):
                errors.append({"draft_id": did, "question_number": q_num, "error": "Missing or invalid official answer"})
                continue
            if ans_matched != 1:
                errors.append({"draft_id": did, "question_number": q_num, "error": "Answer matching unconfirmed"})
                continue
            if ans_source not in ('answer_key', 'inline_explanation', 'inline_and_key', 'pdf_explanation', 'human_review'):
                errors.append({"draft_id": did, "question_number": q_num, "error": f"Invalid answer source: {ans_source}"})
                continue

            # 4. Source traceable
            if not src_doc or not src_loc:
                errors.append({"draft_id": did, "question_number": q_num, "error": "Missing source provenance"})
                continue

            # 5. Module valid
            if mod not in CANONICAL_MODULES:
                errors.append({"draft_id": did, "question_number": q_num, "error": f"Invalid module: {mod}"})
                continue

            # 5b. Asset refs must be normalized to the static assets mount.
            # Drafts may carry Hub document-asset URLs (/api/v1/documents/...) which
            # this app does not serve; publishing them verbatim breaks question images.
            try:
                _stem_assets = json.loads(r["stem_assets_json"]) if r["stem_assets_json"] else []
                _option_assets = json.loads(r["option_assets_json"]) if r["option_assets_json"] else {}
            except (TypeError, ValueError):
                errors.append({"draft_id": did, "question_number": q_num, "error": "Asset JSON unparseable"})
                continue
            _bad_refs = [
                a for a in _iter_asset_refs(_stem_assets, _option_assets)
                if not (isinstance(a, str) and a.startswith("/assets/questions/"))
            ]
            if _bad_refs:
                errors.append({"draft_id": did, "question_number": q_num,
                               "error": f"Unnormalized asset refs: {_bad_refs[:3]}"})
                continue

            # 6. Skill binding must resolve to an existing authoritative LF1 skill.
            # Importing a question is never allowed to expand the Learning Framework.
            kn_code = r["knowledge_node_code"]
            raw_bindings = json.loads(r["skill_bindings_json"]) if r["skill_bindings_json"] else []
            binding_specs = raw_bindings or [{
                "learning_skill_id": r["skill_id"],
                "skill_code": r["skill_code"],
                "knowledge_node_code": kn_code,
                "role": "primary",
                "weight": 1.0,
            }]
            resolved_bindings: list[dict[str, Any]] = []
            for binding in binding_specs:
                binding_kn_code = binding.get("knowledge_node_code") or kn_code
                requested_skill = binding.get("learning_skill_id") or binding.get("skill_code")
                skill_row = self.db.execute(
                    "SELECT id, code, knowledge_node_code FROM learning_skills "
                    "WHERE knowledge_node_code=? AND (? IS NULL OR id=? OR code=?) "
                    "ORDER BY id LIMIT 1",
                    (binding_kn_code, requested_skill, requested_skill, requested_skill),
                ).fetchone()
                if skill_row:
                    resolved_bindings.append({
                        "learning_skill_id": skill_row["id"],
                        "knowledge_node_code": skill_row["knowledge_node_code"],
                        "role": binding.get("role", "primary"),
                        "weight": float(binding.get("weight", 1.0)),
                    })

            if not resolved_bindings:
                reasons = json.loads(r["review_reasons_json"]) if r["review_reasons_json"] else []
                if ReviewReason.SKILL_UNMAPPED.value not in reasons:
                    reasons.append(ReviewReason.SKILL_UNMAPPED.value)
                self.db.execute(
                    "UPDATE question_import_drafts SET validation_status=?, review_reasons_json=?, updated_at=? WHERE id=?",
                    (ValidationStatus.NEEDS_REVIEW.value, json.dumps(reasons, ensure_ascii=False), now, did),
                )
                errors.append({"draft_id": did, "question_number": q_num, "error": ReviewReason.SKILL_UNMAPPED.value})
                continue

            # --- IDEMPOTENCY CHECK ---
            existing_q = self.db.execute(
                "SELECT id FROM questions WHERE content_fingerprint = ?", (fp,)
            ).fetchone()

            if existing_q:
                # Already published, skip duplicate creation and link draft
                pub_qid = existing_q["id"]
                skipped_count += 1
            else:
                # Generate new formal question
                pub_qid = f"q_{uuid4().hex[:12]}"
                self.db.execute(
                    "INSERT INTO questions ("
                    "  id, source, year, exam_type, subject, module, stem, options_json, difficulty,"
                    "  answer, explanation, estimated_seconds, is_verified, passage_id, stem_assets_json,"
                    "  option_assets_json, source_document_id, source_document_version_id, source_page,"
                    "  source_block_ids_json, source_locator, content_fingerprint"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        pub_qid,
                        f"PDF_IMPORT:{job.filename or src_doc}",
                        2026,
                        "真题导入",
                        r["subject"],
                        mod,
                        stem,
                        r["options_json"],
                        0.5,
                        ans,
                        r["explanation"] or "暂无详细解析",
                        60,
                        1,  # is_verified = 1
                        r["passage_id"],
                        r["stem_assets_json"],
                        r["option_assets_json"],
                        src_doc,
                        r["source_document_version_id"],
                        r["source_page"],
                        r["source_block_ids_json"],
                        src_loc,
                        fp,
                    ),
                )

                # Bind knowledge map
                kn_code = r["knowledge_node_code"] or f"gongkao.xingce.{r['module']}"
                slug = kn_code.split(".")[-1]

                mapped_skill_node_id = resolved_bindings[0]["learning_skill_id"]
                kn_id = mapped_skill_node_id if self.db.execute(
                    "SELECT 1 FROM knowledge_nodes WHERE id=?", (mapped_skill_node_id,)
                ).fetchone() else r["knowledge_node_id"]
                if not kn_id or not self.db.execute("SELECT id FROM knowledge_nodes WHERE id=?", (kn_id,)).fetchone():
                    kn_id = f"kn_{slug}"
                    self.db.execute(
                        "INSERT OR IGNORE INTO knowledge_nodes (id, parent_id, subject, module, name, node_type, weight, exam_priority) "
                        "VALUES (?, NULL, '行测', ?, ?, 'topic', 1.0, 1.0)",
                        (kn_id, r["module"], slug),
                    )
                self.db.execute(
                    "INSERT OR IGNORE INTO question_knowledge_map (question_id, knowledge_node_id, weight) "
                    "VALUES (?, ?, 1.0)",
                    (pub_qid, kn_id),
                )

                # Bind question skills
                for binding in resolved_bindings:
                    sk_id = binding["learning_skill_id"]
                    sk_kn_code = binding["knowledge_node_code"]
                    role = binding["role"]
                    weight = binding["weight"]
                    binding_id = f"qsb_{pub_qid}_{sk_id}_{role}"
                    self.db.execute(
                        "INSERT OR IGNORE INTO question_skill_bindings ("
                        "  id, question_id, learning_skill_id, knowledge_node_code, role, weight,"
                        "  provenance, status, metadata_json, created_at"
                        ") VALUES (?, ?, ?, ?, ?, ?, 'imported_published', 'active', '{}', ?)",
                        (binding_id, pub_qid, sk_id, sk_kn_code, role, weight, now),
                    )

            # Mark draft published
            self.db.execute(
                "UPDATE question_import_drafts SET validation_status=?, published_question_id=?, updated_at=? WHERE id=?",
                (ValidationStatus.PUBLISHED.value, pub_qid, now, did),
            )
            published_ids.append(pub_qid)

        self._refresh_job_counts(job_id)
        self.db.commit()

        return PublishResultDTO(
            job_id=job_id,
            total_drafts=len(draft_rows),
            published_count=len(published_ids) - skipped_count,
            skipped_count=skipped_count,
            failed_count=len(errors),
            published_question_ids=published_ids,
            errors=errors,
        )

    # =========================================================================
    # Reclassification
    # =========================================================================

    async def reclassify_drafts(self, payload: ReclassifyInput) -> ReclassifyResultDTO:
        """Reclassifies drafts without altering official answers or stem contents."""
        job_id = payload.job_id
        conditions = ["job_id = ?"]
        params: list[Any] = [job_id]

        if payload.draft_ids:
            placeholders = ",".join("?" for _ in payload.draft_ids)
            conditions.append(f"id IN ({placeholders})")
            params.extend(payload.draft_ids)
        elif payload.scope == 'low_confidence':
            conditions.append("(validation_status = 'NEEDS_REVIEW' OR knowledge_confidence < ?)")
            params.append(payload.confidence_threshold)
        elif payload.scope == 'unmapped':
            conditions.append("(knowledge_node_code IS NULL OR knowledge_node_code = 'UNMAPPED')")

        query = f"SELECT * FROM question_import_drafts WHERE {' AND '.join(conditions)}"
        rows = self.db.execute(query, tuple(params)).fetchall()

        reclassified_count = 0
        auto_accepted_count = 0
        needs_review_count = 0
        now = utc_now_iso()

        for r in rows:
            did = r["id"]
            stem = r["stem"]
            opts = json.loads(r["options_json"])
            exp = r["explanation"]
            mod = r["module"]

            class_res = await self.classifier.classify(
                module=mod,
                stem=stem,
                options=opts,
                explanation=exp,
                has_critical_error=bool(r["answer"] is None or r["answer_matched"] != 1),
            )

            status = class_res.validation_status
            if status == ValidationStatus.AUTO_ACCEPTED:
                auto_accepted_count += 1
            else:
                needs_review_count += 1

            self.db.execute(
                "UPDATE question_import_drafts SET "
                "  knowledge_node_id=?, knowledge_node_code=?, knowledge_confidence=?,"
                "  knowledge_candidates_json=?, skill_id=?, skill_code=?, skill_confidence=?,"
                "  skill_candidates_json=?, skill_bindings_json=?, classification_provenance_json=?,"
                "  validation_status=?, updated_at=? "
                "WHERE id=?",
                (
                    class_res.knowledge_node_id,
                    class_res.knowledge_node_code,
                    class_res.knowledge_confidence,
                    json.dumps(class_res.knowledge_candidates, ensure_ascii=False),
                    class_res.skill_id,
                    class_res.skill_code,
                    class_res.skill_confidence,
                    json.dumps(class_res.skill_candidates, ensure_ascii=False),
                    json.dumps([b.model_dump() for b in class_res.skill_bindings], ensure_ascii=False),
                    json.dumps(class_res.provenance.model_dump(), ensure_ascii=False),
                    status.value,
                    now,
                    did,
                ),
            )
            reclassified_count += 1

        self._refresh_job_counts(job_id)
        self.db.commit()

        return ReclassifyResultDTO(
            job_id=job_id,
            reclassified_count=reclassified_count,
            auto_accepted_count=auto_accepted_count,
            still_needs_review_count=needs_review_count,
        )

    # =========================================================================
    # Helpers
    # =========================================================================

    def _refresh_job_counts(self, job_id: str):
        stats = self.db.execute(
            "SELECT "
            "  COUNT(*) as total,"
            "  SUM(CASE WHEN validation_status = 'AUTO_ACCEPTED' THEN 1 ELSE 0 END) as auto_accepted,"
            "  SUM(CASE WHEN validation_status IN ('AUTO_ACCEPTED', 'ACCEPTED_WITH_AUDIT', 'READY_TO_PUBLISH') THEN 1 ELSE 0 END) as validated,"
            "  SUM(CASE WHEN validation_status = 'NEEDS_REVIEW' THEN 1 ELSE 0 END) as needs_review,"
            "  SUM(CASE WHEN validation_status = 'PUBLISHED' THEN 1 ELSE 0 END) as published "
            "FROM question_import_drafts WHERE job_id = ?",
            (job_id,),
        ).fetchone()

        total = stats["total"] or 0
        auto_accepted = stats["auto_accepted"] or 0
        validated = stats["validated"] or 0
        needs_review = stats["needs_review"] or 0
        published = stats["published"] or 0

        # Determine status
        if total > 0 and published == total:
            status = JobStatus.COMPLETED
        elif needs_review > 0:
            status = JobStatus.NEEDS_REVIEW
        elif validated > 0:
            status = JobStatus.READY_TO_PUBLISH
        else:
            status = JobStatus.COMPLETED if total == 0 else JobStatus.NEEDS_REVIEW

        self.db.execute(
            "UPDATE question_import_jobs SET "
            "  total_candidates=?, parsed_questions=?, validated_questions=?,"
            "  needs_review=?, auto_accepted_count=?, published_questions=?, status=?, updated_at=? "
            "WHERE id=?",
            (total, total, validated, needs_review, auto_accepted, published, status.value, utc_now_iso(), job_id),
        )

    def _row_to_draft_dto(self, r: sqlite3.Row) -> DraftQuestionDTO:
        provenance = None
        if r["classification_provenance_json"]:
            parsed = json.loads(r["classification_provenance_json"])
            if parsed and isinstance(parsed, dict) and "classification_source" in parsed and "classifier_type" in parsed:
                provenance = ClassificationProvenance(**parsed)

        bindings = []
        if r["skill_bindings_json"]:
            raw_bindings = json.loads(r["skill_bindings_json"])
            if raw_bindings:
                for b in raw_bindings:
                    if isinstance(b, dict):
                        bindings.append(SkillBindingItem(**b))

        return DraftQuestionDTO(
            id=r["id"],
            job_id=r["job_id"],
            question_number=r["question_number"],
            raw_question_number_str=r["raw_question_number_str"],
            passage_id=r["passage_id"],
            passage_text=r["passage_text"],
            subject=r["subject"],
            module=r["module"],
            module_source=r["module_source"],
            stem=r["stem"],
            stem_assets=json.loads(r["stem_assets_json"]) if r["stem_assets_json"] else [],
            options=json.loads(r["options_json"]) if r["options_json"] else {},
            option_assets=json.loads(r["option_assets_json"]) if r["option_assets_json"] else {},
            answer=r["answer"],
            answer_source=r["answer_source"],
            answer_matched=r["answer_matched"] or 0,
            explanation=r["explanation"] or '',
            explanation_source=r["explanation_source"],
            knowledge_node_id=r["knowledge_node_id"],
            knowledge_node_code=r["knowledge_node_code"],
            knowledge_confidence=r["knowledge_confidence"] or 0.0,
            knowledge_candidates=json.loads(r["knowledge_candidates_json"]) if r["knowledge_candidates_json"] else [],
            skill_id=r["skill_id"],
            skill_code=r["skill_code"],
            skill_confidence=r["skill_confidence"] or 0.0,
            skill_candidates=json.loads(r["skill_candidates_json"]) if r["skill_candidates_json"] else [],
            skill_bindings=bindings,
            classification_provenance=provenance,
            validation_status=ValidationStatus(r["validation_status"]),
            review_reasons=json.loads(r["review_reasons_json"]) if r["review_reasons_json"] else [],
            source_document_id=r["source_document_id"],
            source_document_version_id=r["source_document_version_id"],
            source_page=r["source_page"],
            source_block_ids=json.loads(r["source_block_ids_json"]) if r["source_block_ids_json"] else [],
            source_locator=r["source_locator"],
            content_fingerprint=r["content_fingerprint"],
            published_question_id=r["published_question_id"],
            reviewed_by=r["reviewed_by"],
            reviewed_at=r["reviewed_at"],
            review_comment=r["review_comment"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )
