# -*- coding: utf-8 -*-
"""教师方法上下文：把规则库组织为"塑造模型判断方法"的指导材料。

设计目标（对应"教师课程与批改案例 → 提炼方法 → 塑造 AI 批改"）：
- 教师规则是方法指导，不是逐条机械执行的判错清单；
- 按"核心原则 / 审题与阅读 / 信息取舍与概括 / 组织与表达 / 本题题型相关"组织，
  避免把全部资料堆进提示词；规则保留稳定 ID 便于追溯；
- 正反例随题型规则进入上下文（示例解释方法，不要求先找到相似案例才能批改）；
- method_notes.json 记录过度绝对化规则的应用条件与例外（可追溯到原规则与案例）；
- 两位教师资料相互独立，互不混用。
- 适用性一致：方法上下文与引用名单必须来自同一份经过适用性筛选的来源记录，
  确实适用的通用方法保留，不适用的规则不注入；无适用规则时两者一致为空。
"""

import json
import re

from . import library as lib

_METHOD_NOTES_CACHE: dict | None = None

READING_KW = ("审题", "问法", "读材料", "材料阅读", "先看", "审读", "题干")
SELECTION_KW = ("取舍", "概括", "提炼", "总结句", "规范词", "压缩", "省略", "删除",
                "过滤", "保留", "采点", "关键词", "得分词", "舍弃", "推导", "升华")
ORGANIZE_KW = ("结构", "组织", "分条", "条理", "前置", "归位", "分区", "表述", "表达",
               "序号", "布局", "开头", "结尾", "分段", "格式")

GROUP_BUDGET = 4        # 每个通用方法组的规则数上限
TYPE_RULE_BUDGET = 6    # 本题题型相关规则数上限
EXAMPLE_BUDGET = 5      # 带正反例的规则数上限
RULE_TEXT_MAX = 110     # 单条规则文本截断

# 引擎题型 → 各教师题库中可能的同族表述片段（做法/经验等细分问法靠词级匹配）
_TYPE_FAMILY: dict[str, list[str]] = {
    "归纳概括": ["归纳概括"],
    "分析理解": ["分析理解", "综合分析"],
    "公文题": ["公文题", "应用文"],
    "文章写作": ["文章写作", "议论文", "大作文"],
}

# 题型无法判定时的标记：不按题型过滤，如实说明，不默认任何具体题型
UNKNOWN_QUESTION_TYPES = {"", "待判定", "未知"}


def _question_type_family(question_type: str) -> list[str]:
    """引擎题型 → 家族词列表（如 归纳概括-做法 → ['归纳概括','做法']；分析理解 → ['分析理解','综合分析']）。"""
    parts = re.split(r"[-—]", question_type or "")
    base = parts[0]
    fam = list(_TYPE_FAMILY.get(base, [base])) if parts else []
    if base == "归纳概括" and len(parts) > 1:
        fam.append(parts[1])
        if parts[1] == "对策":
            fam.extend(["对策题", "提出对策", "对策"])
        elif parts[1] == "启示":
            fam.extend(["经验", "启示类"])
    elif "对策" in (question_type or ""):
        fam.extend(["对策", "对策题", "提出对策"])
    return [p for p in fam if p]


def _applies_compatible(applies_to: list[str], question_type: str) -> bool:
    """策略声明的题型与当前题型是否兼容（双向子串 + 题型同义族映射；空 applies_to 视为通用）。"""
    if not applies_to or not question_type:
        return True
    fam = _question_type_family(question_type)
    for a in applies_to:
        if any(f in a or a in f for f in fam):
            return True
        if a in question_type or question_type in a:
            return True
    return False


def load_method_notes() -> dict:
    """方法应用说明（过度绝对化规则的应用条件与例外），带缓存。"""
    global _METHOD_NOTES_CACHE
    if _METHOD_NOTES_CACHE is None:
        try:
            with open(lib.KB_DIR / "method_notes.json", encoding="utf-8") as f:
                _METHOD_NOTES_CACHE = json.load(f).get("notes", {}) or {}
        except Exception:
            _METHOD_NOTES_CACHE = {}
    return _METHOD_NOTES_CACHE


def _group_of(policy: dict) -> str:
    text = policy.get("name", "") + policy.get("trigger", "") + policy.get("rule", "")
    if any(k in text for k in READING_KW):
        return "reading"
    if any(k in text for k in SELECTION_KW):
        return "selection"
    if any(k in text for k in ORGANIZE_KW):
        return "organize"
    return "selection"  # 取舍与概括是申论批改的主体方法，未命中者默认归入


