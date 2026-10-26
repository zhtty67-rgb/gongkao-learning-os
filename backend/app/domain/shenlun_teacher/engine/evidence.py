# -*- coding: utf-8 -*-
"""证据选择与程序核验。

职责（纯本地、确定性、零模型调用）：
1. build_evidence_pack：按教师隔离 + 题型兼容筛选检索结果，产出带稳定来源 ID 的证据包。
   - 不做兜底回退：当前题型没有兼容规则时如实返回空并说明，不偷偷换用不相关规则。
2. 核验函数：verify_user_quote / verify_material_quote / verify_refs。
   AI 语义审查的每项输出都必须先通过这里的程序核验才会作为"已支持"结论展示。
"""

import re
from difflib import SequenceMatcher

from .retriever import Retriever
from .method_context import (
    UNKNOWN_QUESTION_TYPES,
    _TYPE_FAMILY,
    _applies_compatible,
    _question_type_family,
    build_method_context,
    load_method_notes,
)

_PUNCT = re.compile(r"[，。；、！？,;:.“”\"'‘’（）()\[\]【】\s]")


def _norm(text: str) -> str:
    return _PUNCT.sub("", text or "")


def _lcs(a: str, b: str) -> int:
    m = SequenceMatcher(None, a, b, autojunk=False)
    return m.find_longest_match(0, len(a), 0, len(b)).size


def _case_type_compatible(case_type: str, question_type: str) -> bool:
    """题目案例的 question_type 与引擎题型的宽松族匹配。

    例：引擎 '归纳概括-做法' ↔ 案例 '归纳概括题-做法类'/'归纳概括题-经验类' 同族兼容；
        引擎 '归纳概括-做法' ↔ '综合分析题' 不兼容。
    """
    if not case_type or not question_type:
        return True
    fam = _question_type_family(question_type)
    return any(w in case_type for w in fam)


def _normalize_str_list(value) -> list[str]:
    """案例库字段类型不统一（list/None/dict 混存），归一化为字符串列表。

    dict 形如 {"措施": [..], "问题": [..]}，展开为“分组名：条目”字符串，不丢弃信息。
    """
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, dict):
        out = []
        for group, items in value.items():
            if isinstance(items, list):
                out.extend(f"{group}：{str(it).strip()}" for it in items if str(it).strip())
            elif str(items).strip():
                out.append(f"{group}：{str(items).strip()}")
        return out
    return [str(value).strip()]


# ---------- 证据包 ----------

POLICY_TOP_K = 8
QUESTION_CASE_TOP_K = 2
CRITIQUE_CASE_TOP_K = 3


