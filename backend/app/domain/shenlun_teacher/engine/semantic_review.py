# -*- coding: utf-8 -*-
"""AI 批改审查：教师方法塑造模型判断。

定位（对应最初设计：教师课程与案例 → 提炼方法 → 塑造 AI 批改 → 用户追问/质疑/纠正）：
- 模型先独立阅读本题问法、材料、字数要求和用户作答，判断最值得改进的内容；
- 教师规则是方法指导（塑造"怎么判断"），不是逐条机械执行的判错清单；
- 本地机械检查（关键词、重合度等）只提供可选提醒：可能误报，可合并、可忽略；
  模型也可发现提醒之外的遗漏、逻辑或表达亮点；
- 案例帮助模型理解教师如何应用方法（按需参照），不要求先找到相似案例才能批改；
- 程序负责：不编造（原文引文定位、来源真实）、会话与作答版本一致、状态一致。

底线（程序保留）：不编造材料、用户原话或教师来源；展示为原文的内容必须能回到原始
文本；不串题、不串教师、不混用作答版本；模型失败不能伪装成功。
"""

from typing import Literal

from pydantic import Field

from ....ai import Message, get_model_gateway
from ....ai.schemas import StrictModel
from .method_context import build_method_context, format_method_context


class ReviewRef(StrictModel):
    kind: Literal["policy", "case", "question_case"]
    ref: str = Field(min_length=1)


class ReviewItem(StrictModel):
    """一条批改意见。教师方法支持时给 refs（稳定 ID）；纯本题分析可不带 refs。"""

    suspicion_id: str = ""  # 对应本地机械提醒的编号；模型可合并/忽略，允许为空
    verdict: Literal["confirmed", "rejected", "revised"] = "confirmed"
    user_quote: str = ""    # 涉及的用户作答原句；漏点类问题可留空
    material_quote: str = ""  # 逐字摘录的材料原文片段（程序会定位）；概括说明写入 material_point
    material_point: str = ""  # 材料依据的概括/语义说明
    refs: list[ReviewRef] = Field(default_factory=list)
    applicability: str = ""  # 所用教师方法为何适用于本题
    problem: str = Field(min_length=1)
    suggested_fix: str = ""
    severity: Literal["high", "medium", "low"] = "medium"


class ReviewFinding(StrictModel):
    """模型独立阅读发现的问题或亮点（机械提醒之外）。"""

    user_quote: str = ""
    material_quote: str = ""
    material_point: str = ""
    refs: list[ReviewRef] = Field(default_factory=list)
    applicability: str = ""
    problem: str = Field(min_length=1)
    suggested_fix: str = ""
    severity: Literal["high", "medium", "low"] = "medium"


class SemanticReviewOutput(StrictModel):
    evidence_sufficient: bool = True
    items: list[ReviewItem] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)
    overall_note: str = ""


def _format_pack(pack: dict) -> str:
    """课堂案例与同题案例：帮助模型理解教师如何应用方法（按需参照，不强制命中）。"""
    blocks = []
    for qc in pack.get("question_cases", []):
        kps = list(qc.get("key_points") or [])[:5]
        kp_text = "\n    ".join(kps)
        blocks.append(
            f"[题目案例 {qc['question_id']}]《{qc.get('title', '')}》（{qc.get('question_type', '')}，{qc.get('word_limit', '')}）\n"
            f"    核心任务：{qc.get('core_task', '')}\n"
            + (f"    老师认可的组织方式：\n    {kp_text}\n" if kp_text else "")
            + (f"    老师的推导理由：{qc.get('teacher_reasoning', '')}" if qc.get("teacher_reasoning") else "")
        )
    for c in pack.get("critique_cases", []):
        blocks.append(
            f"[纠错案例 {c['case_id']}] 题：{c['question'][:40]}\n"
            f"    学生原句：{c['student_error_snippet'][:80]}\n    错误类型：{c['error_type']}\n"
            f"    老师诊断：{c['diagnosis'][:150]}\n    改法：{c['remedy_instruction'][:150]}"
        )
    return "\n\n".join(blocks) if blocks else "（本题未检索到相似案例——正常情况，直接依据方法与材料批改即可）"


def _format_suspicions(suspicions: list[dict]) -> str:
    """本地机械检查提醒：仅供参考，可能误报，可合并/忽略，不要求逐条回应。"""
    if not suspicions:
        return "（本地机械检查未产生提醒）"
    blocks = []
    for s in suspicions:
        blocks.append(
            f"[{s['suspicion_id']}] {s['type']}：{s['detail'][:90]}"
        )
    return "\n".join(blocks)


