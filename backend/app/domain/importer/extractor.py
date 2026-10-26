"""Deterministic extractor for Question Bank Importer (QI1).

Extracts questions, options, passages, image assets, answer keys, and explanations
from Knowledge Hub ParsedDocument structure without making model guesses.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any
from uuid import uuid4

from .schemas import (
    BoundingBox,
    ExtractedAnswerKeyItem,
    ExtractedExplanationItem,
    ExtractedPassage,
    ExtractedQuestion,
    ParsedBlock,
    ParsedDocument,
    ReviewReason,
)

logger = logging.getLogger(__name__)

# Canonical module names in Civil Service Exams (行测)
CANONICAL_MODULES = [
    '政治理论',
    '常识判断',
    '言语理解与表达',
    '数量关系',
    '判断推理',
    '图形推理',
    '立体图推',
    '定义判断',
    '类比推理',
    '逻辑判断',
    '资料分析',
]

MODULE_ALIASES: dict[str, str] = {
    '政治': '政治理论',
    '政治理论': '政治理论',
    '常识': '常识判断',
    '常识部分': '常识判断',
    '常识判断': '常识判断',
    '言语': '言语理解与表达',
    '言语理解': '言语理解与表达',
    '言语理解与表达': '言语理解与表达',
    '数量': '数量关系',
    '数量关系': '数量关系',
    '数学运算': '数量关系',
    '判断': '判断推理',
    '判断推理': '判断推理',
    '图形推理': '图形推理',
    '立体图推': '立体图推',
    '立体图形': '立体图推',
    '空间重构': '立体图推',
    '定义判断': '定义判断',
    '类比推理': '类比推理',
    '逻辑判断': '逻辑判断',
    '资料': '资料分析',
    '资料分析': '资料分析',
}

# Regex for section module headings
MODULE_HEADING_RE = re.compile(
    r'(?:第[一二三四五六七八九十]+部分|部分[一二三四五]|SECTION\s*\d+)?\s*'
    r'([常言数判资][识语量断料][判断理关解算]*[表达关系推理分析]*)',
    re.IGNORECASE,
)

# Regex for Answer/Explanation section marker
ANSWER_SECTION_HEADING_RE = re.compile(
    r'^(?:【?参考答案[与及]?解析?】?|【?答案[与及]?解析?】?|参考答案|参考解析|答案及解析)(?:\b|\n|\s|$)'
)

# Regex for passage header: "根据以下资料，回答第101-105题："
PASSAGE_HEADER_RE = re.compile(
    r'(?:[一二三四五]、)?\s*根据(?:以下|下列|所给)?(?:材料|资料|图表)[，,]\s*'
    r'回答第?\s*(\d+)\s*[~～\-—至到]\s*(\d+)\s*题[：:]?',
)

# Alternative passage header: "阅读下列材料，回答第101—105题："
PASSAGE_HEADER_ALT_RE = re.compile(
    r'阅读(?:以下|下列)?材料[，,]\s*回答第?\s*(\d+)\s*[~～\-—至到]\s*(\d+)\s*题[：:]?'
)

# Section / Outline heading pattern: "1.1", "1.1.1", "2.3.4"
SECTION_HEADING_RE = re.compile(
    r'^\d+(?:[\.、．]\d+)+'
)

# Example question pattern: "【例1】", "【例 1】", "【例题1】", "【例题 1】", "例1", "例 1", "例题1", "例题 1", "【例题】", "例题"
EXAMPLE_QUESTION_RE = re.compile(
    r'^(?:【\s*例(?:题)?\s*(\d*)\s*】|例(?:题)?\s*(\d+)[：:\.、．\s]|【\s*例题\s*】|例题[：:\.、．\s])\s*(.*)$'
)

# Question number pattern: "1. ", "1、", "1．", "第1题：", "（1）" (excluding section headings like 1.1)
QUESTION_NUM_RE = re.compile(
    r'^(?:第\s*(\d+)\s*题[：:]?|（(\d+)）|\((\d+)\)|(\d+)[\.、．](?!\d))\s*(.*)$'
)

# Option patterns: "A. ", "A、", "（A）", "(A)", "A．", "A ．", "A )", "A ）", "A 。"
OPTION_LINE_RE = re.compile(
    r'^(?:[（\(]\s*([A-D])\s*[）\)]|([A-D])\s*[\.、．。:：\)\）])\s*(.*)$',
    re.IGNORECASE,
)

# Inline options on a single line: "A. xxx   B. yyy   C. zzz   D. www"
INLINE_OPTIONS_RE = re.compile(
    r'(?:^|[\s。？?！!；;：:,，])(?:[（\(]\s*([A-D])\s*[）\)]|([A-D])\s*[\.、．。:：\)\）])\s*([^\sABCD（\(]+(?:\s+[^\sABCD（\(]+)*)',
    re.IGNORECASE,
)

# Inline answer and explanation (enhanced with "选 B", "选择 A 选项", "定位 A 项", etc.)
INLINE_ANSWER_RE = re.compile(
    r'(?:【(?:参考)?答案】|(?:正确)?答案[：:])\s*([A-D])\b'
    r'|(?:因此[，,]?\s*)?(?:选|选择|定位)\s*([A-D])\s*(?:项|选项|\b)'
)
INLINE_EXPLANATION_RE = re.compile(
    r'【(?:参考|实战)?解析】\s*(.*)|解析[：:]\s*(.*)',
    re.DOTALL,
)

# Answer table item: "1-5: BCADA" or "1. B" or "1-5 BCADA"
ANSWER_GRID_RE = re.compile(
    r'(\d+)\s*[-—~～]\s*(\d+)\s*[：:]?\s*([A-D]{2,10})'
)
SINGLE_ANSWER_KEY_RE = re.compile(
    r'(?:第\s*(\d+)\s*题|(\d+)[\.、．](?!\d)|【\s*例(?:题)?\s*(\d+)\s*】)\s*[：:]?\s*(?:正确答案[：:]\s*)?([A-D])\b'
)


def normalize_module(text: str) -> str | None:
    """Normalize extracted text or heading into a canonical civil service module."""
    cleaned = text.strip().replace(' ', '')
    for alias, canon in MODULE_ALIASES.items():
        if alias in cleaned:
            return canon
    match = MODULE_HEADING_RE.search(cleaned)
    if match:
        matched_str = match.group(1)
        for alias, canon in MODULE_ALIASES.items():
            if alias in matched_str:
                return canon
    return None


def extract_content_fingerprint(
    doc_version_id: str | None,
    q_num: int,
    stem: str,
    options: dict[str, str],
) -> str:
    raw = f"{doc_version_id or 'v0'}:{q_num}:{stem.strip()}:{json.dumps(options, sort_keys=True)}"
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


class DocumentExtractionResult:
    def __init__(
        self,
        questions: list[ExtractedQuestion],
        passages: list[ExtractedPassage],
        answer_keys: list[ExtractedAnswerKeyItem],
        explanations: list[ExtractedExplanationItem],
    ):
        self.questions = questions
        self.passages = passages
        self.answer_keys = answer_keys
        self.explanations = explanations


class QuestionExtractor:
    """Deterministic extractor parsing ParsedDocument blocks into structured entities."""

    def __init__(self, doc: ParsedDocument):
        self.doc = doc
        self.doc_id = doc.document_id or doc.document_version_id
        self.version_id = doc.document_version_id

    def extract(self) -> DocumentExtractionResult:
        blocks = self.doc.blocks
        if not blocks:
            logger.warning("Document has no parsed blocks: %s", self.doc_id)
            return DocumentExtractionResult([], [], [], [])

        # Phase 1: Split into Question section vs Answer/Explanation section
        question_blocks: list[ParsedBlock] = []
        answer_blocks: list[ParsedBlock] = []
        in_answer_section = False

        for block in blocks:
            text_clean = block.text.strip()
            # Check if block signals transition to Answer section
            if ANSWER_SECTION_HEADING_RE.match(text_clean):
                in_answer_section = True
                lines = text_clean.split('\n')
                if len(lines) > 1:
                    rest_text = '\n'.join(lines[1:]).strip()
                    answer_blocks.append(
                        ParsedBlock(
                            block_id=block.block_id,
                            block_type='paragraph',
                            text=rest_text,
                            page=block.page,
                            bounding_box=block.bounding_box,
                        )
                    )
                continue
            if in_answer_section:
                answer_blocks.append(block)
            else:
                # Also check heading paths
                if any(ANSWER_SECTION_HEADING_RE.match(h.strip()) for h in block.heading_path):
                    in_answer_section = True
                    answer_blocks.append(block)
                else:
                    question_blocks.append(block)

        # Phase 2: Extract Answer Keys and Explanations from answer section
        answer_keys, explanations = self._extract_answers_and_explanations(answer_blocks)

        # Phase 3: Extract Passages and Questions from question blocks
        passages, questions = self._extract_questions_and_passages(question_blocks)

        return DocumentExtractionResult(
            questions=questions,
            passages=passages,
            answer_keys=answer_keys,
            explanations=explanations,
        )

    def _extract_answers_and_explanations(
        self, blocks: list[ParsedBlock]
    ) -> tuple[list[ExtractedAnswerKeyItem], list[ExtractedExplanationItem]]:
        answer_keys: list[ExtractedAnswerKeyItem] = []
        explanations: list[ExtractedExplanationItem] = []

        seen_answers: dict[int, str] = {}
        current_explanation_qnum: int | None = None
        current_explanation_lines: list[str] = []
        current_explanation_ans: str | None = None
        current_exp_block_id: str | None = None
        current_exp_page: int | None = None

        def flush_explanation():
            nonlocal current_explanation_qnum, current_explanation_lines, current_explanation_ans
            if current_explanation_qnum is not None:
                exp_text = "\n".join(current_explanation_lines).strip()
                if exp_text or current_explanation_ans:
                    explanations.append(
                        ExtractedExplanationItem(
                            question_number=current_explanation_qnum,
                            explanation=exp_text,
                            extracted_answer=current_explanation_ans,
                            source_page=current_exp_page,
                            source_block_id=current_exp_block_id,
                        )
                    )
            current_explanation_qnum = None
            current_explanation_lines = []
            current_explanation_ans = None

        for block in blocks:
            text = block.text.strip()
            page = block.page
            bid = block.block_id

            # 1. Check for grid answers like "1-5: BCADA"
            grid_matches = ANSWER_GRID_RE.findall(text)
            for start_str, end_str, ans_letters in grid_matches:
                start_num = int(start_str)
                end_num = int(end_str)
                letters = ans_letters.strip()
                if len(letters) == (end_num - start_num + 1):
                    for idx, char in enumerate(letters):
                        q_num = start_num + idx
                        if seen_answers.get(q_num) != char:
                            seen_answers[q_num] = char
                            answer_keys.append(
                                ExtractedAnswerKeyItem(
                                    question_number=q_num,
                                    answer=char,
                                    source_page=page,
                                    source_block_id=bid,
                                )
                            )

            # 2. Check for single answer key item: "1. B", "1、C"
            single_matches = SINGLE_ANSWER_KEY_RE.findall(text)
            for m_item in single_matches:
                q1, q2, q3, ans_char = m_item
                q_num = int(q1 or q2 or q3)
                if seen_answers.get(q_num) != ans_char:
                    seen_answers[q_num] = ans_char
                    answer_keys.append(
                        ExtractedAnswerKeyItem(
                            question_number=q_num,
                            answer=ans_char,
                            source_page=page,
                            source_block_id=bid,
                        )
                    )

            # 3. Check for detailed explanation items like:
            # "1.【答案】B。解析：..." or "第101题 【答案】A" or "【例1】... 选B"
            q_match = QUESTION_NUM_RE.match(text)
            ex_match = None
            if not q_match:
                ex_match = EXAMPLE_QUESTION_RE.match(text)

            if q_match or ex_match:
                flush_explanation()
                if q_match:
                    q_num_str = q_match.group(1) or q_match.group(2) or q_match.group(3) or q_match.group(4)
                    current_explanation_qnum = int(q_num_str)
                    rest_text = q_match.group(5).strip()
                else:
                    q_num_str = ex_match.group(1) or ex_match.group(2)
                    if q_num_str and q_num_str.isdigit():
                        current_explanation_qnum = int(q_num_str)
                    else:
                        current_explanation_qnum = (current_explanation_qnum or 0) + 1
                    rest_text = ex_match.group(3).strip()

                current_exp_page = page
                current_exp_block_id = bid

                # Check if answer is inline
                ans_match = INLINE_ANSWER_RE.search(rest_text) or INLINE_ANSWER_RE.search(text)
                if ans_match:
                    ans = ans_match.group(1) or ans_match.group(2)
                    current_explanation_ans = ans
                    if seen_answers.get(current_explanation_qnum) != ans:
                        seen_answers[current_explanation_qnum] = ans
                        answer_keys.append(
                            ExtractedAnswerKeyItem(
                                question_number=current_explanation_qnum,
                                answer=ans,
                                source_page=page,
                                source_block_id=bid,
                            )
                        )

                # Collect initial explanation text
                exp_match = INLINE_EXPLANATION_RE.search(rest_text)
                if exp_match:
                    current_explanation_lines.append((exp_match.group(1) or exp_match.group(2)).strip())
                elif rest_text:
                    current_explanation_lines.append(rest_text)
            else:
                # Continuation of current explanation
                if current_explanation_qnum is not None:
                    if current_explanation_ans is None:
                        ans_m = INLINE_ANSWER_RE.search(text)
                        if ans_m:
                            ans = ans_m.group(1) or ans_m.group(2)
                            current_explanation_ans = ans
                            if seen_answers.get(current_explanation_qnum) != ans:
                                seen_answers[current_explanation_qnum] = ans
                                answer_keys.append(
                                    ExtractedAnswerKeyItem(
                                        question_number=current_explanation_qnum,
                                        answer=ans,
                                        source_page=page,
                                        source_block_id=bid,
                                    )
                                )
                    current_explanation_lines.append(text)

        flush_explanation()
        return answer_keys, explanations

    def _extract_questions_and_passages(
        self, blocks: list[ParsedBlock]
    ) -> tuple[list[ExtractedPassage], list[ExtractedQuestion]]:
        passages: list[ExtractedPassage] = []
        questions: list[ExtractedQuestion] = []

        current_module = '资料分析'
        current_module_source = 'heading_rule'

        # Passage tracking state
        current_passage_id: str | None = None
        current_passage_lines: list[str] = []
        current_passage_assets: list[str] = []
        current_passage_start_page: int | None = None
        current_passage_end_page: int | None = None
        current_passage_qstart: int | None = None
        current_passage_qend: int | None = None

        # Question tracking state
        current_q_num: int | None = None
        current_q_raw_str: str | None = None
        current_stem_lines: list[str] = []
        current_stem_assets: list[str] = []
        current_options: dict[str, str] = {}
        current_option_assets: dict[str, list[str]] = {}
        current_inline_answer: str | None = None
        current_inline_explanation: str | None = None
        current_q_page: int | None = None
        current_q_start_page: int | None = None
        current_q_end_page: int | None = None
        current_q_blocks: list[str] = []
        current_q_locator: str | None = None
        current_bbox: BoundingBox | None = None
        current_q_review_reasons: list[ReviewReason] = []
        parsing_options_mode = False
        last_option_key: str | None = None

        def flush_passage():
            nonlocal current_passage_id, current_passage_lines, current_passage_assets
            nonlocal current_passage_start_page, current_passage_end_page
            nonlocal current_passage_qstart, current_passage_qend

            if current_passage_id and current_passage_lines:
                passages.append(
                    ExtractedPassage(
                        id=current_passage_id,
                        source_document_id=self.doc_id,
                        source_document_version_id=self.version_id,
                        source_page_start=current_passage_start_page or 1,
                        source_page_end=current_passage_end_page or (current_passage_start_page or 1),
                        source_locator=f"p:{current_passage_start_page or 1}",
                        question_range_start=current_passage_qstart,
                        question_range_end=current_passage_qend,
                        content="\n".join(current_passage_lines).strip(),
                        assets=list(current_passage_assets),
                    )
                )
            current_passage_id = None
            current_passage_lines = []
            current_passage_assets = []
            current_passage_start_page = None
            current_passage_end_page = None
            current_passage_qstart = None
            current_passage_qend = None

        def flush_question():
            nonlocal current_q_num, current_q_raw_str, current_stem_lines, current_stem_assets
            nonlocal current_options, current_option_assets, current_inline_answer, current_inline_explanation
            nonlocal current_q_page, current_q_start_page, current_q_end_page, current_q_blocks, current_q_locator, current_bbox
            nonlocal current_q_review_reasons, parsing_options_mode, last_option_key

            if current_q_num is not None:
                stem_text = "\n".join(current_stem_lines).strip()
                reasons = list(current_q_review_reasons)

                # Validate options
                has_all_options = all(k in current_options for k in ('A', 'B', 'C', 'D'))
                has_graphic_options = all(k in current_option_assets for k in ('A', 'B', 'C', 'D'))
                is_graphic_reasoning = (
                    current_module == '判断推理' and bool(current_stem_assets or has_graphic_options)
                )

                if not has_all_options and not has_graphic_options:
                    # In graphic reasoning, if whole-question figure is preserved in stem_assets,
                    # options are embedded in the visual asset. Do NOT mark OPTION_PARSE_FAILED!
                    if is_graphic_reasoning and current_stem_assets:
                        pass
                    else:
                        reasons.append(ReviewReason.OPTION_PARSE_FAILED)

                # Validate boundary
                if not stem_text and not current_stem_assets:
                    reasons.append(ReviewReason.QUESTION_BOUNDARY_AMBIGUOUS)

                # Find active passage if any
                active_passage_id = None
                active_passage_text = None
                for p in passages:
                    if p.question_range_start and p.question_range_end:
                        if p.question_range_start <= current_q_num <= p.question_range_end:
                            active_passage_id = p.id
                            active_passage_text = p.content
                            break

                loc = current_q_locator
                if not loc and current_q_blocks:
                    loc = f"p:{current_q_page or 1}#blocks:{','.join(current_q_blocks[:2])}"

                fingerprint = extract_content_fingerprint(
                    self.version_id,
                    current_q_num,
                    stem_text,
                    current_options,
                )

                p_start = current_q_start_page or current_q_page or 1
                p_end = current_q_end_page or current_q_page or 1

                questions.append(
                    ExtractedQuestion(
                        question_number=current_q_num,
                        raw_question_number_str=current_q_raw_str or str(current_q_num),
                        passage_id=active_passage_id,
                        passage_text=active_passage_text,
                        subject='行测',
                        module=current_module,
                        module_source=current_module_source,
                        stem=stem_text,
                        stem_assets=list(current_stem_assets),
                        options=dict(current_options),
                        option_assets=dict(current_option_assets),
                        inline_answer=current_inline_answer,
                        inline_explanation=current_inline_explanation,
                        source_document_id=self.doc_id,
                        source_document_version_id=self.version_id,
                        source_page=p_start,
                        source_page_end=p_end,
                        source_block_ids=list(current_q_blocks),
                        source_locator=loc,
                        bounding_box=current_bbox,
                        content_fingerprint=fingerprint,
                        review_reasons=reasons,
                    )
                )

            # Reset question state
            current_q_num = None
            current_q_raw_str = None
            current_stem_lines = []
            current_stem_assets = []
            current_options = {}
            current_option_assets = {}
            current_inline_answer = None
            current_inline_explanation = None
            current_q_page = None
            current_q_start_page = None
            current_q_end_page = None
            current_q_blocks = []
            current_q_locator = None
            current_bbox = None
            current_q_review_reasons = []
            parsing_options_mode = False
            last_option_key = None

        for block in blocks:
            text = block.text.strip()
            block_type = block.block_type
            page = block.page or 1
            bid = block.block_id

            # 1. Update module from headings if available
            norm_mod = None
            for h in block.heading_path:
                norm_mod = normalize_module(h)
                if norm_mod:
                    break
            if not norm_mod:
                norm_mod = normalize_module(text)
            if norm_mod:
                current_module = norm_mod
                current_module_source = 'heading_rule'

            # 2. Check for Passage Header
            passage_match = PASSAGE_HEADER_RE.search(text) or PASSAGE_HEADER_ALT_RE.search(text)
            if passage_match:
                # Flush previous question and passage
                flush_question()
                flush_passage()

                current_passage_id = f"passage_{uuid4().hex[:12]}"
                current_passage_start_page = page
                current_passage_end_page = page
                current_passage_qstart = int(passage_match.group(1))
                current_passage_qend = int(passage_match.group(2))
                current_passage_lines.append(text)
                if block.asset_reference:
                    current_passage_assets.append(block.asset_reference)
                continue

            # If currently collecting passage materials (before the first question of passage)
            if current_passage_id is not None and current_q_num is None:
                # If this block is not yet a question, it belongs to the passage
                q_match_test = QUESTION_NUM_RE.match(text) or EXAMPLE_QUESTION_RE.match(text)
                if not q_match_test or SECTION_HEADING_RE.match(text):
                    current_passage_lines.append(text)
                    current_passage_end_page = page
                    if block.asset_reference:
                        current_passage_assets.append(block.asset_reference)
                    continue
                else:
                    # First question encountered, seal passage
                    flush_passage()

            # 3. Check for Question Boundary: e.g. "1. ", "101、", "(1)", "【例 1】", "例1"
            # Explicitly exclude section/outline numbering (e.g. 1.1, 1.1.1, 2.3)
            if SECTION_HEADING_RE.match(text):
                continue

            q_match = QUESTION_NUM_RE.match(text)
            ex_match = None
            if not q_match:
                ex_match = EXAMPLE_QUESTION_RE.match(text)

            if q_match or ex_match:
                if q_match:
                    q_num_str = q_match.group(1) or q_match.group(2) or q_match.group(3) or q_match.group(4)
                    candidate_q_num = int(q_num_str)
                    rest_stem = q_match.group(5).strip()
                else:
                    q_num_str = ex_match.group(1) or ex_match.group(2)
                    if q_num_str and q_num_str.isdigit():
                        candidate_q_num = int(q_num_str)
                    else:
                        candidate_q_num = (current_q_num or 0) + 1
                    rest_stem = ex_match.group(3).strip()

                # Heuristic: Check if this is a real question number vs an inline sub-clause item
                is_real_question = True
                if current_q_num is not None:
                    # If number jumps backward without reason, flag review
                    if candidate_q_num < current_q_num and q_match:
                        # Might be an inline list item (1) inside stem
                        if '(' in text[:3] or '（' in text[:3]:
                            is_real_question = False

                if is_real_question:
                    flush_question()
                    current_q_num = candidate_q_num
                    current_q_raw_str = q_num_str or str(candidate_q_num)
                    current_q_page = page
                    current_q_start_page = page
                    current_q_end_page = page
                    current_q_blocks.append(bid)
                    current_bbox = block.bounding_box
                    current_q_locator = f"p:{page}#blocks:{bid}"

                    # Check for inline answers/explanations inside the same block
                    ans_m = INLINE_ANSWER_RE.search(rest_stem)
                    if ans_m:
                        current_inline_answer = ans_m.group(1) or ans_m.group(2)
                    exp_m = INLINE_EXPLANATION_RE.search(rest_stem)
                    if exp_m:
                        current_inline_explanation = (exp_m.group(1) or exp_m.group(2)).strip()

                    # Check if stem has inline options: "A. xxx B. yyy"
                    inline_opts = self._extract_inline_options(rest_stem)
                    if inline_opts:
                        m_first = re.search(r'(?:^|[\s。？?！!；;：:,，])(?:[（\(]\s*([A-D])\s*[）\)]|([A-D])\s*[\.、．。:：\)\）])\s*', rest_stem, re.IGNORECASE)
                        first_opt_idx = m_first.start() if m_first else 0
                        clean_stem = rest_stem[:first_opt_idx].rstrip('。？?！!；;：:,， \t').strip()
                        current_stem_lines.append(clean_stem)
                        for opt_k in ('A', 'B', 'C', 'D'):
                            if opt_k in inline_opts:
                                current_options[opt_k] = inline_opts[opt_k]
                        parsing_options_mode = True
                    else:
                        if rest_stem:
                            current_stem_lines.append(rest_stem)

                    if block.asset_reference:
                        current_stem_assets.append(block.asset_reference)
                    if block.asset_refs:
                        for aref in block.asset_refs:
                            if aref not in current_stem_assets:
                                current_stem_assets.append(aref)
                    continue

            # 4. If currently inside a question
            if current_q_num is not None:
                current_q_blocks.append(bid)
                current_q_end_page = page

                # Check if block is an option line: "A. xxx", "A、xxx", "A ． xxx"
                opt_match = OPTION_LINE_RE.match(text)
                if opt_match:
                    parsing_options_mode = True
                    opt_letter = (opt_match.group(1) or opt_match.group(2)).upper()
                    opt_content = opt_match.group(3).strip()
                    last_option_key = opt_letter

                    # Check if this line also has following options (e.g. "A. 10%   B. 20%")
                    inline_opts = self._extract_inline_options(text)
                    if inline_opts and len(inline_opts) > 1:
                        for k, v in inline_opts.items():
                            current_options[k] = v
                    else:
                        current_options[opt_letter] = opt_content
                        if block.asset_reference:
                            current_option_assets.setdefault(opt_letter, []).append(block.asset_reference)
                        if block.asset_refs:
                            for aref in block.asset_refs:
                                if aref not in current_option_assets.setdefault(opt_letter, []):
                                    current_option_assets[opt_letter].append(aref)
                    continue

                # Check if this block has inline options: "A. xx   B. yy"
                inline_opts = self._extract_inline_options(text)
                if inline_opts:
                    parsing_options_mode = True
                    for k, v in inline_opts.items():
                        current_options[k] = v
                    continue

                # Check if image block inside question
                if block_type in ('picture', 'image') or block.asset_reference or block.asset_refs:
                    refs = list(block.asset_refs) if block.asset_refs else ([block.asset_reference] if block.asset_reference else [bid])
                    if parsing_options_mode and last_option_key:
                        for r in refs:
                            if r not in current_option_assets.setdefault(last_option_key, []):
                                current_option_assets[last_option_key].append(r)
                    else:
                        for r in refs:
                            if r not in current_stem_assets:
                                current_stem_assets.append(r)
                    continue

                # Check if block contains inline answer/explanation
                ans_m = INLINE_ANSWER_RE.search(text)
                if ans_m:
                    current_inline_answer = ans_m.group(1) or ans_m.group(2)
                exp_m = INLINE_EXPLANATION_RE.search(text)
                if exp_m:
                    current_inline_explanation = (exp_m.group(1) or exp_m.group(2)).strip()
                    continue

                # Otherwise, it's stem continuation or option continuation
                if parsing_options_mode and last_option_key:
                    # Option text continuation
                    current_options[last_option_key] = f"{current_options.get(last_option_key, '')} {text}".strip()
                else:
                    current_stem_lines.append(text)

        flush_question()
        flush_passage()

        return passages, questions

    def _extract_inline_options(self, text: str) -> dict[str, str]:
        """Extract inline options A, B, C, D if present in text."""
        result: dict[str, str] = {}
        pattern = re.compile(
            r'(?:^|[\s。？?！!；;：:,，])(?:[（\(]\s*([A-D])\s*[）\)]|([A-D])\s*[\.、．。:：\)\）])\s*',
            re.IGNORECASE,
        )
        matches = list(pattern.finditer(text))
        if not matches or len(matches) < 2:
            return result

        letters = [(m.group(1) or m.group(2)).upper() for m in matches]
        if letters not in (['A', 'B'], ['C', 'D'], ['A', 'B', 'C'], ['A', 'B', 'C', 'D']):
            return result

        for i, match in enumerate(matches):
            key = letters[i]
            start_pos = match.end()
            end_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            opt_text = text[start_pos:end_pos].strip()
            opt_text = re.sub(r'[\s。？?！!；;：:,，]+$', '', opt_text)
            ans_m = INLINE_ANSWER_RE.search(opt_text)
            if ans_m:
                opt_text = opt_text[:ans_m.start()].strip()
            exp_m = INLINE_EXPLANATION_RE.search(opt_text)
            if exp_m:
                opt_text = opt_text[:exp_m.start()].strip()
            result[key] = opt_text

        return result
