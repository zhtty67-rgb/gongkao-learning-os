# -*- coding: utf-8 -*-
"""L 老师·言语理解与表达 教师知识库加载与分词匹配工具。"""

import json
from pathlib import Path
from typing import Dict, List, Any

def phrases(text_or_list, min_len=2):
    if not text_or_list:
        return []
    if isinstance(text_or_list, list):
        res = []
        for item in text_or_list:
            res.extend(phrases(item, min_len))
        return res
    if not isinstance(text_or_list, str):
        return []
    import re
    words = re.split(r"[\s,，.。、;:：；!！?？\"'“”‘’（）()—\-_/\\\[\]]+", text_or_list)
    return [w.strip() for w in words if len(w.strip()) >= min_len]

class HuashengVerbalLibrary:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        self.library_dir = self.base_dir / "library"
        self.cases_dir = self.base_dir / "cases"
        self.profile_dir = self.base_dir / "profile"
        
        self.policies = self._load_json(self.library_dir / "policies_full.json", default=[])
        
        # 兼容 library 和 cases 两个目录
        q_cases = self._load_json(self.cases_dir / "question_cases_full.json", default=None)
        if q_cases is None:
            q_cases = self._load_json(self.library_dir / "question_cases_full.json", default=[])
        self.question_cases = q_cases or []

        crit_cases = self._load_json(self.cases_dir / "critique_cases_full.json", default=None)
        if crit_cases is None:
            crit_cases = self._load_json(self.library_dir / "critique_cases_full.json", default=[])
        self.critique_cases = crit_cases or []

        self.profile = self._load_json(self.profile_dir / "teacher_profile.json", default={})

    def _load_json(self, path: Path, default=None):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
