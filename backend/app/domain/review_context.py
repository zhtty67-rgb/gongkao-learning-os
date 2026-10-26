# -*- coding: utf-8 -*-
"""
backend/app/domain/review_context.py

Unified, traceable pedagogical review context builder.
Strictly separates:
  1. Observed facts (stem, options, standard answer, user selection, elapsed time, confidence)
  2. Authoritative textbook explanation (ground truth formulas, steps, margin notes)
  3. Knowledge tree node hierarchy (parent paths, definitions, core formulas, methods, common pitfalls)
  4. Material verified data (extracts real verifiable figures for Data Analysis, explicitly flags unreadable charts)
  5. User本次作答 facts & confirmed attribution
  6. Attempt-scoped multi-turn dialogue history
"""

import ast
import json
import logging
import re
from typing import Any, Dict, List, Optional
import sqlite3

logger = logging.getLogger(__name__)

# =============================================================================
# Problem-Solving Stages by Module (Dimension 2: 失误环节)
# =============================================================================

MODULE_PROBLEM_SOLVING_STAGES: Dict[str, List[Dict[str, str]]] = {
    "资料分析": [
        {"code": "data_locate", "label": "数据定位", "desc": "材料主体、段落定位错误或找错统计图表指标"},
        {"code": "time_or_scope", "label": "时间/统计口径", "desc": "混淆基期现期、月度累计、同比环比或口径范围"},
        {"code": "formula_selection", "label": "公式列式", "desc": "公式方向记错、正负混淆或比重/增长模型套错"},
        {"code": "calc_accuracy", "label": "运算精度/截位", "desc": "直除截位不足、分子分母估算放缩失准或速算失误"},
        {"code": "option_judgment", "label": "选项辨析/审题", "desc": "看错题干所求（如多多少倍 vs 是多少倍、选非项）"},
    ],
    "数量关系": [
        {"code": "problem_translation", "label": "题意条件转化", "desc": "未能将实际问题抽象为数学关系，遗漏隐藏条件"},
        {"code": "model_selection", "label": "模型/公式选用", "desc": "工程、行程、排列组合等题型模型识别或公式套用错误"},
        {"code": "method_efficiency", "label": "特值/技巧选用", "desc": "未能应用设特值、奇偶倍数特性或代入排除等更优解法"},
        {"code": "calculation_error", "label": "计算求解失误", "desc": "列式正确但在方程移项、通分或算术运算中出现失误"},
        {"code": "question_trap", "label": "所求问陷阱", "desc": "算对中间变量但看错最终所求（如甲的工效 vs 合作时间）"},
    ],
    "言语理解": [
        {"code": "main_idea", "label": "行文脉络/主旨", "desc": "未能准确概括文段中心论点或宏观脉络"},
        {"code": "key_details", "label": "转折/关键信息", "desc": "忽略关联词（但是/因此）、代词指代或分述举例关系"},
        {"code": "option_distortion", "label": "选项偷换/无中生有", "desc": "选项偷换概念、强加因果、绝对化或无依据外延"},
        {"code": "word_nuance", "label": "词义/色彩搭配", "desc": "选词填空中近义词轻重、感情色彩或语体习惯辨析不清"},
    ],
    "判断推理": [
        {"code": "rule_application", "label": "推理规则应用", "desc": "假言命题逆否、或且矛盾规则或三段论推导错误"},
        {"code": "argument_relation", "label": "论点论据关联", "desc": "论证题中未能锁定论点核心范围，论据论点脱节"},
        {"code": "causal_reasoning", "label": "削弱加强判定", "desc": "因果倒置、另有他因、搭桥与拆桥力度判断偏差"},
        {"code": "exclusion_verify", "label": "选项排他验证", "desc": "未能逐项比对排除，被强干扰项带偏"},
    ],
    "图形推理": [
        {"code": "feature_sensitivity", "label": "特征图敏感度", "desc": "未能从九宫格或一组图中敏锐识别特殊图元特征"},
        {"code": "dimension_identification", "label": "规律维度识别", "desc": "在位置、样式、数量、属性、空间五个维度中选错切入点"},
        {"code": "pattern_derivation", "label": "细分规律推导", "desc": "笔画数、对称轴方向、交点类型等细分规律推导错误"},
        {"code": "option_comparison", "label": "选项比对排除", "desc": "多规律复合时未能完整验证全部选项"},
    ],
    "常识判断": [
        {"code": "knowledge_recall", "label": "知识点识别", "desc": "未识别题目涉及的法律、政治、历史、科技等知识点"},
        {"code": "fact_accuracy", "label": "事实与概念辨析", "desc": "记错事实、混淆相近概念或适用条件"},
        {"code": "context_application", "label": "情境适用", "desc": "掌握知识点但未能结合题干情境判断"},
        {"code": "option_verification", "label": "选项核验", "desc": "未逐项核对限定词、例外或选非要求"},
    ],
    "通用解题": [
        {"code": "stem_comprehension", "label": "题干理解", "desc": "遗漏题干条件或看错所求"},
        {"code": "knowledge_application", "label": "知识应用", "desc": "未能准确调用或应用相关知识"},
        {"code": "option_verification", "label": "选项核验", "desc": "未充分比较和核对选项"},
    ],
    "通用补充": [
        {"code": "time_pressure", "label": "时间紧迫/慌乱", "desc": "考试或训练剩余时间不足，草率作答"},
        {"code": "pure_guess", "label": "纯粹猜测/蒙题", "desc": "完全无思路，凭感觉随机猜选"},
        {"code": "slip_of_hand", "label": "看错题问/手滑", "desc": "误把选非题看作选是题，或手误点击错误选项"},
    ],
}

