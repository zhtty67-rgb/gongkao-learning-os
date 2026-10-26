# -*- coding: utf-8 -*-
"""
backend/app/domain/interactive_assessor.py

Domain service for unified review, cause attribution, and corrigible multi-hypothesis dialogue.
Adheres to strict invariants:
  1. Authoritative Separation: Textbook explanation is ground-truth; AI explanation is attempt-scoped.
  2. Never writes AI generation back to questions table.
  3. Verifiable figures & knowledge hierarchy enforcement.
  4. Two-dimensional error attribution: Knowledge Node x Problem-Solving Stage.
  5. Short-transaction pattern & read-only GET.
"""

from datetime import datetime, timezone
import json
import logging
import re
from typing import Any, Dict, List, Literal, Optional
import uuid
from fastapi import HTTPException
from pydantic import Field

from ..ai import Message, get_model_gateway
from ..ai.schemas import GatewayError, StrictModel
from .attempt_verdict import correct_expr
from .review_context import (
    MODULE_PROBLEM_SOLVING_STAGES,
    SupportValidationResult,
    build_unified_review_context,
    build_unified_review_context_with_hub,
    extract_knowledge_node_context,
    format_unified_prompt_blocks,
    get_stages_for_module,
    verify_explanation_support,
    verify_followup_support,
)

logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


STANDARD_ERROR_TYPES = {
    "knowledge_gap", "conceptual_error", "method_selection", "reading_error",
    "calculation_error", "time_pressure", "careless_error", "transfer_failure", "unknown"
}

# Standard mapping from hypothesis misconception code to error event taxonomy
MISCONCEPTION_TO_ERROR_TYPE: dict[str, str] = {
    "data_locate": "reading_error",
    "time_or_scope": "reading_error",
    "formula_selection": "method_selection",
    "calc_accuracy": "calculation_error",
    "option_judgment": "reading_error",
    "problem_translation": "conceptual_error",
    "model_selection": "method_selection",
    "method_efficiency": "method_selection",
    "calculation_error": "calculation_error",
    "question_trap": "reading_error",
    "main_idea": "conceptual_error",
    "key_details": "reading_error",
    "option_distortion": "reading_error",
    "word_nuance": "conceptual_error",
    "rule_application": "method_selection",
    "argument_relation": "conceptual_error",
    "causal_reasoning": "conceptual_error",
    "exclusion_verify": "reading_error",
    "feature_sensitivity": "method_selection",
    "dimension_identification": "method_selection",
    "pattern_derivation": "method_selection",
    "option_comparison": "reading_error",
    "time_pressure": "time_pressure",
    "pure_guess": "unknown",
    "slip_of_hand": "careless_error",
    "unknown": "unknown",
}


# =============================================================================
# User Review Preferences
# =============================================================================

def get_user_review_preference(db, user_id: str = "default_user") -> str:
    """Retrieve persisted user review preference mode (AUTO_ASK | MANUAL | EXPLANATION_ONLY). Defaults to MANUAL."""
    try:
        row = db.execute(
            "SELECT preference_mode FROM user_review_preferences WHERE user_id=?", (user_id,)
        ).fetchone()
        if row and row["preference_mode"]:
            return row["preference_mode"]
    except Exception as exc:
        logger.debug("Failed to read user_review_preferences: %s", exc)
    return "MANUAL"


def set_user_review_preference(db, mode: Literal["AUTO_ASK", "MANUAL", "EXPLANATION_ONLY"], user_id: str = "default_user") -> str:
    """Update persisted user review preference mode."""
    if mode not in ("AUTO_ASK", "MANUAL", "EXPLANATION_ONLY"):
        raise HTTPException(400, f"无效的复盘偏好模式: {mode}")
    now_time = now_iso()
    db.execute(
        """INSERT INTO user_review_preferences (user_id, preference_mode, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(user_id) DO UPDATE SET preference_mode=excluded.preference_mode, updated_at=excluded.updated_at""",
        (user_id, mode, now_time),
    )
    return mode


# =============================================================================
# Schemas
# =============================================================================

class DiagnosisHypothesis(StrictModel):
    hypothesis_id: str = Field(min_length=1)
    stage_code: str = Field(min_length=1, description="失误环节编码")
    label: str = Field(min_length=1, description="失误环节简短标签")
    rationale: str = Field(min_length=1, description="推测依据")
    missing_info: str = Field(default="")


class InitialDiagnosisInference(StrictModel):
    can_conclude_now: bool = Field(description="当前信息是否足以得出唯一确定诊断")
    hypotheses: list[DiagnosisHypothesis] = Field(default_factory=list, description="1到3个可能的失误环节假设")
    clarification_question: str | None = Field(default=None, description="简短且有区分度的追问")
    clarification_options: list[str] = Field(default_factory=list, description="供用户快速点击的选项")
    suggested_remedy: str = Field(min_length=1, description="针对性的复盘建议")


class StepExplanationSchema(StrictModel):
    knowledge_node: str = Field(description="考点与知识节点层级路径")
    given_and_target: str = Field(description="题目所求与已知条件，包含材料真实取数")
    method_name: str = Field(description="教材对应解法（如假设分配法、415份数法等）")
    derivation_steps: list[str] = Field(description="具体推导步骤列表，包含可核验算式")
    answer_verification: str = Field(description="核对计算结果与选项匹配，明确正确答案")
    attempt_check_point: str = Field(description="本次作答值得核对的一步：中肯分析考生选项可能的偏差")


# =============================================================================
# Read-Only Details Fetching (GET contract)
# =============================================================================

def _legacy_question_explanation(db, attempt_id: str) -> Any:
    """Old AI explanations belong to a question, not a particular attempt."""
    row = db.execute(
        """SELECT q.ai_explanation_json FROM attempts a
           JOIN questions q ON q.id=a.question_id WHERE a.id=?""",
        (attempt_id,),
    ).fetchone()
    if not row or not row["ai_explanation_json"]:
        return None
    raw = row["ai_explanation_json"]
    try:
        return json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return None


