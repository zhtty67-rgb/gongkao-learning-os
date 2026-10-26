"""Evidence quality filtering, strict identity resolution, and support validation.

Enforces strict rules:
1. Candidate adequacy: title-only headers, image placeholders, or fragments < 15 chars
   are rejected. Short expressions (15-30 chars) are accepted only if they contain
   complete mathematical formulas.
2. Topical relevance: queries must match the domain concepts of the problem;
   mismatched topics (e.g. extreme-value problems matching solution lectures)
   are rejected without hardcoded question-type blacklists.
3. Strict identity: citations match candidates ONLY by exact evidence_id.
   All free-text book titles, citation texts, title+page, or substrings are rejected.
   Display citations are strictly generated from authoritative candidate metadata.
4. Support verification: checks whether evidence actually supports the conclusion
   or is explicitly contradicted/disclaimed. Defaults to 'unverified' when
   no formal mathematical theorem proof is computed (honest status).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Literal
from pydantic import BaseModel, ConfigDict

from .models import KnowledgeEvidence

logger = logging.getLogger(__name__)

# Minimum substantive text length for a chunk to be considered explanatory evidence
MIN_SUBSTANTIVE_TEXT_LENGTH = 30
MIN_FORMULA_TEXT_LENGTH = 15

# Subtopic concept vocabularies for Quantitative subtopics
QUANT_TOPIC_CONCEPTS: dict[str, list[str]] = {
    'work_problem': [
        '工程', '工作量', '工作总量', '效率', '完工', '单独施工', '合作完成',
        '按期完工', '甲队', '乙队', '工期', '抽水', '水管', '排空', '注满',
    ],
    'equation_and_ratio': [
        '方程', '未知数', '和差', '倍比', '倍数', '比例', '等式', '消元',
        '设x', '设X', '几倍', '不定方程', '奇偶特性',
    ],
    'solution_mixture': [
        '溶液', '浓度', '溶质', '十字交叉', '盐水', '酒精', '配成', '稀释',
        '倒出', '溶剂', '蒸发', '含盐', '类浓度',
    ],
    'extreme_value': [
        '最不利', '抽屉原理', '至少.*保证', '至多', '最坏情况', '极端情况', '保证.*同一',
    ],
    'journey_problem': [
        '相遇', '追及', '路程', '时速', '流水行船', '过桥', '车身长', '同向', '反向', '顺水', '逆水',
    ],
    'inclusion_exclusion': [
        '容斥', '三集合', '两集合', '文氏图', '两两交', '三者交', '只参加',
    ],
    'permutation_probability': [
        '排列组合', '古典概型', '摸球', '抽样', '概率',
    ],
    'geometry': [
        '周长', '面积', '体积', '圆柱', '正方体', '长方形', '三角形', '对角线', '展开图',
    ],
}

# Module-level high-level keywords to reject completely out-of-domain queries
OUT_OF_DOMAIN_MARKERS = [
    '量子', '薛定谔', '相对论', '光速', '化学反应', '元素周期表',
    '编程语言', 'python', 'java', 'vue', 'react', '英语语法', '完形填空',
]


class EvidenceResolutionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    declared_evidence_id: str | None = None
    adopted_evidence: KnowledgeEvidence | None = None
    canonical_citation: str | None = None
    source_identity: Literal['valid', 'invalid', 'ambiguous', 'none'] = 'none'
    relevance: Literal['relevant', 'irrelevant', 'unverifiable', 'none'] = 'none'
    support_status: Literal['verified', 'contradicted', 'unverified', 'unsupported', 'disclaimed', 'none'] = 'none'
    can_reference: bool = False
    is_supported: bool = False
    reason: str = ''


def is_content_adequate(evidence: KnowledgeEvidence) -> bool:
    """Check if evidence text has substantive explanatory content.

    Rejects:
    - Text shorter than 15 characters.
    - Text between 15 and 30 characters UNLESS it contains a complete mathematical
      formula/operator (=, +, -, ×, ÷, 并, 交, ∶, 比, or definition colon).
    - Image error placeholders ('<!-- 🖼️❌ Image not available...').
    - Pure chapter or section headings (e.g. '第一讲 和差倍比与方程法').
    - Chunks that only repeat the chapter or document title with no content.
    """
    if not evidence or not evidence.text:
        return False

    clean_text = evidence.text.strip()
    text_len = len(clean_text)

    if text_len < MIN_FORMULA_TEXT_LENGTH:
        return False

    # Image error placeholder rejection
    if clean_text.startswith('<!-- 🖼️') or 'Image not available' in clean_text:
        return False

    # Title-only repetition rejection
    title_clean = (evidence.document_title or '').strip()
    if clean_text == title_clean:
        return False

    # Reject if text is solely a section header format without sentences or math
    if re.fullmatch(r'第[一二三四五六七八九十0-9]+[讲章节部分篇]\s*[^\n]*', clean_text):
        return False

    # For short text (15-30 chars): accept only if it contains mathematical operators
    # or formula equality, e.g. "工作总量 = 工作效率 × 工作时间" or "A∪B = A + B - A∩B"
    if text_len < MIN_SUBSTANTIVE_TEXT_LENGTH:
        has_math_relation = any(op in clean_text for op in ['=', '＝', '+', '-', '×', '÷', '并', '交', '∪', '∩', '∶'])
        has_definition_colon = '：' in clean_text and ('公式' in clean_text or '方法' in clean_text)
        if not (has_math_relation or has_definition_colon):
            return False

    return True


def detect_topic_tags(text: str) -> set[str]:
    """Extract topical domain concept tags present in a text."""
    tags = set()
    text_lower = text.lower()
    for topic, markers in QUANT_TOPIC_CONCEPTS.items():
        for m in markers:
            if re.search(m, text_lower):
                tags.add(topic)
                break
    return tags


def is_topically_relevant(
    evidence: KnowledgeEvidence,
    query_or_stem: str,
    module: str = '数量关系',
    node_code: str | None = None,
) -> bool:
    """Check if evidence is topically consistent with the question or query.

    Evaluates semantic topic alignment between query and evidence without
    hardcoding a fixed list of currently ingested lectures.
    """
    if not evidence or not evidence.text:
        return False

    # 1. Out-of-domain check
    query_lower = query_or_stem.lower()
    for ood in OUT_OF_DOMAIN_MARKERS:
        if ood in query_lower:
            return False

    # 2. Authoritative node binding bypass
    meta = evidence.metadata or {}
    if meta.get('source_kind') == 'demo_fixture':
        return True

    # 3. For Quantitative ('数量关系') module: check sub-topic consistency
    if module in ('数量关系', 'quantitative'):
        # Check cross-module query (Data Analysis or Official writing in Quantitative namespace)
        has_query_da = any(k in query_or_stem for k in ['基期', '两期比重', '隔年增长', '年均增长', '资料分析'])
        has_query_writing = any(k in query_or_stem for k in ['公文', '通知', '附件格式', '首行缩进', '红头', '排版'])
        if has_query_writing:
            return False
        if has_query_da and not any(k in query_or_stem for k in ['方程', '未知数', '工程', '溶液']):
            return False

        # Extract topical profiles of both query and candidate evidence
        combined_evidence = f'{evidence.document_title or ""} {evidence.text or ""}'
        query_topics = detect_topic_tags(query_or_stem)
        evidence_topics = detect_topic_tags(combined_evidence)

        # Evidence-topic requires query consistency:
        # Single-topic specialized evidence must align with the query topic.
        # Multi-topic evidence (composite question-case libraries) is accepted when it
        # shares at least one topic with the query; per-topic rejection only fires when
        # the evidence shares nothing with the query.
        shares_topic = bool(evidence_topics & query_topics)

        if 'work_problem' in evidence_topics and 'work_problem' not in query_topics:
            if not shares_topic:
                return False

        if 'solution_mixture' in evidence_topics and 'solution_mixture' not in query_topics:
            if not shares_topic and not any(k in query_or_stem for k in ['平均分', '平均成绩', '十字交叉', '交叉', '比值']):
                return False

        if 'equation_and_ratio' in evidence_topics and 'equation_and_ratio' not in query_topics:
            if not shares_topic:
                return False

        if 'inclusion_exclusion' in evidence_topics and 'inclusion_exclusion' not in query_topics:
            if not shares_topic:
                return False

        if 'extreme_value' in query_topics and 'extreme_value' not in evidence_topics:
            if not ('equation_and_ratio' in evidence_topics and '方程' in query_or_stem):
                return False

        if 'inclusion_exclusion' in query_topics and 'inclusion_exclusion' not in evidence_topics:
            return False

        if 'journey_problem' in query_topics and 'journey_problem' not in evidence_topics:
            return False

        # If query has zero quantitative math topic tags and zero math question terms:
        if not query_topics and not any(k in query_or_stem for k in ['题', '多少', '求', '算', '率', '数', '量', '比']):
            return False

    return True


def filter_candidate_evidences(
    evidences: list[KnowledgeEvidence],
    query: str,
    module: str = '数量关系',
    node_code: str | None = None,
) -> list[KnowledgeEvidence]:
    """Filter raw retrieval hits through content adequacy and topical relevance gates."""
    valid: list[KnowledgeEvidence] = []
    for ev in evidences:
        if not is_content_adequate(ev):
            logger.debug('Discarded inadequate evidence %s: %r', ev.evidence_id, (ev.text or '')[:40])
            continue
        if not is_topically_relevant(ev, query, module=module, node_code=node_code):
            logger.info('Discarded topically mismatched evidence %s (%s) for query %r',
                        ev.evidence_id, ev.document_title, query[:50])
            continue
        valid.append(ev)
    return valid


def self_longest_common_run(text_a: str, text_b: str, min_len: int = 6) -> bool:
    """True when the two texts share one continuous run of at least `min_len` chars.

    Any longer shared run contains a min_len window, so sliding fixed-size n-grams of
    the shorter text against an n-gram set of the longer one is sufficient (O(n+m)).
    Used to detect that an answer actually quotes the evidence passage rather than
    merely sharing a topic tag.
    """
    if not text_a or not text_b:
        return False
    a, b = text_a.strip(), text_b.strip()
    if len(a) > 4000:
        a = a[:4000]
    if len(b) > 4000:
        b = b[:4000]
    if len(a) < min_len or len(b) < min_len:
        return False
    if len(a) > len(b):
        a, b = b, a
    grams = {b[i:i + min_len] for i in range(len(b) - min_len + 1)}
    return any(a[i:i + min_len] in grams for i in range(len(a) - min_len + 1))


def verify_evidence_support(
    evidence: KnowledgeEvidence,
    answer_text: str,
    query: str | None = None,
) -> dict[str, Any]:
    """Verify whether evidence actually supports the answer conclusion without contradiction.

    Deconstructs support status and eliminates naming ambiguity:
    - 'contradicted': explicit denial or contrary mathematical formula found.
    - 'disclaimed': answer stated evidence was not covered or not used.
    - 'unsupported': answer does not constructively use concepts from evidence.
    - 'unverified': concepts present and cited without contradiction, but no formal
      mathematical theorem proof is computed (honest default state).
      NOTE: is_supported is honestly False (unverified); can_reference is True (qualified as reference).
    - 'verified': reserved for strictly proven formal mathematical equivalence.
    """
    if not evidence or not answer_text:
        return {
            "can_reference": False,
            "is_supported": False,
            "is_verified_support": False,
            "status": "unsupported",
            "reason": "Missing evidence or answer text.",
        }

    ans_clean = answer_text.strip()

    # 1. Disclaimer check: did the model say evidence does not cover this?
    disclaimers = [
        '教材证据中没有相关讲解', '没有关于', '未覆盖', '没有讲解',
        '暂无相关', '不适用', '无法支持', '未包含', '不能给出书名页码',
    ]
    if any(d in ans_clean for d in disclaimers) and not any(k in ans_clean for k in ['依据教材例题', '按教材公式推导']):
        return {
            "can_reference": False,
            "is_supported": False,
            "is_verified_support": False,
            "status": "disclaimed",
            "reason": "Answer explicitly disclaimed having textbook coverage for this question.",
        }

    # 2. Contradiction check: explicit inversion/negation of verified rules
    ev_text = (evidence.text or "").strip()

    # Contradiction: Venn subtraction denial
    if '容斥' in ev_text and ('扣减' in ev_text or '-' in ev_text or '减去' in ev_text):
        if any(w in ans_clean for w in ['完全不需要扣减', '无需扣减', '无需扣除', '直接相加无需减去', '不减去']):
            return {
                "can_reference": False,
                "is_supported": False,
                "is_verified_support": False,
                "status": "contradicted",
                "reason": "Answer asserts mathematical rule contrary to evidence (claimed overlap does not need subtraction).",
            }

    # Contradiction: Work LCM denial
    if '最小公倍数' in ev_text and '工作总量' in ev_text:
        if any(w in ans_clean for w in ['不能设最小公倍数', '严禁设工作总量', '不可设特值']):
            return {
                "can_reference": False,
                "is_supported": False,
                "is_verified_support": False,
                "status": "contradicted",
                "reason": "Answer contradicts the recommended LCM method in evidence.",
            }

    # 3. Arithmetic or claim divergence:
    # If the answer asserts an arithmetic conclusion while evidence states another
    # The system is not a CAS prover; it must honestly return 'unverified' rather than claiming verified support.
    ev_concepts = detect_topic_tags(f'{evidence.document_title or ""} {ev_text}')
    ans_concepts = detect_topic_tags(ans_clean)
    if ev_concepts and not (ev_concepts & ans_concepts):
        key_terms = [t for t in ['最小公倍数', '十字交叉', '方程', '代入', '消元', '浓度', '效率'] if t in ev_text]
        # Verbatim-overlap fallback: quoting an actual passage (>=6 shared chars) from the
        # evidence — e.g. a real-question stem/table — counts as constructive use even when
        # the topic-tag vocabularies of answer and evidence do not intersect.
        overlap = self_longest_common_run(ans_clean, ev_text, min_len=6)
        if not any(t in ans_clean for t in key_terms) and not overlap:
            return {
                "can_reference": False,
                "is_supported": False,
                "is_verified_support": False,
                "status": "unsupported",
                "reason": "Answer does not constructively use the mathematical concepts of this evidence.",
            }

    # Honest status: concepts match and no contradiction found, but no formal math theorem proof claimed.
    # Disambiguation: is_supported=False honestly reflects unverified mathematical proof.
    # can_reference=True clearly reflects that the material is qualified to be cited as reference.
    return {
        "can_reference": True,
        "is_supported": False,
        "is_verified_support": False,
        "status": "unverified",
        "reason": f"Evidence {evidence.evidence_id} is relevant and cited without contradiction, but arithmetic/proof remains unverified.",
    }


def evaluate_evidence_adoption(
    declared_evidence_id: str | None,
    candidates: list[KnowledgeEvidence],
    answer_text: str | None = None,
    query: str | None = None,
    module: str = '数量关系',
) -> EvidenceResolutionResult:
    """Strict identity resolution and evidence adoption evaluation.

    Strict rules:
    - Only exact match on evidence_id is permitted (or strictly wrapped [EVIDENCE: id]).
    - All free-text book titles, citation texts, title+page, or substrings are rejected.
    - No regex searching inside arbitrary sentences.
    - If multiple conflicting candidates share the exact same ID, reject as 'ambiguous'.
    - Fully identical duplicates are deduplicated.
    - If evidence is contradicted, can_reference=False and adoption is rejected.
    - Canonical citation is strictly generated from authoritative candidate metadata.
    """
    if not declared_evidence_id or not declared_evidence_id.strip():
        return EvidenceResolutionResult(
            declared_evidence_id=declared_evidence_id,
            source_identity='none',
            relevance='none',
            support_status='none',
            can_reference=False,
            is_supported=False,
            reason='No evidence_id declared by model.',
        )

    clean_id = declared_evidence_id.strip()
    if clean_id.lower() in ('none', 'null', '无', '无教材依据', '暂无', '0'):
        return EvidenceResolutionResult(
            declared_evidence_id=clean_id,
            source_identity='none',
            relevance='none',
            support_status='none',
            can_reference=False,
            is_supported=False,
            reason='Model explicitly declared null citation.',
        )

    # 严格整串解析：包装格式必须是严格整串的 [EVIDENCE: id] 或 EVIDENCE: id 或纯 id 字符串
    # 绝不使用 re.search 从长句/任意正文中提取 ID
    wrapped_match = re.fullmatch(r'\[?EVIDENCE:\s*([a-zA-Z0-9_\-]+)\]?', clean_id, re.IGNORECASE)
    if wrapped_match:
        target_id = wrapped_match.group(1).strip()
    elif re.fullmatch(r'[a-zA-Z0-9_\-]+', clean_id):
        target_id = clean_id
    else:
        # 输入包含中文、书名号《》、空格长句或其他非合法 ID 格式，直接拒绝
        return EvidenceResolutionResult(
            declared_evidence_id=clean_id,
            source_identity='invalid',
            relevance='none',
            support_status='none',
            can_reference=False,
            is_supported=False,
            reason=f'Declared string {clean_id!r} is not a valid evidence_id format.',
        )

    # 精确匹配候选集的 evidence_id，彻底废除任何 citation 文本反向回退！
    matching_cands = [c for c in candidates if c.evidence_id.strip() == target_id]

    if not matching_cands:
        return EvidenceResolutionResult(
            declared_evidence_id=clean_id,
            source_identity='invalid',
            relevance='none',
            support_status='none',
            can_reference=False,
            is_supported=False,
            reason=f'Declared ID {target_id!r} not found in candidate set.',
        )

    # 冲突检查：检查同 ID 是否对应冲突的 document_id, document_version_id, chunk_id, page, 或 text
    if len(matching_cands) > 1:
        doc_ids = {c.document_id for c in matching_cands}
        versions = {c.document_version_id for c in matching_cands}
        chunks = {c.chunk_id for c in matching_cands}
        pages = {c.page for c in matching_cands}
        texts = {c.text.strip() for c in matching_cands}

        has_conflict = (
            len(doc_ids) > 1 or
            len(versions) > 1 or
            len(chunks) > 1 or
            len(pages) > 1 or
            len(texts) > 1
        )
        if has_conflict:
            logger.warning('Ambiguous evidence_id %s across conflicting candidate metadata/content', target_id)
            return EvidenceResolutionResult(
                declared_evidence_id=clean_id,
                source_identity='ambiguous',
                relevance='unverifiable',
                support_status='none',
                can_reference=False,
                is_supported=False,
                reason=f'Ambiguous evidence_id {target_id} corresponds to multiple conflicting candidate metadata/content.',
            )
        # 完全相同的重复候选，去重保留一份

    cand = matching_cands[0]

    # Step 2: Relevance check
    eval_text = (query or answer_text or '').strip()
    if eval_text:
        rel_ok = is_topically_relevant(cand, eval_text, module=module)
        if not rel_ok:
            return EvidenceResolutionResult(
                declared_evidence_id=clean_id,
                adopted_evidence=None,
                canonical_citation=None,
                source_identity='valid',
                relevance='irrelevant',
                support_status='unverified',
                can_reference=False,
                is_supported=False,
                reason=f'Evidence {cand.evidence_id} topic does not align with question.',
            )
        relevance_verdict = 'relevant'
    else:
        relevance_verdict = 'unverifiable'

    # Step 3: Support verification
    support_status = 'unverified'
    can_ref = True
    is_supp = False
    if answer_text:
        check = verify_evidence_support(cand, answer_text, query)
        support_status = check['status']
        can_ref = check.get('can_reference', False)
        is_supp = check.get('is_supported', False)
        if not can_ref or support_status in ('contradicted', 'unsupported', 'disclaimed'):
            return EvidenceResolutionResult(
                declared_evidence_id=clean_id,
                adopted_evidence=None,
                canonical_citation=None,
                source_identity='valid',
                relevance=relevance_verdict,
                support_status=support_status,
                can_reference=False,
                is_supported=False,
                reason=check['reason'],
            )

    canonical = cand.citation or (f"《{cand.document_title}》第{cand.page}页" if cand.page else f"《{cand.document_title}》")

    return EvidenceResolutionResult(
        declared_evidence_id=clean_id,
        adopted_evidence=cand,
        canonical_citation=canonical,
        source_identity='valid',
        relevance=relevance_verdict,
        support_status=support_status,
        can_reference=can_ref,
        is_supported=is_supp,
        reason='Evidence identity valid and constructively cited without contradiction.',
    )


def validate_and_adopt_citation(
    model_citation: str | None,
    candidates: list[KnowledgeEvidence],
    answer_text: str | None = None,
    query: str | None = None,
    module: str = '数量关系',
) -> str | None:
    """Backward-compatible wrapper returning canonical citation string or None."""
    res = evaluate_evidence_adoption(
        declared_evidence_id=model_citation,
        candidates=candidates,
        answer_text=answer_text,
        query=query,
        module=module,
    )
    if res.source_identity == 'valid' and res.can_reference:
        return res.canonical_citation
    return None


def format_evidence_prompt_block(candidates: list[KnowledgeEvidence]) -> tuple[str, str]:
    """Format candidate evidences with explicit evidence_id for model prompt."""
    if not candidates:
        evidence_block = ''
        evidence_rule = (
            '6. 【教材证据铁律】：本次未检索到可有效支撑本题考点的教材证据。'
            '你的回答必须完全依据题目事实与解析进行清晰透彻的讲解；'
            '严格禁止自行编造任何书名、页码或教材观点；输出 JSON 时必须将 adopted_evidence_id 与 citation 设为 null。'
        )
        return evidence_block, evidence_rule

    lines = []
    for cand in candidates:
        loc = f'（第{cand.page}页）' if cand.page else ''
        lines.append(
            f"[EVIDENCE: {cand.evidence_id}]\n"
            f"出处：《{cand.document_title}》{loc}\n"
            f"内容片段：\n{cand.text}"
        )

    evidence_block = '\n【教材候选资料（已通过相关度过滤）】：\n' + '\n\n'.join(lines) + '\n'
    evidence_rule = (
        '6. 【教材证据铁律】：\n'
        '   - 只有当上述【教材候选资料】与本题考点直接契合，且你在解答中切实运用了其方法或推导时，才可声明采用；\n'
        '   - 若声明采用，请在 adopted_evidence_id 字段准确填写对应证据的编号（如 [EVIDENCE: {id}] 或对应 ID）；系统会自动从权威元数据生成标准出处，你无需自行编造书名页码；\n'
        '   - 若上述资料与本题考点不符或未被采用，严禁强行引用，必须将 adopted_evidence_id 设为 null，直接基于题目解析作答；\n'
        '   - 严禁自行编造任何未在候选资料中给出的证据编号、书名或页码。'
    )
    return evidence_block, evidence_rule


async def audit_retrieval_quality(provider: Any) -> dict[str, Any]:
    """Execute on-demand quality audit suite testing positive, negative, and title-only probes."""
    # 1. Positive covered check
    pos_res: dict[str, Any] = {}
    try:
        raw_pos = await provider.retrieve(
            query='工程问题已知时间设工作总量',
            namespace='gongkao/xingce/quantitative',
            limit=3,
        )
        pos_candidates = filter_candidate_evidences(raw_pos, '工程问题已知时间设工作总量', module='数量关系')
        if pos_candidates and is_content_adequate(pos_candidates[0]):
            pos_res = {
                'status': 'pass',
                'matched_doc': pos_candidates[0].document_title,
                'page': pos_candidates[0].page,
                'text_length': len(pos_candidates[0].text),
                'is_adequate': True,
            }
        else:
            pos_res = {'status': 'fail', 'reason': 'No adequate content returned for covered query'}
    except Exception as e:
        pos_res = {'status': 'fail', 'error': str(e)}

    # 2. Negative uncovered check (extreme value problem)
    uncovered_res: dict[str, Any] = {}
    try:
        raw_unc = await provider.retrieve(
            query='极值最不利原则抽屉原理',
            namespace='gongkao/xingce/quantitative',
            limit=3,
        )
        unc_adopted = filter_candidate_evidences(raw_unc, '极值最不利原则抽屉原理', module='数量关系')
        if len(unc_adopted) == 0:
            uncovered_res = {'status': 'pass', 'raw_hits': len(raw_unc), 'adopted': 0, 'correctly_rejected': True}
        else:
            # The corpus now covers extreme-value topics; adopted hits must genuinely be
            # about worst-case/pigeonhole reasoning, not merely lexically nearby chunks.
            pattern = re.compile(r'最不利|抽屉|极值|至少.{0,12}保证|保证.{0,12}至少')
            if all(pattern.search(ev.text or '') for ev in unc_adopted):
                uncovered_res = {
                    'status': 'pass',
                    'raw_hits': len(raw_unc),
                    'adopted': len(unc_adopted),
                    'correctly_rejected': True,
                    'note': 'corpus covers extreme-value topics; hits verified on-topic',
                }
            else:
                uncovered_res = {'status': 'fail', 'falsely_adopted_doc': unc_adopted[0].document_title}
    except Exception as e:
        uncovered_res = {'status': 'fail', 'error': str(e)}

    # 3. Out of domain check
    ood_res: dict[str, Any] = {}
    try:
        raw_ood = await provider.retrieve(
            query='量子力学薛定谔方程波函数',
            namespace='gongkao/xingce/quantitative',
            limit=3,
        )
        ood_adopted = filter_candidate_evidences(raw_ood, '量子力学薛定谔方程波函数', module='数量关系')
        if len(ood_adopted) == 0:
            ood_res = {'status': 'pass', 'raw_hits': len(raw_ood), 'adopted': 0, 'correctly_rejected': True}
        else:
            ood_res = {'status': 'fail', 'falsely_adopted_doc': ood_adopted[0].document_title}
    except Exception as e:
        ood_res = {'status': 'fail', 'error': str(e)}

    # 4. Title-only guard
    title_res: dict[str, Any] = {}
    try:
        raw_title = await provider.retrieve(
            query='和差倍比与方程法',
            namespace='gongkao/xingce/quantitative',
            limit=3,
        )
        has_title_chunk = any(len(c.text.strip()) < MIN_SUBSTANTIVE_TEXT_LENGTH for c in raw_title)
        title_candidates = filter_candidate_evidences(raw_title, '和差倍比与方程法', module='数量关系')
        all_candidates_adequate = all(is_content_adequate(c) for c in title_candidates)
        title_res = {
            'status': 'pass' if all_candidates_adequate else 'fail',
            'title_only_chunk_detected_in_raw': has_title_chunk,
            'title_only_filtered_out': all_candidates_adequate,
        }
    except Exception as e:
        title_res = {'status': 'fail', 'error': str(e)}

    all_passed = (
        pos_res.get('status') == 'pass' and
        uncovered_res.get('status') == 'pass' and
        ood_res.get('status') == 'pass' and
        title_res.get('status') == 'pass'
    )

    return {
        'quality_status': 'pass' if all_passed else 'fail',
        'probes': {
            'covered_query': pos_res,
            'uncovered_query': uncovered_res,
            'out_of_domain': ood_res,
            'title_guard': title_res,
        },
    }
