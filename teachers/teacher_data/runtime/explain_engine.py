# -*- coding: utf-8 -*-
"""资料分析讲题引擎：多教师标注规则检索与速算解题报告合成。"""

import json

from library import DataLibrary, phrases

MIN_LEN = 2

class DataExplainEngine:
    def __init__(self, base_dir=None):
        self.lib = DataLibrary(base_dir)

    def rank_policies(self, topic: str, stem: str, student_thought: str = ""):
        hay = f"{topic}，{stem}，{student_thought}"
        scored = []
        for p in self.lib.policies:
            score = 0.0
            hits = []
            cat = p.get("category", "")
            if topic and (topic in cat or cat in topic or ("比重" in topic and "比重" in cat) or ("平均" in topic and "平均" in cat) or ("增长" in topic and "ABRX" in cat)):
                score += 8.0
                hits.append(cat)
            if any(pct in hay for pct in ["14.3%", "16.7%", "12.5%", "11.1%", "9.1%", "8.3%", "7.7%", "7.1%", "6.7%"]) and "小分" in p.get("name", ""):
                score += 10.0
                hits.append("小分互换")
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
            "# 📊 协作组团队 · 资料分析讲题报告",
            f"**题型定位**：{topic}",
            f"**题干数据**：{stem}...",
            "",
            "## 一、 教师解题心法与速算定理"
        ]
        for _, hits, p in rules:
            teacher_tag = p.get("author_teacher", "L 老师")
            lines.append(f"- **【{p['name']}】** ({p['policy_id']}) —— 指导名师：【{teacher_tag}】（命中特征：{', '.join(hits[:3])}）")
            lines.append(f"  - 速算法则：{p['rule']}")
            for src in p.get("source", []):
                lines.append(f"  - 来源：{src.get('file', src.get('course'))}，行{src.get('line_start', '待核对')}")
            lines.append(f"  - 避坑要点：{', '.join(p.get('forbidden_transformations', []) or ['先看选项差距，防范时间单位陷阱'])}")

        lines.append("")
        lines.append("## 二、 课堂相似母题推演")
        if cases:
            for c in cases:
                t_tag = c.get("author_teacher", "L 老师")
                lines.append(f"### 典例：{c['title']} ({c['question_id']})")
                lines.append(f"- **授课名师**：{t_tag}")
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
