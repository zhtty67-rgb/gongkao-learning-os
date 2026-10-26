# -*- coding: utf-8 -*-
"""教师 Agent：产出待核查疑点 + 按教师/题型筛选的证据包。

定位变化：本地确定性检查器只负责"提出疑点"，不再直接判错。
- 连续重合 / 关键词缺失 / 热词命中 / 句式标记等只产生疑点，是否成立由
  AI 语义审查（semantic_review）结合本题材料与教师规则判断；
- 确定性的格式、字数类检查保留确定性结论，但注明实际计算口径；
- 题目案例（question_cases）通过 evidence.build_evidence_pack 进入批改上下文。
"""

import re
from difflib import SequenceMatcher

from . import material_analyzer as ma
from . import library as lib
from .evidence import build_evidence_pack

# ---------- 相似度工具 ----------

def lcs_ratio(a, b):
    """最长公共连续子串长度（用于检测照抄/泄露）。"""
    m = SequenceMatcher(None, a, b, autojunk=False)
    match = m.find_longest_match(0, len(a), 0, len(b))
    return match.size


_PUNCT = re.compile(r"[，。；、！？,;:.“”\"'‘’（）()\s]")


def longest_common_substr(a, b):
    """返回 a/b 的最长公共连续子串字符串（用于生成可验证标志 needle）。"""
    m = SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return a[m.a:m.a + m.size]


def lcs_nopunct(a, b):
    """去标点后的最长公共连续子串长度（抓无标点照抄）。"""
    return lcs_ratio(_PUNCT.sub("", a), _PUNCT.sub("", b))


def char_sim(a, b):
    m = SequenceMatcher(None, a, b, autojunk=False)
    return m.ratio()


# ---------- 检索器 ----------

from .retriever import Retriever  # noqa: E402  (纯 Python TF-IDF，零依赖)


# ---------- 诊断检查器 ----------

def check_descriptive_leak(answer_points, mat):
    """疑点一：与材料描述性语言连续重合（POL_002 类规则）。

    重合不必然错误：合理保留材料中的规范表述应被接受，故仅作为待核查疑点。
    """
    items = []
    desc_sents = [s["text"] for s in mat["descriptive_sentences"]]
    all_sents = [s["text"] for p in mat["paragraphs"] for s in p["sentences"]]
    for pt in answer_points:
        best_len, best_src = 0, ""
        for sent in desc_sents + all_sents:
            size = max(lcs_ratio(pt, sent), lcs_nopunct(pt, sent))
            if size > best_len:
                best_len, best_src = size, sent
        if best_len >= 12:
            needle = longest_common_substr(pt, best_src) or longest_common_substr(
                _PUNCT.sub("", pt), _PUNCT.sub("", best_src)
            )
            items.append(
                {
                    "type": "VERBOSE",
                    "severity": "high" if best_len >= 16 else "medium",
                    "student_span": pt,
                    "evidence": best_src[:60],
                    "detail": (
                        f"与材料原文连续重合 {best_len} 字。若保留的是材料中的规范性表述属合理；"
                        "若为叙事性/案例性细节照抄则需提炼改写。请核查该句在材料中的作用。"
                    ),
                    "verify": {"kind": "span_absent", "needle": needle, "threshold": 8},
                }
            )
    return items