def get_stages_for_module(module: str) -> List[Dict[str, str]]:
    """Return the problem solving stages relevant to the module, plus common supplementary causes."""
    m_clean = module or ""
    if "资料" in m_clean:
        return MODULE_PROBLEM_SOLVING_STAGES["资料分析"]
    elif "数量" in m_clean:
        return MODULE_PROBLEM_SOLVING_STAGES["数量关系"]
    elif "言语" in m_clean:
        return MODULE_PROBLEM_SOLVING_STAGES["言语理解"]
    elif "图" in m_clean:
        return MODULE_PROBLEM_SOLVING_STAGES["图形推理"]
    elif "常识" in m_clean:
        return MODULE_PROBLEM_SOLVING_STAGES["常识判断"]
    elif any(k in m_clean for k in ("判断", "逻辑", "定义", "类比")):
        return MODULE_PROBLEM_SOLVING_STAGES["判断推理"]
    else:
        return MODULE_PROBLEM_SOLVING_STAGES["通用解题"]


# =============================================================================
# Knowledge Tree Node Context Extractor
# =============================================================================

def extract_knowledge_node_context(db: Any, question_id: str, module: str, explanation: str = "") -> Dict[str, Any]:
    """
    Extract authoritative knowledge node path, definition, formulas, and pitfalls from DB.
    Never returns a bare node name without parent path or definitions.
    """
    c = db.cursor()

    # 1. Fetch primary skill binding
    c.execute("""
        SELECT qsb.learning_skill_id, qsb.knowledge_node_code, ls.name, ls.description, ls.metadata_json
        FROM question_skill_bindings qsb
        LEFT JOIN learning_skills ls ON ls.id = qsb.learning_skill_id
        WHERE qsb.question_id = ? AND qsb.role = 'primary'
    """, (question_id,))
    binding_row = c.fetchone()

    # 2. Refine using explanation's 【题型考点】
    cols = {r[1] for r in c.execute("PRAGMA table_info(knowledge_nodes)").fetchall()}
    has_code_col = "code" in cols
    has_kn_code_col = "knowledge_node_code" in cols
    desc_expr = "description" if "description" in cols else "'' AS description"
    if 'description' not in cols and 'metadata_json' in cols:
        desc_expr = "COALESCE(json_extract(CASE WHEN json_valid(metadata_json) THEN metadata_json ELSE '{}' END, '$.description'), '') AS description"

    refined_node = None
    if explanation and cols:
        m_cat = re.search(r'【题型(?:考点|分类)?】\s*([^\n]+)', explanation)
        if m_cat:
            cat_text = m_cat.group(1).strip()
            priority_kw_map = [
                ("综合分析", ["data_analysis"] if module == "资料分析" else []),
                ("两期比重", ["da_prop_two_period", "two_period"]),
                ("基期比重", ["da_prop_base", "data_analysis_base"]),
                ("基期", ["da_base_general", "da_base_special", "data_analysis_base"]),
                ("现期", ["da_base_general", "data_analysis_base"]),
                ("增长量", ["da_amount_general", "da_amount_special", "data_analysis_abrx"]),
                ("间隔", ["da_base_interval", "data_analysis_growth_rate_interval"]),
                ("隔年", ["da_base_interval", "data_analysis_growth_rate_interval"]),
                ("混合", ["da_rate_general", "data_analysis_growth_rate_mixed"]),
                ("年均", ["da_annual_rate", "da_annual_growth", "data_analysis_growth_rate_annual"]),
                ("乘积", ["growth"]),
                ("工程问题", ["quant_work_cooperation", "work_problem", "work"]),
                ("行程问题", ["quant_competition_journey", "journey"]),
                ("经济利润", ["quant_profit_problems", "profit"]),
            ]
            for kw, target_candidates in priority_kw_map:
                if kw in cat_text:
                    if isinstance(target_candidates, str):
                        target_candidates = [target_candidates]
                    for target_id in target_candidates:
                        kn_field = "knowledge_node_code" if has_kn_code_col else "id AS knowledge_node_code"
                        if has_code_col:
                            c.execute(f"SELECT id, parent_id, name, {desc_expr}, {kn_field} FROM knowledge_nodes WHERE id = ? OR code = ?", (target_id, target_id))
                        else:
                            c.execute(f"SELECT id, parent_id, name, {desc_expr}, {kn_field} FROM knowledge_nodes WHERE id = ?", (target_id,))
                        candidate = c.fetchone()
                        if candidate:
                            refined_node = candidate
                            break
                    if refined_node:
                        break

    active_node = refined_node
    if not active_node and binding_row and (binding_row[0] or binding_row[1]) and cols:
        skill_id = binding_row[0]
        kn_code_val = binding_row[1] if len(binding_row) > 1 else skill_id
        kn_field = "knowledge_node_code" if has_kn_code_col else "id AS knowledge_node_code"
        if has_code_col and has_kn_code_col:
            c.execute(f"SELECT id, parent_id, name, {desc_expr}, {kn_field} FROM knowledge_nodes WHERE id = ? OR code = ? OR knowledge_node_code = ?", (skill_id, skill_id, kn_code_val))
        elif has_kn_code_col:
            c.execute(f"SELECT id, parent_id, name, {desc_expr}, {kn_field} FROM knowledge_nodes WHERE id = ? OR knowledge_node_code = ?", (skill_id, kn_code_val))
        else:
            c.execute(f"SELECT id, parent_id, name, {desc_expr}, id AS knowledge_node_code FROM knowledge_nodes WHERE id = ?", (skill_id,))
        active_node = c.fetchone()

    # 3. Resolve parent path
    path_nodes = []
    if active_node:
        curr = active_node
        path_nodes.append(curr[2])
        pid = curr[1]
        visited = set()
        while pid and pid not in visited:
            visited.add(pid)
            c.execute("SELECT id, parent_id, name FROM knowledge_nodes WHERE id = ?", (pid,))
            p_row = c.fetchone()
            if p_row:
                path_nodes.append(p_row[2])
                pid = p_row[1]
            else:
                break
        path_nodes.reverse()

    full_path_str = " > ".join(path_nodes) if path_nodes else (module or "行测通识")
    node_name = (active_node[2] if active_node else (binding_row[2] if binding_row else None)) or "未绑定具体考点"
    node_desc = active_node[3] if active_node else (binding_row[3] if binding_row else "")
    node_code = active_node[4] if active_node else (binding_row[1] if binding_row else "")

    return {
        "node_id": active_node[0] if active_node else (binding_row[0] if binding_row else "unknown"),
        "node_name": node_name,
        "full_path": full_path_str,
        "description": node_desc or "标准公考考点推导法则",
        "knowledge_code": node_code,
        "knowledge_node_code": node_code,
    }


