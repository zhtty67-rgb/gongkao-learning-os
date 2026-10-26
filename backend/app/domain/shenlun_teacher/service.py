# -*- coding: utf-8 -*-
"""申论教师批改服务（多教师版）：本题上下文 → 按教师/题型检索证据 → 疑点检测
→ AI 受约束语义审查 → 程序核验依据 → 落库 → 用户追问/异议可纠正。

两阶段设计：
1. run_teacher_diagnosis（同步、零模型调用）：先于外部评分运行并立即落库。
   产出"疑点 + 证据包"，review_status='pending'。任何异常不阻塞主提交流程。
2. apply_semantic_review（异步）：对每位教师的疑点做 AI 语义审查，并经程序核验
   （原句定位 / 材料引文存在 / 来源 ID 属于该教师证据包）后更新诊断。
   模型不可用或输出不合规时 review_status='unavailable'，诚实降级为"疑点待确认"。

历史不可变：诊断行只插入不改写；异议产生的维持/调整/撤回记录在
shenlun_target_revisions，读取时折叠为当前有效版本。
"""

import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from .engine import library as lib
from .engine.boundary_guard import check_jiangmuyun_boundary
from .engine.coach import provisional_targets_from_suspicions, coach_note_for
from .engine.evidence import locate_quote, verify_refs
from .engine.semantic_review import review_answer
from .engine.teacher_agent import grade, lcs_nopunct

ENGINE_VERSION = "v3.0"

# 文体词（应用文/公文题）：整体作答任务是"写成一篇某种文体"，优先级最高
_GENRE_WORDS = (
    r"公开信|倡议书|宣传稿|新闻稿|简报|发言稿|讲话稿|发言提纲|提纲|短评|编者按|"
    r"通告|通知|调研报告|调查报告|报告|汇报材料|工作方案|工作方案|指导意见|简讯|解说词|广播稿"
)
# 文章写作标记
_ESSAY_WORDS = r"议论文|大作文|写一篇(文章|作文|短文)|文章写作"
# 对策任务词
_COUNTERMEASURE_WORDS = r"(提出|给出|给出你的|提出你的|提出解决)?(解决|处理)?(对策|建议|措施)|如何解决|怎么办|提出建议"
# 归纳概括任务词
_SUMMARY_WORDS = r"概括|归纳|梳理|指出|归纳出|提炼"
# 综合分析任务词
_ANALYSIS_WORDS = r"理解|含义|谈谈对|谈谈你的|评析|看法|分析"


def infer_question_type(question_stem: str) -> str:
    """从题干推断引擎题型标签。

    判定的是"整体作答任务"，优先级：应用文（文体词）→ 文章写作 → 对策 → 归纳概括（细分问法）
    → 综合分析 → 待判定。题干内部的"分析、建议"等普通词语不控制整体分类。
    无法确定时返回"待判定"，不默认归纳概括-做法。
    """
    s = question_stem or ""
    if not s.strip():
        return "待判定"

    # 1) 应用文/公文题：出现文体词即按应用文处理（"起草一份调研报告，分析……"属于此类）
    if re.search(_GENRE_WORDS, s):
        return "公文题"

    # 2) 文章写作：议论文/大作文/写一篇文章
    if re.search(_ESSAY_WORDS, s):
        return "文章写作"

    # 3) 对策题：作答任务包含提出对策/建议/措施
    if re.search(_COUNTERMEASURE_WORDS, s):
        return "归纳概括-对策"

    # 4) 归纳概括（细分问法：变化/启示/做法/问题等）
    if re.search(r"哪些(新)?变化|新变化|前后对比|发生了哪", s):
        return "归纳概括-变化"
    if re.search(r"启示|经验教训|借鉴|经验之谈", s):
        return "归纳概括-启示"
    if re.search(_SUMMARY_WORDS, s) or re.search(r"(怎样|如何)(当好|做好|做到|开展|推进|实现)", s):
        return "归纳概括-做法"

    # 5) 综合分析（理解/含义/评析/看法/分析）
    if re.search(_ANALYSIS_WORDS, s):
        return "分析理解"

    return "待判定"

_BULLET = re.compile(
    r"^\s*(?:[一二三四五六七八九十]+[、.．]|[（(][一二三四五六七八九十]+[)）]|\d+[、.．]|①②③④⑤⑥⑦⑧⑨⑩|[-*•])\s*"
)


def split_answer_points(final_answer: str) -> list[str]:
    """把整篇作答拆成要点级片段：按换行拆分并剥去序号；无换行时整体作为单点。"""
    raw = [line.strip() for line in (final_answer or "").splitlines() if line.strip()]
    if not raw:
        return [final_answer.strip()] if final_answer and final_answer.strip() else []
    points = []
    for line in raw:
        cleaned = _BULLET.sub("", line)
        if cleaned:
            points.append(cleaned)
    return points or [final_answer.strip()]


def answer_hash(final_answer: str) -> str:
    """作答版本指纹：归一化空白后取 sha256，用于区分不同作答版本的诊断归属。"""
    return hashlib.sha256("".join((final_answer or "").split()).encode("utf-8")).hexdigest()[:16]