def build_evidence_pack(
    teacher_id: str,
    payload: dict,
    policies: list[dict],
    question_cases: list[dict],
    critique_cases: list[dict],
) -> dict:
    """按教师 + 题型组织上下文来源记录（方法规则 + 检索规则 + 题目案例 + 纠错案例）。

    统一名单与上下文：
    - 教师方法上下文规则（原则、审题阅读、取舍概括、组织表达、题型专属）与检索规则
      统一形成合法的允许引用名单（去重并保留完整快照）；
    - 提示词构造、首次批改校验和后续复核使用一致的来源记录；
    - 来源必须来自当前教师、真实资料及本轮实际上下文，不放行未提供的 ID。
    """
    question = payload.get("question", "")
    question_type = payload.get("question_type", "")
    answer_points = [a for a in payload.get("student_answer", []) if a and a.strip()]
    query = question + " " + question_type + " " + " ".join(answer_points)
    unknown_type = question_type in UNKNOWN_QUESTION_TYPES
    has_compatible_policies = any(_applies_compatible(p.get("applies_to", []), question_type) for p in policies)

    # 0) 教师方法上下文（塑造模型判断的核心方法）
    mc = build_method_context(teacher_id, question_type, policies)
    notes = load_method_notes()
    policy_by_id = {p["policy_id"]: p for p in policies if isinstance(p, dict) and p.get("policy_id")}

    def _pack_policy_dict(p: dict, score: float = 1.0) -> dict:
        out = {
            "policy_id": p["policy_id"],
            "name": p.get("name", ""),
            "trigger": p.get("trigger", ""),
            "rule": p.get("rule", ""),
            "reasoning": p.get("reasoning", ""),
            "applies_to": p.get("applies_to", []),
            "must_preserve": p.get("must_preserve", []),
            "may_remove": p.get("may_remove", []),
            "forbidden_transformations": p.get("forbidden_transformations", []),
            "positive_example": p.get("positive_example", {}) or {},
            "negative_example": p.get("negative_example", {}) or {},
            "confidence": float(p.get("confidence", 0.8) or 0.8),
            "score": score,
            "source_quote": ((p.get("source") or [{}])[0].get("quote", "") or "")[:200],
        }
        note = notes.get(p["policy_id"])
        if note and note.get("application"):
            out["application_note"] = note["application"]
        return out

    # 1) 题目案例：检索 → 同族题型过滤（题型待判定时不过滤，如实说明）
    qc_hits: list[dict] = []
    if question_cases:
        qc_docs = []
        for c in question_cases:
            analysis = c.get("analysis") if isinstance(c.get("analysis"), dict) else {}
            core_task = str((analysis or {}).get("core_task") or "")
            qc_docs.append(
                c.get("title", "") + " " + c.get("question_type", "") + " " + core_task
            )
        ranked = Retriever(qc_docs).search(query, top_k=max(QUESTION_CASE_TOP_K * 3, 8))
        for i, score in ranked:
            c = question_cases[i]
            if not unknown_type and not _case_type_compatible(c.get("question_type", ""), question_type):
                continue
            qc_hits.append({
                "question_id": c.get("question_id", ""),
                "title": c.get("title", ""),
                "question_type": c.get("question_type", ""),
                "core_task": str((c.get("analysis", {}) or {}).get("core_task", "") or ""),
                "key_points": _normalize_str_list((c.get("analysis", {}) or {}).get("key_points")),
                "descriptive_filters": _normalize_str_list((c.get("analysis", {}) or {}).get("descriptive_filters")),
                "teacher_reasoning": c.get("teacher_reasoning", ""),
                "word_limit": c.get("word_limit", ""),
                "score": round(score, 4),
            })
            if len(qc_hits) >= QUESTION_CASE_TOP_K:
                break

    # 2) 纠错案例：检索（不按题型硬过滤；问法适用性交 AI 审查核对）
    cc_hits: list[dict] = []
    if critique_cases:
        cc_docs = [c.get("question", "") + " " + c.get("student_error_snippet", "") for c in critique_cases]
        for i, score in Retriever(cc_docs).search(query, top_k=CRITIQUE_CASE_TOP_K):
            c = critique_cases[i]
            cc_hits.append({
                "case_id": c.get("case_id", ""),
                "question": c.get("question", ""),
                "student_error_snippet": c.get("student_error_snippet", ""),
                "error_type": c.get("error_type", ""),
                "diagnosis": c.get("diagnosis", ""),
                "remedy_instruction": c.get("remedy_instruction", ""),
                "severity": c.get("severity", ""),
                "score": round(score, 4),
            })

    # 若题型已知且教师规则库完全没有兼容规则：不挂载不相关规则，如实返回空
    if not unknown_type and not has_compatible_policies:
        return {
            "teacher_id": teacher_id,
            "question_type": question_type,
            "type_compatible": False,
            "compat_note": f"在 {teacher_id} 的规则库中未找到声明适用于“{question_type}”的规则，本次批改不挂载该教师的规则依据（不做不相关规则兜底）。",
            "method_context": mc,
            "policies": [],
            "question_cases": qc_hits,
            "critique_cases": cc_hits,
        }

    unified_policies: list[dict] = []
    seen_pids: set[str] = set()

    for pid in mc.get("all_policy_ids", []):
        if pid in policy_by_id and pid not in seen_pids:
            p = policy_by_id[pid]
            if unknown_type and p.get("applies_to"):
                continue  # 待判定时不得挂题型专属规则
            seen_pids.add(pid)
            unified_policies.append(_pack_policy_dict(p, 1.0))

    # 3) 规则检索：补足针对性规则（与方法上下文规则去重合并）
    pol_docs = [p.get("name", "") + " " + p.get("trigger", "") + " " + p.get("rule", "") for p in policies]
    compat_note = ""
    if pol_docs:
        ranked = Retriever(pol_docs).search(query, top_k=max(POLICY_TOP_K * 2, 12))
        hits = [policies[i] for i, _s in ranked]
        if unknown_type:
            compatible = [p for p in hits if not p.get("applies_to")]
            compat_note = (
                "题型待判定：本次仅使用未限定题型的通用策略，未按题型过滤；"
                "请逐条核对规则的适用条件，不适用则不要采用。"
            )
        else:
            compatible = [p for p in hits if _applies_compatible(p.get("applies_to", []), question_type)]
            general = [p for p in hits if not p.get("applies_to")]
            compatible = compatible + general
        for p in compatible:
            pid = p["policy_id"]
            if pid not in seen_pids:
                if unknown_type and p.get("applies_to"):
                    continue
                seen_pids.add(pid)
                score = next((round(s, 4) for i, s in ranked if policies[i]["policy_id"] == pid), 0.0)
                unified_policies.append(_pack_policy_dict(p, score))

    if not unified_policies and not compat_note:
        compat_note = (
            f"在 {teacher_id} 的规则库中未找到适用于“{question_type}”的规则，"
            "本次批改不挂载该教师的规则依据（不做不相关规则兜底）。"
        )

    return {
        "teacher_id": teacher_id,
        "question_type": question_type,
        "type_compatible": bool(unified_policies),
        "compat_note": compat_note,
        "method_context": mc,
        "policies": unified_policies,
        "question_cases": qc_hits,
        "critique_cases": cc_hits,
    }