def get_interactive_review_detail(db, attempt_id: str) -> dict[str, Any]:
    """
    Retrieve full interactive review record.
    STRICTLY READ-ONLY: If no diagnosis exists, returns a NOT_STARTED payload without creating DB rows or calling AI.
    """
    # Fetch unified context to ensure full stage taxonomy is always returned to frontend
    try:
        ctx = build_unified_review_context(db, attempt_id)
        stages = ctx["problem_solving_stages"]
        kn_ctx = ctx["knowledge_context"]
    except Exception as exc:
        logger.warning("Failed to build unified context for detail GET: %s", exc)
        stages = MODULE_PROBLEM_SOLVING_STAGES["资料分析"]
        kn_ctx = {"node_name": "核心考点", "full_path": "行测通识", "description": ""}

    row = db.execute("SELECT * FROM interactive_diagnoses WHERE attempt_id=?", (attempt_id,)).fetchone()
    if not row:
        att = db.execute(
            f"""SELECT a.id, a.question_id, a.selected_answer, {correct_expr(db)} AS correct, a.confidence, a.elapsed_ms, q.module, q.stem
               FROM attempts a JOIN questions q ON q.id=a.question_id WHERE a.id=?""",
            (attempt_id,),
        ).fetchone()

        err_row = db.execute(
            "SELECT error_type, explanation, source, metadata_json FROM error_events WHERE attempt_id=? ORDER BY created_at DESC LIMIT 1",
            (attempt_id,),
        ).fetchone()

        msg_rows = db.execute(
            """SELECT id, attempt_id, question_id, role, content, turn_type, status, metadata_json, created_at
               FROM attempt_followups
               WHERE attempt_id=?
               ORDER BY created_at ASC, rowid ASC""",
            (attempt_id,),
        ).fetchall()
        messages_list = [dict(m) for m in msg_rows]

        exp_data = _legacy_question_explanation(db, attempt_id)
        return {
            "status": "NOT_STARTED",
            "attempt_id": attempt_id,
            "question_id": att["question_id"] if att else None,
            "has_review": len(messages_list) > 0,
            "messages": messages_list,
            "hypotheses": [],
            "clarification_question": None,
            "clarification_options": [],
            "user_feedback_type": None,
            "user_feedback_text": None,
            "final_diagnosis": None,
            "is_user_confirmed": False,
            "selected_error_type": err_row["error_type"] if err_row else None,
            "cause_source": err_row["source"] if err_row else "PENDING",
            "cause_history": [],
            "suggested_action": "",
            "ai_explanation": exp_data,
            "ai_explanation_scope": "QUESTION_LEGACY_UNATTRIBUTED" if exp_data else None,
            "summary": None,
            "knowledge_node": kn_ctx,
            "problem_solving_stages": stages,
            "observed_facts": {
                "stem": att["stem"] if att else "",
                "user_selected": att["selected_answer"] if att else "",
                "is_correct": bool(att["correct"]) if att else False,
                "confidence": float(att["confidence"]) if (att and att["confidence"] is not None) else None,
                "elapsed_ms": att["elapsed_ms"] or 0 if att else 0,
                "module": att["module"] if att else "",
            } if att else {},
        }

    r = _format_diagnosis_record(row)
    exp_data = _legacy_question_explanation(db, attempt_id)
    r["ai_explanation"] = exp_data
    r["ai_explanation_scope"] = "QUESTION_LEGACY_UNATTRIBUTED" if exp_data else None
    r["knowledge_node"] = kn_ctx
    r["problem_solving_stages"] = stages

    msg_rows = db.execute(
        """SELECT id, attempt_id, question_id, role, content, turn_type, status, metadata_json, created_at
           FROM attempt_followups
           WHERE attempt_id=?
           ORDER BY created_at ASC, rowid ASC""",
        (attempt_id,),
    ).fetchall()
    r["messages"] = [dict(m) for m in msg_rows]
    r["has_review"] = True
    return r


# =============================================================================
# Path 2: Two-Dimensional Error Cause Selection
# =============================================================================

