# -*- coding: utf-8 -*-
"""G 老师图推知识库加载与索引（纯本地，零 API）。"""

import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SPLIT_RE = re.compile(r"[，。；、！？：,\.;:!?\(\)（）\[\]【】\s]+")


def phrases(text: str, min_len: int = 2):
    """把自由文本切成候选关键词短语。"""
    if not text:
        return []
    if isinstance(text, list):
        text = "，".join(str(t) for t in text)
    return [p.strip() for p in SPLIT_RE.split(str(text)) if len(p.strip()) >= min_len]


class LongfeiLibrary:
    def __init__(self, base: Path = None):
        base = base or BASE
        lib = base / "library"
        self.policies = json.loads((lib / "policies_full.json").read_text(encoding="utf-8"))
        self.question_cases = json.loads((lib / "question_cases_full.json").read_text(encoding="utf-8"))
        self.critique_cases = json.loads((lib / "critique_cases_full.json").read_text(encoding="utf-8"))
        self.profile = json.loads((base / "profile" / "teacher_profile.json").read_text(encoding="utf-8"))

        # 政策索引：识别特征短语 -> policy
        self.feature_index = {}
        for p in self.policies:
            feats = phrases(p.get("identification_features")) + phrases(p.get("name"))
            for f in feats:
                self.feature_index.setdefault(f, []).append(p)
        # 案例 索引用全文短语（惰性构建由引擎完成）

    def policies_by_category(self, *categories):
        return [p for p in self.policies if p.get("category") in categories]