# ---------- 引文定位（区分原文引用与语义概括；区分排版符号与语义符号） ----------

# 标点/符号 → 归一为占位符；连续标点折叠为一个占位符。
# 这只做"排版归一化"：实义字符（否定词、数量、主体、范围、时间等）一律保留参与比较。
_PUNCT_CLASS = re.compile(r"[，。；、！？,;:.∶·…―—–\-“”\"'‘’（）()\[\]【】《》〈〉{}<>？！!?～~@#￥%&\*\+=/\\|°℃]")

# 有语义的符号：小数点、正负号、百分号、分数/除号、单位（℃等）、比较符号。
# 它们在数字上下文中保留原样参与比较，不折叠为占位符——
# 因此 1/5 与 1.5、1℃ 与 1% 无法互相冒充。
_ALWAYS_SEMANTIC = set("%℃℉°±×÷≥≤><=＝％")
_NUMERIC_SEMANTIC = set("+-－−/／.·")  # 仅在数字邻接时视为语义符号


def _full2half(ch: str) -> str:
    """全角字母/数字/符号 → 半角（中文汉字不变）。"""
    code = ord(ch)
    if 0xFF01 <= code <= 0xFF5E and ch != '　':
        return chr(code - 0xFEE0)
    if ch == '　':
        return ' '
    return ch


def _is_digit(ch: str) -> bool:
    return ch.isdigit()


def _build_norm_index(text: str) -> tuple[str, list[int]]:
    """构造引文定位用的归一化串 + 每个归一化字符在原文中的位置。

    规则：
    - 去除所有空白（纯排版）；
    - 标点（含全半角变体）归一为单个占位符并折叠连续标点——但语义符号除外：
      百分号/摄氏度/比较符号等始终保留；小数点、正负号、除号仅在数字邻接时保留；
    - 其余字符一律保留（全角→半角与小写化）。
    任何实义差异（含数值/单位符号差异）都会导致匹配失败。
    """
    out: list[str] = []
    idx: list[int] = []
    prev_punct = False
    for pos, raw in enumerate(text):
        ch = _full2half(raw)
        if ch.isspace():
            continue
        if _PUNCT_CLASS.match(ch):
            prev_kept = out[-1] if out else ''
            next_pos = pos + 1
            while next_pos < len(text) and _full2half(text[next_pos]).isspace():
                next_pos += 1
            next_kept = _full2half(text[next_pos]) if next_pos < len(text) else ''
            semantic = ch in _ALWAYS_SEMANTIC or (
                ch in _NUMERIC_SEMANTIC and (_is_digit(prev_kept) or _is_digit(next_kept))
            )
            if semantic:
                out.append(ch)
                idx.append(pos)
                prev_punct = False
                continue
            if prev_punct:
                continue
            out.append('|')
            idx.append(pos)
            prev_punct = True
        else:
            out.append(ch.lower())
            idx.append(pos)
            prev_punct = False
    return ''.join(out), idx


_ELLIPSIS = re.compile(r"\.{3,}|…+|。{2,}")
_SENT_SPLIT = re.compile(r"[。！？；!?;…：:]|\n")


def _sentence_ranges(text: str) -> list[tuple[int, int]]:
    """原文分句（完整分句边界），返回 [(start, end)] 字符区间（end 含句末标点）。"""
    ranges = []
    start = 0
    for m in _SENT_SPLIT.finditer(text):
        ranges.append((start, m.start() + 1))
        start = m.end()
    if start < len(text):
        ranges.append((start, len(text)))
    return [(s, e) for s, e in ranges if text[s:e].strip()]


def _norm_strip_edges(s: str) -> str:
    n, _ = _build_norm_index(s)
    return n.strip('|')