def set_review_cause(
    db,
    attempt_id: str,
    error_type: str,
    explanation: str = "",
    source: str = "USER_DIRECT",
    stage_code: Optional[str] = None,
    knowledge_node_id: Optional[str] = None,
    supplementary_cause: Optional[str] = None,
) -> dict[str, Any]:
    """
    Handle Path 2: Two-dimensional error attribution (Knowledge Node x Problem-Solving Stage).
    Idempotent single record in error_events, preventing duplicate counting.
    """
    ctx = build_unified_review_context(db, attempt_id)
    now_time = now_iso()
    question_id = ctx["question_id"]
    clean_expl = (explanation or "").strip()

    kn = ctx["knowledge_context"]
    active_stage_code = stage_code or error_type
    stage_label = active_stage_code
    for stg in ctx["problem_solving_stages"]:
        if stg["code"] == active_stage_code:
            stage_label = stg["label"]
            break

    # Build rich metadata
    meta = {
        "knowledge_node_id": knowledge_node_id or kn["node_id"],
        "knowledge_node_name": kn["node_name"],
        "knowledge_node_path": kn["full_path"],
        "stage_code": active_stage_code,
        "stage_label": stage_label,
        "supplementary_cause": supplementary_cause or "",
        "explanation": clean_expl,
    }

    # Map to standard category taxonomy for backwards compatibility
    if active_stage_code in STANDARD_ERROR_TYPES:
        legacy_cat = active_stage_code
    else:
        legacy_cat = MISCONCEPTION_TO_ERROR_TYPE.get(active_stage_code, "method_selection")
    if supplementary_cause == "time_pressure":
        legacy_cat = "time_pressure"
    elif supplementary_cause == "pure_guess":
        legacy_cat = "unknown"

    subtype_desc = f"{kn['node_name']} · {stage_label}"

    # 1. Idempotent sync to error_events
    existing_err = db.execute("SELECT id FROM error_events WHERE attempt_id=?", (attempt_id,)).fetchone()
    if existing_err:
        db.execute(
            """UPDATE error_events
               SET error_type=?, error_subtype=?, explanation=?, source='USER', diagnosis_source='user_confirmed', metadata_json=?, created_at=?
               WHERE attempt_id=?""",
            (legacy_cat, subtype_desc, clean_expl, json.dumps(meta, ensure_ascii=False), now_time, attempt_id),
        )
    else:
        db.execute(
            """INSERT INTO error_events (id, attempt_id, question_id, error_type, error_subtype, explanation, source, diagnosis_source, metadata_json, occurred_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'USER', 'user_confirmed', ?, ?, ?)""",
            (str(uuid.uuid4()), attempt_id, question_id, legacy_cat, subtype_desc, clean_expl, json.dumps(meta, ensure_ascii=False), now_time, now_time),
        )

    # 2. Update interactive_diagnoses record
    existing_diag = db.execute("SELECT * FROM interactive_diagnoses WHERE attempt_id=?", (attempt_id,)).fetchone()
    history = []
    if existing_diag and existing_diag["cause_history_json"]:
        try:
            history = json.loads(existing_diag["cause_history_json"])
        except Exception:
            history = []

    history.append({
        "error_type": legacy_cat,
        "stage_code": active_stage_code,
        "stage_label": stage_label,
        "knowledge_node": kn["node_name"],
        "source": source,
        "explanation": clean_expl,
        "supplementary": supplementary_cause or "",
        "changed_at": now_time,
    })

    summary_text = f"错因确认：【{kn['node_name']}】{stage_label}" + (f" ({clean_expl[:18]})" if clean_expl else "")

    if existing_diag:
        db.execute(
            """UPDATE interactive_diagnoses
               SET selected_error_type=?, cause_source=?, cause_history_json=?,
                   user_feedback_text=COALESCE(user_feedback_text, ?),
                   summary=?, last_message_at=?, updated_at=?
               WHERE id=?""",
            (active_stage_code, source, json.dumps(history, ensure_ascii=False), clean_expl, summary_text, now_time, now_time, existing_diag["id"]),
        )
    else:
        record_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO interactive_diagnoses
               (id, attempt_id, question_id, status, observed_facts_json, hypotheses_json, initial_inference_json,
                selected_error_type, cause_source, cause_history_json, user_feedback_text,
                suggested_action, summary, last_message_at, created_at, updated_at, dedup_key)
               VALUES (?, ?, ?, 'CONFIRMED', ?, '[]', '{}', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record_id, attempt_id, question_id,
                json.dumps(ctx, ensure_ascii=False),
                active_stage_code, source, json.dumps(history, ensure_ascii=False), clean_expl,
                f"已记录错因：考点【{kn['node_name']}】，失误环节【{stage_label}】。做题时可对照教材解析避开陷阱。",
                summary_text, now_time, now_time, now_time, f"{attempt_id}:diagnosis"
            ),
        )

    # 3. Log a user action message in attempt_followups
    msg_id = str(uuid.uuid4())
    msg_content = f"【选定错因】：考点【{kn['node_name']}】 · 失误环节【{stage_label}】" + (f"\n补充说明：{clean_expl}" if clean_expl else "")
    db.execute(
        """INSERT INTO attempt_followups (id, attempt_id, question_id, role, content, turn_type, status, metadata_json, created_at)
           VALUES (?, ?, ?, 'user', ?, 'cause_selection', 'completed', ?, ?)""",
        (msg_id, attempt_id, question_id, msg_content, json.dumps(meta, ensure_ascii=False), now_time),
    )

    return get_interactive_review_detail(db, attempt_id)


# =============================================================================
# Path 1: AI Dialogue Navigation (帮我找错因)
# =============================================================================

async def initiate_interactive_diagnosis(db, attempt_id: str, client_request_id: str | None = None) -> dict[str, Any]:
    """
    Initiate diagnostic hypotheses rooted in the knowledge tree node, problem-solving stages, and relevant Hub evidence.
    Never asserts user's thinking; strictly outputs hypothesis and clarification question.
    """
    # 1. Fetch unified context with Knowledge Hub evidence
    ctx = await build_unified_review_context_with_hub(db, attempt_id)

    # 2. Check for existing diagnosis session (Idempotency)
    existing = db.execute("SELECT * FROM interactive_diagnoses WHERE attempt_id=?", (attempt_id,)).fetchone()
    if existing:
        return get_interactive_review_detail(db, attempt_id)

    prompt_body = format_unified_prompt_blocks(ctx)
    stages_info = "\n".join(f"- {s['code']}: {s['label']}（{s['desc']}）" for s in ctx["problem_solving_stages"])

    system_prompt = (
        "你是公考 Learning OS 的专业学术导师与诊断评估器。\n"
        "【核心任务】：基于题目事实、教材原解析权威依据与本题知识树节点，客观推测考生可能的失误环节，并提出一个有区分度的追问。\n"
        "【铁律】：\n"
        "1. 严禁凭空断言考生的心算细节；若信息不足必须以追问形式呈现；\n"
        "2. 错因假设必须紧密依托提供的解题环节，禁止输出泛泛的‘粗心’；\n"
        "3. 保持中立、启发性，绝不诱导或贬低考生的解法。\n\n"
        f"【本题可选失误环节】：\n{stages_info}\n\n"
        "必须严格按照 Schema 返回合法的 JSON。"
    )

    user_prompt = (
        f"{prompt_body}\n\n"
        "请分析考生本次作答，提出1-3个可能的失误环节假设（hypotheses），并提出一个关键追问（clarification_question）及2-3个快速选项（clarification_options）。"
    )

    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]

    gateway = get_model_gateway()
    try:
        result = await gateway.generate(
            task_type="error_diagnosis",
            messages=messages,
            schema=InitialDiagnosisInference,
            model_policy="BALANCED",
        )
        inference: InitialDiagnosisInference = result.data
    except Exception as exc:
        logger.warning("Initiate diagnosis fallback triggered: %s", exc)
        inference = _fallback_initial_inference(ctx)

    record_id = str(uuid.uuid4())
    created_at = now_iso()
    hypotheses_dict = [h.model_dump() for h in inference.hypotheses]
    init_inf_dict = inference.model_dump()

    init_status = "CLARIFYING" if (not inference.can_conclude_now and inference.clarification_question) else "HYPOTHESIZED"
    summary_text = f"初始推断：{inference.hypotheses[0].label}" if inference.hypotheses else (inference.clarification_question or "复盘进行中")

    db.execute(
        """INSERT INTO interactive_diagnoses
           (id, attempt_id, question_id, status, observed_facts_json, hypotheses_json, initial_inference_json,
            clarification_question, clarification_options_json, suggested_action, summary,
            cause_source, client_request_id, last_message_at, created_at, updated_at, dedup_key)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'AI_INFERRED', ?, ?, ?, ?, ?)""",
        (
            record_id, attempt_id, ctx["question_id"], init_status,
            json.dumps(ctx, ensure_ascii=False),
            json.dumps(hypotheses_dict, ensure_ascii=False),
            json.dumps(init_inf_dict, ensure_ascii=False),
            inference.clarification_question,
            json.dumps(inference.clarification_options, ensure_ascii=False),
            inference.suggested_remedy,
            summary_text,
            client_request_id,
            created_at, created_at, created_at, f"{attempt_id}:diagnosis"
        ),
    )

    init_msg_content = (
        f"🔍 【错因与卡点推测】：{inference.suggested_remedy}\n"
        + (f"\n💬 【针对性确认追问】：{inference.clarification_question}" if inference.clarification_question else "")
    )
    db.execute(
        """INSERT INTO attempt_followups (id, attempt_id, question_id, role, content, turn_type, status, metadata_json, created_at)
           VALUES (?, ?, ?, 'assistant', ?, 'initial_diagnosis', 'completed', ?, ?)""",
        (str(uuid.uuid4()), attempt_id, ctx["question_id"], init_msg_content, json.dumps({"hypotheses": hypotheses_dict}, ensure_ascii=False), created_at),
    )

    return get_interactive_review_detail(db, attempt_id)


