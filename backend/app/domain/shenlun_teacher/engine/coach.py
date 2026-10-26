# -*- coding: utf-8 -*-
"""Coach Agent：汇总诊断条目 → 去重 → 排序 → 选出本题最该改的 1~2 项 → 固定格式输出。

新流程下 coach 职责拆为两个纯函数（service 调用）：
- provisional_targets_from_suspicions：AI 审查前，把疑点转成"待确认"暂定目标；
- coach_note_for：按当前条目状态生成诚实的总述措辞。
旧 coach() 保留兼容（消费 teacher_agent.grade 的 legacy 输出）。
"""

SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}


def _dedupe(diagnosis):
    """按 type 去重，保留严重度最高的一条；同 type 多条时其余进 suppressed。"""
    kept = {}
    suppressed = []
    for d in diagnosis:
        t = d["type"]
        if t not in kept:
            kept[t] = d
        else:
            if SEVERITY_ORDER.get(d["severity"], 0) > SEVERITY_ORDER.get(kept[t]["severity"], 0):
                suppressed.append(kept[t])
                kept[t] = d
            else:
                suppressed.append(d)
    return list(kept.values()), suppressed


def _rank(diagnosis, matched_policies):
    def score(d):
        base = SEVERITY_ORDER.get(d["severity"], 0) * 10
        conf = 0.0
        for mp in matched_policies:
            if mp["policy_id"] == d.get("policy_ref"):
                conf = mp["score"]
                break
        return base + conf

    return sorted(diagnosis, key=score, reverse=True)


def _next_action(d):
    """根据错误类型给出训练目标与指令（指令优先取关联策略/相似案例的原文本）。"""
    type_to_skill = {
        "VERBOSE": "shenlun.descriptive_filter",
        "UNSUPPORTED_INFERENCE": "shenlun.no_inference",
        "OVER_ABSTRACTION": "shenlun.no_slogan",
        "SCOPE_EXPANSION": "shenlun.scope_preservation",
        "MISSING_POINT": "shenlun.summary_first",
        "POOR_STRUCTURE": "shenlun.answer_structure",
        "COUNTERMEASURE_MISMATCH": "shenlun.verb_object",
    }
    skill = type_to_skill.get(d["type"], "shenlun.general")
    instruction = d.get("policy_rule") or ""
    if d["type"] == "VERBOSE":
        instruction = instruction or "删去叙事性、画面性语言，改写为规范动宾短语。"
    elif d["type"] == "UNSUPPORTED_INFERENCE":
        instruction = instruction or "材料有什么答什么，删去自行推导的品质词。"
    elif d["type"] == "OVER_ABSTRACTION":
        instruction = instruction or "删去无材料依据的热词，按材料实际表述改写。"
    elif d["type"] == "SCOPE_EXPANSION":
        instruction = instruction or "补回范围限定词，避免扩大命题外延。"
    elif d["type"] == "MISSING_POINT":
        instruction = instruction or "回到该段段首总结句，优先采用总结句表述。"
    elif d["type"] == "POOR_STRUCTURE":
        instruction = instruction or "按题干要求的结构重新组织（如：原来/现在 对比）。"
    elif d["type"] == "COUNTERMEASURE_MISMATCH":
        instruction = instruction or "把该点改写为“动词+宾语”的可执行对策。"
    return {"skill": skill, "instruction": instruction}


def provisional_targets_from_suspicions(suspicions: list[dict]) -> list[dict]:
    """AI 审查前的暂定目标：疑点原样转为 status='pending'，不冒充已支持结论。"""
    targets = []
    for s in suspicions:
        targets.append(
            {
                "target_key": s["suspicion_id"],
                "status": "pending",
                "type": s["type"],
                "check_kind": s["type"],
                "severity": s["severity"],
                "user_quote": s["student_span"],
                "student_span": s["student_span"],
                "problem": s["detail"],
                "reason": s["detail"],
                "material_quote": "",
                "material_quote_verified": False,
                "material_point": "",
                "teacher_basis": (
                    [{"kind": "policy", "ref": s["policy_ref"], "title": s["policy_name"],
                      "applicability": "本地提示关联，未经语义核验"}]
                    if s.get("policy_ref") else []
                ),
                "policy_ref": s.get("policy_ref", ""),
                "policy_name": s.get("policy_name", ""),
                "suggested_fix": "",
                "suspicion_id": s["suspicion_id"],
                "verify": s.get("verify"),
            }
        )
    ranked = sorted(targets, key=lambda t: (-SEVERITY_ORDER.get(t["severity"], 0),))
    return ranked