def check_inference_and_slogans(answer_points, mat):
    """疑点二：材料中未出现的品质词/热词（POL_004/POL_006 类规则）。

    “材料没有这个词”不等于概括无依据：忠实概括常需换词，故仅作为疑点交语义审查。
    """
    items = []
    mat_text = "".join(s["text"] for p in mat["paragraphs"] for s in p["sentences"])
    mat_text_flat = mat_text.replace("“", "").replace("”", "")
    for pt in answer_points:
        for w in ma.ABSTRACT_QUALITY:
            if w in pt and w not in mat_text_flat:
                items.append(
                    {
                        "type": "UNSUPPORTED_INFERENCE",
                        "severity": "medium",
                        "student_span": pt,
                        "evidence": w,
                        "detail": (
                            f"材料中未出现“{w}”这一表述。若它是对材料内容的忠实概括则可保留；"
                            "若材料无对应内容支撑则属考生自行推导/拔高。请核查材料是否有依据。"
                        ),
                        "verify": {"kind": "word_absent", "needle": w},
                    }
                )
        for w in ma.MACRO_SLOGAN:
            if w in pt and w not in mat_text_flat:
                items.append(
                    {
                        "type": "OVER_ABSTRACTION",
                        "severity": "high",
                        "student_span": pt,
                        "evidence": w,
                        "detail": (
                            f"材料中未出现“{w}”这一热词。若材料有对应事实支撑则可保留；"
                            "若无依据属套用热词（假大空）。请核查材料是否有依据。"
                        ),
                        "verify": {"kind": "word_absent", "needle": w},
                    }
                )
    return items


def check_qualifier_loss(answer_points, mat):
    """疑点三：范围限定词丢失（SCOPE_EXPANSION）。"""
    items = []
    for q in mat["all_qualifiers"]:
        for p in mat["paragraphs"]:
            for s in p["sentences"]:
                if q not in s["text"]:
                    continue
                # 找到带限定词的材料句，看学生是否有对应点保留了它
                matched = [pt for pt in answer_points if lcs_ratio(pt, s["text"]) >= 8]
                if matched and not any(q in pt for pt in matched):
                    items.append(
                        {
                            "type": "SCOPE_EXPANSION",
                            "severity": "medium",
                            "student_span": matched[0],
                            "evidence": s["text"][:60],
                            "detail": (
                                f"材料对应表述含限定词“{q}”，作答中未见保留，存在范围扩大风险。"
                                "若限定词已被其他词忠实概括可保留原样，请核查。"
                            ),
                            "verify": {"kind": "word_present", "needle": q},
                        }
                    )
    return items


def check_change_structure(answer_points, question_text):
    """疑点四：变化题缺少“原来/现在”对比结构（POL_005，口径：仅检出题干问“变化/前后对比”时）。"""
    items = []
    if not re.search(r"变化|新变化|前后", question_text or ""):
        return items
    joined = "".join(answer_points)
    if not any(m in joined for m in ma.CHANGE_MARKERS):
        items.append(
            {
                "type": "POOR_STRUCTURE",
                "severity": "high",
                "student_span": joined[:60],
                "evidence": "题干要求概括变化",
                "detail": (
                    "题干问“变化”而作答中未检出“原来/现在/过去/如今”等对比标记"
                    "（计算口径：CHANGE_MARKERS 词表逐字匹配）。变化类题目通常需要前后对比结构。"
                ),
                "verify": {"kind": "any_present", "needles": list(ma.CHANGE_MARKERS)},
            }
        )
    return items


def check_summary_first(answer_points, mat):
    """疑点五：总分段落疑似漏用段首总结句（POL_001）。"""
    items = []
    for p in mat["paragraphs"]:
        if p["structure"] != "总分":
            continue
        head = p["sentences"][0]
        examples = [s for s in p["sentences"][1:] if s["type"] in ("example", "descriptive")]
        if not examples:
            continue
        over_head = max((lcs_ratio(pt, head["text"]) for pt in answer_points), default=0)
        over_ex = max((lcs_ratio(pt, ex["text"]) for pt in answer_points for ex in examples), default=0)
        if over_ex >= 10 and over_head < 6:
            items.append(
                {
                    "type": "MISSING_POINT",
                    "severity": "medium",
                    "student_span": max(answer_points, key=lambda pt: lcs_ratio(pt, examples[0]["text"])),
                    "evidence": head["text"][:60],
                    "detail": "该段为总-分结构：前有总结、后有案例。疑似只采了案例而漏用段首总结句的信息，请核查要点覆盖。",
                }
            )
    return items


