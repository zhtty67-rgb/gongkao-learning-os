# -*- coding: utf-8 -*-
"""逻辑判断讲题引擎：确定性知识检索与教师讲题报告合成。"""

import json

from library import LogicLibrary, phrases

MIN_LEN = 2

class LogicExplainEngine:
    def __init__(self, base_dir=None):
        self.lib = LogicLibrary(base_dir)

    def rank_policies(self, question_type: str, stem: str, student_thought: str = ""):
        hay = f"{question_type}，{stem}，{student_thought}"
        scored = []
        for p in self.lib.policies:
            score = 0.0
            hits = []
            cat = p.get("category", "")
            if question_type and (question_type in cat or cat in question_type):
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
        flow = [s for s in scored if s[2].get("category") == "解题流程"]
        rules = [s for s in scored if s[2].get("category") != "解题流程"]
        return flow[:2], rules[:5]

    def find_cases(self, stem: str, top=2):
        scored = []
        tokens = set(phrases(stem, MIN_LEN))
        for c in self.lib.question_cases:
            c_text = f"{c.get('title')} {c.get('stem')} {c.get('analysis', {}).get('law_located')}"
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
        q_type = question.get("question_type", "")
        stem = question.get("stem", "")
        options = question.get("options", {})
        student_thought = question.get("student_reasoning", "")
        student_choice = question.get("student_choice", "")

        flow, rules = self.rank_policies(q_type, stem, student_thought)
        cases = self.find_cases(stem)
        critiques = self.find_critiques(student_thought)

        lines = [
            "# 🏛️ L 老师 · 逻辑判断讲题报告",
            f"**题型定位**：{q_type}",
            f"**题干核心**：{stem}...",
            "",
            "## 一、 教师解题心法与核心口诀"
        ]
        if flow:
            for _, hits, p in flow:
                lines.append(f"- **【{p['name']}】** ({p['policy_id']})")
                lines.append(f"  > 规则要领：{p['rule']}")
        if rules:
            for _, hits, p in rules:
                lines.append(f"- **【{p['name']}】** ({p['policy_id']})（命中特征：{', '.join(hits[:3])}）")
                lines.append(f"  - 规则：{p['rule']}")
                for src in p.get("source", []):
                    lines.append(f"  - 来源：{src.get('file', src.get('course'))}，行{src.get('line_start', '待核对')}")
                lines.append(f"  - 避坑：{', '.join(p.get('forbidden_transformations', []) or ['注意因果时序与边界'])}")
        else:
            lines.append("- 紧扣论证核心三圈，削弱看因果倒置与另有他因，支持用搭桥与排除他因。")

        lines.append("")
        lines.append("## 二、 课堂相似真题推演")
        if cases:
            for c in cases:
                lines.append(f"### 典例：{c['title']} ({c['question_id']})")
                lines.append(f"- **题目来源**：{c.get('source_exam', '课堂经典例题')}")
                lines.append(f"- **课件原文解析**：{c.get('teacher_reasoning', '')}")
                for src in c.get("source", []):
                    lines.append(f"- **来源**：{src.get('file')}，第{src.get('page')}页")
                lines.append(f"- **课件例题答案（不是本题答案）**：{c.get('answer', '')}")
        else:
            lines.append("未直接检索到高重合度课堂母题，请直接运用上述规则推演。")

        lines.extend(["", "## 当前题核验状态", "以上为教学方法和课件参考，并非本题答案。当前题的计算、选项和错因须另行核验。"])
        if options:
            lines.extend(["", "## 当前题选项", json.dumps(options, ensure_ascii=False)])
        lines.append("不同选项必须逐项核验，不可直接采用相似题答案；未核验的学生思路不作错误诊断。")
        return "\n".join(lines)