# =============================================================================
# Material Verified Data Extractor
# =============================================================================

def extract_material_verified_data(
    passage_content: Optional[str],
    explanation: str,
    module: str,
    stem: str
) -> Dict[str, Any]:
    """
    Ensure the model receives VERIFIABLE FIGURES for Data Analysis.
    Never relies on '图表见下方图片' as data.
    """
    has_real_passage_text = bool(
        passage_content
        and len(passage_content.strip()) > 30
        and "图表见下方" not in passage_content
        and "见下方高保真" not in passage_content
    )

    extracted_figures = []
    # If passage content is just a placeholder and module is Data Analysis,
    # extract the authoritative numbers quoted in the official textbook explanation!
    if "资料" in (module or "") and explanation:
        # Search for lines locating passage data, e.g., "定位材料第一段，全国发电量8059亿千瓦时，同比增长4.5%"
        m_loc = re.findall(r'(?:定位[^\n，。；]+[，：])([^\n。；]+(?:[0-9]+(?:\.[0-9]+)?%?|[0-9]+万|[0-9]+亿)[^\n。；]*)', explanation)
        for loc in m_loc:
            cleaned = loc.strip()
            if cleaned and len(cleaned) > 6:
                extracted_figures.append(cleaned)

        # Also search for formula numbers like "B=8059 R=4.5%"
        m_formula_vals = re.findall(r'([A-Za-z0-9_]+\s*=\s*[0-9]+(?:\.[0-9]+)?%?(?:万|亿)?)', explanation)
        if m_formula_vals:
            extracted_figures.extend(m_formula_vals[:6])

    data_summary = ""
    if has_real_passage_text:
        data_summary = passage_content.strip()
    elif extracted_figures:
        data_summary = "【教材原解析权威材料取数（已核验真实数据）】：\n" + "\n".join(f"• {f}" for f in list(dict.fromkeys(extracted_figures)))
    else:
        if "资料" in (module or ""):
            data_summary = "【注意】：本题材料为图表扫描件，纯文本中未内嵌全部明细数据。推导必须严格以【教材原解析权威依据】中的真实取数与算式为准，严禁凭空捏造数据。"

    return {
        "has_real_passage_text": has_real_passage_text,
        "data_summary": data_summary,
        "is_chart_dependent": "图表见下方" in (passage_content or "") or "见下方高保真" in (passage_content or ""),
    }


