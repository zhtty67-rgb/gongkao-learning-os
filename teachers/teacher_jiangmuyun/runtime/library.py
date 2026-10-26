# -*- coding: utf-8 -*-
"""W 老师文段分析知识库加载器。"""

import json
from pathlib import Path

DEFAULT_BASE = Path(__file__).resolve().parent.parent

def load_profile(base_dir: Path = None) -> dict:
    base = base_dir or DEFAULT_BASE
    p = base / "library" / "teacher_profile.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}

def load_policies(base_dir: Path = None) -> list:
    base = base_dir or DEFAULT_BASE
    p = base / "library" / "policies_full.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []

def load_question_cases(base_dir: Path = None) -> list:
    base = base_dir or DEFAULT_BASE
    p = base / "library" / "question_cases_full.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []

def load_critique_cases(base_dir: Path = None) -> list:
    base = base_dir or DEFAULT_BASE
    p = base / "library" / "critique_cases_full.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return []
