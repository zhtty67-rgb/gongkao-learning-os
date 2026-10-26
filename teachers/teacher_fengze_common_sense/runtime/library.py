# -*- coding: utf-8 -*-
"""
P 老师常识判断教师知识库加载与分词匹配工具。
支持知识库核心条目(knowledge_base_full.json)、42讲全文切片(transcript_chunks.json)、
勘误与跨讲纠偏对照库(errata_registry.json)、规则库、案例库与画像。
"""

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

class FengzeCommonSenseLibrary:
    def __init__(self, base_dir=None):
        self.base_dir = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        self.library_dir = self.base_dir / "library"
        self.profile_dir = self.base_dir / "profile"
        
        # 1. 结构化核心知识库
        self.knowledge_base = self._load_json(self.library_dir / "knowledge_base_full.json", default=[])
        
        # 2. 42讲全文可检索切片 (1433 chunks, 96万字全覆盖)
        self.transcript_chunks = self._load_json(self.library_dir / "transcript_chunks.json", default=[])
        
        # 3. 勘误与跨讲纠偏对照库
        self.errata_registry = self._load_json(self.library_dir / "errata_registry.json", default=[])
        
        # 4. 辅助规则库（42条做题心法与排他法则）
        self.policies = self._load_json(self.library_dir / "policies_full.json", default=[])
        
        # 5. 案例库与纠偏库
        self.question_cases = self._load_json(self.library_dir / "question_cases_full.json", default=[])
        self.critique_cases = self._load_json(self.library_dir / "critique_cases_full.json", default=[])
        
        # 6. 教师认知画像
        self.profile = self._load_json(self.profile_dir / "teacher_profile.json", default={})

    def _load_json(self, path: Path, default=None):
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
