# -*- coding: utf-8 -*-
"""数量关系讲题引擎：确定性数学套路检索与速算报告合成。"""

import json

from library import QuantLibrary, phrases

MIN_LEN = 2

class QuantExplainEngine:
    def __init__(self, base_dir=None):
        self.lib = QuantLibrary(base_dir)

    def rank_policies(self, topic: str, stem: str, student_thought: str = ""):
        hay = f"{topic}，{stem}，{student_thought}"
        scored = []
        for p in self.lib.policies:
            score = 0.0
            hits = []
            cat = p.get("category", "")
            if topic and (topic in cat or cat in topic):
                score += 5.0
                hits.append(cat)
            for f in set(phrases(p.get("identification_features"), MIN_LEN)):
                if f in hay:
                    score += 3.0
                    hits.append(f)
            for f in set(phrases(p.get("name"), MIN_LEN)):
                if f in hay:
                    score += 2.0
                    hits.append(f)
            for f in set(phrases(p.get("trigger"), MIN_LEN)):
                if f in hay:
                    score += 1.5
                    hits.append(f)
            if score > 0:
                scored.append((score, list(set(hits)), p))
        scored.sort(key=lambda x: -x[0])
        rules = [s for s in scored]
        if not rules:
            rules = []
        return rules[:4]

    def find_cases(self, topic: str, stem: str, top=2):
        scored = []
        tokens = set(phrases(f"{topic} {stem}", MIN_LEN))
        for c in self.lib.question_cases:
            c_text = f"{c.get('title')} {c.get('stem')}"
            hits = sum(1.0 for t in tokens if t in c_text)
            if hits > 0:
                scored.append((hits, c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:top]]

    def find_critiques(self, student_thought: str, top=2):
        if not student_thought:
            return []
        tokens = set(phrases(student_thought, MIN_LEN))
        scored = []
        for crit in self.lib.critique_cases:
            crit_text = f"{crit.get('error_type')} {crit.get('student_error_snippet')} {crit.get('diagnosis')}"
            hits = sum(1.0 for t in tokens if t in crit_text)
            if hits > 0:
                scored.append((hits, crit))
        scored.sort(key=lambda x: -x[0])
        return [crit for _, crit in scored[:top]]

    def generate_report(self, question: dict) -> str:
        topic = question.get("topic", "")
        stem = question.get("stem", "")
        options = question.get("options", {})
        student_choice = question.get("student_choice", "")
        student_thought = question.get("student_reasoning", "")

        rules = self.rank_policies(topic, stem, student_thought)
        cases = self.find_cases(topic, stem)
        critiques = self.find_critiques(student_thought)

        lines = [
            "# 🧮 协作组团队 · 数量关系讲题报告",
            f"**题型定位**：{topic}",
            f"**题干条件**：{stem}...",
            "",
            "## 一、 教师解题心法与特值套路"
        ]
        for _, hits, p in rules:
            lines.append(f"- **【{p['name']}】** ({p['policy_id']})（命中特征：{', '.join(hits[:3])}）")
            lines.append(f"  - 套路核心：{p['rule']}")
            for src in p.get("source", []):
                lines.append(f"  - 来源：{src.get('file', src.get('course'))}，行{src.get('line_start', '待核对')}")
            lines.append(f"  - 避坑警示：{', '.join(p.get('forbidden_transformations', []) or ['切勿盲目列复杂多元方程，注意整数约束'])}")

        lines.append("")
        lines.append("## 二、 课堂相似母题推演")
        if cases:
            for c in cases:
                lines.append(f"### 典例：{c['title']} ({c['question_id']})")
                lines.append(f"- **题型考点**：{c.get('source_exam', '课堂母题精讲')}")
                lines.append(f"- **课件原文解析**：{c.get('teacher_reasoning', '')}")
                for src in c.get("source", []):
                    lines.append(f"- **来源**：{src.get('file')}，第{src.get('page')}页")
                lines.append(f"- **课件例题答案（不是本题答案）**：{c.get('answer', '')}")
        else:
            lines.append("未找到已核验课件例题；需依据本题条件另行求解。")

        lines.extend(["", "## 当前题核验状态", "以上为教学方法和课件参考，并非本题答案。当前题的计算、选项和错因须另行核验。"])
        if options:
            lines.extend(["", "## 当前题选项", json.dumps(options, ensure_ascii=False)])
        lines.append("不同选项必须逐项核验，不可直接采用相似题答案；未核验的学生思路不作错误诊断。")
        return "\n".join(lines)