def build_method_context(teacher_id: str, question_type: str, policies: list[dict] | None = None) -> dict:
    """按教师组织方法上下文。两位教师的规则与风格独立，互不混用。

    规则来源与筛选原则：
    - 仅从与当前题型兼容的适用规则中组织方法，不把不属于当前题型的规则当成通用规则；
    - 题型同义映射（如 分析理解 ↔ 综合分析、文章写作 ↔ 议论文/大作文）统一处理；
    - 当前题型确实没有适用规则时（如完全陌生题型），方法上下文规则为空（0 条规则），
      仅提供核心教学原则，不注入不相关规则。
    """
    profile = lib.load_profile(teacher_id)
    if policies is None:
        policies = lib.load_policies(teacher_id)
    notes = load_method_notes()

    unknown_type = question_type in UNKNOWN_QUESTION_TYPES

    if unknown_type:
        applicable = [p for p in policies if not p.get("applies_to")]
    else:
        applicable = [p for p in policies if _applies_compatible(p.get("applies_to", []), question_type)]

    # 若当前题型确实没有适用规则（如完全陌生题型）：
    # 方法上下文与引用名单一致为空，只提供高层原则，不注入不相关规则
    if not applicable:
        return {
            "teacher_id": teacher_id,
            "teacher_name": profile.get("name", teacher_id),
            "principles": [str(x) for x in profile.get("core_principles", [])][:6],
            "reading": [],
            "selection": [],
            "organize": [],
            "type_rules": [],
            "examples_included": 0,
            "all_policy_ids": [],
        }

    def _is_specific(p: dict) -> bool:
        parts = re.split(r"[-—]", question_type or "")
        if len(parts) > 1 and any(parts[1] in a for a in p.get("applies_to", [])):
            return True
        specific_kws = ("词句理解", "观点评价", "评价类", "分论点", "立意", "宣传稿", "公开信", "做法类", "变化类", "启示类", "原因类")
        return any(any(sk in a for sk in specific_kws) for a in p.get("applies_to", []))

    specific_rules = [p for p in applicable if _is_specific(p)]
    general_rules = [p for p in applicable if p not in specific_rules] or list(applicable)
    type_rules = specific_rules or list(applicable)

    def _brief(p: dict) -> dict:
        out = {
            "policy_id": p["policy_id"],
            "name": p.get("name", ""),
            "rule": p.get("rule", "")[:RULE_TEXT_MAX],
            "applies_to": p.get("applies_to", []),
        }
        note = notes.get(p["policy_id"])
        if note:
            out["application_note"] = note.get("application", "")
        return out

    def _with_example(p: dict) -> dict:
        pos = p.get("positive_example", {}) or {}
        neg = p.get("negative_example", {}) or {}
        out = _brief(p)
        out["trigger"] = p.get("trigger", "")[:RULE_TEXT_MAX]
        if pos.get("preferred"):
            out["positive_example"] = {
                "input": str(pos.get("input", ""))[:80],
                "preferred": str(pos.get("preferred", ""))[:110],
            }
        if neg.get("bad_output"):
            out["negative_example"] = {
                "bad_output": str(neg.get("bad_output", ""))[:110],
                "reason": str(neg.get("reason", ""))[:90],
            }
        return out

    type_sorted = sorted(type_rules, key=lambda x: -x.get("confidence", 0.8))
    type_selected = [_with_example(p) for p in type_sorted[:TYPE_RULE_BUDGET]]
    selected_pids = {p["policy_id"] for p in type_selected}

    groups: dict[str, list[dict]] = {"reading": [], "selection": [], "organize": []}
    for p in sorted(general_rules, key=lambda x: -x.get("confidence", 0.8)):
        if p["policy_id"] not in selected_pids:
            groups[_group_of(p)].append(p)

    reading_selected = [_brief(p) for p in groups["reading"][:GROUP_BUDGET]]
    selection_selected = [_brief(p) for p in groups["selection"][:GROUP_BUDGET]]
    organize_selected = [_brief(p) for p in groups["organize"][:GROUP_BUDGET]]

    all_selected_ids = [
        p["policy_id"]
        for group in (type_selected, reading_selected, selection_selected, organize_selected)
        for p in group
    ]

    return {
        "teacher_id": teacher_id,
        "teacher_name": profile.get("name", teacher_id),
        "principles": [str(x) for x in profile.get("core_principles", [])][:6],
        "reading": reading_selected,
        "selection": selection_selected,
        "organize": organize_selected,
        "type_rules": type_selected,
        "examples_included": min(len(type_sorted), EXAMPLE_BUDGET),
        "all_policy_ids": all_selected_ids,
    }


def _fmt_rule(p: dict) -> str:
    applies = "、".join(p.get("applies_to", []) or []) or "通用"
    line = f"[{p['policy_id']}] {p['name']}（适用：{applies}）：{p['rule']}"
    if p.get("application_note"):
        line += f"\n    应用说明：{p['application_note']}"
    return line


def _fmt_rule_with_example(p: dict) -> str:
    line = _fmt_rule(p)
    if p.get("trigger"):
        line += f"\n    触发：{p['trigger']}"
    pos = p.get("positive_example") or {}
    if pos.get("preferred"):
        line += f"\n    正例：{pos.get('input', '')} → {pos.get('preferred', '')}"
    neg = p.get("negative_example") or {}
    if neg.get("bad_output"):
        line += f"\n    反例：{neg.get('bad_output', '')}（{neg.get('reason', '')}）"
    return line


def format_method_context(mc: dict) -> str:
    """方法上下文 → 提示词块（控制篇幅；保留规则 ID 与应用说明供追溯）。"""
    parts = [f"【{mc['teacher_name']}核心教学原则】"]
    parts += [f"- {p}" for p in mc.get("principles", [])]

    for key, title in (("reading", "审题与材料阅读"), ("selection", "信息取舍与概括"),
                       ("organize", "答案组织与表达")):
        rules = mc.get(key) or []
        if rules:
            parts.append(f"【{title}方法】")
            parts += [f"- {_fmt_rule(r)}" for r in rules]

    type_rules = mc.get("type_rules") or []
    if type_rules:
        parts.append(f"【本题题型（{type_rules[0].get('applies_to') and type_rules[0]['applies_to'][0] or '相关'}）相关规则与示例】")
        parts += [_fmt_rule_with_example(r) for r in type_rules]

    return "\n".join(parts)
