# -*- coding: utf-8 -*-
"""申论教师批改引擎（Shenlun Teacher Diagnosis）。

数据来源：D:/gong/teacher_feiyang 与 D:/gong/teacher_zhanzhang 课程逐字稿提炼，
kb/teacher_*/ 目录即插即用（feiyang 123 规则 / 62 题目案例 / 68 纠错实录；
zhanzhang 83 / 42 / 44）。

流程：本题上下文 → 按教师/题型检索规则与案例 → 疑点检测（不判错）
→ AI 受约束语义审查 → 程序核验依据（原句定位/材料引文/来源 ID）
→ 落库（含审查状态与作答版本指纹）→ 追问与异议可维持/调整/撤回。
"""

from .service import (
    apply_semantic_review,
    answer_hash,
    get_latest_teacher_diagnosis,
    infer_question_type,
    run_teacher_diagnosis,
    split_answer_points,
)
from .followup import answer_teacher_followup, get_teacher_followups

__all__ = [
    "run_teacher_diagnosis",
    "apply_semantic_review",
    "answer_hash",
    "get_latest_teacher_diagnosis",
    "infer_question_type",
    "split_answer_points",
    "answer_teacher_followup",
    "get_teacher_followups",
]