def coach_note_for(items: list[dict], compat_note: str = "", reviewed: bool = False) -> str:
    """按当前条目状态生成总述措辞（诚实区分已支持/待确认/一般建议）。"""
    supported = [i for i in items if i.get("status") == "supported"]
    ai_only = [i for i in items if i.get("status") in ("ai_analysis", "suggestion", "supported_no_teacher_basis")]
    pending = [i for i in items if i.get("status") == "pending"]
    parts = []
    if reviewed:
        if supported:
            names = [i.get("policy_name") or i.get("check_kind") or i.get("type", "") for i in supported]
            parts.append(f"按教师方法判断，最需要改的是：{'、'.join(n for n in names if n)}。")
        if ai_only:
            parts.append("另有几条是基于本题材料的 AI 分析（未引用教师方法），供参考。")
        if pending:
            parts.append(f"还有 {len(pending)} 项证据不足，列为待确认。")
        if not items:
            parts.append("经逐点核查未发现问题。请对照材料复核覆盖度与字数分配。")
    else:
        if pending:
            parts.append("本地检查发现疑点（尚未经语义审查确认）：")
            names = [i.get("check_kind") or i.get("type", "") for i in pending[:2]]
            parts.append("、".join(n for n in names if n) + "等条目请先按提示自查。")
        else:
            parts.append("本地检查未发现疑点。")
    if compat_note:
        parts.append(compat_note)
    parts.append("本反馈依据所选教师的课程资料与本题材料生成，属辅助参考，不代表教师本人批改，也不是官方评分标准。")
    return "".join(parts)


def coach(grade_result, profile=None):
    diagnosis, suppressed = _dedupe(grade_result["diagnosis"])
    ranked = _rank(diagnosis, grade_result["matched_policies"])

    top = ranked[:2]
    rest = ranked[2:]

    targets = []
    for d in top:
        targets.append(
            {
                "type": d["type"],
                "severity": d["severity"],
                "student_span": d["student_span"],
                "reason": d["reason"],
                "policy_ref": d.get("policy_ref", ""),
                "policy_name": d.get("policy_name", ""),
                "verify": d.get("verify"),
                "next_action": _next_action(d),
            }
        )

    followups = []
    for d in rest:
        followups.append(
            {
                "type": d["type"],
                "severity": d["severity"],
                "student_span": d["student_span"],
                "reason": d["reason"],
                "policy_ref": d.get("policy_ref", ""),
                "next_action": _next_action(d),
            }
        )

    strengths = [{"point": s["point"], "basis": s["basis"]} for s in grade_result["strength"]]

    coach_note = "本题先不要改全部问题。"
    if targets:
        names = []
        for t in targets:
            n = t["policy_name"] or t["type"]
            if n not in names:
                names.append(n)
        coach_note += f"当前最需要改的是：{'、'.join(names)}。请按训练目标修改对应要点，其余部分暂时不动。"
    else:
        coach_note = "未检出明显问题。请对照材料逐点复核覆盖度，注意字数分配。"

    return {
        "training_targets": targets,
        "followups": followups,
        "strength": strengths,
        "similar_cases": grade_result["similar_cases"],
        "matched_policies": grade_result["matched_policies"],
        "coach_note": coach_note,
        "give_full_answer": False,
        "suppressed_duplicates": len(suppressed),
        "teacher": (profile or {}).get("name", "飞扬老师"),
    }
