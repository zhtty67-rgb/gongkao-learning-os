# -*- coding: utf-8 -*-
"""数量关系教师模型本地知识库封装。"""

import json
import re
from pathlib import Path

def phrases(s, min_len=2):
    if not s:
        return []
    if isinstance(s, list):
        out = []
        for x in s:
            out.extend(phrases(x, min_len))
        return out
    tokens = re.split(r"[\s,，、/／;；:：。！？—_()（）\[\]【】\"'“”‘’]+", str(s))
    return [t for t in tokens if len(t) >= min_len]

class QuantLibrary:
    def __init__(self, base_dir=None):
        base = Path(base_dir) if base_dir else Path(__file__).resolve().parent.parent
        lib_dir = base / "library"
        self.policies = json.loads((lib_dir / "policies_full.json").read_text(encoding="utf-8"))
        self.question_cases = json.loads((lib_dir / "question_cases_full.json").read_text(encoding="utf-8"))
        self.critique_cases = json.loads((lib_dir / "critique_cases_full.json").read_text(encoding="utf-8"))
        self.policies = [p for p in self.policies if p.get("verification_status") != "quarantined"]
        self.question_cases = [c for c in self.question_cases if c.get("verification_status") == "source_text_verified"]
        self.critique_cases = []  # Unverified classroom examples are never student diagnoses.
        self.profile = json.loads((base / "profile" / "teacher_profile.json").read_text(encoding="utf-8"))