def _build_payload(session_row, final_answer: str) -> dict:
    materials = json.loads(session_row["materials_json"])
    material_text = "\n".join(m.get("content", "") for m in materials if isinstance(m, dict))
    # 兼容未 JOIN reference_answer 的旧调用方（sqlite3.Row 按列名取值）
    has_ref = "reference_answer" in (session_row.keys() if hasattr(session_row, "keys") else [])
    reference = session_row["reference_answer"] if has_ref else ""
    return {
        "question": session_row["question_stem"],
        "question_type": infer_question_type(session_row["question_stem"]),
        "word_limit": session_row["max_words"],
        "material": [m.get("content", "") for m in materials if isinstance(m, dict)],
        "material_text": material_text,
        "reference_answer": (reference or "").strip(),
        "student_answer": split_answer_points(final_answer),
    }


def _run_one_teacher(teacher_id: str, payload: dict) -> dict | None:
    """运行单个教师的本地阶段：疑点 + 证据包（AI 审查在 apply_semantic_review）。"""
    policies = lib.load_policies(teacher_id)
    if not policies:
        return None

    # 江牧云·文段分析教师范围门禁：严禁公文、大作文、整卷评分、脱离材料编对策等非文段分析任务
    if teacher_id == "teacher_jiangmuyun":
        guard = check_jiangmuyun_boundary(
            question_stem=payload.get("question", ""),
            question_type=payload.get("question_type", ""),
            student_text="\n".join(payload.get("student_answer", [])),
            material_text=payload.get("material_text", "")
        )
        if not guard["allowed"]:
            profile = lib.load_profile(teacher_id)
            c = {
                "teacher_id": teacher_id,
                "teacher_name": profile.get("name", "江牧云·文段分析"),
                "training_targets": [],
                "followups": [],
                "strength": [],
                "similar_cases": [],
                "referenced_question_cases": [],
                "matched_policies": [],
                "suspicions": [],
                "evidence_pack": {
                    "compat_note": guard["message"]
                },
                "coach_note": guard["message"],
                "dismissed": [],
                "review_audit": [],
                "give_full_answer": False,
                "suppressed_duplicates": 0,
                "teacher": profile.get("name", "江牧云·文段分析"),
                "out_of_scope_rejected": True,
                "rejection_reason": guard["reason"],
                "material_summary": {
                    "summary_sentence_count": 0,
                    "descriptive_sentence_count": 0,
                    "qualifiers": [],
                    "material_hotwords": [],
                },
            }
            return c

    payload = {**payload, "teacher_id": teacher_id}
    g = grade(payload, policies, lib.load_question_cases(teacher_id), lib.load_critique_cases(teacher_id))
    profile = lib.load_profile(teacher_id)
    targets = provisional_targets_from_suspicions(g["suspicions"])
    c = {
        "teacher_id": teacher_id,
        "teacher_name": profile.get("name", teacher_id),
        "training_targets": targets[:2],
        "followups": targets[2:],
        "strength": [{"point": s["point"], "basis": s["basis"]} for s in g["strength"]],
        "similar_cases": g["similar_cases"],
        "referenced_question_cases": g["referenced_question_cases"],
        "matched_policies": g["matched_policies"],
        "suspicions": g["suspicions"],
        "evidence_pack": g["evidence_pack"],
        "coach_note": coach_note_for(targets, g["evidence_pack"].get("compat_note", ""), reviewed=False),
        "dismissed": [],
        "review_audit": [],
        "give_full_answer": False,
        "suppressed_duplicates": 0,
        "teacher": profile.get("name", "飞扬老师"),
    }
    c["material_summary"] = {
        "summary_sentence_count": len(g["material_analysis"].get("summary_sentences", [])),
        "descriptive_sentence_count": len(g["material_analysis"].get("descriptive_sentences", [])),
        "qualifiers": g["material_analysis"].get("all_qualifiers", []),
        "material_hotwords": g["material_analysis"].get("material_hotwords", []),
    }
    return c