def locate_quote(quote: str, source: str) -> dict:
    """在 source 中定位 quote 的真实连续片段（原文引用核验）。

    - 允许：空白差异、全/半角、普通标点排版差异、用省略号省略中段（各段须逐字连续且按序）；
      数值与单位符号（小数点/正负号/百分号/除号/℃/比较符号）保留语义，不得互相冒充。
    - 不允许：任何实义字符差异（删改否定词、数量、主体、范围、时间等），内容跳步拼接。
    - 返回：
      status: 'verbatim'（可定位）| 'not_found'（无法定位为原文）；
      spans: 程序从 source 取回的原始片段（不信任模型填写文本）；
      positions: 各片段在 source 中的 [start, end) 偏移；
      clauses: 各片段所在完整分句（程序提取，用于核对截断是否丢失否定/数量/条件等）；
      partial: 是否存在片段未覆盖其所在完整分句（截断引用，不能单独作为完整支持依据）。
    """
    empty = {'status': 'not_found', 'spans': [], 'positions': [], 'clauses': [], 'partial': False, 'reason': ''}
    q = (quote or '').strip()
    if not q:
        return {**empty, 'reason': '引文为空'}
    norm_src, src_idx = _build_norm_index(source or '')
    segments = [s for s in _ELLIPSIS.split(q) if s and s.strip()]
    if not segments:
        return {**empty, 'reason': '引文无有效内容'}

    sentences = _sentence_ranges(source)
    spans: list[str] = []
    positions: list[list[int]] = []
    clauses: list[str] = []
    partial = False
    search_from = 0
    for seg in segments:
        norm_seg, _seg_idx = _build_norm_index(seg)
        if not norm_seg:
            continue
        pos = norm_src.find(norm_seg, search_from)
        if pos < 0:
            return {**empty, 'reason': '引文与原文存在实义差异或不在原文中（含数值/单位符号差异）'}
        start_orig = src_idx[pos]
        end_norm = pos + len(norm_seg) - 1
        end_orig = src_idx[end_norm]
        while end_orig + 1 < len(source) and _PUNCT_CLASS.match(_full2half(source[end_orig + 1])):
            end_orig += 1
        spans.append(source[start_orig:end_orig + 1])
        positions.append([start_orig, end_orig + 1])
        # 所在完整分句（程序提取）
        clause = next(
            (source[s:e].strip() for s, e in sentences if s <= start_orig and end_orig + 1 <= e),
            source[max(0, start_orig - 20):min(len(source), end_orig + 21)],
        )
        clauses.append(clause)
        # 完整性：片段覆盖其所在分句（归一化后，允许句首/句尾纯标点差异）
        if _norm_strip_edges(clause) != _norm_strip_edges(spans[-1]):
            partial = True
        search_from = end_norm + 1
    return {
        'status': 'verbatim', 'spans': spans, 'positions': positions,
        'clauses': clauses, 'partial': partial, 'reason': '',
    }


# ---------- 程序核验（兼容旧接口） ----------

def verify_user_quote(quote: str, answer_points: list[str], min_ratio: float = 0.75) -> bool:
    """旧接口：模型给出的“用户原句”能否定位回作答（现为逐字定位）。"""
    return locate_quote(quote, '\n'.join(answer_points))['status'] == 'verbatim'


def verify_material_quote(quote: str, material_text: str, min_len: int = 8) -> dict:
    """旧接口：材料引文能否定位回本题材料原文。"""
    result = locate_quote(quote, material_text)
    return {'ok': result['status'] == 'verbatim', 'reason': result.get('reason', ''), 'spans': result.get('spans', [])}


def verify_refs(refs: list[dict], pack: dict) -> tuple[list[dict], list[dict]]:
    """核验 AI 引用的来源 ID：必须存在于证据包中，且属于当前教师。

    返回 (valid, invalid)。invalid 中的条目会被拒绝挂载，绝不采用模型生成的
    书名/课程名/引用文字作为来源。
    """
    teacher_id = pack.get("teacher_id", "")
    valid_ids: dict[tuple[str, str], dict] = {}
    for p in pack.get("policies", []):
        valid_ids[("policy", p["policy_id"])] = {"kind": "policy", "ref": p["policy_id"], "title": p.get("name", "")}
    for c in pack.get("critique_cases", []):
        valid_ids[("case", c["case_id"])] = {"kind": "case", "ref": c["case_id"], "title": f"课堂纠错案例：{c.get('question', '')[:30]}"}
    for qc in pack.get("question_cases", []):
        valid_ids[("question_case", qc["question_id"])] = {
            "kind": "question_case", "ref": qc["question_id"], "title": f"题目案例：{qc.get('title', '')[:30]}"
        }

    valid, invalid = [], []
    seen: set[tuple[str, str]] = set()
    for r in refs or []:
        if not isinstance(r, dict):
            continue
        kind = r.get("kind", "")
        ref = (r.get("ref") or "").strip()
        if not ref:
            continue
        key = (kind, ref)
        if key in valid_ids and key not in seen:
            seen.add(key)
            valid.append(dict(valid_ids[key]))
        elif key not in seen:
            seen.add(key)
            invalid.append({"kind": kind, "ref": ref, "reason": f"来源不在 {teacher_id} 的本次证据包中（不存在或未检索到）"})
    return valid, invalid