def check_countermeasures(answer_points, question_text):
    """疑点六：对策题动宾缺失（口径：VERB_BANK 词表匹配，未命中仅提示复核）。"""
    items = []
    if not re.search(r"对策|建议|措施|怎么办|如何解决", question_text or ""):
        return items
    for pt in answer_points:
        if len(pt) >= 10 and not any(v in pt for v in ma.VERB_BANK):
            items.append(
                {
                    "type": "COUNTERMEASURE_MISMATCH",
                    "severity": "medium",
                    "student_span": pt,
                    "evidence": "对策需动词+宾语的可执行表述",
                    "detail": (
                        "该对策点未命中机关公文高频动词词表（计算口径：VERB_BANK 匹配），"
                        "可能缺少动词+宾语的可执行表述，请核查是否需要改为动宾结构。"
                    ),
                }
            )
    return items


def check_expert_quote_copy(answer_points, mat):
    """疑点七：与专家评论/哲理句连续重合（POL_006 关联）。

    专家发言是否可以入答案取决于题目任务及该句在材料中的作用，不能一律排除，
    故仅作为疑点交语义审查结合题干判断。
    """
    items = []
    commentary_paras = []
    for p in mat["paragraphs"]:
        ptext = "".join(s["text"] for s in p["sentences"])
        if re.search(r"评论|指出|认为|表示|感叹|直言|强调|说道", ptext):
            commentary_paras.append(ptext)
    for pt in answer_points:
        best_len, best_src = 0, ""
        for ptext in commentary_paras:
            size = max(lcs_ratio(pt, ptext), lcs_nopunct(pt, ptext))
            if size > best_len:
                best_len, best_src = size, ptext
        if best_len >= 8:
            needle = longest_common_substr(pt, best_src) or longest_common_substr(
                _PUNCT.sub("", pt), _PUNCT.sub("", best_src)
            )
            items.append(
                {
                    "type": "OVER_ABSTRACTION",
                    "severity": "high",
                    "student_span": pt,
                    "evidence": best_src[:60],
                    "detail": (
                        "与专家评论/哲理升华句连续重合。此类句子能否入答案取决于本题任务与该句作用"
                        "（有时恰是作答对象），请结合题干核查，不直接判错。"
                    ),
                    "verify": {"kind": "span_absent", "needle": needle, "threshold": 8},
                }
            )
    return items


ALL_CHECKS = [
    check_descriptive_leak,
    check_inference_and_slogans,
    check_qualifier_loss,
    check_summary_first,
]

# 错误类型 → 关键词库：用于把诊断挂到语义最相关的策略上
ERROR_KEYWORDS = {
    "VERBOSE": ["描述", "叙事", "总结句", "照抄", "案例", "画面", "规范词", "转化"],
    "UNSUPPORTED_INFERENCE": ["推导", "拔高", "主观", "尊重原文", "材料有什么", "脑补"],
    "OVER_ABSTRACTION": ["热词", "假大空", "套用", "融合", "空泛", "金句"],
    "SCOPE_EXPANSION": ["范围", "限定", "外延", "扩大", "缩小"],
    "MISSING_POINT": ["总结句", "漏点", "要点", "总分", "首尾"],
    "POOR_STRUCTURE": ["结构", "对比", "组织", "原来", "现在", "小标题", "分条"],
    "COUNTERMEASURE_MISMATCH": ["对策", "动词", "可执行", "动宾", "建议"],
}


def _applies_compatible(applies_to, question_type):
    """策略声明的题型与当前题型是否兼容（双向子串匹配；空 applies_to 视为通用）。"""
    if not applies_to or not question_type:
        return True
    for a in applies_to:
        if a in question_type or question_type in a:
            return True
    return False