# =============================================================================
# Unified Review Context Builder
# =============================================================================

def build_unified_review_context(db: Any, attempt_id: str) -> Dict[str, Any]:
    """
    Single source of truth for constructing review context across:
      1. Initial Diagnosis / Clarification (帮我找错因)
      2. Step-by-Step Explanation (给我分步讲解)
      3. Follow-up Chat (继续提问)
    """
    attempt = db.execute(
        """SELECT a.*, q.stem, q.options_json, q.answer, q.explanation AS q_explanation, q.module, q.estimated_seconds,
                  q.stem_assets_json, q.option_assets_json, q.passage_id,
                  qp.content AS passage_content
           FROM attempts a
           JOIN questions q ON q.id=a.question_id
           LEFT JOIN question_passages qp ON qp.id=q.passage_id
           WHERE a.id=?""",
        (attempt_id,),
    ).fetchone()

    if not attempt:
        raise ValueError(f"Attempt {attempt_id} not found")

    module = attempt["module"] or "资料分析"
    stem = attempt["stem"] or ""
    q_explanation = attempt["q_explanation"] or ""
    passage_content = attempt["passage_content"] or ""

    # 1. Knowledge tree node
    kn_ctx = extract_knowledge_node_context(db, attempt["question_id"], module, q_explanation)

    # 2. Problem solving stages
    stages = get_stages_for_module(module)

    # 3. Material verified data
    mat_ctx = extract_material_verified_data(passage_content, q_explanation, module, stem)

    # 4. Attempt facts
    opts_raw = attempt["options_json"]
    options = json.loads(opts_raw) if isinstance(opts_raw, str) else (opts_raw or {})
    confidence_val = float(attempt["confidence"]) if attempt["confidence"] is not None else None
    confidence_pct = int(confidence_val * 100) if confidence_val is not None else None
    elapsed_ms_val = attempt["elapsed_ms"] or 0
    elapsed_sec = round(elapsed_ms_val / 1000.0, 1)

    stem_assets_raw = attempt["stem_assets_json"] if "stem_assets_json" in attempt.keys() else None
    stem_assets = json.loads(stem_assets_raw or "[]") if stem_assets_raw else []

    # 5. Existing review state & confirmed attribution
    diag_row = db.execute("SELECT * FROM interactive_diagnoses WHERE attempt_id=?", (attempt_id,)).fetchone()
    selected_error_type = diag_row["selected_error_type"] if diag_row else None
    cause_source = diag_row["cause_source"] if diag_row else "PENDING"
    user_feedback_text = diag_row["user_feedback_text"] if diag_row else None

    # 6. Attempt followups conversation history (strictly attempt-scoped)
    msg_rows = db.execute(
        """SELECT role, content, turn_type FROM attempt_followups
           WHERE attempt_id=? ORDER BY created_at ASC, rowid ASC""",
        (attempt_id,),
    ).fetchall()

    # 7. Four-module teacher intelligence context
    teacher_context = None
    try:
        from .module_teacher_service import ModuleTeacherService
        mts = ModuleTeacherService()
        teacher_context = mts.get_teacher_context_for_review(
            module=module,
            stem=stem,
            explanation=q_explanation,
            user_selected=attempt["selected_answer"] or "",
            student_thought=user_feedback_text or ""
        )
    except Exception as exc:
        logger.debug("Failed to extract module teacher context: %s", exc)

    return {
        "attempt_id": attempt_id,
        "question_id": attempt["question_id"],
        "module": module,
        "stem": stem,
        "options": options,
        "standard_answer": attempt["answer"],
        "user_selected": attempt["selected_answer"],
        "is_correct": bool(attempt["correct"]),
        "confidence": confidence_val,
        "confidence_pct": confidence_pct,
        "elapsed_ms": elapsed_ms_val,
        "elapsed_sec": elapsed_sec,
        "has_stem_assets": bool(stem_assets),
        "stem_assets": stem_assets,
        "explanation": q_explanation,
        "knowledge_context": kn_ctx,
        "problem_solving_stages": stages,
        "material_context": mat_ctx,
        "authoritative_explanation": q_explanation,
        "selected_error_type": selected_error_type,
        "cause_source": cause_source,
        "user_feedback_text": user_feedback_text,
        "dialogue_history": [dict(m) for m in msg_rows],
        "teacher_context": teacher_context,
    }


