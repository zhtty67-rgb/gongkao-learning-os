"""KnowledgeNode and LearningSkill classifier with candidate narrowing and ModelGateway routing.

Strict rules enforced:
1. Model CANNOT invent new knowledge nodes or skill codes.
2. Model must choose strictly from the provided candidate list.
3. Priority order: PDF tag > Heading rule > Explanation keyword / alias > Fast Model > Strong Model > Review.
4. Records full classification provenance (model, provider, prompt version, candidate set, confidence).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any
import sqlite3

from ...ai.gateway import ModelGateway
from ...ai.schemas import GatewayError, Message, TaskType
from ...knowledge import get_knowledge_provider
from .schemas import (
    ClassificationProvenance,
    KnowledgeCandidate,
    KnowledgeClassificationOutput,
    ReviewReason,
    SkillBindingItem,
    SkillCandidate,
    SkillClassificationOutput,
    ValidationStatus,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

PROMPT_VERSION = "qi1-v1.0"

# Common keywords / aliases mapped to canonical knowledge node codes and names
DEFAULT_KNOWLEDGE_RULES = [
    # 资料分析
    {
        "code": "gongkao.xingce.data_analysis.growth_rate.mixed",
        "name": "混合增长率",
        "module": "资料分析",
        "aliases": ["混合增长率", "十字交叉", "线段法", "两部分混合", "整体增长率介于"],
    },
    {
        "code": "gongkao.xingce.data_analysis.proportion.two_period",
        "name": "两期比重",
        "module": "资料分析",
        "aliases": ["两期比重", "比重上升", "比重下降", "比重差", "部分增速大于整体增速"],
    },
    {
        "code": "gongkao.xingce.data_analysis.growth_rate.interval",
        "name": "间隔增长率",
        "module": "资料分析",
        "aliases": ["间隔增长率", "隔年增长率", "隔年", "r1+r2+r1*r2"],
    },
    {
        "code": "gongkao.xingce.data_analysis.growth_rate.base",
        "name": "基期量计算",
        "module": "资料分析",
        "aliases": ["基期量", "基期值", "去年同期为", "上年同期为"],
    },
    {
        "code": "gongkao.xingce.data_analysis.growth_rate",
        "name": "增长率",
        "module": "资料分析",
        "aliases": ["增长率", "增长量", "增速", "增幅", "同比增长", "环比增长", "增加约", "增加多少", "多多少"],
    },
    # 判断推理
    {
        "code": "gongkao.xingce.reasoning.graphic",
        "name": "图形推理",
        "module": "判断推理",
        "aliases": ["图形推理", "对称轴", "笔画数", "一笔画", "交点数", "面数量", "旋转翻转", "黑白块"],
    },
    {
        "code": "gongkao.xingce.reasoning.graphic.spatial",
        "name": "立体图推",
        "module": "立体图推",
        "aliases": ["立体图推", "空间重构", "立体拼合", "多面体折叠", "纸盒折叠", "六面体", "截面图", "三视图"],
    },
    {
        "code": "gongkao.xingce.reasoning.conditional_logic",
        "name": "充分条件推理",
        "module": "判断推理",
        "aliases": ["充分条件", "必要条件", "如果那么", "只要就", "只有才", "逆否命题"],
    },
    {
        "code": "gongkao.xingce.reasoning.definition",
        "name": "定义判断",
        "module": "判断推理",
        "aliases": ["定义判断", "符合定义", "不符合定义"],
    },
    {
        "code": "gongkao.xingce.reasoning.analogy",
        "name": "类比推理",
        "module": "判断推理",
        "aliases": ["类比推理", "对于 相当于", "词项关系"],
    },
    # 数量关系
    {
        "code": "gongkao.xingce.quantitative.work_problem",
        "name": "工程问题",
        "module": "数量关系",
        "aliases": ["工程问题", "完工时间", "合作效率", "工作量", "单独做需要"],
    },
    {
        "code": "gongkao.xingce.quantitative.journey",
        "name": "行程问题",
        "module": "数量关系",
        "aliases": ["行程问题", "相遇", "追及", "流水行船", "平均速度"],
    },
    # 言语理解与表达
    {
        "code": "gongkao.xingce.verbal.fragment_reading",
        "name": "中心理解题",
        "module": "言语理解与表达",
        "aliases": ["中心理解", "主旨概括", "意图推断", "这段文字主要说明", "这段文字意在强调"],
    },
    {
        "code": "gongkao.xingce.verbal.logic_fill",
        "name": "逻辑填空",
        "module": "言语理解与表达",
        "aliases": ["逻辑填空", "依次填入画横线部分最恰当", "成语填空"],
    },
    # 常识判断
    {
        "code": "gongkao.xingce.general.politics",
        "name": "政治常识",
        "module": "常识判断",
        "aliases": ["政治常识", "新时代", "党的二十大", "中国式现代化"],
    },
    {
        "code": "gongkao.xingce.general.law",
        "name": "法律常识",
        "module": "常识判断",
        "aliases": ["法律常识", "民法典", "行政处罚法", "刑法", "宪法"],
    },
]


class ClassificationResult:
    def __init__(
        self,
        knowledge_node_id: str | None,
        knowledge_node_code: str | None,
        knowledge_confidence: float,
        knowledge_candidates: list[str],
        skill_id: str | None,
        skill_code: str | None,
        skill_confidence: float,
        skill_candidates: list[str],
        skill_bindings: list[SkillBindingItem],
        provenance: ClassificationProvenance,
        validation_status: ValidationStatus,
        added_review_reasons: list[ReviewReason],
    ):
        self.knowledge_node_id = knowledge_node_id
        self.knowledge_node_code = knowledge_node_code
        self.knowledge_confidence = knowledge_confidence
        self.knowledge_candidates = knowledge_candidates
        self.skill_id = skill_id
        self.skill_code = skill_code
        self.skill_confidence = skill_confidence
        self.skill_candidates = skill_candidates
        self.skill_bindings = skill_bindings
        self.provenance = provenance
        self.validation_status = validation_status
        self.added_review_reasons = added_review_reasons


class QuestionClassifier:
    """Orchestrates candidate generation, rule matching, and model routing for questions."""

    def __init__(self, db: sqlite3.Connection, gateway: ModelGateway | None = None):
        self.db = db
        self.gateway = gateway or ModelGateway()

    def get_knowledge_candidates(self, module: str, stem: str, explanation: str) -> list[KnowledgeCandidate]:
        """Fetch candidate knowledge nodes from DB and rule table matching the module."""
        candidates_map: dict[str, KnowledgeCandidate] = {}

        # 1. Fetch from rule definitions
        for item in DEFAULT_KNOWLEDGE_RULES:
            if item["module"] == module:
                code = item["code"]
                candidates_map[code] = KnowledgeCandidate(
                    id=code,
                    code=code,
                    name=item["name"],
                    module=item["module"],
                    canonical_name=item["name"],
                    aliases=item.get("aliases", []),
                    relevance_score=0.0,
                )

        # 2. Fetch from DB knowledge_nodes and learning_skills
        rows = self.db.execute(
            "SELECT kn.id, kn.name, kn.module, COALESCE(kn.knowledge_node_code, ls.knowledge_node_code) AS code, ls.canonical_name "
            "FROM knowledge_nodes kn "
            "LEFT JOIN learning_skills ls ON ls.id = kn.id "
            "WHERE kn.module = ?",
            (module,),
        ).fetchall()

        for r in rows:
            code = r["code"] or f"gongkao.xingce.{r['id']}"
            if code not in candidates_map:
                candidates_map[code] = KnowledgeCandidate(
                    id=r["id"],
                    code=code,
                    name=r["name"],
                    module=r["module"],
                    canonical_name=r["canonical_name"] or r["name"],
                    aliases=[r["name"]],
                    relevance_score=0.0,
                )

        # 3. Score candidates based on keyword matches in stem and explanation
        full_text = f"{stem}\n{explanation}"
        for cand in candidates_map.values():
            score = 0.0
            if cand.name in full_text:
                score += 0.5
            for alias in cand.aliases:
                if alias in full_text:
                    score += 0.3
            cand.relevance_score = min(1.0, score)

        # Sort by relevance score descending
        sorted_cands = sorted(candidates_map.values(), key=lambda c: c.relevance_score, reverse=True)
        # Return top 8 candidates
        return sorted_cands[:8]

    def get_skill_candidates(self, knowledge_node_code: str, knowledge_node_id: str | None) -> list[SkillCandidate]:
        """Fetch candidate LearningSkills under the selected KnowledgeNode."""
        candidates: list[SkillCandidate] = []

        # Query DB learning_skills
        query = (
            "SELECT id, code, name, knowledge_node_code, description, difficulty_band "
            "FROM learning_skills "
            "WHERE knowledge_node_code = ? OR parent_id = ? OR id = ?"
        )
        rows = self.db.execute(query, (knowledge_node_code, knowledge_node_id or '', knowledge_node_id or '')).fetchall()

        for r in rows:
            candidates.append(
                SkillCandidate(
                    id=r["id"],
                    code=r["code"],
                    name=r["name"],
                    knowledge_node_code=r["knowledge_node_code"],
                    description=r["description"],
                    difficulty_band=r["difficulty_band"],
                )
            )

        if not candidates and knowledge_node_code.startswith('gongkao.xingce.political_theory'):
            row = self.db.execute("SELECT id,code,name,knowledge_node_code,description,difficulty_band FROM learning_skills WHERE id='politics'").fetchone()
            if row:
                candidates.append(SkillCandidate(id=row['id'],code=row['code'],name=row['name'],
                    knowledge_node_code=knowledge_node_code,description=row['description'],difficulty_band=row['difficulty_band']))
        return candidates

    async def classify(
        self,
        module: str,
        stem: str,
        options: dict[str, str],
        explanation: str,
        heading_path: list[str] | None = None,
        has_critical_error: bool = False,
    ) -> ClassificationResult:
        """Execute the multi-tier classification workflow."""
        added_reasons: list[ReviewReason] = []
        headings_text = " ".join(heading_path or [])
        full_text = f"{headings_text}\n{stem}\n{explanation}"
        candidates = self.get_knowledge_candidates(module, stem, f"{headings_text}\n{explanation}")
        candidate_codes = [c.code for c in candidates]

        if not candidates:
            # UNMAPPED
            provenance = ClassificationProvenance(
                classification_source="unmapped",
                classifier_type="unmapped",
                prompt_version=PROMPT_VERSION,
                candidate_set=[],
                confidence=0.0,
            )
            return ClassificationResult(
                knowledge_node_id=None,
                knowledge_node_code=None,
                knowledge_confidence=0.0,
                knowledge_candidates=[],
                skill_id=None,
                skill_code=None,
                skill_confidence=0.0,
                skill_candidates=[],
                skill_bindings=[],
                provenance=provenance,
                validation_status=ValidationStatus.NEEDS_REVIEW,
                added_review_reasons=[ReviewReason.KNOWLEDGE_LOW_CONFIDENCE],
            )

        # Tier 1 & 2: Deterministic Rule / Alias Match
        unique_rule_hit: KnowledgeCandidate | None = None
        
        # Check for exact name match first
        exact_name_matches = [c for c in candidates if c.name in full_text]
        filtered_exact = [c for c in exact_name_matches if not any(c.name != other.name and c.name in other.name for other in exact_name_matches)]

        if len(filtered_exact) == 1:
            unique_rule_hit = filtered_exact[0]
        else:
            matched_cands: list[KnowledgeCandidate] = []
            for cand in candidates:
                if cand.name in full_text:
                    matched_cands.append(cand)
                else:
                    for alias in cand.aliases:
                        if alias in full_text:
                            matched_cands.append(cand)
                            break

            # Filter out matches that are strict substrings of a longer matched candidate
            filtered_matched: list[KnowledgeCandidate] = []
            for c in matched_cands:
                is_sub = any(c.name != other.name and c.name in other.name for other in matched_cands)
                if not is_sub:
                    filtered_matched.append(c)

            # If exactly one candidate matches directly via alias
            if len(filtered_matched) == 1:
                unique_rule_hit = filtered_matched[0]

        if unique_rule_hit is not None:
            chosen_code = unique_rule_hit.code
            chosen_id = unique_rule_hit.id
            confidence = 1.0
            provenance = ClassificationProvenance(
                classification_source="alias_rule",
                classifier_type="deterministic_alias",
                prompt_version=PROMPT_VERSION,
                candidate_set=candidate_codes,
                confidence=confidence,
            )
            # Fetch skills
            skill_cands = self.get_skill_candidates(chosen_code, chosen_id)
            skill_codes = [s.code for s in skill_cands]
            if not skill_cands:
                return ClassificationResult(
                    knowledge_node_id=chosen_id,
                    knowledge_node_code=chosen_code,
                    knowledge_confidence=confidence,
                    knowledge_candidates=candidate_codes,
                    skill_id=None,
                    skill_code=None,
                    skill_confidence=0.0,
                    skill_candidates=[],
                    skill_bindings=[],
                    provenance=provenance,
                    validation_status=ValidationStatus.NEEDS_REVIEW,
                    added_review_reasons=[ReviewReason.SKILL_UNMAPPED],
                )
            primary_skill = skill_cands[0]
            bindings = [
                SkillBindingItem(
                    learning_skill_id=primary_skill.id,
                    skill_code=primary_skill.code,
                    skill_name=primary_skill.name,
                    knowledge_node_code=chosen_code,
                    role="primary",
                    weight=1.0,
                )
            ]
            status = ValidationStatus.NEEDS_REVIEW if has_critical_error else ValidationStatus.AUTO_ACCEPTED

            return ClassificationResult(
                knowledge_node_id=chosen_id,
                knowledge_node_code=chosen_code,
                knowledge_confidence=confidence,
                knowledge_candidates=candidate_codes,
                skill_id=primary_skill.id,
                skill_code=primary_skill.code,
                skill_confidence=1.0,
                skill_candidates=skill_codes,
                skill_bindings=bindings,
                provenance=provenance,
                validation_status=status,
                added_review_reasons=[],
            )

        # Tier 3: Model Classification via ModelGateway
        system_prompt = (
            "You are a Civil Service Exam (行测) Knowledge Classifier.\n"
            "Select the most accurate primary knowledge node code STRICTLY from the provided candidate list.\n"
            "DO NOT invent any new code or node names.\n"
            f"Candidate list:\n{json.dumps([c.model_dump() for c in candidates], ensure_ascii=False, indent=2)}"
        )
        user_prompt = f"Module: {module}\nStem: {stem}\nOptions: {json.dumps(options, ensure_ascii=False)}\nExplanation: {explanation}"

        messages = [
            Message(role="system", content=system_prompt),
            Message(role="user", content=user_prompt),
        ]

        output: KnowledgeClassificationOutput | None = None
        used_model = None
        used_provider = None
        for used_policy in ('FAST', 'STRONG'):
            try:
                gen_res = await self.gateway.generate(
                    task_type="question_classification", messages=messages,
                    schema=KnowledgeClassificationOutput, model_policy=used_policy,
                )
            except GatewayError as exc:
                logger.warning("%s classification failed: %s", used_policy, type(exc).__name__)
                output = None
                continue
            output = gen_res.data
            used_model = gen_res.model_name
            used_provider = gen_res.provider_name
            if output is not None and output.primary_knowledge_node_code in candidate_codes:
                break

        if output is None or output.primary_knowledge_node_code not in candidate_codes:
            # Still invalid: Reject and mark UNMAPPED
            provenance = ClassificationProvenance(
                classification_source="model_rejected",
                classifier_type=f"llm_{used_policy.lower()}",
                model_provider=used_provider,
                model_name=used_model,
                prompt_version=PROMPT_VERSION,
                candidate_set=candidate_codes,
                confidence=0.0,
            )
            return ClassificationResult(
                knowledge_node_id=None,
                knowledge_node_code=None,
                knowledge_confidence=0.0,
                knowledge_candidates=candidate_codes,
                skill_id=None,
                skill_code=None,
                skill_confidence=0.0,
                skill_candidates=[],
                skill_bindings=[],
                provenance=provenance,
                validation_status=ValidationStatus.NEEDS_REVIEW,
                added_review_reasons=[ReviewReason.KNOWLEDGE_LOW_CONFIDENCE],
            )

        chosen_code = output.primary_knowledge_node_code
        confidence = output.confidence
        chosen_cand = next((c for c in candidates if c.code == chosen_code), None)
        chosen_id = chosen_cand.id if chosen_cand else None

        # Check for multiple close primary candidates
        if len(matched_cands) > 1 and confidence < 0.85:
            added_reasons.append(ReviewReason.MULTIPLE_PRIMARY_CANDIDATES)

        provenance = ClassificationProvenance(
            classification_source=f"model_{used_policy.lower()}",
            classifier_type=f"llm_{used_policy.lower()}",
            model_provider=used_provider,
            model_name=used_model,
            prompt_version=PROMPT_VERSION,
            candidate_set=candidate_codes,
            confidence=confidence,
        )

        # Tier 4: Skill Classification
        skill_cands = self.get_skill_candidates(chosen_code, chosen_id)
        skill_codes = [s.code for s in skill_cands]
        if not skill_cands:
            return ClassificationResult(
                knowledge_node_id=chosen_id,
                knowledge_node_code=chosen_code,
                knowledge_confidence=confidence,
                knowledge_candidates=candidate_codes,
                skill_id=None,
                skill_code=None,
                skill_confidence=0.0,
                skill_candidates=[],
                skill_bindings=[],
                provenance=provenance,
                validation_status=ValidationStatus.NEEDS_REVIEW,
                added_review_reasons=added_reasons + [ReviewReason.SKILL_UNMAPPED],
            )
        primary_skill = skill_cands[0]
        bindings = [
            SkillBindingItem(
                learning_skill_id=primary_skill.id,
                skill_code=primary_skill.code,
                skill_name=primary_skill.name,
                knowledge_node_code=chosen_code,
                role="primary",
                weight=1.0,
            )
        ]
        skill_conf = 0.90

        # Determine validation status
        if has_critical_error or added_reasons:
            val_status = ValidationStatus.NEEDS_REVIEW
        elif confidence >= 0.85:
            val_status = ValidationStatus.AUTO_ACCEPTED
        elif confidence >= 0.65:
            val_status = ValidationStatus.ACCEPTED_WITH_AUDIT
        else:
            val_status = ValidationStatus.NEEDS_REVIEW
            added_reasons.append(ReviewReason.KNOWLEDGE_LOW_CONFIDENCE)

        return ClassificationResult(
            knowledge_node_id=chosen_id,
            knowledge_node_code=chosen_code,
            knowledge_confidence=confidence,
            knowledge_candidates=candidate_codes,
            skill_id=primary_skill.id,
            skill_code=primary_skill.code,
            skill_confidence=skill_conf,
            skill_candidates=skill_codes,
            skill_bindings=bindings,
            provenance=provenance,
            validation_status=val_status,
            added_review_reasons=added_reasons,
        )
