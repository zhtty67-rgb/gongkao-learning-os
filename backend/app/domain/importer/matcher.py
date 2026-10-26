"""Deterministic answer and explanation matcher for Question Bank Importer (QI1).

Strictly enforces:
1. Model NEVER guesses answers.
2. Official answer must come from authoritative sources (answer keys, inline tags, PDF explanation).
3. Detects answer missing, duplicate/conflict answers, and explanation mismatches.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from .schemas import (
    AnswerExplanationAuditOutput,
    ExtractedAnswerKeyItem,
    ExtractedExplanationItem,
    ExtractedQuestion,
    ReviewReason,
)

logger = logging.getLogger(__name__)

# Patterns for extracting concluding answer from explanation text
EXPLANATION_CONCLUDING_ANSWER_RE = re.compile(
    r'(?:故本题选|故正确答案为|因此选择|因此选|本题选|答案应选|正确答案是|故选|选择|锁定|因此)\s*([A-D])(?:\s*项|\b)'
)


class MatchResult:
    def __init__(
        self,
        question_number: int,
        answer: str | None,
        answer_source: str,
        answer_matched: int,
        explanation: str,
        explanation_source: str,
        review_reasons: list[ReviewReason],
    ):
        self.question_number = question_number
        self.answer = answer
        self.answer_source = answer_source
        self.answer_matched = answer_matched
        self.explanation = explanation
        self.explanation_source = explanation_source
        self.review_reasons = review_reasons


class AnswerMatcher:
    """Matches answers and explanations to extracted questions with deterministic authority."""

    def __init__(
        self,
        answer_keys: list[ExtractedAnswerKeyItem],
        explanations: list[ExtractedExplanationItem],
    ):
        self.answer_keys_map: dict[int, ExtractedAnswerKeyItem] = {}
        # Track duplicate answers in answer keys
        self.duplicate_key_questions: set[int] = set()
        for k in answer_keys:
            if k.question_number in self.answer_keys_map:
                if self.answer_keys_map[k.question_number].answer != k.answer:
                    self.duplicate_key_questions.add(k.question_number)
            self.answer_keys_map[k.question_number] = k

        self.explanations_map: dict[int, ExtractedExplanationItem] = {
            e.question_number: e for e in explanations
        }

    def match_question(self, question: ExtractedQuestion) -> MatchResult:
        q_num = question.question_number
        reasons = list(question.review_reasons)

        key_item = self.answer_keys_map.get(q_num)
        exp_item = self.explanations_map.get(q_num)

        # 1. Answer Resolution
        resolved_answer: str | None = None
        answer_source = 'unresolved'
        answer_matched = 0

        # Check duplicate answer in answer key
        if q_num in self.duplicate_key_questions:
            reasons.append(ReviewReason.ANSWER_CONFLICT)

        inline_ans = question.inline_answer
        key_ans = key_item.answer if key_item else None

        if inline_ans and key_ans:
            if inline_ans == key_ans:
                resolved_answer = inline_ans
                answer_source = 'inline_and_key'
                answer_matched = 1
            else:
                # Direct conflict between inline answer and answer key
                reasons.append(ReviewReason.ANSWER_CONFLICT)
                answer_source = 'conflict'
                resolved_answer = None
                answer_matched = 0
        elif inline_ans:
            resolved_answer = inline_ans
            answer_source = 'inline_explanation'
            answer_matched = 1
        elif key_ans:
            resolved_answer = key_ans
            answer_source = 'answer_key'
            answer_matched = 1
        elif exp_item and exp_item.extracted_answer:
            resolved_answer = exp_item.extracted_answer
            answer_source = 'pdf_explanation'
            answer_matched = 1
        else:
            reasons.append(ReviewReason.ANSWER_MISSING)
            answer_source = 'unresolved'
            resolved_answer = None
            answer_matched = 0

        # 2. Explanation Resolution
        resolved_explanation = ''
        explanation_source = 'none'

        if question.inline_explanation:
            resolved_explanation = question.inline_explanation
            explanation_source = 'inline_explanation'
        elif exp_item and exp_item.explanation:
            resolved_explanation = exp_item.explanation
            explanation_source = 'pdf_explanation'

        # 3. Check for conflict between explanation text and resolved answer
        if resolved_answer and resolved_explanation:
            m = EXPLANATION_CONCLUDING_ANSWER_RE.search(resolved_explanation)
            if m:
                concluding_ans = m.group(1)
                if concluding_ans != resolved_answer:
                    reasons.append(ReviewReason.EXPLANATION_MISMATCH)
                    resolved_answer = None
                    answer_matched = 0

        if ReviewReason.ANSWER_CONFLICT in reasons:
            resolved_answer = None
            answer_matched = 0
            answer_source = "conflict"

        # Deduplicate review reasons while preserving order
        seen = set()
        deduped_reasons = []
        for r in reasons:
            if r not in seen:
                seen.add(r)
                deduped_reasons.append(r)

        return MatchResult(
            question_number=q_num,
            answer=resolved_answer,
            answer_source=answer_source,
            answer_matched=answer_matched,
            explanation=resolved_explanation,
            explanation_source=explanation_source,
            review_reasons=deduped_reasons,
        )

    def match_all(self, questions: list[ExtractedQuestion]) -> list[MatchResult]:
        return [self.match_question(q) for q in questions]