async def build_unified_review_context_with_hub(db: Any, attempt_id: str, query: str = "") -> Dict[str, Any]:
    """
    Build unified review context augmented with Knowledge Hub textbook evidence slices.
    Gracefully degrades if Hub is offline or returns no matches without halting review.
    """
    ctx = build_unified_review_context(db, attempt_id)

    try:
        from .tutor import get_knowledge_provider, MODULE_NAMESPACE_SLUGS
        from ..knowledge.evidence_filter import filter_candidate_evidences, format_evidence_prompt_block

        provider = get_knowledge_provider()
        module = ctx.get("module") or "资料分析"
        namespace = f"gongkao/xingce/{MODULE_NAMESPACE_SLUGS.get(module, 'reasoning')}"

        kn_ctx = ctx.get("knowledge_context") or {}
        kn_code = kn_ctx.get("knowledge_node_code") or kn_ctx.get("knowledge_code")

        stem = ctx.get("stem") or ""
        search_query = " ".join(part for part in (query.strip(), stem[:80]) if part)[:200]

        raw_evidences = []
        precision_attempted = False
        precision_filters = None
        precision_succeeded = False
        fallback_attempted = False

        if kn_code:
            precision_attempted = True
            precision_filters = {"knowledge_node_code": kn_code}
            try:
                raw_evidences = await provider.retrieve(
                    query=search_query,
                    namespace=namespace,
                    filters=precision_filters,
                    limit=2,
                )
                if raw_evidences:
                    precision_succeeded = True
            except Exception as e:
                logger.warning("Hub retrieval with precision filter failed: %s", e)

        # Fallback to controlled general retrieval when precision search returns no evidence
        if not raw_evidences:
            fallback_attempted = True
            try:
                raw_evidences = await provider.retrieve(
                    query=search_query,
                    namespace=namespace,
                    filters=None,
                    limit=3,
                )
            except Exception as e:
                logger.warning("Hub general retrieval failed: %s", e)

        candidates = filter_candidate_evidences(raw_evidences, stem, module=module)
        evidence_block, evidence_rule = format_evidence_prompt_block(candidates)

        ctx["hub_evidences"] = [
            cand.model_dump() if hasattr(cand, "model_dump") else dict(cand)
            for cand in candidates
        ]
        ctx["hub_evidence_block"] = evidence_block
        ctx["hub_evidence_rule"] = evidence_rule
        ctx["hub_retrieval_meta"] = {
            "precision_attempted": precision_attempted,
            "precision_filters": precision_filters,
            "precision_succeeded": precision_succeeded,
            "fallback_attempted": fallback_attempted,
            "candidate_count": len(candidates),
        }
        ctx["hub_evidence_rule"] = evidence_rule
    except Exception as exc:
        logger.warning("Hub evidence integration failed gracefully: %s", exc)
        ctx["hub_evidences"] = []
        ctx["hub_evidence_block"] = ""
        ctx["hub_evidence_rule"] = ""

    return ctx