def link_policy(item, matched_policies, question_type=""):
    """按关键词命中数把疑点挂到最相关的兼容策略。

    题型兼容是硬条件：兼容池为空时返回 None（由调用方如实标注"无兼容规则"），
    绝不静默退回不兼容规则。
    """
    kws = ERROR_KEYWORDS.get(item["type"], [])
    if not kws:
        return None

    def score_policy(p):
        text = p["name"] + p["rule"] + "".join(p["forbidden_transformations"]) + p["trigger"]
        kw_score = sum(1 for k in kws if k in text)
        return kw_score

    compatible = [mp["policy"] for mp in matched_policies if _applies_compatible(mp["policy"]["applies_to"], question_type)]
    # 无兼容结果 → 不兜底，宁可无规则来源也不挂不相关规则
    best_p, best = None, (0, 0.0)
    for p in compatible:
        kw = score_policy(p)
        if kw == 0:
            continue
        key = (kw, p["confidence"])
        if key > best:
            best, best_p = key, p
    if best_p is None:
        # 关键词未命中时，仍限兼容池内取语义最接近者
        best_s = 0.0
        for p in compatible:
            s = char_sim(item["type"] + item["detail"], p["name"] + p["rule"])
            if s > best_s:
                best_s, best_p = s, p
    return best_p


def run_checks(answer_points, mat, question_text):
    """运行全部疑点检查器并编号（S1, S2, ...）。"""
    items = []
    for fn in ALL_CHECKS:
        items.extend(fn(answer_points, mat))
    items.extend(check_change_structure(answer_points, question_text))
    items.extend(check_countermeasures(answer_points, question_text))
    items.extend(check_expert_quote_copy(answer_points, mat))
    for i, it in enumerate(items, 1):
        it["suspicion_id"] = f"S{i}"
    return items


# ---------- 教师 Agent 主流程 ----------

def grade(payload, policies, question_cases, critique_cases):
    """本地阶段：材料分析 → 疑点检测 → 证据包构建。

    返回结果供两处消费：
    - service.run_teacher_diagnosis：落库（疑点即暂定目标，状态 pending）；
    - semantic_review：疑点 + 证据包进入 AI 受约束语义审查。
    """
    question = payload.get("question", "")
    question_type = payload.get("question_type", "")
    answer_points = [a for a in payload.get("student_answer", []) if a and a.strip()]
    material = payload.get("material", [])

    mat = ma.analyze_material(material)

    # 证据包：按教师隔离 + 题型兼容筛选（question_cases 在此实际进入批改上下文）
    pack = build_evidence_pack(payload.get("teacher_id", ""), payload, policies, question_cases, critique_cases)

    # 规则检索结果（兼容过滤后）用于疑点挂载提示与前端展示
    matched_policies = [
        {"policy": p, "score": 1.0}
        for p in pack["policies"]
    ]

    # 疑点检测（只提出，不判错）
    suspicions = run_checks(answer_points, mat, question)
    diagnosis_hints = []
    for it in suspicions:
        best_p = link_policy(it, matched_policies, question_type)
        it["policy_ref"] = best_p["policy_id"] if best_p else ""
        it["policy_name"] = best_p["name"] if best_p else ""
        it["policy_rule"] = best_p["rule"] if best_p else ""
        diagnosis_hints.append(it)

    # 亮点：与学生要点高度重合的规范/总结句（保留材料规范表述是合理行为）
    strength = []
    norm_sents = [s["text"] for p in mat["paragraphs"] for s in p["sentences"] if s["type"] in ("summary", "normative")]
    for pt in answer_points:
        best_len, best_sent = 0, ""
        for sent in norm_sents:
            size = lcs_ratio(pt, sent)
            if size > best_len:
                best_len, best_sent = size, sent
        if best_len >= 6:
            strength.append({"point": pt, "basis": best_sent[:60], "matched_chars": best_len})

    return {
        "material_analysis": mat,
        "suspicions": suspicions,
        "evidence_pack": pack,
        "matched_policies": [
            {
                "policy_id": p["policy_id"],
                "name": p["name"],
                "score": 1.0,
                "rule": p["rule"],
            }
            for p in pack["policies"]
        ],
        "diagnosis": diagnosis_hints,  # 兼容旧消费方：现为"疑点+暂定规则提示"
        "strength": strength,
        "similar_cases": [
            {
                "case_id": c["case_id"],
                "question": c["question"],
                "error_type": c["error_type"],
                "diagnosis": c["diagnosis"],
                "remedy": c["remedy_instruction"],
                "score": c["score"],
            }
            for c in pack["critique_cases"]
        ],
        "referenced_question_cases": pack["question_cases"],
        "give_full_answer": False,
    }