def _fallback_initial_inference(ctx: Dict[str, Any]) -> InitialDiagnosisInference:
    """Robust fallback when model call fails or in isolated tests."""
    stages = ctx["problem_solving_stages"]
    kn = ctx["knowledge_context"]
    first_stg = stages[0] if stages else {"code": "formula_selection", "label": "公式列式"}
    second_stg = stages[1] if len(stages) > 1 else {"code": "calc_accuracy", "label": "运算精度/截位"}

    if ctx["is_correct"]:
        return InitialDiagnosisInference(
            can_conclude_now=False,
            hypotheses=[
                DiagnosisHypothesis(
                    hypothesis_id="h1",
                    stage_code=first_stg["code"],
                    label=f"稳健推导（{kn['node_name']}）",
                    rationale="严格按照题干条件与教材公理推导得出正确结果。",
                )
            ],
            clarification_question="做这道题时，你是直接按部就班计算，还是应用了选项特征/速算技巧？",
            clarification_options=["直接按公式正向计算", "运用了速算/数字特性技巧", "排除部分选项后代入验证"],
            suggested_remedy=f"恭喜答对！本题考查【{kn['full_path']}】。建议对照官方解析复盘，进一步巩固速算精度与技巧。",
        )

    return InitialDiagnosisInference(
        can_conclude_now=False,
        hypotheses=[
            DiagnosisHypothesis(
                hypothesis_id="h1",
                stage_code=first_stg["code"],
                label=f"环节卡点：{first_stg['label']}",
                rationale=f"可能在【{kn['node_name']}】的{first_stg['desc']}环节出现偏差。",
            ),
            DiagnosisHypothesis(
                hypothesis_id="h2",
                stage_code=second_stg["code"],
                label=f"环节卡点：{second_stg['label']}",
                rationale=f"可能在【{kn['node_name']}】的{second_stg['desc']}环节出现偏差。",
            ),
        ],
        clarification_question=f"回顾刚完成的这道题，你在哪个环节感觉最吃力或产生犹豫？",
        clarification_options=[f"{first_stg['label']}环节", f"{second_stg['label']}环节", "看错题目具体所求", "时间紧张凭感觉猜的"],
        suggested_remedy=f"本题考点为【{kn['full_path']}】。核心公式为：{kn['description'][:80]}。建议核对数据定位与公式选取。",
    )


# =============================================================================
# Path 1/2 User Feedback on Hypotheses (Confirmation & Correction)
# =============================================================================