def format_unified_prompt_blocks(ctx: Dict[str, Any]) -> str:
    """Format the unified context into structured, authoritative prompt blocks."""
    from .student_work_check import STUDENT_WORK_RULE
    options_text = "\n".join(f"{k}. {v}" for k, v in ctx["options"].items())
    kn = ctx["knowledge_context"]
    mat = ctx["material_context"]

    blocks = [
        STUDENT_WORK_RULE,
        "【上下文优先级】：题干与可核验材料是事实依据；教材解析与知识树的定义、公式、适用条件是主要教学依据；教师方法是补充，必须先满足适用条件。发现依据冲突应明确指出，不能为迎合答案编造推导。知识节点缺失时不得声称已掌握该节点。",
        f"【题型模块】：{ctx['module']}",
        f"【知识树考点】：{kn['full_path']}（{kn['node_name']}）",
        f"【考点核心法则/公式/易错点】：{kn['description']}",
        "",
        f"【题目干】：{ctx['stem']}",
        f"【选项】：\n{options_text}",
        f"【标准答案】：{ctx['standard_answer']}",
        f"【考生本次作答】：{ctx['user_selected']}（{'作答正确' if ctx['is_correct'] else '作答错误'}） | 信心：{str(ctx['confidence_pct']) + '%' if ctx['confidence_pct'] is not None else '未记录'} | 用时：{ctx['elapsed_sec']}秒",
    ]

    if mat["data_summary"]:
        blocks.extend(["", f"【材料与可核验数据】：\n{mat['data_summary']}"])

    if ctx.get("hub_evidence_block"):
        blocks.extend([
            "",
            "【关联教材文献/考点切片依据】：",
            ctx["hub_evidence_block"].strip(),
        ])

    if ctx["authoritative_explanation"]:
        blocks.extend([
            "",
            "【教材原解析权威依据（Ground Truth，必须无条件遵循）】：",
            ctx["authoritative_explanation"],
            "（重要准则：教材原解析是讲解基准。依据题干与知识树核验定义、公式和适用条件；若材料、解析或答案存在矛盾，应指出待核实处，不得编造数据或错误列式迎合答案。）"
        ])

    if ctx["selected_error_type"]:
        blocks.extend(["", f"【已确认错因/失误环节】：{ctx['selected_error_type']}（来源：{ctx['cause_source']}）"])
    if ctx["user_feedback_text"]:
        blocks.extend(["", f"【考生实际自述反馈】：{ctx['user_feedback_text']}"])

    if ctx.get("teacher_context"):
        t_ctx = ctx["teacher_context"]
        t_name = t_ctx.get("teacher_name", "名师团队")
        pols = t_ctx.get("policies", [])
        pol_strs = []
        for p in pols:
            pol_strs.append(f"• 【{p['name']}】({p['policy_id']})：{p['rule']}")
            if p.get("forbidden_transformations"):
                pol_strs.append(f"  * 易错陷阱警示：{', '.join(p['forbidden_transformations'])}")

        crit = t_ctx.get("critique")
        crit_str = f"• 针对作答错因纠偏（{crit.get('error_type')}）：{crit.get('diagnosis')} 纠偏指南：{crit.get('remedy')}" if crit else ""

        blocks.extend([
            "",
            f"【{t_name} 教学方法参考（须核验适用条件）】：",
            "\n".join(pol_strs) if pol_strs else "依循题干核心条件与逻辑公理严密推导。",
            crit_str,
            f"• 考场秒杀口诀：{t_ctx.get('signature_advice', '')}",
            "（以上仅为相关教学方法，不是对考生的错因诊断；先核验题干与公式边界，不得据此否定正确思路或套用课堂例题答案。）"
        ])

    return "\n".join(blocks)


# =============================================================================
# Support Validation: Anti-Hallucination & Logic Consistency Gates
# =============================================================================

class SupportValidationResult:
    def __init__(self, is_valid: bool, issues: List[str]):
        self.is_valid = is_valid
        self.issues = issues

    def __repr__(self):
        return f"SupportValidationResult(is_valid={self.is_valid}, issues={self.issues})"


_NUMERIC_EQUATION = re.compile(
    r"(?=(?<![A-Za-z0-9_.+\-*/×÷%(（])([+\-]?[0-9][0-9\s.+\-*/×÷%()（）]{0,100}?)\s*(=|＝|≈|≃)\s*([+\-]?[0-9][0-9\s.+\-*/×÷%()（）]{0,100})(?![0-9.]))"
)


