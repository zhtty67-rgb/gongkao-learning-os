# -*- coding: utf-8 -*-
"""G 老师图推讲题引擎：确定性检索 + 报告合成。

输入是题目的**文字描述**（逐图转述），引擎做三件事：
1) 按识别特征/触发条件检索G 老师的方法规则（policies），
2) 按题面相似度检索课堂真题案例（question cases），
3) 有学生思路时检索课堂纠偏实录（critique cases），
合成一份"G 老师式讲题报告"，所有结论均可反查知识 ID。
引擎不看图、不发明规律——只会讲G 老师讲过的东西。
"""

import re

from library import LongfeiLibrary, phrases

# 识别特征短语最低长度（避免"线""面"单字噪声）
MIN_FEATURE_LEN = 2
GENERIC_APPLIES = {"通用", ""}


def _text_of(entry) -> str:
    """把案例压成检索用文本。"""
    a = entry.get("analysis") or {}
    parts = [entry.get("title", ""), entry.get("figure_description", ""),
             a.get("law_located", ""), "，".join(a.get("key_points", []) or [])]
    return "，".join(str(x) for x in parts if x)


class ExplainEngine:
    def __init__(self, base=None):
        self.lib = LongfeiLibrary(base)
        self._case_texts = [(c, _text_of(c)) for c in self.lib.question_cases]

    # ---------- 检索 ----------
    def rank_policies(self, question_format: str, feature_text: str, focus: str = ""):
        """返回 (流程骨架, 候选规律) 两组排序后的政策。"""
        hay = f"{feature_text}，{focus or ''}"
        scored = []
        for p in self.lib.policies:
            score, hits = 0.0, []
            applies = set(p.get("applies_to") or [])
            if question_format and question_format != "unknown":
                if question_format in applies:
                    score += 4.0
                elif applies and not (applies & GENERIC_APPLIES):
                    score -= 1.5  # 题型不匹配的降权（政策只对其他题型成立）
            for f in set(phrases(p.get("identification_features"), MIN_FEATURE_LEN)):
                if f in hay:
                    score += 3.0
                    hits.append(f)
            for f in set(phrases(p.get("trigger"), MIN_FEATURE_LEN)):
                if f in hay:
                    score += 1.5
                    hits.append(f)
            for f in set(phrases(p.get("name"), MIN_FEATURE_LEN)):
                if f in hay:
                    score += 1.0
                    hits.append(f)
            if score > 0:
                scored.append((score, hits, p))
        scored.sort(key=lambda x: -x[0])

        flow = [s for s in scored if s[2].get("category") == "解题流程"]
        rules = [s for s in scored if s[2].get("category") != "解题流程"]
        return flow[:3], rules[:8]

    def similar_cases(self, question_format: str, feature_text: str, top=3):
        qf_bonus = 2.0 if question_format and question_format != "unknown" else 0.0
        hay_phrases = set(phrases(feature_text, MIN_FEATURE_LEN))
        scored = []
        for c, text in self._case_texts:
            score = sum(1.0 for ph in hay_phrases if ph and ph in text)
            if c.get("question_format") == question_format:
                score += qf_bonus
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        return scored[:top]

    def critique_for(self, feature_text: str, student_reasoning: str = "", top=3):
        hay = f"{feature_text}，{student_reasoning or ''}"
        hay_phrases = set(phrases(hay, MIN_FEATURE_LEN))
        scored = []
        for c in self.lib.critique_cases:
            text = "，".join([c.get("question", ""), c.get("diagnosis", ""),
                              c.get("remedy_instruction", ""), c.get("student_error_snippet", "")])
            score = sum(1.0 for ph in hay_phrases if ph and ph in text)
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: -x[0])
        return scored[:top]

    # ---------- 报告合成 ----------
    def explain(self, question: dict) -> str:
        qf = question.get("question_format") or "unknown"
        fig = question.get("figure_description") or ""
        focus = question.get("focus") or ""
        student = question.get("student_reasoning") or ""

        flow, rules = self.rank_policies(qf, fig, focus)
        cases = self.similar_cases(qf, fig)
        critiques = self.critique_for(fig, student) if student else []

        lines = ["# G 老师图推讲题报告", ""]
        lines.append(f"**题型**：{qf}")
        if fig:
            lines.append(f"**图形描述**：{fig}")
        if student:
            lines.append(f"**学生思路**：{student}")
        lines.append("")
        lines.append("> 引擎只讲G 老师课上的方法，每条结论带知识 ID 可反查（library/policies_full.json 等）。")

        lines += ["", "## 一、先对齐颗粒度（G 老师的看图顺序）"]
        if flow:
            for score, hits, p in flow:
                lines.append(f"- **{p['name']}**（{p['policy_id']}）：{p['rule']}")
        else:
            lines.append("- 未命中流程类政策；按G 老师总纲：先判断这组图考哪个维度，再进具体规律。")

        lines += ["", "## 二、规律定位候选（按识别特征命中排序）"]
        if rules:
            for i, (score, hits, p) in enumerate(rules, 1):
                lines.append(f"{i}. **{p['name']}**（{p['policy_id']}，{p['category']}）")
                lines.append(f"   - 规则：{p['rule']}")
                if hits:
                    lines.append(f"   - 命中特征：{'、'.join(sorted(set(hits)))}")
                ft = p.get("forbidden_transformations") or []
                if ft:
                    lines.append(f"   - 易错警告：{'；'.join(ft[:2])}")
        else:
            lines.append("未命中具体规律。G 老师的观点：单幅图不定规律，先回题干找共性，再用选项差异反推。")

        lines += ["", "## 三、相似课堂真题"]
        if cases:
            for score, c in cases:
                a = c.get("analysis") or {}
                lines.append(f"- **{c['title']}**（{c['question_id']}，{c.get('question_format','unknown')}"
                             f"{('，' + c['source_exam']) if c.get('source_exam') and c.get('source_exam') != '课堂讲解题' else ''}）")
                if a.get("entry_features"):
                    lines.append(f"  - 识别特征：{'；'.join(a['entry_features'][:3])}")
                if a.get("law_located"):
                    lines.append(f"  - 定位规律：{a['law_located']}")
                if c.get("answer") and c["answer"] != "unknown":
                    lines.append(f"  - 课堂答案：{c['answer']}")
        else:
            lines.append("- 案例库中未找到相似题（图推案例的图形均为课堂口头描述，建议补充更细的图形文字描述）。")

        lines += ["", "## 四、易错与纠偏提醒"]
        if critiques:
            for score, c in critiques:
                lines.append(f"- **{c['error_type']}**（{c['case_id']}）：{c['diagnosis']}")
                if c.get("remedy_instruction"):
                    lines.append(f"  - 纠正：{c['remedy_instruction']}")
        else:
            lines.append("- 未提供学生思路或未命中纠偏案例。")

        lines += ["", "## 五、诚实声明"]
        lines.append("- 图形推理题目本体是图形；本引擎基于题目文字描述检索，图形细节描述越完整，检索越可靠。")
        lines.append("- 案例库答案为G 老师课堂口述（个别题课堂未报答案，标 unknown）；老师前后冲突处按宪法双写保留。")
        return "\n".join(lines)


def run(question: dict, base=None) -> str:
    return ExplainEngine(base).explain(question)