def build_review_messages(payload: dict, pack: dict, suspicions: list[dict]) -> list[Message]:
    teacher_id = payload.get("teacher_id") or pack.get("teacher_id") or "teacher_feiyang"
    mc = pack.get("method_context") or build_method_context(teacher_id, payload.get("question_type", ""))
    method_text = format_method_context(mc)

    # 统一名单与上下文：若 pack["policies"] 中含有补充检索到的针对性规则，一并在提示词中列出
    mc_ids = set(mc.get("all_policy_ids", []))
    extra_policies = [p for p in pack.get("policies", []) if p["policy_id"] not in mc_ids]
    if extra_policies:
        method_text += "\n\n【本题作答相关检索规则】\n" + "\n".join(
            f"- [{p['policy_id']}] {p['name']}（适用：{'、'.join(p.get('applies_to', []) or []) or '通用'}）：{p['rule']}"
            for p in extra_policies
        )

    system_prompt = (
        f"你是依据{mc['teacher_name']}教学方法进行批改的申论批改老师。该教师的方法已整理如下，"
        "用于塑造你的判断——理解、比较、概括和评判都沿用这套方法，而不是把规则当逐条执行的清单。\n\n"
        f"{method_text}\n\n"
        "【批改步骤】\n"
        "1. 先独立阅读本题问法、材料全文、字数要求和用户作答，自己判断最值得改进的 1~3 处"
        "（输出按'哪里有问题—为什么—怎么改'组织）。\n"
        "2. 教师方法适用时沿用其思路给出判断，并在 refs 中给出来源规则 ID；引用时先核对"
        "适用条件（问法不同，方法取舍可能不同）。教师资料没有相关方法时，不要把一般性建议"
        "归到教师名下（不写 refs，程序会将其标为'基于本题的 AI 分析'）。\n"
        "3. 底线：不编造材料、用户原话或教师来源。material_quote 只放逐字摘录的本题材料原文"
        "（程序会定位，定位不到的概括请写入 material_point）；user_quote 只放用户作答中的原句，"
        "漏点类问题（作答里缺了内容）可以留空，直接说明材料中的重要内容与答案缺失的对应关系。\n"
        "4. 本地机械检查提醒仅供参考：可能误报，可合并同类、可忽略，不必逐条回应；"
        "没有提醒时你仍应发现遗漏、逻辑或表达问题，也可以指出作答亮点。\n"
        "5. 概括、结构、逻辑等判断允许用简明的语义说明支撑，不要求每条都有逐字引文；"
        "局部引用即可，程序会补齐所在分句。\n"
        "6. 参考答案（如有）仅供参考，不要求逐字复述；作答与参考答案组织方式不同不是错误。\n"
        "7. 不输出精确扣分，不把教师方法当成官方评分标准；材料或证据不足时把 "
        "evidence_sufficient 置为 false 并在 overall_note 说明不确定在哪里。\n"
        "8. 不解释内部思考过程，只输出简明、可核查的判断依据。"
    )

    user_prompt_parts = [
        f"【题目】{payload.get('question', '')}\n"
        f"【题型判定】{payload.get('question_type', '')}\n"
        f"【字数限制】{payload.get('word_limit') or '未提供'}\n\n",
        f"【本题材料】\n{payload.get('material_text', '')}\n\n",
        "【用户作答】\n" + "\n".join(f"- {pt}" for pt in payload.get("student_answer", [])) + "\n\n",
    ]
    if payload.get("reference_answer"):
        user_prompt_parts.append(
            f"【参考答案】（来源：题库参考答案，仅供参考，不要求逐字复述）\n{payload.get('reference_answer', '')}\n\n"
        )
    user_prompt_parts.append(
        f"【教师课堂案例参照】（帮助理解方法如何应用；没有相似案例属正常，直接依据方法与材料批改）\n"
        f"{_format_pack(pack)}\n\n"
    )
    if pack.get("compat_note"):
        user_prompt_parts.append(f"【题型说明】{pack.get('compat_note')}\n")
    user_prompt_parts.append(f"【本地机械检查提醒（可选参考，可能误报）】\n{_format_suspicions(suspicions)}")

    return [
        Message(role="system", content=system_prompt),
        Message(role="user", content="".join(user_prompt_parts)),
    ]


async def review_answer(payload: dict, pack: dict, suspicions: list[dict], meta: dict | None = None) -> SemanticReviewOutput | None:
    """调用模型网关做语义审查。任何失败（不可用/超时/输出不合规）返回 None。

    meta 可选：回写实际执行的 provider/model/policy（含网关回退后真正服务的模型）。
    """
    def _fail(err: str) -> None:
        if meta is not None:
            meta.update({"ok": False, "error": str(err)[:200], "provider": "", "model": "", "policy_used": ""})

    if not payload.get("student_answer"):
        _fail("no answer")
        return None
    try:
        gateway = get_model_gateway()
        result = await gateway.generate(
            task_type="error_diagnosis",
            messages=build_review_messages(payload, pack, suspicions),
            schema=SemanticReviewOutput,
            model_policy="STRONG",
        )
        if meta is not None:
            meta.update({
                "ok": True, "error": "",
                "provider": result.provider_name,
                "model": result.model_name,
                "policy_used": result.policy_used,
            })
        return result.data
    except Exception as exc:
        _fail(exc)
        return None
