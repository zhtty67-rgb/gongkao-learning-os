# -*- coding: utf-8 -*-
"""定义判断讲题引擎：确定性规则检索与教师讲题报告合成。"""

import json

from library import DefinitionLibrary, phrases

MIN_LEN = 2

class DefinitionExplainEngine:
    def __init__(self, base_dir=None):
        self.lib = DefinitionLibrary(base_dir)

    def rank_policies(self, term: str, definition_body: str, student_thought: str = ""):
        hay = f"{term}，{definition_body}，{student_thought}"
        scored = []
        for p in self.lib.policies:
            score = 0.0
            hits = []
            cat = p.get("category", "")
            # 基础解题方法天然有基础分
            if cat in ["被定义词拆解", "核心要素拆解", "圈词避坑原则"]:
                score += 5.0
                hits.append("定义通用方法")
            if "法律" in hay and ("法律" in cat or "法律" in p.get("name", "")):
                score += 8.0
                hits.append("法律类专业定义")
            if any(k in hay for k in ["效应", "博弈", "心理", "崩溃", "失调"]) and "心理学" in p.get("name", ""):
                score += 8.0
                hits.append("心理学/效应类定义")
            for f in set(phrases(p.get("identification_features"), MIN_LEN)):
                if f in hay:
                    score += 3.0
                    hits.append(f)
            for f in set(phrases(p.get("name"), MIN_LEN)):
                if f in hay:
                    score += 2.0
                    hits.append(f)
            scored.append((score, list(set(hits)), p))
        scored.sort(key=lambda x: -x[0])
        return scored[:3]

    def find_cases(self, term: str, definition_body: str, top=2):
        scored = []
        tokens = set(phrases(f"{term} {definition_body}", MIN_LEN))
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
        term = question.get("term", "")
        definition_body = question.get("definition_body") or question.get("stem", "")
        options = question.get("options", {})
        student_choice = question.get("student_choice", "")
        student_thought = question.get("student_reasoning", "")

        rules = self.rank_policies(term, definition_body, student_thought)
        cases = self.find_cases(term, definition_body)
        critiques = self.find_critiques(student_thought)

        lines = [
            "# 📘 协作组团队 · 定义判断讲题报告",
            f"**被定义词**：【{term}】",
            f"**定义正文摘要**：{definition_body}...",
            "",
            "## 一、 教师解题心法与圈词要领"
        ]
        for _, hits, p in rules:
            lines.append(f"- **【{p['name']}】** ({p['policy_id']})（命中特征：{', '.join(hits[:3])}）")
            lines.append(f"  - 规则要义：{p['rule']}")
            for src in p.get("source", []):
                lines.append(f"  - 来源：{src.get('file', src.get('course'))}，行{src.get('line_start', '待核对')}")
            lines.append(f"  - 避坑原则：{', '.join(p.get('forbidden_transformations', []) or ['防贪多嚼不烂，抓最硬伤'])}")

        lines.append("")
        lines.append("## 二、 课堂相似真题推演")
        if cases:
            for c in cases:
                lines.append(f"### 典例：{c['title']} ({c['question_id']})")
                lines.append(f"- **题源出处**：{c.get('source_exam', '课堂真题精讲')}")
                lines.append(f"- **课件原文解析**：{c.get('teacher_reasoning', '')}")
                for src in c.get("source", []):
                    lines.append(f"- **来源**：{src.get('file')}，第{src.get('page')}页")
                lines.append(f"- **课件例题答案（不是本题答案）**：{c.get('answer', '')}")
        else:
            lines.append("本题为独立场景拓展题，先看被定义词偏正猜想，再核查主体与客体三大要素。")

        lines.extend(["", "## 当前题核验状态", "以上为教学方法和课件参考，并非本题答案。当前题的计算、选项和错因须另行核验。"])
        if options:
            lines.extend(["", "## 当前题选项", json.dumps(options, ensure_ascii=False)])
        lines.append("不同选项必须逐项核验，不可直接采用相似题答案；未核验的学生思路不作错误诊断。")
        return "\n".join(lines)