def _arithmetic_value(expression: str) -> Optional[float]:
    """Evaluate only numeric arithmetic; model text is never passed to eval()."""
    expression = expression.translate(str.maketrans("×÷（）", "*/()"))
    expression = re.sub(r"(\d+(?:\.\d+)?)%", r"(\1/100)", expression)
    try:
        tree = ast.parse(expression, mode="eval")

        def visit(node: ast.AST) -> float:
            if isinstance(node, ast.Expression):
                return visit(node.body)
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                return float(node.value)
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                value = visit(node.operand)
                return value if isinstance(node.op, ast.UAdd) else -value
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                left, right = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add):
                    return left + right
                if isinstance(node.op, ast.Sub):
                    return left - right
                if isinstance(node.op, ast.Mult):
                    return left * right
                return left / right
            raise ValueError("unsupported arithmetic")

        return visit(tree)
    except (SyntaxError, ValueError, ZeroDivisionError, OverflowError):
        return None


def verify_explanation_support(
    data: Dict[str, Any],
    ctx: Dict[str, Any]
) -> SupportValidationResult:
    """
    Rigorously validate model generated step explanation against ground truth facts.
    Gates:
      1. Correct Answer Invariant: model must conclude with ground-truth answer.
      2. Temporal / Base-Period Invariant: for base period questions (e.g. 2021 from 2022 data),
         must not invert base and current period.
      3. Verifiable Numbers: for quantitative/data-analysis, equations must not invent false numbers.
      4. No Self-Contradiction with Textbook Explanation.
    """
    issues = []
    std_ans = ctx.get("standard_answer", "").strip().upper()
    stem = ctx.get("stem", "")
    module = ctx.get("module", "")

    # Combine all model output text
    full_text = " ".join([
        data.get("knowledge_node", ""),
        data.get("given_and_target", ""),
        data.get("method_name", ""),
        " ".join(data.get("derivation_steps", [])),
        data.get("answer_verification", ""),
        data.get("attempt_check_point", ""),
    ])

    # 1. Answer gate
    ans_verif = data.get("answer_verification", "").strip()
    if std_ans:
        # Check if model asserts a different answer option
        other_answers = [o for o in ["A", "B", "C", "D"] if o != std_ans]
        for bad_opt in other_answers:
            if re.search(rf'(?:正确答案为|故选|选择|答案为|选)\s*[{bad_opt}][项选项]?', ans_verif):
                if not re.search(rf'(?:正确答案为|故选|选择|答案为|选)\s*[{std_ans}][项选项]?', ans_verif):
                    issues.append(f"答案核对不符：标准答案为 {std_ans}，模型结论出现 {bad_opt}")

    # 2. Temporal direction gate for Base Period (基期)
    # Fire only when the output treats the asked year as a growth (current) period.
    # Merely repeating material facts about OTHER years (e.g. "2022年同比增长4.5%")
    # is legitimate in a base-period explanation, so the year must come from the
    # interrogative clause (多少/约为/求), never from the first year of the stem.
    base_year = re.search(r'(201\d|202\d)\s*年[^。；\n]{0,12}(?:为|是|作为)基期', stem)
    if base_year and re.search(rf'{base_year.group(1)}\s*年\s*(?:为|是|作为)现期', full_text):
        issues.append(f"时间口径颠倒：题干明确 {base_year.group(1)} 年为基期，输出称其为现期")
    else:
        base_context = ("基期" in data.get("knowledge_node", "")
                        or "基期" in (ctx.get("knowledge_context") or {}).get("node_name", "")
                        or "基期" in (ctx.get("authoritative_explanation") or ""))
        asked_year = None
        if base_context:
            for clause in re.split(r'[。？！\n]', stem):
                if re.search(r'多少|约为|求', clause):
                    m = re.search(r'((?:19|20)\d{2})\s*年', clause)
                    if m:
                        asked_year = m.group(1)
                        break
        if asked_year and (re.search(rf'{asked_year}\s*年[^。；\n]{{0,15}}?同比', full_text)
                           or re.search(rf'{asked_year}\s*年\s*(?:为|是|作为)\s*现期', full_text)):
            issues.append(f"时间口径可能颠倒：题干所求为 {asked_year} 年（基期），输出将其作为增长现期表述")

    # 3. Verifiable figures check for Data Analysis
    if "资料" in module and ctx.get("authoritative_explanation"):
        auth_exp = ctx["authoritative_explanation"]
        # Extract 3-5 digit key numbers from official explanation (e.g. 8059, 7712, 7710)
        auth_nums = set(re.findall(r'\b\d{3,5}\b', auth_exp))
        if auth_nums:
            # Check model steps for major fabricated integers (excluding standard calculation products)
            step_nums = set(re.findall(r'\b\d{3,5}\b', " ".join(data.get("derivation_steps", []))))
            # Common allowed numbers
            allowed_nums = auth_nums | {"1000", "100", "365", "360", "2020", "2021", "2022", "2023", "2024", "2025"}
            # Check if none of the core auth numbers appeared in derivation
            core_overlap = auth_nums & step_nums
            if not core_overlap and len(auth_nums) >= 2:
                issues.append("推导列式未采用教材原解析中的任何核心材料取数")

    # A cited source and a correct option do not make an incorrect calculation valid.
    # Check explicit numeric equations in the derivation; prose and symbolic formulae
    # are deliberately outside this narrow, deterministic arithmetic gate.
    if any(token in module for token in ("资料", "数量")):
        for step in data.get("derivation_steps", []):
            step = step.replace("−", "-").replace("－", "-")
            # Teacher replies now render LaTeX; explicit multiplication/division
            # must still pass the arithmetic gate instead of escaping it.
            for latex, plain in [(r'\times', '×'), (r'\cdot', '×'), (r'\div', '÷'),
                                 (r'\%', '%'), (r'\approx', '≈'), (r'\left', ''), (r'\right', '')]:
                step = step.replace(latex, plain)
            for match in _NUMERIC_EQUATION.finditer(step):
                # Lookahead finds overlapping candidates. Do not treat the tail
                # of "12 + 15 + 30 = 57" as a separate "15 + 30 = 57" equation.
                prefix = step[:match.start(1)]
                if re.search(r'[0-9%）)]\s*[+\-*/×÷]\s*$', prefix):
                    continue
                lhs, relation, rhs = match.groups()
                if not any(op in lhs for op in ("+", "-", "*", "/", "×", "÷")):
                    continue
                calculated = _arithmetic_value(lhs)
                if calculated is None:
                    continue
                stated = _arithmetic_value(rhs.strip())
                if stated is None:
                    continue
                # Percentage-point units express a ratio difference multiplied by 100.
                # The lookahead matcher has an empty span; use group 3's end.
                if '%' in lhs and '%' not in rhs and re.match(r'\s*(?:个)?百分点', step[match.end(3):]):
                    stated /= 100
                tolerance = max(1e-8, abs(calculated) * (0.02 if relation in ("≈", "≃") else 1e-8))
                # A displayed decimal is rounded to its last digit; e.g. 125/6
                # written as 20.8333. Do not grant that tolerance to expressions.
                decimal = re.fullmatch(r'[+\-]?\d+\.(\d+)(%)?', rhs.strip())
                if decimal:
                    rounding = 0.5 * 10 ** -len(decimal.group(1))
                    if decimal.group(2):
                        rounding /= 100
                    tolerance = max(tolerance, rounding + 1e-10)
                if abs(calculated - stated) > tolerance:
                    issues.append(f"列式计算不符：{lhs.strip()} {relation} {rhs}")

    return SupportValidationResult(is_valid=(len(issues) == 0), issues=issues)


