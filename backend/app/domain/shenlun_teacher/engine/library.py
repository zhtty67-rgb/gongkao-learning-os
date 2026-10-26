# -*- coding: utf-8 -*-
"""飞扬老师知识库加载器（多教师版：kb/teacher_<id>/ 目录，每教师一套合并全量库）。"""

import json
from pathlib import Path
from ...teacher_asset_stats import teacher_asset_stats, current_teacher_profile

KB_DIR = Path(__file__).resolve().parent.parent / "kb"
DEFAULT_TEACHER = "teacher_feiyang"

_synonym_cache: dict | None = None


def load_synonym_groups() -> list[list[str]]:
    """加载跨教师共享的领域同义词组（kb/synonyms.json），带缓存。"""
    global _synonym_cache
    if _synonym_cache is not None:
        return _synonym_cache
    groups: list[list[str]] = []
    try:
        with open(KB_DIR / "synonyms.json", encoding="utf-8") as f:
            groups = json.load(f).get("groups", []) or []
    except Exception:
        groups = []
    _synonym_cache = groups
    return groups


def expand_query(text: str) -> str:
    """同义词查询扩展：命中任一变体即追加全组词（仅追加不改写，保持确定性）。"""
    additions: list[str] = []
    for group in load_synonym_groups():
        if any(v in text for v in group):
            additions.extend(v for v in group if v and v not in text)
    return f"{text} {' '.join(additions)}" if additions else text


def list_teachers() -> list[str]:
    """扫描 kb/ 下全部 teacher_* 目录。"""
    if not KB_DIR.exists():
        return []
    return sorted(d.name for d in KB_DIR.iterdir() if d.is_dir() and d.name.startswith("teacher_"))


def _load_array(path: Path) -> list:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def load_policies(teacher_id: str = DEFAULT_TEACHER) -> list[dict]:
    return [
        {
            "policy_id": p.get("policy_id", ""),
            "teacher_id": p.get("teacher_id", teacher_id),
            "name": p.get("name", ""),
            "status": p.get("status", "explicit"),
            "trigger": p.get("trigger", ""),
            "rule": p.get("rule", ""),
            "reasoning": p.get("reasoning", ""),
            "applies_to": p.get("applies_to", []) or [],
            "must_preserve": p.get("must_preserve", []) or [],
            "may_remove": p.get("may_remove", []) or [],
            "forbidden_transformations": p.get("forbidden_transformations", []) or [],
            # 正反例是教师方法的一部分（示范如何应用），随规则完整传递给方法上下文
            "positive_example": p.get("positive_example", {}) or {},
            "negative_example": p.get("negative_example", {}) or {},
            "confidence": float(p.get("confidence", 0.8) or 0.8),
            "source": p.get("source", []) or [],
        }
        for p in _load_array(KB_DIR / teacher_id / "policies_full.json")
        if isinstance(p, dict) and p.get("policy_id")
    ]


def load_question_cases(teacher_id: str = DEFAULT_TEACHER) -> list[dict]:
    return [
        {
            "question_id": c.get("question_id", ""),
            "title": c.get("title", c.get("question", "")),
            "question_type": c.get("question_type", ""),
            "analysis": c.get("analysis", {}) or {},
            "teacher_reasoning": c.get("teacher_reasoning", ""),
        }
        for c in _load_array(KB_DIR / teacher_id / "question_cases_full.json")
        if isinstance(c, dict)
    ]


def load_critique_cases(teacher_id: str = DEFAULT_TEACHER) -> list[dict]:
    return [
        {
            "case_id": c.get("case_id", ""),
            "question": c.get("question", ""),
            "student_error_snippet": c.get("student_error_snippet", ""),
            "error_type": c.get("error_type", "OTHER"),
            "diagnosis": c.get("diagnosis", ""),
            "severity": c.get("severity", "medium"),
            "remedy_instruction": c.get("remedy_instruction", ""),
        }
        for c in _load_array(KB_DIR / teacher_id / "critique_cases_full.json")
        if isinstance(c, dict)
    ]


def load_profile(teacher_id: str = DEFAULT_TEACHER) -> dict:
    try:
        with open(KB_DIR / teacher_id / "teacher_profile.json", encoding="utf-8") as f:
            profile = json.load(f)
        return current_teacher_profile(profile, teacher_asset_stats(KB_DIR / teacher_id, shenlun=True))
    except Exception:
        return {}


def build_text_for_retrieval(policy: dict) -> str:
    parts = [policy["name"], policy["trigger"], policy["rule"], policy["reasoning"]]
    parts += policy["applies_to"] + policy["forbidden_transformations"]
    return " ".join(x for x in parts if x)


def build_text_for_case(case: dict) -> str:
    parts = [
        case.get("question", ""),
        case.get("student_error_snippet", ""),
        case.get("diagnosis", ""),
        case.get("error_type", ""),
    ]
    return " ".join(x for x in parts if x)