async def apply_user_diagnosis_feedback(
    db,
    attempt_id: str,
    feedback_type: Literal["CONFIRMED", "CORRECTED", "SKIPPED"],
    selected_hypothesis_id: str | None = None,
    user_text: str | None = None,
) -> dict[str, Any]:
    """
    Handle user feedback on the diagnosis hypotheses:
    - CONFIRMED: User confirms an AI hypothesis. Strictly maps to two-dimensional error attribution.
    - CORRECTED: User provides correction. AI revises explanation; remains an AI inference based on user self report.
    - SKIPPED: User skips clarification to see solution directly (cause_source='PENDING').
    """
    existing = db.execute("SELECT * FROM interactive_diagnoses WHERE attempt_id=?", (attempt_id,)).fetchone()
    if not existing:
        raise HTTPException(404, "该作答尚未生成诊断，请先发起复盘诊断")

    ctx = build_unified_review_context(db, attempt_id)
    now_time = now_iso()
    kn = ctx["knowledge_context"]
    hypotheses = json.loads(existing["hypotheses_json"] or "[]")
    question_id = ctx["question_id"]

    history = []
    if existing["cause_history_json"]:
        try:
            history = json.loads(existing["cause_history_json"])
        except Exception:
            history = []

    if feedback_type == "SKIPPED":
        summary_text = "用户已跳过追问，直接查看解析方法。"
        history.append({"error_type": "unknown", "source": "PENDING", "action": "SKIPPED", "changed_at": now_time})
        db.execute(
            """UPDATE interactive_diagnoses
               SET status='SKIPPED', user_feedback_type='SKIPPED', cause_source='PENDING',
                   cause_history_json=?, summary=?, last_message_at=?, updated_at=?
               WHERE id=?""",
            (json.dumps(history, ensure_ascii=False), summary_text, now_time, now_time, existing["id"]),
        )
        return get_interactive_review_detail(db, attempt_id)

    if feedback_type == "CONFIRMED":
        target = next((h for h in hypotheses if h.get("hypothesis_id") == selected_hypothesis_id), None)
        if not target:
            raise HTTPException(400, f"无效的假设ID: {selected_hypothesis_id}")

        stage_code = target.get("stage_code", "method_selection")
        stage_label = target.get("label", "解题环节失误")
        legacy_cat = MISCONCEPTION_TO_ERROR_TYPE.get(stage_code, "method_selection")
        subtype_desc = f"{kn['node_name']} · {stage_label}"

        meta = {
            "knowledge_node_id": kn["node_id"],
            "knowledge_node_name": kn["node_name"],
            "stage_code": stage_code,
            "stage_label": stage_label,
            "hypothesis_id": selected_hypothesis_id,
        }

        # Sync to error_events
        existing_err = db.execute("SELECT id FROM error_events WHERE attempt_id=?", (attempt_id,)).fetchone()
        if existing_err:
            db.execute(
                """UPDATE error_events
                   SET error_type=?, error_subtype=?, explanation=?, source='USER', diagnosis_source='user_confirmed', metadata_json=?, created_at=?
                   WHERE attempt_id=?""",
                (legacy_cat, subtype_desc, target.get("rationale", "") if target else "", json.dumps(meta, ensure_ascii=False), now_time, attempt_id),
            )
        else:
            db.execute(
                """INSERT INTO error_events (id, attempt_id, question_id, error_type, error_subtype, explanation, source, diagnosis_source, metadata_json, occurred_at, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'USER', 'user_confirmed', ?, ?, ?)""",
                (str(uuid.uuid4()), attempt_id, question_id, legacy_cat, subtype_desc, target.get("rationale", "") if target else "", json.dumps(meta, ensure_ascii=False), now_time, now_time),
            )

        history.append({
            "error_type": legacy_cat,
            "stage_code": stage_code,
            "stage_label": stage_label,
            "source": "AI_CONFIRMED",
            "changed_at": now_time,
        })

        summary_text = f"错因确认：【{kn['node_name']}】{stage_label}"
        db.execute(
            """UPDATE interactive_diagnoses
               SET status='CONFIRMED', user_feedback_type='CONFIRMED', selected_error_type=?,
                   cause_source='AI_CONFIRMED', is_user_confirmed=1, cause_history_json=?,
                   summary=?, last_message_at=?, updated_at=?
               WHERE id=?""",
            (stage_code, json.dumps(history, ensure_ascii=False), summary_text, now_time, now_time, existing["id"]),
        )

        user_content = f"【确认失误环节】：{stage_label}"
        db.execute(
            """INSERT INTO attempt_followups (id, attempt_id, question_id, role, content, turn_type, status, metadata_json, created_at)
               VALUES (?, ?, ?, 'user', ?, 'user_feedback', 'completed', '{}', ?)""",
            (str(uuid.uuid4()), attempt_id, question_id, user_content, now_time),
        )
        return get_interactive_review_detail(db, attempt_id)

    if feedback_type == "CORRECTED":
        clean_user_text = (user_text or "").strip()
        if not clean_user_text:
            raise HTTPException(400, "自述修正内容不能为空")

        # Save user self report
        history.append({
            "error_type": "reading_error",
            "self_report": clean_user_text,
            "source": "USER_SELF_REPORT",
            "changed_at": now_time,
        })
        summary_text = f"自述纠正：{clean_user_text[:28]}"

        final_diag = {
            "user_self_report": clean_user_text,
            "source": "USER_SELF_REPORT",
            "stage_code": "user_correction",
            "revised_at": now_time,
        }

        db.execute(
            """UPDATE interactive_diagnoses
               SET status='CORRECTED', user_feedback_type='CORRECTED', user_feedback_text=?,
                   is_user_confirmed=0, cause_source='USER_SELF_REPORT',
                   final_diagnosis_json=?,
                   cause_history_json=?, summary=?, last_message_at=?, updated_at=?
               WHERE id=?""",
            (clean_user_text, json.dumps(final_diag, ensure_ascii=False), json.dumps(history, ensure_ascii=False), summary_text, now_time, now_time, existing["id"]),
        )

        user_content = f"【我的真实做题想法/纠正】：{clean_user_text}"
        db.execute(
            """INSERT INTO attempt_followups (id, attempt_id, question_id, role, content, turn_type, status, metadata_json, created_at)
               VALUES (?, ?, ?, 'user', ?, 'user_feedback', 'completed', '{}', ?)""",
            (str(uuid.uuid4()), attempt_id, question_id, user_content, now_time),
        )

        ai_reply = f"感谢你的如实反馈！已根据你的自述记录复盘卡点：「{clean_user_text}」。你可以继续在下方提问，或者查看分步推导与教材原解析。"
        db.execute(
            """INSERT INTO attempt_followups (id, attempt_id, question_id, role, content, turn_type, status, metadata_json, created_at)
               VALUES (?, ?, ?, 'assistant', ?, 'clarification', 'completed', '{}', ?)""",
            (str(uuid.uuid4()), attempt_id, question_id, ai_reply, now_time),
        )
        return get_interactive_review_detail(db, attempt_id)

    raise HTTPException(400, f"未知的反馈类型: {feedback_type}")


# =============================================================================
# Step-by-Step Explanation Generation (给我分步讲解)
# =============================================================================

