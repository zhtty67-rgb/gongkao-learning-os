# -*- coding: utf-8 -*-
"""教师追问与异议重审服务：申论会话内，以指定教师的规则库 + 课堂案例 + 范文语料为依据。

两种模式（共用同一份本题上下文准备 build_followup_context）：
1. 一般追问：LLM 以教师教学体系为依据答疑（代言模式），只引用检索到的规则/案例并标注出处；
   引用列表只收录回复中实际采用（[n] 标注）且经检查的依据，检索候选不自动算作已引用。
2. 异议重审：带本题材料、当前作答、原诊断与原依据重新审查，可维持/调整/撤回。
   每种决定有最小依据门槛（虚构引用必须拒绝）；决定写入 shenlun_target_revisions
   （诊断原始行不动，读取时按 service.effective_targets 折叠为当前有效版本）。

铁律：LLM 只做"有依据的判断"，不当"无据的教师"——
所有判断性内容必须来自检索到的规则/案例/语料并标注稳定来源 ID；
检索不到依据时必须明说"当前检索资料中未找到相关依据"，严禁编造教师观点。
本服务产出的是依据教师资料的辅助反馈，不是教师本人批改，也不是官方评分。
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field

from ...ai import Message, get_model_gateway
from ...ai.schemas import StrictModel
from .engine import library as lib
from .engine.boundary_guard import check_jiangmuyun_boundary
from .engine.evidence import locate_quote, verify_refs
from .engine.retriever import Retriever
from .engine.semantic_review import ReviewRef
from .service import answer_hash, effective_targets

CORPUS_NAME = "corpus_fanwen_baipian.txt"
CHUNK_SIZE = 700
# OCR 页眉水印行（站长课程广告），切块前剔除
_WATERMARK = re.compile(r"微博|小红书|B站|抖音|cctalk|公众号|淘宝|QQ|站长爱申论|申论大本营")

_corpus_cache: dict = {"mtime": None, "chunks": None, "retriever": None}

# 异议触发词（保守匹配；仅在 intent='auto' 时使用，显式 intent 优先）
_OBJECTION_MARKERS = [
    "为什么错", "为什么算", "为什么说", "不对吧", "不是这样", "不是这么", "没有讲过", "没讲过",
    "误判", "判错了", "冤枉", "我的意思是", "我不是这个意思", "这不算", "不算错", "没问题",
    "没错", "有依据", "材料里有", "材料中提到", "老师不是", "你搞错", "搞错了", "怎么就",
]


def resolve_intent(question: str, intent: str = "auto") -> str:
    """决定追问走哪种模式。显式 intent（前端异议入口）优先于关键词启发式。"""
    if intent in ("objection", "question"):
        return intent
    q = question or ""
    return "objection" if any(m in q for m in _OBJECTION_MARKERS) else "question"


def is_objection(question: str) -> bool:
    """兼容旧调用：关键词启发式判断。"""
    return resolve_intent(question, "auto") == "objection"


def _corpus_path(teacher_id: str) -> Path:
    return lib.KB_DIR / teacher_id / CORPUS_NAME


def _load_corpus_chunks(teacher_id: str) -> list[str]:
    """懒加载范文语料：按页切分 → 去水印行 → 合并成 ~700 字块。带 mtime 缓存。"""
    path = _corpus_path(teacher_id)
    if not path.exists():
        return []
    mtime = path.stat().st_mtime
    if _corpus_cache["mtime"] == mtime and _corpus_cache["chunks"] is not None:
        return _corpus_cache["chunks"]

    raw = path.read_text(encoding="utf-8")
    pages = re.split(r"=== 第 \d+ 页 ===", raw)
    cleaned_pages = []
    for page in pages:
        lines = [ln for ln in page.splitlines() if ln.strip() and not _WATERMARK.search(ln)]
        cleaned_pages.append("".join(ln.strip() for ln in lines))
    chunks, buf = [], ""
    for page in cleaned_pages:
        if not page:
            continue
        buf += page
        while len(buf) >= CHUNK_SIZE:
            chunks.append(buf[:CHUNK_SIZE])
            buf = buf[CHUNK_SIZE:]
    if buf.strip():
        chunks.append(buf)

    _corpus_cache["mtime"] = mtime
    _corpus_cache["chunks"] = chunks
    return chunks


def retrieve_evidence(teacher_id: str, query: str, top_k: int = 6) -> list[dict]:
    """检索该教师的规则、课堂纠错案例与范文语料，返回带出处的证据列表。

    检索前先做领域同义词扩展（口语 → 规则库术语），弥补字面重合缺口。
    返回的是检索候选；只有被回复实际引用（[n]）或通过核验的条目才作为"依据"展示。
    """
    query = lib.expand_query(query)
    evidence = []

    policies = lib.load_policies(teacher_id)
    if policies:
        docs = [lib.build_text_for_retrieval(p) + " " + " ".join(
            s.get("quote", "") for s in p.get("source", [])
        ) for p in policies]
        for idx, score in Retriever(docs).search(query, top_k=top_k):
            p = policies[idx]
            quote = (p.get("source") or [{}])[0].get("quote", "")
            evidence.append({
                "kind": "policy",
                "ref": p["policy_id"],
                "title": p["name"],
                "text": p["rule"],
                "quote": quote[:120],
            })

    cases = lib.load_critique_cases(teacher_id)
    if cases:
        docs = [lib.build_text_for_case(c) for c in cases]
        for idx, score in Retriever(docs).search(query, top_k=4):
            c = cases[idx]
            evidence.append({
                "kind": "case",
                "ref": c["case_id"],
                "title": f"课堂纠错案例：{c['question'][:30]}",
                "text": c["diagnosis"],
                "quote": c["remedy_instruction"][:120],
            })

    q_cases = lib.load_question_cases(teacher_id)
    if q_cases:
        qc_docs = [
            c.get("title", "") + " " + c.get("question_type", "") + " "
            + str((c.get("analysis") if isinstance(c.get("analysis"), dict) else {}).get("core_task", ""))
            for c in q_cases
        ]
        for idx, score in Retriever(qc_docs).search(query, top_k=3):
            qc = q_cases[idx]
            analysis = qc.get("analysis") if isinstance(qc.get("analysis"), dict) else {}
            kps = list(analysis.get("key_points") or [])[:3]
            evidence.append({
                "kind": "question_case",
                "ref": qc["question_id"],
                "title": f"题目案例：{qc.get('title', '')[:30]}",
                "text": f"核心任务：{analysis.get('core_task', '')} 组织方式：{' '.join(str(p) for p in kps)[:100]}",
                "quote": qc.get("teacher_reasoning", "")[:120],
            })

    chunks = _load_corpus_chunks(teacher_id)
    if chunks:
        for idx, score in Retriever(chunks).search(query, top_k=4, min_score=0.08):
            evidence.append({
                "kind": "corpus",
                "ref": f"范文语料#{idx + 1}",
                "title": "《站长申论范文百篇》片段",
                "text": chunks[idx][:500],
                "quote": "",
            })

    return evidence


def _format_evidence(evidence: list[dict]) -> str:
    blocks = []
    for i, e in enumerate(evidence, 1):
        tag = {"policy": "规则", "case": "案例", "corpus": "范文", "question_case": "题目案例"}.get(e["kind"], "资料")
        block = f"[{i}]（{tag} {e['ref']}）{e['title']}：{e['text']}"
        if e.get("quote"):
            block += f"\n    课堂原话：{e['quote']}"
        blocks.append(block)
    return "\n".join(blocks) if blocks else "（无检索结果）"


def _load_current_targets(db, session_id: str, teacher_id: str, diagnosis_row=None) -> list[dict]:
    """当前有效诊断条目（复用 service.effective_targets 统一读取，含修订折叠）。"""
    return effective_targets(db, session_id, teacher_id, diagnosis_row)


def _session_with_material(sess_row) -> dict:
    """会话行 → 附带材料全文的 dict；材料缺失时如实标记。"""
    sess = dict(sess_row)
    materials = json.loads(sess.get("materials_json") or "[]")
    material_text = "\n".join(
        m.get("content", "") for m in materials if isinstance(m, dict) and m.get("content")
    ).strip()
    sess["material_text"] = material_text
    sess["material_available"] = bool(material_text)
    return sess


def build_followup_context(db, sess_row, teacher_id: str, question: str) -> dict:
    """普通追问与异议复核共用的本题上下文准备。

    提供：题干（题目要求）、完整可用材料、当前答案、当前有效诊断（含修订折叠）、
    作答版本标识。复核锚定诊断自带的作答文本（answer_text）——历史诊断可真实复核；
    文本未留存的旧记录如实标记不可核验。材料缺失时 material_available=False。
    """
    sess = _session_with_material(sess_row)
    diag_row = db.execute(
        '''SELECT * FROM shenlun_teacher_diagnoses
           WHERE session_id=? AND teacher_id=?
           ORDER BY created_at DESC, id DESC LIMIT 1''',
        (sess["id"], teacher_id),
    ).fetchone()
    targets = _load_current_targets(db, sess["id"], teacher_id, diag_row) if diag_row else []
    current_answer = sess.get("final_answer") or ""
    current_hash = answer_hash(current_answer)
    diag_hash = diag_row["answer_hash"] if diag_row else ""
    stale = bool(diag_row is not None and diag_hash and diag_hash != current_hash)

    # 复核用的作答文本：优先诊断自带文本（历史版本可真实复核）；
    # 其次哈希与当前作答一致时用当前文本；都不可用则如实标记。
    diag_answer_text = ((diag_row["answer_text"] if diag_row else "") or "").strip()
    if diag_answer_text:
        reexamine_answer_text = diag_answer_text
        version_note = "该诊断对应其生成时的作答版本（文本已随诊断保存），原句按该版本核验。"
        reexamine_answer_available = True
    elif diag_row is not None and diag_hash and diag_hash == current_hash and current_answer.strip():
        reexamine_answer_text = current_answer
        version_note = ""
        reexamine_answer_available = True
    else:
        reexamine_answer_text = ""
        version_note = "该诊断对应版本的作答文本未留存，无法对其原句做逐字核验。"
        reexamine_answer_available = False

    return {
        "session_id": sess["id"],
        "teacher_id": teacher_id,
        "question_stem": sess.get("question_stem", ""),
        "word_limit": sess.get("max_words", ""),
        "material_text": sess["material_text"],
        "material_available": sess["material_available"],
        "answer_text": current_answer or "（见会话记录）",
        "answer_hash": current_hash,
        "reexamine_answer_text": reexamine_answer_text,
        "reexamine_answer_available": reexamine_answer_available,
        "version_note": version_note,
        "targets": targets,
        "active_targets": [t for t in targets if t.get("status") != "withdrawn"],
        "withdrawn_count": sum(1 for t in targets if t.get("status") == "withdrawn"),
        "diagnosis_id": diag_row["id"] if diag_row else "",
        "diagnosis_answer_hash": diag_hash,
        "stale": stale,
    }


def get_teacher_followups(db, session_id: str, teacher_id: str) -> list[dict]:
    rows = db.execute(
        '''SELECT id, teacher_id, role, content, citations_json, kind, target_key, created_at
           FROM shenlun_teacher_followups
           WHERE session_id=? AND teacher_id=?
           ORDER BY created_at ASC, rowid ASC''',
        (session_id, teacher_id),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["citations"] = json.loads(d.pop("citations_json"))
        d.setdefault("kind", "question")
        d.setdefault("target_key", "")
        out.append(d)
    return out


class ReexamineDecision(StrictModel):
    target_key: str = Field(min_length=1)
    action: Literal["maintain", "adjust", "withdraw"]
    reason: str = ""
    revised_problem: str = ""
    revised_fix: str = ""
    refs: list[ReviewRef] = Field(default_factory=list)
    user_quote: str = ""     # 可选：与本决定相关的用户原句（程序会逐字定位）
    material_quote: str = "" # 可选：本题材料原文片段（程序会逐字定位）
    material_point: str = "" # 可选：材料依据的概括说明
    applicability: str = ""  # 可选：所引依据为何适用于本题
    # 依据处理方式（adjust 专用）：replace=以本次核验的新依据替换；keep=保留原依据但必须
    # 重新核验仍适用；clear=清除教师依据（可保留新提供的材料依据）。空字段语义由此显式化。
    basis_mode: Literal["replace", "keep", "clear"] = "replace"


class ReexamineOutput(StrictModel):
    decisions: list[ReexamineDecision] = Field(default_factory=list)
    reply_text: str = ""
    overall_note: str = ""


def _format_targets_for_context(targets: list[dict], max_len: int = 120) -> str:
    """当前有效诊断的完整明细（含条目 ID/状态/问题/原句/材料依据/教师依据/改法/修订说明）。

    超长字段截断并显式标注，不悄悄丢弃；供普通追问与复核上下文复用。
    """
    def _cut(text, n):
        text = (text or "").strip()
        if len(text) <= n:
            return text
        return text[:n] + "…（截断）"

    blocks = []
    for t in targets:
        refs = t.get("teacher_basis") or []
        refs_text = "；".join(f"{r.get('kind', '')}:{r.get('ref', '')} {r.get('title', '')}" for r in refs) or "无"
        lines = [
            f"[{t.get('target_key', '?')}]（状态 {t.get('status', '')}）类型 {t.get('check_kind') or t.get('type', '')}",
            f"    问题：{_cut(t.get('problem') or t.get('reason', ''), max_len * 2)}",
        ]
        if t.get("material_quote"):
            mat_line = f"    材料依据：{_cut(t['material_quote'], max_len)}"
            if t.get("material_clause"):
                mat_line += f"（所在分句：{_cut(t['material_clause'], max_len)}）"
            if t.get("material_point"):
                mat_line += f"（说明：{_cut(t['material_point'], max_len)}）"
            lines.append(mat_line)
        else:
            lines.append("    材料依据：无（未提供可核验的材料引文）")
        lines.append(f"    用户原句：{_cut(t.get('user_quote') or t.get('student_span') or '', max_len)}")
        lines.append(f"    教师依据：{_cut(refs_text, max_len)}")
        lines.append(f"    建议改法：{_cut(t.get('suggested_fix', ''), max_len)}")
        if t.get("revision_note"):
            lines.append(f"    修订说明：{_cut(t.get('revision_note', ''), max_len)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _format_targets_for_review(targets: list[dict]) -> str:
    return "\n".join(
        f"[{t.get('target_key', '?')}]（{t.get('status', '')}）类型 {t.get('check_kind') or t.get('type', '')}\n"
        f"    用户原句：{(t.get('user_quote') or t.get('student_span') or '')[:100]}\n"
        f"    诊断：{t.get('problem') or t.get('reason', '')}\n"
        f"    建议改法：{t.get('suggested_fix', '')}\n"
        f"    现有依据：{json.dumps(t.get('teacher_basis', []) or [], ensure_ascii=False)}"
        for t in targets
    )


def _format_question_cases(question_cases: list[dict]) -> str:
    """题目案例 → 复核上下文块（带稳定 ID，供引用核验）。"""
    blocks = []
    for qc in question_cases or []:
        kps = list(qc.get("key_points") or [])[:4]
        blocks.append(
            f"[题目案例 {qc.get('question_id', '')}]《{qc.get('title', '')}》（{qc.get('question_type', '')}）\n"
            f"    核心任务：{qc.get('core_task', '')}\n"
            + (f"    老师认可的组织方式：{' '.join(kps)[:160]}\n" if kps else "")
            + (f"    老师的推导理由：{qc.get('teacher_reasoning', '')[:120]}" if qc.get("teacher_reasoning") else "")
        )
    return "\n\n".join(blocks)


def _build_reexamine_messages(ctx: dict, teacher_id: str, objection: str, evidence: list[dict],
                              history: list[dict], pack: dict | None = None) -> list[Message]:
    profile = lib.load_profile(teacher_id)
    system_prompt = (
        "你是申论批改的复核审查员，负责回应用户对一次教师辅助诊断的异议。\n"
        "你面前有：本题材料、用户当前作答、原诊断的当前有效条目（含此前修订结果）与重新检索的教师资料。\n\n"
        "【复核原则】\n"
        "1. 逐条核对用户质疑的条目，输出 maintain（维持）/ adjust（调整）/ withdraw（撤回）决定。\n"
        "2. 最小依据要求（程序会逐字核验，达不到则该决定无效）：\n"
        "   - withdraw：必须说明撤回理由，并给出本题事实依据——逐字引用本题材料原文片段"
        "（material_quote 字段）或用户作答原句（user_quote 字段），或引用有效的教师规则 ID；\n"
        "   - maintain：必须引用有效的教师规则 ID，或逐字引用本题材料原文说明为什么原诊断成立；\n"
        "   - adjust：必须给出修改后的问题说明（revised_problem），并关联可定位的用户原句，"
        "外加逐字材料引文或有效教师来源。\n"
        "3. 引用必须逐字：user_quote/material_quote 从原文复制，不要改写任何字词——"
        "否定词、数量词（如“部分/所有”）、范围、时间一字不能动；中间省略用……。"
        "程序会拒绝定位不到原文的引文，被拒绝的决定不会生效。\n"
        "4. 引用教师资料只能使用给出的稳定 ID；检索不到依据时明说"
        "“当前检索资料中未找到相关依据”，不得编造课程、书名或引文。\n"
        "5. 撤回可以不依赖教师引用：纠正误引原文、发现原诊断无依据时，依据本题事实即可撤回。\n"
        "6. 用户对答案的理解可能与你不同：先确认用户的真实意思（结合追问历史），再下结论。\n"
        "7. reply_text 用平实口吻说明复核结果；最终生效哪些决定以程序核验为准，不要宣称未生效的修改。\n"
        "8. 本反馈是依据教师资料生成的辅助复核，不代表教师本人意见，也不是官方评分标准。\n"
        + ("9. 注意：该诊断对应历史作答版本（原句按被复核作答核验），请在 reply_text 开头提醒用户这一点。\n" if ctx.get("stale") else "")
        + "\n你的教学体系约束（引用教师观点时不得违背）：\n"
        + "\n".join(f"- {p}" for p in profile.get("core_principles", []))
    )

    material_block = (
        f"【本题材料】\n{ctx['material_text']}\n\n"
        if ctx.get("material_available")
        else "【本题材料】（缺失：未能读取到本题材料，以下判断无法核对材料引文）\n\n"
    )
    user_prompt = (
        f"【题目】{ctx.get('question_stem', '')}\n\n"
        + material_block
        + f"【被复核作答（该诊断对应版本，原句按此核验）】\n{ctx.get('reexamine_answer_text', '')}\n\n"
        + (f"【用户当前作答（仅作语境参考，不用于核验本诊断）】\n{ctx.get('answer_text', '')}\n\n"
           if ctx.get("stale") else "")
        + f"【原诊断条目（当前有效版本）】\n{_format_targets_for_review(ctx.get('targets', []))}\n\n"
        + (f"【注意】此前已有 {ctx.get('withdrawn_count', 0)} 条被撤回；撤回条目不会自动恢复。\n" if ctx.get("withdrawn_count") else "")
        + f"【重新检索的教师资料】\n{_format_evidence(evidence)}\n\n"
        + (f"【原证据包中的题目案例】（可引用其稳定 ID）\n{_format_question_cases((pack or {}).get('question_cases', []))}\n\n"
           if pack and pack.get("question_cases") else "")
        + f"【用户异议】{objection}"
    )

    from ..student_work_check import STUDENT_WORK_RULE
    system_prompt += STUDENT_WORK_RULE
    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content="以下是我此前的追问记录（如有），供你了解语境。"),
        Message(role="assistant", content="好，我已了解此前讨论。"),
    ]
    for m in history[-6:]:
        messages.append(Message(role=m["role"], content=m["content"]))
    messages.append(Message(role="user", content=user_prompt))
    return messages


async def answer_teacher_followup(db, session_id: str, teacher_id: str, question: str,
                            user_attribution: str = "", intent: str = "auto") -> dict:
    """处理追问：显式 intent 优先；质疑类走异议重审（可维持/调整/撤回），其余走答疑。"""
    clean_question = (question or "").strip()
    if not clean_question:
        raise ValueError("追问内容不能为空")
    if teacher_id not in lib.list_teachers():
        raise ValueError(f"未知教师：{teacher_id}")

    sess_row = db.execute(
        '''SELECT s.*, m.question_stem, m.materials_json FROM shenlun_sessions s
           JOIN shenlun_materials m ON m.id = s.material_id WHERE s.id=?''',
        (session_id,),
    ).fetchone()
    if sess_row is None:
        raise ValueError("申论会话不存在")

    history = get_teacher_followups(db, session_id, teacher_id)
    now_iso = datetime.now(timezone.utc).isoformat()
    uid = str(uuid4())
    kind = resolve_intent(clean_question, intent)

    # W 老师·文段分析教师范围门禁：追问入口统一越界拦截
    if teacher_id == "teacher_jiangmuyun":
        guard = check_jiangmuyun_boundary(
            question_stem=sess_row["question_stem"],
            student_text=clean_question
        )
        if not guard["allowed"]:
            profile = lib.load_profile(teacher_id)
            teacher_name = profile.get("name", "W 老师·文段分析")
            reject_msg = guard["message"]
            aid = str(uuid4())
            db.execute(
                "INSERT INTO shenlun_teacher_followups (id, session_id, teacher_id, role, content, citations_json, kind, target_key, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (uid, session_id, teacher_id, "user", clean_question, "[]", kind, "", now_iso),
            )
            db.execute(
                "INSERT INTO shenlun_teacher_followups (id, session_id, teacher_id, role, content, citations_json, kind, target_key, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (aid, session_id, teacher_id, "assistant", reject_msg, "[]", kind, "", now_iso),
            )
            db.commit()
            return {
                "id": aid,
                "user_message_id": uid,
                "teacher_id": teacher_id,
                "teacher_name": teacher_name,
                "role": "assistant",
                "content": reject_msg,
                "citations": [],
                "kind": kind,
                "revisions": [],
                "created_at": now_iso,
            }

    if kind == "question":
        result = await _answer_plain_followup(db, dict(sess_row), teacher_id, clean_question, history)
    else:
        result = await _answer_objection(db, dict(sess_row), teacher_id, clean_question, history)

    citations = result.get("citations", [])
    db.execute(
        "INSERT INTO shenlun_teacher_followups (id, session_id, teacher_id, role, content, citations_json, kind, target_key, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (uid, session_id, teacher_id, "user", clean_question, "[]", kind, result.get("target_key", ""), now_iso),
    )
    if (user_attribution or "").strip():
        db.execute(
            "INSERT INTO shenlun_teacher_followups (id, session_id, teacher_id, role, content, citations_json, kind, target_key, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (str(uuid4()), session_id, teacher_id, "user",
             f"【我的最终错因归属】{user_attribution.strip()}", "[]", kind, result.get("target_key", ""), now_iso),
        )
    aid = str(uuid4())
    # 异议回复持久化修订摘要（target_key 列复用为 "条目:动作" 清单），刷新后徽章可恢复
    target_key_persist = result.get("target_key", "")
    if kind == "objection" and result.get("revisions"):
        target_key_persist = ";".join(f"{r['target_key']}:{r['action']}" for r in result["revisions"])
    db.execute(
        "INSERT INTO shenlun_teacher_followups (id, session_id, teacher_id, role, content, citations_json, kind, target_key, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?)",
        (aid, session_id, teacher_id, "assistant", result["content"], json.dumps(citations, ensure_ascii=False),
         kind, target_key_persist, now_iso),
    )
    db.commit()

    return {
        "id": aid,
        "user_message_id": uid,
        "teacher_id": teacher_id,
        "teacher_name": result.get("teacher_name", teacher_id),
        "role": "assistant",
        "content": result["content"],
        "citations": citations,
        "kind": kind,
        "revisions": result.get("revisions", []),
        "created_at": now_iso,
    }


def _parse_used_citations(reply_text: str, evidence: list[dict]) -> list[dict]:
    """只把回复中实际标注采用（[n]）的检索候选作为依据展示。"""
    used: set[int] = set()
    for m in re.findall(r"\[(\d{1,2})\]", reply_text or ""):
        n = int(m)
        if 1 <= n <= len(evidence):
            used.add(n)
    return [
        {"kind": e["kind"], "ref": e["ref"], "title": e["title"]}
        for i, e in enumerate(evidence, 1) if i in used
    ]


async def _answer_plain_followup(db, sess: dict, teacher_id: str, question: str, history: list[dict]) -> dict:
    """一般追问：教师代言答疑。与异议复核共用上下文（含本题材料与当前有效诊断）。"""
    ctx = build_followup_context(db, sess, teacher_id, question)
    evidence = retrieve_evidence(teacher_id, question)
    profile = lib.load_profile(teacher_id)
    teacher_name = profile.get("name", teacher_id)

    principles = "\n".join(f"- {p}" for p in profile.get("core_principles", []))
    system_prompt = (
        f"你是基于{teacher_name}教学体系构建的 AI 辅助答疑助手（不是{teacher_name}本人），"
        f"正在课后为考生解答针对批改结果的疑问。\n\n"
        f"你的教学体系依据（必须严格遵循，不得违背）：\n{principles}\n\n"
        "【铁律】\n"
        "1. 你的全部判断必须来自【依据材料】中的规则、课堂纠错案例与范文片段，"
        "引用时用编号标注（如 [1][3]）；未标注编号的观点不得归到教师资料名下。\n"
        "2. 涉及作答内容的问题，必须先对照【本题材料】与【用户作答】再回答；"
        "材料缺失时如实说明，不得假装已核对材料。\n"
        "3. 依据材料不足以回答时，必须明确说：\"当前检索资料中未找到相关依据\"，"
        "然后仅基于已有材料给出最靠近的提示，不得冒充教师观点。\n"
        "4. 不得引入依据材料之外的申论知识，不得更改教学方法论。\n"
        "5. 直接、具体、可操作；先给结论再给理由；排版用分段与序号，重点加粗。\n"
        "6. 如果考生追问的是批改中提到的错误，结合当前有效诊断具体展开怎么改。\n"
        "7. 本回答是依据教师课程资料生成的辅助反馈，不代表教师本人批改，也不是官方评分标准。"
    )

    material_block = (
        f"【本题材料】\n{ctx['material_text']}\n\n"
        if ctx["material_available"]
        else "【本题材料】（缺失：未能读取到本题材料，无法核对材料原文）\n\n"
    )
    if ctx["active_targets"]:
        diag_summary = "【当前有效诊断（当前有效版本，含此前修订结果）】\n" + _format_targets_for_context(ctx["active_targets"])
    else:
        diag_summary = (
            "【当前有效诊断】当前没有有效问题"
            + (f"（原始 {ctx['withdrawn_count']} 条均已被撤回，不得作为有效问题重新提出）" if ctx["withdrawn_count"] else "（未检出问题）")
        )

    user_prompt = (
        f"【考生作答的题目】{ctx['question_stem']}"
        f"（限字数：{ctx['word_limit']} 字）\n"
        + material_block
        + f"【考生作答】\n{ctx['answer_text']}\n"
        f"{diag_summary}\n\n"
        f"【依据材料】（规则库/课堂案例/范文语料检索结果，引用时标 [编号]）\n{_format_evidence(evidence)}\n\n"
        f"【考生追问】{question}"
    )

    from ..student_work_check import STUDENT_WORK_RULE
    system_prompt += STUDENT_WORK_RULE
    messages = [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt + "\n\n（以上是题目背景，请记住，接下来听我的追问。）"),
        Message(role="assistant", content="好，这是我批改的这道题，你说。"),
    ]
    for m in history[-10:]:
        messages.append(Message(role=m["role"], content=m["content"]))
    messages.append(Message(role="user", content=question))

    gateway = get_model_gateway()
    result = await gateway.generate(
        task_type="tutor_followup",
        messages=messages,
        schema=None,
        model_policy="BALANCED",
    )
    answer_text = result.raw_text.strip() or "抱歉，这个问题我需要再想想，请重试。"
    citations = _parse_used_citations(answer_text, evidence)
    return {"content": answer_text, "citations": citations, "teacher_name": teacher_name}


def _collect_known_refs(pack: dict, evidence: list[dict]) -> dict[tuple[str, str], dict]:
    """证据包 + 新检索候选中的合法来源（供修订引用核验）。

    统一收录 policy / case / question_case 三种来源，与 verify_refs 的身份规则一致：
    教师归属与稳定 ID 以证据包为准，不因标题相似放行。
    """
    known: dict[tuple[str, str], dict] = {}
    for p in pack.get("policies", []):
        known[("policy", p["policy_id"])] = {"kind": "policy", "ref": p["policy_id"], "title": p.get("name", "")}
    for c in pack.get("critique_cases", []):
        known[("case", c["case_id"])] = {"kind": "case", "ref": c["case_id"], "title": f"课堂纠错案例：{c.get('question', '')[:30]}"}
    for qc in pack.get("question_cases", []):
        known[("question_case", qc["question_id"])] = {
            "kind": "question_case", "ref": qc["question_id"], "title": f"题目案例：{qc.get('title', '')[:30]}"
        }
    for e in evidence:
        if e["kind"] in ("policy", "case", "question_case"):
            known.setdefault((e["kind"], e["ref"]), {"kind": e["kind"], "ref": e["ref"], "title": e["title"]})
    return known


def _judge_status(mat_state: str, has_refs: bool, fabricated: bool = False, sufficient: bool = True) -> tuple[str, str]:
    """统一的状态判定规则（adjust 新版本与主审查共用同一逻辑）。

    mat_state: 'verbatim'（完整分句级原文定位）| 'verbatim_partial'（局部片段）| 'not_found'。
    - supported：材料引文完整核验 + 教师来源合法；
    - suggestion：材料引文完整核验但无教师依据（一般建议，不冒充教师判断）；
    - pending：局部片段（截断风险）、引文缺失/概括或来源未过核验。
    """
    if mat_state == "verbatim" and has_refs and sufficient and not fabricated:
        return "supported", "引文与来源已由程序逐字核验；问题结论的判断来自模型审查，程序未证明诊断正确。"
    if mat_state == "verbatim" and sufficient and not fabricated:
        return "suggestion", "一般建议：材料引文已逐字核验，但无教师来源依据（或所引来源未通过核验），不冒充教师判断。"
    if mat_state == "verbatim_partial":
        return "pending", "材料引文为局部片段，程序已附所在完整分句，请核对截断是否丢失否定、数量或条件后再采信。"
    if fabricated:
        return "pending", "所引教师来源未通过核验，本条降为待确认。"
    return "pending", "材料引文未能定位为原文（仅概括、缺失或被清除），本条待确认。"


def _build_adjust_version(d: ReexamineDecision, target: dict, ctx: dict, known_refs: dict, check: dict) -> dict:
    """adjust 的完整新版本：问题、原句、材料依据、教师依据、改法、核验结果、状态一体生成。

    basis_mode 显式化空字段语义：
    - replace：以本次核验的新依据替换（默认）；
    - keep：保留原依据，但必须重新核验仍适用（材料引文重定位 + 教师来源重核验），
      失败则状态降为 pending 并记录 kept_basis_verified=False；
    - clear：清除教师依据；材料依据取本次决定提供且可定位者，否则清空。
    返回 dict 中的键都是"显式应用"——fold 时按存在与否区分保留/更新。
    """
    mat_state = check["verification"]["material_quote_state"]
    refs = check["verification"]["refs"]
    fabricated = check["verification"]["refs_status"] == "invalid"
    teacher_basis = [{**r, "applicability": d.applicability} for r in refs]

    version = {
        "problem": d.revised_problem,
        "user_quote": check["verification"].get("user_quote_span", "") or target.get("user_quote", ""),
        "material_quote": "……".join(check["verification"]["material_spans"]) if mat_state != "not_found" else "",
        "material_quote_verified": mat_state == "verbatim",
        "material_clause": "；".join(check["verification"].get("material_clauses", [])) if mat_state == "verbatim_partial" else "",
        "material_point": d.material_point,
        "teacher_basis": teacher_basis,
        "policy_ref": teacher_basis[0]["ref"] if teacher_basis else "",
        "policy_name": teacher_basis[0]["title"] if teacher_basis else "",
        "verification": {
            "user_quote": "verbatim",
            "material_quote": mat_state,
            "refs": "valid" if teacher_basis else ("invalid" if fabricated else "none"),
        },
        "kept_basis_verified": None,
    }
    if d.revised_fix:
        version["suggested_fix"] = d.revised_fix
    status, note = _judge_status(mat_state, bool(teacher_basis), fabricated)
    version["status"] = status
    version["status_note"] = note
    version["basis_label"] = (
        "教师依据+材料依据" if status == "supported"
        else ("一般建议（材料依据）" if status == "suggestion" else "待确认疑点")
    )
    return version


def _verify_decision(d: ReexamineDecision, ctx: dict, known_refs: dict, target: dict) -> dict:
    """按决定类型核验最小依据。返回核验结果 dict（ok=False 时 decision 被拒绝）。

    材料引文核验区分完整（verbatim）与局部（verbatim_partial）：
    局部片段真实存在但截断可能丢失否定/数量/条件，不作为完整支持依据。
    """
    refs_dump = [r.model_dump() for r in (d.refs or [])]
    valid_refs, invalid_refs = verify_refs(refs_dump, _pack_from_known(known_refs))
    # 新检索证据中的合法来源也允许
    for r in d.refs or []:
        key = (r.kind, r.ref)
        if key in known_refs and all(v["ref"] != r.ref for v in valid_refs):
            valid_refs.append(known_refs[key])

    user_q = (d.user_quote or "").strip()
    if not user_q:
        # 未提供时以诊断条目记录的原句为候选——但它仍必须在被复核作答文本中真实逐字定位；
        # 诊断记录本身不构成核验，不存在"等于旧诊断原句即可通过"的兜底。
        user_q = (target.get("user_quote") or target.get("student_span") or "").strip()
    anchor_text = ctx.get("reexamine_answer_text") or ""
    user_loc = None
    if user_q and anchor_text:
        user_loc = locate_quote(user_q, anchor_text)
    user_ok = bool(user_loc and user_loc["status"] == "verbatim")
    user_span = user_loc["spans"][0] if user_ok else ""
    mat_loc = locate_quote(d.material_quote, ctx["material_text"]) if (d.material_quote or "").strip() and ctx["material_available"] else None
    mat_found = bool(mat_loc and mat_loc["status"] == "verbatim")
    mat_state = "verbatim" if (mat_found and not mat_loc.get("partial")) else ("verbatim_partial" if mat_found else "not_found")

    result = {
        "ok": False,
        "reason": "",
        "refs": valid_refs,
        "rejected_refs": invalid_refs,
        "verification": {
            "user_quote": "verbatim" if user_ok else ("not_found" if user_q else "not_provided"),
            "user_quote_span": user_span,
            "material_quote": mat_state if mat_loc else "not_provided",
            "material_quote_state": mat_state,
            "material_clauses": mat_loc.get("clauses", []) if mat_found else [],
            "refs": valid_refs,
            "refs_status": "valid" if valid_refs else ("invalid" if refs_dump else "none"),
            "material_spans": mat_loc["spans"] if mat_found else [],
        },
        "revised": {},
        "version": None,
    }

    if invalid_refs:
        result["reason"] = f"所引来源未通过核验（{invalid_refs[0]['ref']}）：虚构引用被拒绝"
        return result

    if d.action == "withdraw":
        if not (d.reason or "").strip():
            result["reason"] = "撤回缺少理由说明"
        elif not (mat_found or user_ok or valid_refs):
            result["reason"] = "撤回缺少可核验的本题事实依据（材料原文/用户原句/教师来源）"
        else:
            result["ok"] = True
    elif d.action == "maintain":
        if not (valid_refs or mat_found):
            result["reason"] = "维持缺少依据：需要有效教师来源或可定位的材料原文"
        else:
            result["ok"] = True
    elif d.action == "adjust":
        if not (d.revised_problem or "").strip():
            result["reason"] = "调整缺少修改后的问题说明"
        elif not user_ok:
            result["reason"] = "调整未能关联可定位的用户原句"
        else:
            mode = d.basis_mode if d.basis_mode in ("replace", "keep", "clear") else "replace"
            base_version = _build_adjust_version(d, target, ctx, known_refs, result)
            if mode == "keep":
                # 保留原依据，但必须逐条重新核验：材料引文重定位 + 每条教师来源重核验。
                # 仅保留本轮确实重验通过的依据；失效者记录原因并剔除；状态按剩余可核验
                # 依据经统一规则（_judge_status）重新判定——不因删掉失效引用而自动维持结论。
                old_mq = (target.get("material_quote") or "").strip()
                old_loc = locate_quote(old_mq, ctx["material_text"]) if old_mq and ctx["material_available"] else None
                if old_loc and old_loc["status"] == "verbatim":
                    old_mat_state = "verbatim_partial" if old_loc.get("partial") else "verbatim"
                    old_spans = old_loc["spans"]
                    old_clauses = old_loc.get("clauses", []) if old_mat_state == "verbatim_partial" else []
                else:
                    old_mat_state, old_spans, old_clauses = "not_found", [], []

                old_refs = target.get("teacher_basis", []) or []
                valid_old, invalid_old = verify_refs(old_refs, _pack_from_known(known_refs))

                version = {
                    "problem": d.revised_problem,
                    "user_quote": user_span or target.get("user_quote", ""),
                    "material_quote": "……".join(old_spans) if old_mat_state != "not_found" else "",
                    "material_quote_verified": old_mat_state == "verbatim",
                    "material_clause": "；".join(old_clauses),
                    "material_point": target.get("material_point", ""),
                    "teacher_basis": [dict(r) for r in valid_old],
                    "policy_ref": valid_old[0]["ref"] if valid_old else "",
                    "policy_name": valid_old[0]["title"] if valid_old else "",
                    "verification": {
                        "user_quote": "verbatim" if user_ok else ("not_found" if user_q else "not_provided"),
                        "user_quote_span": user_span,
                        "material_quote": old_mat_state,
                        "material_spans": old_spans,
                        "material_clauses": old_clauses,
                        "refs": "valid" if valid_old else ("invalid" if old_refs else "none"),
                        "old_refs_rejected": invalid_old,
                    },
                    # 全部旧依据（材料+每条来源）都重验通过才算完整保留
                    "kept_basis_verified": bool(old_mat_state == "verbatim" and not invalid_old and (valid_old or not old_refs)),
                }
                if d.revised_fix:
                    version["suggested_fix"] = d.revised_fix
                status, note = _judge_status(old_mat_state, bool(valid_old))
                # keep 尾项：失效旧引用剔除并记录；不能仅因剩下一个合法 ID 就维持
                # "教师方法支持"——本轮模型只表态保留，并未对剩余依据重新作实质审查，
                # 因此有剔除发生时结论说明降为"AI 分析"，由复核意见（reply）承担实质判断。
                if invalid_old:
                    reasons = "；".join(f"{r['ref']}（{r['reason'][:40]}）" for r in invalid_old)
                    note = (
                        f"已剔除未通过重验的旧依据（{reasons}）；剩余依据真实存在但本轮未重新作实质审查，"
                        "不维持教师方法支持标记，结论以本次复核意见为准。" + note
                    )
                    if status == "supported":
                        status = "ai_analysis"
                elif old_mat_state != "verbatim" and old_mq:
                    note = "原材料引文未通过重定位（缺失或为局部片段），状态按核验结果重判。" + note
                version["status"] = status
                version["status_note"] = note
                version["basis_label"] = (
                    "教师依据+材料依据" if status == "supported"
                    else ("一般建议（材料依据）" if status == "suggestion" else "待确认疑点")
                )
                result["ok"] = True
                result["version"] = version
            elif mode == "clear":
                # 清除教师依据；材料依据取本次决定提供且可定位者，否则清空
                mat_state = base_version["verification"]["material_quote"]
                base_version.update({
                    "teacher_basis": [],
                    "policy_ref": "",
                    "policy_name": "",
                    "verification": {**base_version["verification"], "refs": "none"},
                })
                status, note = _judge_status(mat_state, False)
                base_version["status"] = status
                base_version["status_note"] = "已清除教师依据：" + note
                base_version["basis_label"] = (
                    "教师依据+材料依据" if status == "supported"
                    else ("一般建议（材料依据）" if status == "suggestion" else "待确认疑点")
                )
                result["ok"] = True
                result["version"] = base_version
            else:
                # replace：以决定携带并核验的新依据为准
                if result["verification"]["material_quote_state"] == "not_found" and not valid_refs:
                    result["reason"] = "调整（replace）缺少本题材料引文或有效教师来源"
                else:
                    result["ok"] = True
                    result["version"] = base_version
    return result


def _pack_from_known(known_refs: dict) -> dict:
    """把 known_refs 转成 verify_refs 需要的证据包形态（三种来源统一）。"""
    pack = {"teacher_id": "", "policies": [], "critique_cases": [], "question_cases": []}
    for (kind, ref), item in known_refs.items():
        if kind == "policy":
            pack["policies"].append({"policy_id": ref, "name": item.get("title", "")})
        elif kind == "case":
            pack["critique_cases"].append({"case_id": ref, "question": ""})
        elif kind == "question_case":
            pack["question_cases"].append({"question_id": ref, "title": item.get("title", "")})
    return pack


async def _answer_objection(db, sess: dict, teacher_id: str, objection: str, history: list[dict]) -> dict:
    """异议重审：重新审查当前有效诊断，产出维持/调整/撤回决定并写入修订表。

    有效性门槛：虚构引用被拒绝；达不到最小依据的决定不生效；
    全部被拒时原诊断保持不变，回复不得宣称已修改。
    """
    profile = lib.load_profile(teacher_id)
    teacher_name = profile.get("name", teacher_id)

    diag_row = db.execute(
        '''SELECT * FROM shenlun_teacher_diagnoses
           WHERE session_id=? AND teacher_id=?
           ORDER BY created_at DESC, id DESC LIMIT 1''',
        (sess["id"], teacher_id),
    ).fetchone()
    if diag_row is None:
        return {
            "content": "该教师尚未对本会话作答出具诊断，暂无可复核的条目。请先提交作答生成诊断。",
            "citations": [], "teacher_name": teacher_name,
        }

    ctx = build_followup_context(db, sess, teacher_id, objection)
    targets = ctx["targets"]
    if not targets:
        return {
            "content": "该教师最近一次诊断没有可复核的条目（未检出问题）。",
            "citations": [], "teacher_name": teacher_name,
        }

    # 作答版本门禁（模型调用前）：被复核作答文本不可得（历史版本未留存）时，
    # 原句无法逐字核验——不混用新答案与旧诊断生成有效修订，如实说明。
    if not ctx.get("reexamine_answer_available"):
        return {
            "content": (
                "该诊断对应版本的作答文本未留存，无法对其原句做逐字核验，"
                "因此不能生成有效修订（维持/调整/撤回均不写入），也不以当前作答文本代替。"
                "请对当前作答重新提交生成新诊断后再发起复核。"
            ),
            "citations": [], "teacher_name": teacher_name,
        }
    expected_diag_id = diag_row["id"]
    sess_before = db.execute('SELECT final_answer FROM shenlun_sessions WHERE id=?', (sess["id"],)).fetchone()
    expected_answer_hash = answer_hash((sess_before["final_answer"] if sess_before else "") or "")

    evidence = retrieve_evidence(teacher_id, objection)
    pack = json.loads(diag_row["evidence_json"] or "{}")
    messages = _build_reexamine_messages(ctx, teacher_id, objection, evidence, history, pack)

    fallback = {
        "content": (
            "复核暂时不可用（审查服务未返回有效结果），原诊断保持不变。"
            "你可以稍后重试，或换一种方式描述你的疑问。"
        ),
        "citations": [], "teacher_name": teacher_name,
    }

    try:
        gateway = get_model_gateway()
        result = await gateway.generate(
            task_type="tutor_followup",
            messages=messages,
            schema=ReexamineOutput,
            model_policy="STRONG",
        )
        output: ReexamineOutput = result.data
    except Exception:
        return fallback

    # 版本一致性复核（模型调用后）：等待模型期间用户重新提交会产生新诊断，
    # 此时不写入任何修订，避免串版。
    row_now = db.execute(
        '''SELECT id FROM shenlun_teacher_diagnoses
           WHERE session_id=? AND teacher_id=?
           ORDER BY created_at DESC, id DESC LIMIT 1''',
        (sess["id"], teacher_id),
    ).fetchone()
    sess_now = db.execute('SELECT final_answer FROM shenlun_sessions WHERE id=?', (sess["id"],)).fetchone()
    answer_changed = sess_now is not None and answer_hash(sess_now["final_answer"] or "") != expected_answer_hash
    if row_now is None or row_now["id"] != expected_diag_id or answer_changed:
        return {
            "content": (
                "复核期间作答或诊断已更新（检测到你重新提交了作答或产生了新诊断），"
                "为避免串版，本次复核未写入任何修订。请基于最新诊断重新发起复核。"
            ),
            "citations": [], "teacher_name": teacher_name,
        }

    known_refs = _collect_known_refs(json.loads(diag_row["evidence_json"] or "{}"), evidence)
    valid_keys = {t.get("target_key", "") for t in targets}
    targets_by_key = {t.get("target_key", ""): t for t in targets}

    now_iso = datetime.now(timezone.utc).isoformat()
    applied, rejected = [], []
    for d in output.decisions:
        if d.target_key not in valid_keys:
            rejected.append({"target_key": d.target_key, "action": d.action, "reason": "指向未知的诊断条目"})
            continue
        check = _verify_decision(d, ctx, known_refs, targets_by_key[d.target_key])
        if not check["ok"]:
            rejected.append({"target_key": d.target_key, "action": d.action, "reason": check["reason"]})
            continue
        revised = {
            "verification": check["verification"],
            "refs": check["refs"],
            "rejected_refs": check["rejected_refs"],
        }
        if check.get("version"):
            # adjust：保存完整新版本（问题/原句/依据/核验/状态一体），读取时整体应用
            revised["version"] = check["version"]
        else:
            revised["problem"] = check["revised"].get("problem", "")
            revised["suggested_fix"] = check["revised"].get("suggested_fix", "")
        db.execute(
            '''INSERT INTO shenlun_target_revisions
               (id, session_id, teacher_id, diagnosis_id, target_key, action, reason, revised_json, source, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (str(uuid4()), sess["id"], teacher_id, diag_row["id"], d.target_key,
             d.action, d.reason or "", json.dumps(revised, ensure_ascii=False), "ai", now_iso),
        )
        applied.append({"target_key": d.target_key, "action": d.action, "verification": check["verification"]})

    # 回复必须如实反映程序核验结果：未生效的决定不得被描述为已修改
    reply = output.reply_text.strip()
    status_lines = []
    for a in applied:
        status_lines.append(f"{a['target_key']} {a['action']}：已生效（依据经程序核验）")
    for r in rejected:
        status_lines.append(f"{r['target_key']} {r['action']}：未生效（{r['reason']}），原诊断保持")
    if not applied:
        content = "未能对任何条目做出有效修订，原诊断保持不变。" if not rejected else (
            "以下复核决定未通过程序核验，原诊断保持不变：\n" + "\n".join(f"- {line}" for line in status_lines)
        )
        if output.overall_note:
            content += f"\n\n（复核备注：{output.overall_note}）"
        content += "\n\n——本复核为依据教师资料生成的辅助反馈，不代表教师本人批改，也不是官方评分标准。"
        return {"content": content, "citations": [], "teacher_name": teacher_name, "revisions": []}

    if not reply:
        reply = "；".join(f"{a['target_key']} {a['action']}" for a in applied)
    if ctx.get("stale") and not reply.startswith("注意"):
        reply = "注意：该诊断对应的是你上一版作答。\n" + reply
    reply += "\n\n程序核验结果：\n" + "\n".join(f"- {line}" for line in status_lines)
    if output.overall_note:
        reply += f"\n\n（复核备注：{output.overall_note}）"
    reply += "\n\n——本复核为依据教师资料生成的辅助反馈，不代表教师本人批改，也不是官方评分标准。"

    citations = _citations_from_applied(applied, known_refs)
    return {
        "content": reply,
        "citations": citations,
        "teacher_name": teacher_name,
        "revisions": [{"target_key": a["target_key"], "action": a["action"]} for a in applied],
        "target_key": applied[0]["target_key"] if applied else "",
    }


def _citations_from_applied(applied: list[dict], known_refs: dict) -> list[dict]:
    citations = []
    for a in applied:
        for r in (a.get("verification") or {}).get("refs", []):
            if all(c["ref"] != r["ref"] for c in citations):
                citations.append(r)
    return citations