def _persist(db, session_id: str, c: dict, question_type: str, answer_hash_val: str,
             review_status: str, answer_text: str = "") -> str:
    now_iso = datetime.now(timezone.utc).isoformat()
    did = str(uuid4())
    effective_status = "rejected_out_of_scope" if c.get("out_of_scope_rejected") else review_status
    db.execute(
        '''INSERT INTO shenlun_teacher_diagnoses
           (id, session_id, engine_version, teacher_name, question_type,
            training_targets_json, followups_json, strengths_json,
            matched_policies_json, similar_cases_json, coach_note,
            material_summary_json, created_at, teacher_id,
            suspicions_json, evidence_json, ai_review_json, review_status, answer_hash, answer_text)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
        (
            did,
            session_id,
            ENGINE_VERSION,
            c.get("teacher", c["teacher_id"]),
            question_type,
            json.dumps(c.get("training_targets", []), ensure_ascii=False),
            json.dumps(c.get("followups", []), ensure_ascii=False),
            json.dumps(c.get("strength", []), ensure_ascii=False),
            json.dumps(c.get("matched_policies", []), ensure_ascii=False),
            json.dumps(c.get("similar_cases", []), ensure_ascii=False),
            c.get("coach_note", ""),
            json.dumps(c.get("material_summary", {}), ensure_ascii=False),
            now_iso,
            c["teacher_id"],
            json.dumps(c.get("suspicions", []), ensure_ascii=False),
            json.dumps(c.get("evidence_pack", {}), ensure_ascii=False),
            json.dumps(c.get("ai_review", {}), ensure_ascii=False),
            effective_status,
            answer_hash_val,
            answer_text,
        ),
    )
    c["id"] = did
    c["created_at"] = now_iso
    c["review_status"] = effective_status
    return did


def run_teacher_diagnosis(db, session_row, final_answer: str) -> dict | None:
    """对申论会话执行全部教师的本地疑点检测并逐教师持久化。

    重试去重与选择性执行：
    - 同一作答版本（answer_hash 相同）已有成功审查记录（reviewed / legacy）时直接复用，
      包括其当前有效修订、撤回状态和相关历史，不新建记录、不重新执行已成功环节；
    - 某位教师审查失败（unavailable）时，仅重试该失败教师，将其置回 pending；
    - 尚在处理中（pending）时复用现有记录，不启动重复任务；
    - 用户修改作答（answer_hash 改变）时，按新版本正常生成诊断，旧版本历史完整保留。
    """
    try:
        payload = _build_payload(session_row, final_answer)
        ahash = answer_hash(final_answer)

        teacher_ids = lib.list_teachers() or [lib.DEFAULT_TEACHER]
        outs = []
        for tid in teacher_ids:
            try:
                # 检查该教师对该会话的最新诊断
                existing_row = db.execute(
                    '''SELECT * FROM shenlun_teacher_diagnoses
                       WHERE session_id=? AND teacher_id=?
                       ORDER BY created_at DESC, id DESC LIMIT 1''',
                    (session_row["id"], tid),
                ).fetchone()

                # 情况 1：同一会话同一作答版本
                if existing_row is not None and existing_row["answer_hash"] == ahash:
                    st = existing_row["review_status"]
                    if st in ("reviewed", "legacy"):
                        # 已成功审查：复用当前有效版本（保留已有异议修订与撤回状态）
                        folded = effective_targets(db, session_row["id"], tid, existing_row)
                        d_dict = _row_to_diag(existing_row)
                        out = _strip_internal(d_dict)
                        out["training_targets"] = [t for t in folded if t.get("group") == "top"]
                        out["followups"] = [t for t in folded if t.get("group") == "rest"]
                        out["question_type"] = payload["question_type"]
                        out["engine_version"] = existing_row["engine_version"]
                        outs.append(out)
                        continue
                    elif st == "pending":
                        # 处理中：复用现有 pending 记录，不生成重复行
                        d_dict = _row_to_diag(existing_row)
                        out = _strip_internal(d_dict)
                        out["question_type"] = payload["question_type"]
                        out["engine_version"] = existing_row["engine_version"]
                        outs.append(out)
                        continue
                    elif st == "unavailable":
                        # 此前失败：重试仅将该失败教师置回 pending，供审查重新执行
                        db.execute(
                            "UPDATE shenlun_teacher_diagnoses SET review_status='pending' WHERE id=?",
                            (existing_row["id"],),
                        )
                        d_dict = _row_to_diag(existing_row)
                        d_dict["review_status"] = "pending"
                        out = _strip_internal(d_dict)
                        out["question_type"] = payload["question_type"]
                        out["engine_version"] = existing_row["engine_version"]
                        outs.append(out)
                        continue

                # 情况 2：新提交或作答版本已修改 -> 正常生成新版本诊断行
                c = _run_one_teacher(tid, payload)
                if not c:
                    continue
                # 批改闭环：与该教师上一轮诊断对比验证 + 累积错误轨迹（按当前有效状态统计）
                answer_points = payload["student_answer"]
                c["revision_check"] = _verify_revision(db, session_row["id"], tid, answer_points)
                c["error_timeline"] = _error_timeline(db, session_row["id"], tid)
                _persist(db, session_row["id"], c, payload["question_type"], ahash, "pending",
                         answer_text=final_answer or "")
                out = _strip_internal(c)
                out["question_type"] = payload["question_type"]
                out["engine_version"] = ENGINE_VERSION
                outs.append(out)
            except Exception:
                continue  # 单教师引擎失败不影响其他教师与主流程

        if not outs:
            return None
        if len(outs) == 1:
            return outs[0]
        return {**outs[0], "teachers": outs}
    except Exception:
        return None


def _strip_internal(c: dict) -> dict:
    """返回给调用方/前端时剥去大体量内部字段（疑点与证据包已落库，可按需查询）。"""
    return {k: v for k, v in c.items() if k not in ("suspicions", "evidence_pack", "ai_review")}


# ---------- AI 语义审查 + 程序核验 ----------

_STATUS_PRIORITY = {"high": 3, "medium": 2, "low": 1}


def _verify_review_items(review, suspicions: list[dict], pack: dict, payload: dict) -> dict:
    """程序核验 AI 批改输出：负责数据真实性与一致性，不替代模型判断。

    底线（程序保留）：
    - 展示为原文的引文必须能定位回本题材料/作答（程序取回原始片段，附所在分句）；
      定位不到的"引文"转为模型概括说明，不冒充原文；
    - 教师来源必须真实属于该教师的证据包，虚构来源剔除并记录；
    - 材料缺失或模型自评证据不足时不得标"教师方法支持"。

    状态语义（放松后的设计）：
    - supported：教师方法支持（refs 合法）——结论判断仍来自模型；
    - ai_analysis：基于本题的 AI 分析（无教师方法引用），不归为老师说过的话；
    - pending：保留用于历史兼容与特殊降级。
    局部引用、漏点（无 user_quote）、合理概括不再被机械拦截。
    """
    answer_text = "\n".join(payload["student_answer"])
    material_text = payload.get("material_text", "")
    material_missing = not material_text.strip()
    suspicion_by_id = {s["suspicion_id"]: s for s in suspicions}
    sufficient = bool(getattr(review, "evidence_sufficient", True))

    items: list[dict] = []
    dismissed: list[dict] = []
    audit: list[dict] = []

    def _build_item(source, *, from_suspicion: bool, seq: int) -> dict | None:
        sid = (getattr(source, "suspicion_id", "") or "").strip()
        verdict = getattr(source, "verdict", "confirmed")

        # 机械提醒裁决：模型明确驳回且提醒编号有效 → 记为已排除
        if from_suspicion and sid and sid in suspicion_by_id and verdict == "rejected":
            s = suspicion_by_id[sid]
            dismissed.append({
                "suspicion_id": sid, "type": s["type"], "student_span": s["student_span"],
                "reason": source.problem or "经核查疑点不成立",
            })
            return None
        # 模型未回应的机械提醒不生成条目（提醒仅参考）；编号无效时按模型新意见处理
        if from_suspicion and sid and sid not in suspicion_by_id:
            from_suspicion = False

        label = sid or f"finding#{seq}"

        # 用户原句：提供了则尝试定位；定位到 → 程序片段；定位不到 → 模型转述（不冒充原文）
        uq = (source.user_quote or "").strip()
        user_loc = locate_quote(uq, answer_text) if uq else None
        if user_loc and user_loc["status"] == "verbatim":
            user_quote_final = user_loc["spans"][0]
            user_quote_state = "verbatim"
        elif uq:
            user_quote_final = uq
            user_quote_state = "paraphrase"
        else:
            user_quote_final = ""
            user_quote_state = "empty"  # 漏点类问题没有"用户原句"，属正常

        # 材料引文：逐字定位；定位不到 → 转为概括说明
        mq = (source.material_quote or "").strip()
        if mq:
            mat_loc = locate_quote(mq, material_text)
        else:
            mat_loc = None
        if mat_loc and mat_loc["status"] == "verbatim":
            mat_state = "verbatim_partial" if mat_loc.get("partial") else "verbatim"
            material_quote_final = "……".join(mat_loc["spans"])
            material_clause = "；".join(mat_loc.get("clauses", [])) if mat_state == "verbatim_partial" else ""
        else:
            mat_state = "not_found"
            material_quote_final = ""
            material_clause = ""
        material_point = (source.material_point or "").strip()
        if mq and mat_state == "not_found":
            material_point = (f"模型概括（未定位为原文）：{mq}" + ("；" + material_point if material_point else "")).strip()

        # 教师来源核验：虚构剔除并记录
        valid_refs, invalid_refs = verify_refs(
            [r.model_dump() if hasattr(r, "model_dump") else r for r in (source.refs or [])], pack
        )
        for bad in invalid_refs:
            audit.append({"target": bad["ref"], "reason": f"引用被拒绝：{bad['reason']}"})
        teacher_basis = [{**r, "applicability": source.applicability} for r in valid_refs]

        # 状态：教师方法支持 / 基于本题的 AI 分析
        # evidence_sufficient=false（模型自评证据不足）或材料缺失时，不得标"教师方法支持"。
        if teacher_basis and not material_missing and sufficient:
            status = "supported"
            status_note = "教师方法支持此分析；结论判断来自模型审查，程序核验的是引文与来源的真实性。"
        elif teacher_basis and (material_missing or not sufficient):
            status = "ai_analysis"
            status_note = "教师方法初步分析（材料缺失或模型自评证据不足，无法完整核对依据），供参考。"
        else:
            status = "ai_analysis"
            if material_missing:
                status_note = "基于本题的 AI 分析（材料缺失，无法核对材料引文），不代表教师原话。"
            elif not sufficient:
                status_note = "基于本题的 AI 分析（模型评估材料/证据不足，不确定处见说明），不代表教师原话。"
            else:
                status_note = "基于本题的 AI 分析（该教师检索资料中未找到直接方法依据），不代表教师原话。"

        problem = source.problem
        if from_suspicion and verdict == "revised" and sid in suspicion_by_id:
            problem = problem or suspicion_by_id[sid]["detail"]

        return {
            "target_key": sid if (from_suspicion and sid) else f"F{seq}",
            "status": status,
            "severity": source.severity,
            "check_kind": suspicion_by_id[sid]["type"] if (from_suspicion and sid in suspicion_by_id) else "AI_FINDING",
            "type": suspicion_by_id[sid]["type"] if (from_suspicion and sid in suspicion_by_id) else "AI_FINDING",
            "user_quote": user_quote_final,
            "user_quote_state": user_quote_state,
            "material_quote": material_quote_final,
            "material_quote_verified": mat_state in ("verbatim", "verbatim_partial"),
            "material_clause": material_clause,
            "material_point": material_point,
            "teacher_basis": teacher_basis,
            "policy_ref": teacher_basis[0]["ref"] if teacher_basis else "",
            "policy_name": teacher_basis[0]["title"] if teacher_basis else "",
            "problem": problem,
            "suggested_fix": source.suggested_fix or "",
            "suspicion_id": sid if from_suspicion else "",
            "verify": suspicion_by_id[sid].get("verify") if (from_suspicion and sid in suspicion_by_id) else None,
            "verification": {
                "user_quote": user_quote_state,
                "material_quote": mat_state,
                "refs": "valid" if teacher_basis else ("invalid" if source.refs else "none"),
            },
            "status_note": status_note,
            "basis_label": "教师方法支持" if status == "supported" else "AI 分析（本题）",
        }

    for seq, it in enumerate(review.items, 1):
        built = _build_item(it, from_suspicion=True, seq=seq)
        if built:
            items.append(built)
    for seq, f in enumerate(review.findings, 1):
        built = _build_item(f, from_suspicion=False, seq=seq)
        if built:
            items.append(built)

    sev = {"high": 3, "medium": 2, "low": 1}
    items.sort(key=lambda x: (-sev.get(x["severity"], 0), x["status"] != "supported"))
    # 未被模型采纳的机械提醒记入审计（追溯，不进用户列表）
    handled = {i["suspicion_id"] for i in items if i.get("suspicion_id")} | {d["suspicion_id"] for d in dismissed}
    for s in suspicions:
        if s["suspicion_id"] not in handled:
            audit.append({"target": s["suspicion_id"], "reason": "本地机械提醒未被采纳（模型独立判断未沿用），仅供参考不进结论"})
    return {"items": items, "dismissed": dismissed, "audit": audit, "evidence_sufficient": sufficient}


def _update_targets_from_review(c: dict, verified: dict, note: str) -> None:
    """用核验后的条目重排训练目标（最值得改的在前），其余进 followups。"""
    items = verified["items"]
    ranked = sorted(
        items,
        key=lambda x: (
            -_STATUS_PRIORITY.get(x["severity"], 0),
            0 if x["status"] == "supported" else (1 if x["status"] == "pending" else 2),
        ),
    )
    c["training_targets"] = ranked[:2]
    c["followups"] = ranked[2:]
    c["dismissed"] = verified["dismissed"]
    c["review_audit"] = verified["audit"]
    c["coach_note"] = note


_in_progress_reviews: set[tuple[str, str, str]] = set()  # (session_id, teacher_id, answer_hash)


async def apply_semantic_review(db, session_id: str, final_answer: str | None = None) -> int:
    """对会话内 pending 状态的最新诊断执行 AI 语义审查 + 程序核验，更新诊断行。

    重试去重与串版防护：
    - 仅审查与 final_answer 对应（answer_hash 匹配）且状态为 pending 的诊断行；
    - 已成功审查（reviewed/legacy）的教师不重复执行审查；
    - _in_progress_reviews 集合对并发/双击重复请求去重，不重复启动审查任务；
    - 审查完成写回前复核当前作答版本，若期间用户已提交新作答则放弃写回。
    """
    sess = db.execute(
        '''SELECT s.*, m.question_stem, m.max_words, m.materials_json, m.reference_answer
           FROM shenlun_sessions s JOIN shenlun_materials m ON m.id=s.material_id
           WHERE s.id=?''',
        (session_id,),
    ).fetchone()
    if sess is None:
        return 0
    answer = final_answer if final_answer is not None else (sess["final_answer"] or "")
    payload = _build_payload(sess, answer)
    ahash = answer_hash(answer)

    rows = db.execute(
        '''SELECT * FROM shenlun_teacher_diagnoses
           WHERE session_id=? AND review_status='pending' AND answer_hash=?
           AND created_at = (
               SELECT MAX(created_at) FROM shenlun_teacher_diagnoses s2
               WHERE s2.session_id = shenlun_teacher_diagnoses.session_id
                 AND s2.teacher_id = shenlun_teacher_diagnoses.teacher_id
           )''',
        (session_id, ahash),
    ).fetchall()

    async def _review_row(row):
        tid = row["teacher_id"]
        task_key = (session_id, tid, ahash)
        if task_key in _in_progress_reviews:
            return False  # 已在处理中，去重避免重复调用
        _in_progress_reviews.add(task_key)
        try:
            if row["answer_hash"] and row["answer_hash"] != ahash:
                return False  # 版本不匹配：保持 pending，不写回该诊断行
            # 江牧云·文段分析教师范围门禁：严禁越界任务调用模型审查
            if tid == "teacher_jiangmuyun":
                guard = check_jiangmuyun_boundary(
                    question_stem=payload.get("question", ""),
                    question_type=payload.get("question_type", ""),
                    student_text="\n".join(payload.get("student_answer", [])),
                    material_text=payload.get("material_text", "")
                )
                if not guard["allowed"]:
                    db.execute(
                        "UPDATE shenlun_teacher_diagnoses SET review_status='rejected_out_of_scope', coach_note=?, ai_review_json=? WHERE id=?",
                        (guard["message"], json.dumps({"note": guard["message"], "rejected": True}, ensure_ascii=False), row["id"]),
                    )
                    return True
            suspicions = json.loads(row["suspicions_json"] or "[]")
            pack = json.loads(row["evidence_json"] or "{}")
            review = await review_answer(payload, pack, suspicions)
            if review is None:
                db.execute(
                    "UPDATE shenlun_teacher_diagnoses SET review_status='unavailable', ai_review_json=? WHERE id=?",
                    (json.dumps({"note": "AI 语义审查不可用或输出不合规，以下为疑点待确认，不作为已支持结论"}, ensure_ascii=False), row["id"]),
                )
                return False
            verified = _verify_review_items(review, suspicions, pack, payload)
            had_proposals = bool(review.items or review.findings)
            all_proposals_rejected = had_proposals and (not verified["items"] and not verified["dismissed"])
            if all_proposals_rejected:
                db.execute(
                    "UPDATE shenlun_teacher_diagnoses SET review_status='unavailable', ai_review_json=? WHERE id=?",
                    (json.dumps({"note": "AI 审查输出未通过程序核验（原句定位/材料引文/来源 ID），已整体拒绝，以下为疑点待确认"}, ensure_ascii=False), row["id"]),
                )
                return False

            # 模型调用后复核版本：若审查期间用户提交了新作答，旧结果不写回，避免覆盖新版本
            sess_now = db.execute('SELECT final_answer FROM shenlun_sessions WHERE id=?', (session_id,)).fetchone()
            if sess_now and sess_now['final_answer'] and answer_hash(sess_now['final_answer']) != ahash:
                return False

            c = {"training_targets": [], "followups": [], "dismissed": [], "review_audit": [], "coach_note": ""}
            teacher_name = lib.load_profile(row["teacher_id"]).get("name", row["teacher_id"])
            note = coach_note_for(verified["items"], pack.get("compat_note", ""), reviewed=True)
            _update_targets_from_review(c, verified, note)
            ai_review_blob = {
                "teacher_name": teacher_name,
                "evidence_sufficient": verified["evidence_sufficient"],
                "review": review.model_dump(),
                "verified": verified,
            }
            db.execute(
                '''UPDATE shenlun_teacher_diagnoses
                   SET training_targets_json=?, followups_json=?, ai_review_json=?,
                       review_status='reviewed', coach_note=?
                   WHERE id=?''',
                (
                    json.dumps(c["training_targets"], ensure_ascii=False),
                    json.dumps(c["followups"], ensure_ascii=False),
                    json.dumps(ai_review_blob, ensure_ascii=False),
                    c["coach_note"],
                    row["id"],
                ),
            )
            return True
        except Exception:
            db.execute(
                "UPDATE shenlun_teacher_diagnoses SET review_status='unavailable' WHERE id=? AND review_status='pending'",
                (row["id"],),
            )
            return False
        finally:
            _in_progress_reviews.discard(task_key)

    # 各教师并行审查（互不阻塞；sqlite 写回在事件循环线程内顺序执行）
    results = await asyncio.gather(*(_review_row(row) for row in rows))
    reviewed = sum(1 for ok in results if ok)
    return reviewed


# ---------- 异议修订（当前有效版本） ----------

def load_revisions(db, session_id: str, teacher_id: str) -> dict[str, dict[str, list[dict]]]:
    """该会话该教师的修订记录：{diagnosis_id: {target_key: [revision,...按时间升序]}}。"""
    rows = db.execute(
        '''SELECT * FROM shenlun_target_revisions
           WHERE session_id=? AND teacher_id=? ORDER BY created_at ASC, rowid ASC''',
        (session_id, teacher_id),
    ).fetchall()
    out: dict[str, dict[str, list[dict]]] = {}
    for r in rows:
        d = dict(r)
        d["revised"] = json.loads(d.pop("revised_json") or "{}")
        out.setdefault(d["diagnosis_id"], {}).setdefault(d["target_key"], []).append(d)
    return out


def fold_revisions(targets: list[dict], revisions: list[dict]) -> list[dict]:
    """把某诊断的条目折叠为其当前有效版本（原始记录不动，只在本函数输出中折叠）。

    语义（按修订表时间+写入顺序依次应用，即调用方传入的列表顺序）：
    - maintain：保持当前有效状态与内容不变（不恢复原始诊断）；
    - adjust：基于当前有效版本更新 problem/suggested_fix（留空字段保留当前值），
      不改变核验状态（不把 pending 升级为 supported）；
    - withdraw：置为 withdrawn——终态，后续 maintain/adjust 不自动复活；
      若产品未来支持恢复，必须使用显式 restore 操作并重新核验。
    """
    current: dict[str, dict] = {}
    order: list[str] = []
    for t in targets or []:
        key = t.get("target_key", "")
        if key in current:
            continue
        current[key] = dict(t)
        order.append(key)
    for rev in revisions or []:
        key = rev.get("target_key", "")
        if key not in current:
            continue  # 修订指向未知条目：不入当前有效版本（保留在修订表历史中）
        cur = current[key]
        action = rev.get("action", "")
        reason = rev.get("reason", "")
        source = rev.get("source", "ai")
        if action == "withdraw":
            cur["status"] = "withdrawn"
            cur["revision_note"] = reason or "经复核撤回"
            cur["revised_by"] = source
        elif action == "adjust":
            if cur.get("status") == "withdrawn":
                continue  # 已撤回条目不因 adjust 复活
            revised = rev.get("revised", {}) or {}
            if isinstance(revised.get("version"), dict):
                # 完整新版本（问题/原句/依据/核验/状态一体，写入时已核验生成）：
                # 键存在即显式应用，区分"保留"与"清除"，不残留旧字段
                for k, v in revised["version"].items():
                    cur[k] = v
            else:
                # 旧版修订（仅 problem/suggested_fix），保持向后兼容
                if revised.get("problem"):
                    cur["problem"] = revised["problem"]
                if revised.get("suggested_fix"):
                    cur["suggested_fix"] = revised["suggested_fix"]
            cur["revision_note"] = reason or cur.get("revision_note", "")
            cur["revised_by"] = source
            cur["adjusted"] = True
        elif action == "maintain":
            # 保持当前有效状态与内容，只记录复核轨迹
            cur["revision_note"] = reason or cur.get("revision_note", "")
            cur["revised_by"] = source
    return [current[k] for k in order]


def active_targets(folded: list[dict]) -> list[dict]:
    """当前有效（未被撤回）的问题条目。全部撤回时返回空列表，不回退原始条目。"""
    return [t for t in folded or [] if t.get("status") != "withdrawn"]


def effective_targets(db, session_id: str, teacher_id: str, diagnosis_row=None) -> list[dict]:
    """统一的"当前有效诊断"读取方法。

    页面展示、普通追问、异议复核、统计均复用本方法，保证四处一致：
    取诊断行的原始条目（training_targets + followups），按修订表折叠为当前有效版本。
    旧记录（无 target_key）按索引补齐以保证修订可寻址。
    """
    if diagnosis_row is None:
        diagnosis_row = db.execute(
            '''SELECT * FROM shenlun_teacher_diagnoses
               WHERE session_id=? AND teacher_id=?
               ORDER BY created_at DESC, id DESC LIMIT 1''',
            (session_id, teacher_id),
        ).fetchone()
    if diagnosis_row is None:
        return []
    targets: list[dict] = []
    for group in ("training_targets_json", "followups_json"):
        try:
            group_items = json.loads(diagnosis_row[group] or "[]")
        except Exception:
            group_items = []
        for i, t in enumerate(group_items):
            t = {**t, "group": "top" if group == "training_targets_json" else "rest"}
            t.setdefault("target_key", f"{group[:2].upper()}{i}")
            targets.append(t)
    rev_map = load_revisions(db, session_id, teacher_id).get(diagnosis_row["id"], {})
    revs = [r for k in (t.get("target_key", "") for t in targets) for r in rev_map.get(k, [])]
    return fold_revisions(targets, revs)


# ---------- 闭环验证与统计 ----------

def _verify_revision(db, session_id: str, teacher_id: str, answer_points: list[str]) -> dict:
    """批改闭环：用上一轮训练目标里挂的 verify 标志，检查新一轮作答是否真的改了。
    基于上一轮诊断的"当前有效版本"（折叠修订后），已撤回目标不进入验证。"""
    prev_row = db.execute(
        '''SELECT * FROM shenlun_teacher_diagnoses
           WHERE session_id=? AND teacher_id=?
           ORDER BY created_at DESC, id DESC LIMIT 1''',
        (session_id, teacher_id),
    ).fetchone()
    if not prev_row:
        return {"has_previous": False, "checks": [], "summary": ""}

    # 当前有效版本（含修订与撤回状态）
    prev_targets = [t for t in effective_targets(db, session_id, teacher_id, prev_row)
                    if t.get("status") != "withdrawn"]

    new_text = "".join(answer_points)
    checks = []
    for t in prev_targets:
        v = t.get("verify") or {}
        kind, needle = v.get("kind"), (v.get("needle") or "").strip()
        entry = {"type": t.get("type", ""), "policy_name": t.get("policy_name", "")}
        if not kind or not needle:
            entry.update({"status": "unverifiable", "note": "该问题类型暂无可自动验证的标志"})
        elif kind == "span_absent":
            thr = max(6, int(v.get("threshold", 8)))
            remain = lcs_nopunct(needle, new_text)
            if remain < thr:
                entry.update({"status": "addressed", "note": "原照抄片段已从新作答中移除"})
            else:
                entry.update({"status": "not_addressed", "note": f"原照抄片段仍残留（重合约 {remain} 字）"})
        elif kind == "word_absent":
            if needle not in new_text:
                entry.update({"status": "addressed", "note": f"“{needle}”已从新作答中删去"})
            else:
                entry.update({"status": "not_addressed", "note": f"“{needle}”仍出现在新作答中"})
        elif kind == "word_present":
            if needle in new_text:
                entry.update({"status": "addressed", "note": f"限定词“{needle}”已补回"})
            else:
                entry.update({"status": "not_addressed", "note": f"限定词“{needle}”仍未保留"})
        elif kind == "any_present":
            needles = v.get("needles", [])
            if any(n in new_text for n in needles):
                entry.update({"status": "addressed", "note": "已检出对比结构标记（原来/现在）"})
            else:
                entry.update({"status": "not_addressed", "note": "仍未检出对比结构标记"})
        else:
            entry.update({"status": "unverifiable", "note": "未知验证类型"})
        checks.append(entry)

    addressed = sum(1 for c in checks if c["status"] == "addressed")
    not_addressed = sum(1 for c in checks if c["status"] == "not_addressed")
    unverifiable = sum(1 for c in checks if c["status"] == "unverifiable")
    summary = (
        f"上一轮训练目标 {len(checks)} 项：已改 {addressed}、未改 {not_addressed}"
        + (f"、暂不可自动验证 {unverifiable}" if unverifiable else "")
    )
    return {"has_previous": True, "checks": checks, "summary": summary}


def _error_timeline(db, session_id: str, teacher_id: str) -> dict:
    """该会话内该教师历史诊断的错误类型累积（不含本轮）。

    统计口径（与页面/追问/复核共用 effective_targets，保持一致）：
    - 只计入"当前有效且已确认"的问题：status 缺失（旧记录）或 status='supported'；
    - pending 疑点（含审查不可用时的降级条目）不计为已确认错误；
    - 已撤回问题不计数，且不因后续 maintain 复活（fold_revisions 保证）。
    """
    rows = db.execute(
        '''SELECT * FROM shenlun_teacher_diagnoses
           WHERE session_id=? AND teacher_id=? ORDER BY created_at ASC, id ASC''',
        (session_id, teacher_id),
    ).fetchall()
    counts: dict[str, int] = {}
    for r in rows:
        for t in effective_targets(db, session_id, teacher_id, r):
            if t.get("status") == "withdrawn":
                continue
            status = t.get("status")
            if status not in (None, "", "supported"):
                continue  # pending / suggestion 不是已确认错误
            counts[t.get("type", "?")] = counts.get(t.get("type", "?"), 0) + 1
    return {
        "previous_diagnoses": len(rows),
        "counts": dict(sorted(counts.items(), key=lambda x: -x[1])),
    }


def _row_to_diag(row) -> dict:
    d = dict(row)
    for key in (
        "training_targets_json",
        "followups_json",
        "matched_policies_json",
        "similar_cases_json",
        "material_summary_json",
        "suspicions_json",
        "evidence_json",
    ):
        if key in d.keys():
            d[key.replace("_json", "")] = json.loads(d.pop(key) or ("{}" if key == "evidence_json" else "[]"))
    if "strengths_json" in d.keys():
        d["strength"] = json.loads(d.pop("strengths_json") or "[]")
    if "ai_review_json" in d.keys():
        d["ai_review"] = json.loads(d.pop("ai_review_json") or "{}")
    return d


def get_latest_teacher_diagnosis(db, session_id: str) -> dict | None:
    """返回该会话每位教师的最新诊断（已折叠异议修订为当前有效版本）。

    单教师 → 单个诊断 dict（兼容旧前端结构）；多教师 → 主教师 dict 附 teachers 列表。
    旧记录（review_status='legacy'）仍可读，其条目无 target_key 时按索引补齐。
    """
    rows = db.execute(
        '''SELECT * FROM shenlun_teacher_diagnoses
           WHERE session_id=? AND created_at = (
               SELECT MAX(created_at) FROM shenlun_teacher_diagnoses s2
               WHERE s2.session_id = shenlun_teacher_diagnoses.session_id
                 AND s2.teacher_id = shenlun_teacher_diagnoses.teacher_id
           )
           ORDER BY teacher_id ASC, created_at DESC''',
        (session_id,),
    ).fetchall()
    # 同一教师同一时刻可能有多行（重提交），按 teacher_id 去重取 created_at 最新
    latest_by_teacher: dict[str, dict] = {}
    for row in rows:
        d = _row_to_diag(row)
        tid = d.get("teacher_id") or "teacher_feiyang"
        if tid not in latest_by_teacher or d["created_at"] > latest_by_teacher[tid]["created_at"]:
            latest_by_teacher[tid] = d
    if not latest_by_teacher:
        return None
    outs = []
    for tid, d in latest_by_teacher.items():
        # 统一读取方法：原始条目按修订表折叠为当前有效版本（含 group 元数据）
        row = db.execute('SELECT * FROM shenlun_teacher_diagnoses WHERE id=?', (d["id"],)).fetchone()
        folded = effective_targets(db, session_id, tid, row)
        d["training_targets"] = [t for t in folded if t.get("group") == "top"]
        d["followups"] = [t for t in folded if t.get("group") == "rest"]
        outs.append(d)
    if len(outs) == 1:
        return outs[0]
    return {**outs[0], "teachers": outs}