async def generate_step_by_step_explanation(db, attempt_id: str) -> dict[str, Any]:
    """
    Generate crisp, structured step-by-step explanation:
      Knowledge Node -> Given & Target -> Textbook Method -> Derivation Steps -> Answer Verification -> Attempt Check Point.
    Enforces Support Validation (no inverted temporal directions, no false fabricated figures).
    Never writes back to questions table.
    """
    ctx = await build_unified_review_context_with_hub(db, attempt_id)
    now_time = now_iso()
    kn = ctx["knowledge_context"]
    mat = ctx["material_context"]

    prompt_body = format_unified_prompt_blocks(ctx)

    evidence_rule_text = f"\n\n{ctx['hub_evidence_rule']}" if ctx.get("hub_evidence_rule") else ""
    system_prompt = (
        "你是公考 Learning OS 的专职资深名师导师（AI Tutor）。\n"
        "你正在为刚作答完的考生提供精悍、严密、可核验的分步精讲。\n"
        "【分步精讲铁律】：\n"
        "1. 简短、具体、直击要害，绝不堆砌大段泛泛的练习建议或易错套话；\n"
        "2. 资料分析与数量关系：必须列出可核验的材料取数、真实公式与计算结果；严禁颠倒时间（如把基期当现期）；严禁编造材料中不存在的数据；\n"
        "3. 言语与逻辑：采用行文脉络或逻辑推理链，不强套数学列式；\n"
        "4. 教材解析与知识树为主要依据，教师规则为补充；若题干、公式、解析存在冲突，指出待核实处，不得用错误列式迎合答案；\n"
        "5. 结构必须严格覆盖：考点与知识节点 → 题目所求和已知条件 → 教材对应方法 → 具体推导 → 与答案核对 → 本次作答值得核对的一步。\n\n"
        f"{evidence_rule_text}\n\n"
        "必须返回合法的 JSON，匹配严格 Schema。"
    )

    user_prompt = f"{prompt_body}\n\n请针对本题生成结构化分步精讲。"

    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]

    gateway = get_model_gateway()
    is_fallback = False
    validation_issues = []
    result = None

    images = []
    try:
        if ctx.get("module") in ("图形推理", "立体图推"):
            from .question_vision import question_image_input, VISION_RULE
            images, labels = question_image_input(db, ctx["question_id"])
            messages[0].content += VISION_RULE
            messages[-1].images = images
            messages[-1].content += "\n【本轮图片顺序】\n" + labels
        result = await gateway.generate(
            task_type="tutor_explanation",
            messages=messages,
            schema=StepExplanationSchema,
            model_policy="BALANCED",
        )
        step_data: StepExplanationSchema = result.data

        # Support validation
        val_res = verify_explanation_support(step_data.model_dump(), ctx)
        if not val_res.is_valid:
            logger.warning("Step explanation failed support validation: %s", val_res.issues)
            validation_issues = val_res.issues
            is_fallback = True
    except Exception as exc:
        logger.warning("Step explanation generation error: %s", exc)
        validation_issues.append("模型讲解暂不可用（" + type(exc).__name__ + "）")
        is_fallback = True

    if is_fallback:
        step_data = _fallback_step_explanation(ctx, validation_issues)

    image_unavailable = ctx.get("module") in ("图形推理", "立体图推") and not images
    if image_unavailable:
        is_fallback = True
        validation_issues.append("当前复盘链路没有图像输入，不能核验图形")
        step_data = _fallback_step_explanation(ctx, validation_issues)

    # Format into structured Markdown
    steps_md = "\n".join(f"{i+1}. {st}" for i, st in enumerate(step_data.derivation_steps))
    formatted_content = (
        f"📖 【AI Tutor 分步精讲】\n"
        f"🎯 **考点与知识节点**：{step_data.knowledge_node}\n\n"
        f"📌 **所求与已知条件**：\n{step_data.given_and_target}\n\n"
        f"🛠️ **教材解法**：{step_data.method_name}\n\n"
        f"📝 **分步推导与列式**：\n{steps_md}\n\n"
        f"✅ **答案核对**：{step_data.answer_verification}\n\n"
        f"🔍 **本次作答核对建议**：{step_data.attempt_check_point}"
    )

    t_ctx = ctx.get("teacher_context")
    if t_ctx:
        t_name = t_ctx.get("teacher_name", "名师团队")
        pols = t_ctx.get("policies", [])
        pol_lines = []
        for p in pols[:2]:
            pol_lines.append(f"  - **【{p['name']}】** ({p['policy_id']})：{p['rule']}")
            if p.get("forbidden_transformations"):
                pol_lines.append(f"    * 避坑警示：{', '.join(p['forbidden_transformations'])}")
        pols_text = "\n".join(pol_lines) if pol_lines else "严格对照题干约束与数字特性推演。"

        crit = t_ctx.get("critique")
        crit_text = f"\n  - 错因诊断（{crit.get('error_type')}）：{crit.get('diagnosis')}\n  - 纠偏指导：{crit.get('remedy')}" if crit else ""

        formatted_content += (
            f"\n\n🏛️ 【教学方法参考】（来源：{t_name}，须先核验适用条件）\n"
            f"{pols_text}"
            f"{crit_text}\n"
            f"💡 **教学建议**：{t_ctx.get('signature_advice', '')}\n"
            "以上不是本题结论或考生错因，不能据此否定已核对正确的解法。"
        )

    msg_id = str(uuid.uuid4())
    step_meta = step_data.model_dump()
    step_meta["generation"] = {
        "status": "fallback" if is_fallback else "generated",
        "fallback_reasons": validation_issues,
        "model": getattr(result, "model_name", None),
        "provider": getattr(result, "provider_name", None),
        "policy": "BALANCED",
        "validation_scope": "explicit_answer_period_and_arithmetic",
        "image_input": False,
    }
    if ctx.get("hub_evidences"):
        step_meta["hub_evidences"] = ctx["hub_evidences"]
    if t_ctx:
        step_meta["teacher_context"] = t_ctx

    db.execute(
        """INSERT INTO attempt_followups (id, attempt_id, question_id, role, content, turn_type, status, metadata_json, created_at)
           VALUES (?, ?, ?, 'assistant', ?, 'step_by_step_explanation', ?, ?, ?)""",
        (msg_id, attempt_id, ctx["question_id"], formatted_content, "failed" if is_fallback else "completed", json.dumps(step_meta, ensure_ascii=False), now_time),
    )

    # Update summary in interactive_diagnoses
    existing_diag = db.execute("SELECT id FROM interactive_diagnoses WHERE attempt_id=?", (attempt_id,)).fetchone()
    summary_text = f"分步精讲：{kn['node_name']}"
    if existing_diag:
        db.execute(
            "UPDATE interactive_diagnoses SET summary=?, last_message_at=?, updated_at=? WHERE id=?",
            (summary_text, now_time, now_time, existing_diag["id"])
        )
    else:
        record_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO interactive_diagnoses
               (id, attempt_id, question_id, status, observed_facts_json, hypotheses_json, initial_inference_json,
                suggested_action, summary, cause_source, last_message_at, created_at, updated_at, dedup_key)
               VALUES (?, ?, ?, 'HYPOTHESIZED', ?, '[]', '{}', ?, ?, 'AI_INFERRED', ?, ?, ?, ?)""",
            (
                record_id, attempt_id, ctx["question_id"],
                json.dumps(ctx, ensure_ascii=False),
                f"已提供【{kn['node_name']}】分步讲解",
                summary_text, now_time, now_time, now_time, f"{attempt_id}:diagnosis"
            ),
        )

    detail = get_interactive_review_detail(db, attempt_id)
    if is_fallback:
        detail["failed_message_id"] = msg_id
    return detail


def _fallback_step_explanation(ctx: Dict[str, Any], validation_issues: List[str] = None) -> StepExplanationSchema:
    """High-fidelity fallback built directly from authoritative textbook explanation and verified numbers."""
    kn = ctx["knowledge_context"]
    auth_exp = ctx.get("authoritative_explanation", "")
    ans = ctx.get("standard_answer", "")
    user_sel = ctx.get("user_selected", "")
    is_corr = ctx.get("is_correct", False)
    module = ctx.get("module", "")

    # Extract official analysis text
    m_exp = re.search(r'【实战解析】\s*([\s\S]+?)(?=\n\n【|$)', auth_exp)
    clean_exp_lines = m_exp.group(1).strip().split('\n') if m_exp else [auth_exp[:200]]
    first_few_steps = [l.strip() for l in clean_exp_lines if l.strip() and not l.startswith("【")]

    check_advice = f"本次选择【{user_sel}】，{'与标准答案一致' if is_corr else '与标准答案不同'}。仅凭选项不能判断是否掌握方法，请对照教材核验实际推导。"

    if validation_issues:
        check_advice += f"（系统支持性核验提醒：请以教材原解析取数与列式为绝对基准）"

    return StepExplanationSchema(
        knowledge_node=f"{kn['full_path']}（{kn['node_name']}）",
        given_and_target="AI 完整讲解未通过或暂不可用；以下仅摘录已有教材解析，未完成独立核验。" + ("当前未读取题目图片，不能作看图判断。" if module in ("图形推理", "立体图推") else ""),
        method_name="教材解析摘录（讲解未完成）",
        derivation_steps=first_few_steps if first_few_steps else [auth_exp[:180]],
        answer_verification=f"题库记录的标准答案为【{ans}】；本次未完成独立推导核验。",
        attempt_check_point=check_advice,
    )


# =============================================================================
# Continuous Multi-Turn Dialogue
# =============================================================================

async def continue_interactive_review(
    db,
    attempt_id: str,
    message: str,
    client_request_id: str | None = None,
) -> dict[str, Any]:
    """
    Handle continuous follow-up questions during review.
    Contains full unified context & previous step-by-step steps for seamless continuation.
    """
    clean_msg = (message or "").strip()
    if not clean_msg:
        raise HTTPException(400, "追问或回复内容不能为空")

    ctx = await build_unified_review_context_with_hub(db, attempt_id, query=clean_msg)
    now_time = now_iso()
    question_id = ctx["question_id"]

    # 1. Idempotency check on client_request_id
    if client_request_id:
        prev_user_msg = db.execute(
            "SELECT id FROM attempt_followups WHERE attempt_id=? AND metadata_json LIKE ?",
            (attempt_id, f'%"{client_request_id}"%'),
        ).fetchone()
        if prev_user_msg:
            return get_interactive_review_detail(db, attempt_id)

    # 2. Record user turn in DB
    user_msg_id = str(uuid.uuid4())
    user_meta = {"client_request_id": client_request_id} if client_request_id else {}
    db.execute(
        """INSERT INTO attempt_followups (id, attempt_id, question_id, role, content, turn_type, status, metadata_json, created_at)
           VALUES (?, ?, ?, 'user', ?, 'free_chat', 'completed', ?, ?)""",
        (user_msg_id, attempt_id, question_id, clean_msg, json.dumps(user_meta), now_time),
    )

    # 3. Retrieve recent history for context
    history_rows = db.execute(
        """SELECT role, content, turn_type FROM attempt_followups
           WHERE attempt_id=? ORDER BY created_at ASC, rowid ASC""",
        (attempt_id,),
    ).fetchall()

    from .student_work_check import check_student_work, work_check_prompt, missed_work_correction
    checks = check_student_work(ctx, '\n'.join(m['content'] for m in history_rows if m['role'] == 'user'))
    prompt_body = format_unified_prompt_blocks(ctx) + work_check_prompt(checks)

    system_prompt = (
        "你是公考 Learning OS 的专职资深名师导师（AI Tutor）。\n"
        "你正在与考生针对刚做完的题目进行多轮互动复盘追问。\n"
        "【核心准则】：\n"
        "1. 考生探讨其他解法时（如代入排除、设1分数计算、倍数特性、极端估算），客观评价其适用条件与效率，严禁贬低；\n"
        "2. 紧密接上此前刚讲过的分步推导和算式，针对考生的具体疑问进行定向答疑；\n"
        "3. 以教材解析与知识树为主要依据，教师规则为补充；有冲突应说明待核实处，不得编造推导迎合答案。\n\n"
        f"{prompt_body}"
    )

    prompt_messages = [Message(role="system", content=system_prompt)]
    recent_msgs = history_rows[-8:]
    for m in recent_msgs:
        # Avoid duplicate prompt inclusion
        prompt_messages.append(Message(role=m["role"], content=m["content"]))

    gateway = get_model_gateway()
    reply_msg_id = str(uuid.uuid4())
    reply_time = now_iso()
    is_failed = False
    followup_issues = []
    reply_res = None
    images = []

    try:
        if ctx.get("module") in ("图形推理", "立体图推"):
            from .question_vision import question_image_input, VISION_RULE
            images, labels = question_image_input(db, ctx["question_id"])
            prompt_messages[0].content += VISION_RULE
            prompt_messages[-1].images = images
            prompt_messages[-1].content += "\n【本轮图片顺序】\n" + labels
        reply_res = await gateway.generate(
            task_type="tutor_followup",
            messages=prompt_messages,
            schema=None,
            model_policy="BALANCED",
        )
        ai_reply = (reply_res.raw_text or reply_res.data or "").strip()
        if not ai_reply:
            followup_issues.append("模型返回为空")
            raise RuntimeError("模型返回为空")
        validation = verify_followup_support(ai_reply, ctx, clean_msg)
        if missed_work_correction(ai_reply, checks):
            validation.issues.append('回复没有纠正已核验的上游计算错误')
            validation.is_valid = False
        if not validation.is_valid:
            followup_issues.extend(validation.issues)
            raise ValueError("回复未通过支持性核验")
    except Exception as exc:
        logger.warning("Continue interactive review gateway error: %s", exc)
        is_failed = True
        if not followup_issues:
            followup_issues.append("模型回复暂不可用（" + type(exc).__name__ + "）")
        ai_reply = "本次回复未完成：" + "；".join(followup_issues) + "。你的提问已保存，未展示未经核验的答案。"
        if ctx.get("module") in ("图形推理", "立体图推") and not images:
            ai_reply += "请先对照题目图片与教材解析；当前链路不能声称已观察图形。"

    msg_status = "failed" if is_failed else "completed"
    followup_meta = {}
    followup_meta["teacher_context"] = ctx.get("teacher_context")
    followup_meta["generation"] = {
        "status": "failed" if is_failed else "generated",
        "fallback_reasons": followup_issues,
        "model": getattr(reply_res, "model_name", None),
        "provider": getattr(reply_res, "provider_name", None),
        "policy": "BALANCED",
        "validation_scope": "explicit_arithmetic_and_declared_current_answer",
        "image_input": False,
    }
    if ctx.get("hub_evidences"):
        followup_meta["hub_evidences"] = ctx["hub_evidences"]

    db.execute(
        """INSERT INTO attempt_followups (id, attempt_id, question_id, role, content, turn_type, status, metadata_json, created_at)
           VALUES (?, ?, ?, 'assistant', ?, 'free_chat', ?, ?, ?)""",
        (reply_msg_id, attempt_id, question_id, ai_reply, msg_status, json.dumps(followup_meta, ensure_ascii=False), reply_time),
    )

    new_summary = f"讨论：{clean_msg[:24]}..."
    existing_diag = db.execute("SELECT id FROM interactive_diagnoses WHERE attempt_id=?", (attempt_id,)).fetchone()
    if existing_diag:
        db.execute(
            """UPDATE interactive_diagnoses
               SET summary=?, last_message_at=?, updated_at=?
               WHERE attempt_id=?""",
            (new_summary, reply_time, reply_time, attempt_id),
        )
    else:
        record_id = str(uuid.uuid4())
        db.execute(
            """INSERT INTO interactive_diagnoses
               (id, attempt_id, question_id, status, observed_facts_json, hypotheses_json, initial_inference_json,
                suggested_action, summary, cause_source, last_message_at, created_at, updated_at, dedup_key)
               VALUES (?, ?, ?, 'CLARIFYING', ?, '[]', '{}', '自由讨论中', ?, 'AI_INFERRED', ?, ?, ?, ?)""",
            (
                record_id, attempt_id, question_id,
                json.dumps(ctx, ensure_ascii=False),
                new_summary, reply_time, reply_time, reply_time, f"{attempt_id}:diagnosis"
            ),
        )

    detail = get_interactive_review_detail(db, attempt_id)
    if is_failed:
        detail["failed_message_id"] = reply_msg_id
    return detail


def _fallback_chat_reply(user_msg: str, ctx: Any) -> str:
    """Safe fallback with solution tolerance for fractions, substitution, and elimination."""
    if isinstance(ctx, dict):
        ans = ctx.get("standard_answer") or ctx.get("answer") or ""
        auth_exp = ctx.get("authoritative_explanation") or ctx.get("explanation") or ""
    else:
        ans = getattr(ctx, "answer", "")
        auth_exp = getattr(ctx, "explanation", "")

    msg = user_msg.lower()
    if any(kw in msg for kw in ("代入", "排除", "秒杀", "选项")):
        return (
            "【关于代入排除技巧】：在公考行测中，代入排除法是完全正规且高效的解题策略！"
            f"对于本题，官方标准答案为【{ans}】。结合选项特征与整除倍数反推，也是快速解题的利器。"
        )
    if any(kw in msg for kw in ("设为1", "设1", "分数")):
        return (
            "【关于设总量为1的分数法】：设总量为1是完全正确、严谨的数学解题方法。"
            "但在公考限时场景下，使用最小公倍数设特值能化分数运算为整数运算，降低失误率。"
        )

    return (
        f"收到你的复盘提问：「{user_msg}」。\n"
        f"结合本题（正确答案【{ans}】），核心推导依据如下：\n{auth_exp[:180]}\n"
        "如需进一步比较特定解法的计算量，可以告诉我你具体想尝试的代入或速算步骤。"
    )


def _format_diagnosis_record(row: Any) -> dict[str, Any]:
    """Helper to convert database row to clean dictionary."""
    r = dict(row)
    r["observed_facts"] = json.loads(r.pop("observed_facts_json", "{}"))
    r["hypotheses"] = json.loads(r.pop("hypotheses_json", "[]"))
    r["initial_inference"] = json.loads(r.pop("initial_inference_json", "{}"))
    r["clarification_options"] = json.loads(r.pop("clarification_options_json", "[]"))
    r["cause_history"] = json.loads(r.pop("cause_history_json", "[]")) if "cause_history_json" in r else []
    final_diag_raw = r.pop("final_diagnosis_json", None)
    r["final_diagnosis"] = json.loads(final_diag_raw) if final_diag_raw else None
    r["is_user_confirmed"] = bool(r["is_user_confirmed"])
    return r