def verify_followup_support(text: str, ctx: Dict[str, Any], user_question: str = "") -> SupportValidationResult:
    """Check explicit arithmetic, without imposing this question's option on other examples."""
    result = verify_explanation_support(
        {"derivation_steps": [text]}, {"module": "数量关系"}
    )
    answer = ctx.get("standard_answer") or ""
    for claimed in re.findall(r'(?:本题|这道题)[^。\n]{0,20}正确答案(?:为|是|：|:)\s*([ABCD])', text):
        if answer and claimed != answer:
            result.issues.append("追问回复声明的本题答案与标准答案不符")
    # Check the simple two-worker example independently of option letters.
    # Correct arithmetic (6+3=9) still gives the wrong cooperation model.
    source = user_question or ctx.get("stem", "")
    workers = re.search(r'甲[^。；\n]{0,20}?(\d+(?:\.\d+)?)\s*天[^。；\n]{0,20}?乙[^。；\n]{0,20}?(\d+(?:\.\d+)?)\s*天', source)
    if workers and "合作" in source and not any(w in source for w in ("交替", "轮流", "先", "后", "休息")):
        a, b = map(float, workers.groups())
        if a > 0 and b > 0:
            expected = 1 / (1/a + 1/b)
            for claimed in re.findall(r'(?:合作|共同)[^。；\n]{0,15}?(?:为|需要|需|是|用时)[^。；\n]{0,30}?([0-9]+(?:\.[0-9]+)?)\s*天', text):
                if abs(float(claimed)-expected) > max(0.01, expected*0.01):
                    result.issues.append("合作时间与单独完工时间的效率相加模型不符")
    result.is_valid = not result.issues
    return result
