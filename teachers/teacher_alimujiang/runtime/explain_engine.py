# -*- coding: utf-8 -*-
"""A 老师言语理解与表达讲题引擎：规则检索、案例推演与报告生成。"""

import json
from pathlib import Path
from library import AlimujiangLibrary, phrases

MIN_LEN = 2

class AlimujiangExplainEngine:
    def __init__(self, base_dir=None):
        self.lib = AlimujiangLibrary(base_dir)

    def rank_policies(self, question_type: str, stem: str, student_thought: str = ""):
        hay = f"{question_type} {stem} {student_thought}".lower()
        scored = []
        for p in self.lib.policies:
            score = 0.0
            hits = []
            cat = p.get("category", "")
            name = p.get("name", "")
            trigger = p.get("trigger", "")
            conditions = p.get("conditions", "")

            # 题型/分类匹配
            if question_type:
                q_clean = question_type.replace("题", "").strip()
                if q_clean and (q_clean in cat or q_clean in name or q_clean in trigger):
                    score += 6.0
                    hits.append(f"题型:{question_type}")

            # 核心关键词特征匹配
            kw_weights = [
                ("转折", ["转折", "但是", "然而", "却", "其实", "实际上"]),
                ("因果", ["因果", "因此", "所以", "导致", "造成", "之所以"]),
                ("对策", ["对策", "必须", "应该", "应当", "需要", "务必", "唯有"]),
                ("反面论证", ["如果", "否则", "反之", "假使", "一旦"]),
                ("并列", ["并列", "此外", "另外", "同时", "一方面"]),
                ("细节", ["细节", "相符", "不相符", "正确的一项", "不正确的一项"]),
                ("排序", ["排序", "①", "②", "③", "④", "首句"]),
                ("填空", ["填入横线", "画横线处", "填入最恰当", "衔接"]),
                ("比喻", ["比喻", "形象", "犹如", "如同", "野马", "伺候"]),
                ("成语", ["成语", "词语", "逻辑填空", "正本清源", "拨乱反正", "闭门造车"]),
                ("篇章", ["篇章", "自然段", "第一段", "全文"])
            ]

            for group_name, kws in kw_weights:
                if any(kw in hay for kw in kws):
                    if any(kw in cat or kw in name or kw in trigger or kw in conditions for kw in kws):
                        score += 3.5
                        hits.append(group_name)

            for f in set(phrases(name, MIN_LEN)):
                if f.lower() in hay:
                    score += 2.0
                    hits.append(f)

            if score > 0:
                scored.append((score, list(set(hits)), p))

        scored.sort(key=lambda x: -x[0])
        return [s for s in scored[:4]]

    def find_cases(self, stem: str, top=2):
        scored = []
        tokens = set(phrases(stem, MIN_LEN))
        for c in self.lib.question_cases:
            c_text = f"{c.get('stem')} {c.get('teacher_analysis')}"
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
            crit_text = f"{crit.get('student_misconception')} {crit.get('teacher_refutation')} {crit.get('counter_strategy')}"
            hits = sum(1.0 for t in tokens if t in crit_text)
            if hits > 0:
                scored.append((hits, crit))
        scored.sort(key=lambda x: -x[0])
        return [crit for _, crit in scored[:top]]

    def generate_report(self, question: dict) -> str:
        q_type = question.get("question_type", question.get("topic", "言语理解题"))
        stem = question.get("stem", "")
        options = question.get("options", {})
        student_thought = question.get("student_reasoning", "")
        student_choice = question.get("student_choice", "")

        matched_policies = self.rank_policies(q_type, stem, student_thought)
        cases = self.find_cases(stem)
        critiques = self.find_critiques(student_thought)

        lines = [
            "# 🎙️ A 老师 · 言语理解讲题报告",
            f"**授课教师**：A 老师",
            f"**题型定位**：{q_type}",
            f"**题干切片**：{stem[:120]}{'...' if len(stem) > 120 else ''}",
            "",
            "## 一、 A 老师解题心法与核心规则"
        ]

        if matched_policies:
            for score, hits, p in matched_policies:
                lines.append(f"### 💡 【{p['name']}】 (`{p['policy_id']}`)")
                lines.append(f"- **适用条件**：{p['conditions']}")
                lines.append("- **解题步骤**：")
                for st in p.get("steps", []):
                    lines.append(f"  - {st}")
                lines.append(f"- **课堂金句**：> \"{p['quote']}\"")
                lines.append(f"- **来源出处**：2026系统班第 {p['source_lecture']} 讲，原字幕行 {p['source_raw_line']}（讲义P{p.get('source_page', '见目录')}）")
                lines.append(f"- **避坑防线**：{p['boundaries']}")
                lines.append("")
        else:
            lines.append("- 记住A 老师经典做题原则：先看提问方式定型，读一句预判一句！如果是对策，选项找等价意义；如果是逻辑填空，必须在文段里找客观线索！\n")

        if critiques:
            lines.append("## 二、 学员思路诊断与一针见血纠偏")
            for crit in critiques:
                lines.append(f"- **常见错误思路**：{crit['student_misconception']}")
                lines.append(f"- **A 老师纠偏**：{crit['teacher_refutation']}")
                lines.append(f"  > 课堂原话：\"{crit['quote']}\"（第 {crit['lecture_id']} 讲，第 {crit['source_raw_line']} 行）")
                lines.append(f"- **防坑心法**：{crit['counter_strategy']}")
                lines.append("")

        lines.append("## 三、 课堂相似真题推演")
        if cases:
            for cs in cases:
                lines.append(f"### 典例：{cs['question_type']} (来源第 {cs['lecture_id']} 讲)")
                lines.append(f"**题干**：{cs['stem']}")
                if cs.get("options"):
                    lines.append("**选项**：")
                    for k, v in cs["options"].items():
                        lines.append(f"  - {k}. {v}")
                lines.append(f"**正确答案**：{cs['correct_answer']}")
                lines.append(f"**名师精析**：{cs['teacher_analysis']}")
                lines.append(f"**陷阱排查**：{cs['trap_explanation']}")
                lines.append("")
        else:
            lines.append("- （暂无直接同题干案例，已由核心方法规则提供支撑）\n")

        lines.append("## 四、 本题选项剖析与最终总结")
        if options:
            lines.append("结合A 老师的解题原则分析各选项：")
            for k, v in options.items():
                is_user = f"【学员选择】" if k == student_choice else ""
                lines.append(f"- **{k} 选项** {is_user}：{v}")
        if student_thought:
            lines.append(f"\n**学员原思考诊断**：学员提到「{student_thought}」。请牢记A 老师老师提醒：不可凭主观语感盲猜，紧扣文段逻辑骨架与对策落实！")

        return "\n".join(lines)
