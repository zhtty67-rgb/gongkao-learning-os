# -*- coding: utf-8 -*-
"""P 老师政治理论讲题引擎：规则检索、真题匹配、纠偏识别与报告生成。"""

import json
from pathlib import Path
from library import FengzeLibrary, phrases

MIN_LEN = 2

class FengzeExplainEngine:
    def __init__(self, base_dir=None):
        self.lib = FengzeLibrary(base_dir)

    def rank_policies(self, question_type: str, stem: str, student_thought: str = ""):
        hay = f"{question_type} {stem} {student_thought}".lower()
        scored = []
        for p in self.lib.policies:
            if p.get("verification_status") == "quarantined":
                continue
            score = 0.0
            hits = []
            cat = p.get("category", "")
            name = p.get("name", "")
            trigger = p.get("trigger", "")
            conditions = p.get("conditions", "")
            rule = p.get("rule", "")

            # 题型/分类直接匹配
            if question_type:
                q_clean = question_type.replace("题", "").strip()
                if q_clean and (q_clean in cat or q_clean in name or q_clean in trigger):
                    score += 6.0
                    hits.append(f"题型:{question_type}")

            # 核心主题关键词特征匹配
            topic_weights = [
                ("二十届三中全会", ["三中全会", "深化改革", "2029", "2035", "以制度建设为主线", "以经济体制改革为牵引"]),
                ("中央经济工作会议", ["中央经济工作会议", "稳中求进", "以进促稳", "先立后破", "宏观政策取向一致性"]),
                ("政府工作报告", ["政府工作报告", "预期目标", "赤字率", "超长期特别国债", "两重", "两新"]),
                ("中央一号文件", ["中央一号文件", "千万工程", "粮食安全", "返贫", "农业强国"]),
                ("中国式现代化", ["中国式现代化", "本质要求", "共同富裕", "五大特色"]),
                ("高质量发展与新质生产力", ["高质量发展", "新质生产力", "因地制宜", "全要素生产率"]),
                ("哲学基本问题与唯物论", ["第一性", "思维与存在", "主观唯心", "客观唯心", "古代朴素", "近代形而上学", "客观实在性", "庸俗唯物"]),
                ("辩证法两大特征与三大规律", ["主要矛盾", "次要矛盾", "主要方面", "次要方面", "度", "关节点", "否定之否定", "螺旋式上升", "普遍联系"]),
                ("认识论与实践观", ["实践是认识", "认识的来源", "唯一源泉", "真理客观性", "有用即真理"]),
                ("唯物史观与基本矛盾", ["社会存在", "社会意识", "生产力", "生产关系", "经济基础", "上层建筑", "生产工具"]),
                ("政治经济学", ["商品二因素", "劳动二重性", "使用价值", "价值", "抽象劳动", "具体劳动", "剩余价值", "超额剩余价值", "相对剩余价值"]),
                ("排他做题心法", ["创业带动就业", "就业带动创业", "关键词互换", "偷换概念", "绝对化", "彻底", "完全", "初次分配", "再分配", "第三次分配"])
            ]

            for topic_name, kws in topic_weights:
                if any(kw.lower() in hay for kw in kws):
                    if any(kw.lower() in f"{cat} {name} {trigger} {conditions} {rule}".lower() for kw in kws):
                        score += 4.5
                        hits.append(topic_name)

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
        q_type = question.get("question_type", question.get("topic", "政治理论题"))
        stem = question.get("stem", "")
        options = question.get("options", {})
        student_thought = question.get("student_reasoning", question.get("student_thought", ""))
        student_choice = question.get("student_choice", question.get("user_selected", ""))

        matched_policies = self.rank_policies(q_type, stem, student_thought)
        cases = self.find_cases(stem)
        critiques = self.find_critiques(student_thought)

        lines = [
            "# 🎙️ P 老师 · 政治理论名师讲题报告",
            "",
            f"**授课教师**：{self.lib.profile.get('name', 'P 老师（政治理论）')} | {self.lib.profile.get('title', '协作组公考政治理论主讲名师')}",
            f"**模块归属**：{self.lib.profile.get('module', '政治理论')} | **题型定性**：{q_type}",
            "",
            "---",
            "",
            "### 📖 【题目原卷与情境】",
            f"**题干**：{stem}",
            ""
        ]

        if options:
            lines.append("**选项设置**：")
            for k in sorted(options.keys()):
                lines.append(f"- **{k}**. {options[k]}")
            lines.append("")

        lines.extend([
            "---",
            "",
            "### 🎯 【核心规则与定性指引】"
        ])

        if matched_policies:
            for score, hits, pol in matched_policies[:2]:
                lines.append(f"#### 📌 规则：{pol.get('name')}（{pol.get('policy_id')}）")
                lines.append(f"- **适用类别**：`{pol.get('category')}`")
                lines.append(f"- **触发条件**：{pol.get('trigger')}")
                lines.append("- **解题步骤**：")
                for s in pol.get("steps", []):
                    lines.append(f"  1. {s}")
                lines.append(f"- **适用边界与反例**：{pol.get('boundaries')}")
                lines.append(f"> 💬 **P 老师课堂要领**：“{pol.get('quote')}”")
                lines.append("")
        else:
            lines.append("本题为政治理论综合考查题，建议严格从唯物辩证定性与政策官方表述入手，抓住主体定语，严防关键词顺序互换。\n")

        lines.extend([
            "---",
            "",
            "### 💡 【课堂精讲与推导演进】"
        ])

        if cases:
            primary_case = cases[0]
            lines.append(f"**考点深度剖析**：")
            lines.append(primary_case.get("teacher_analysis", "围绕题干核心概念与逻辑因果展开深入辨析。"))
            lines.append("")
            lines.append(f"**干扰项与命题陷阱**：")
            lines.append(primary_case.get("trap_explanation", "警惕定语偷换、主客倒置、年代错位与绝对化夸大。"))
            lines.append("")
        else:
            lines.append("1. **审清核心范畴**：先找准设问中心词，判断属于马原哲学原理、新思想体系还是重大会议时政。")
            lines.append("2. **逐项比对定语**：警惕关键词颠倒（如创业带动就业 vs 就业带动创业）与偷换主体（如初次分配 vs 再分配）。")
            lines.append("3. **严守时效边界**：涉及具体文件与会议（如三中全会、经济工作会议、政府工作报告），严格锁定2024-2025已知历史事实，切忌超前盲猜。\n")

        if student_thought or student_choice:
            lines.extend([
                "---",
                "",
                "### 🩺 【学员思路诊断与纠偏警示】",
                f"- **学员选择**：`{student_choice}`" if student_choice else "- **学员作答**：未明确提供选择",
                f"- **思考过程记录**：{student_thought}" if student_thought else ""
            ])
            if critiques:
                crit = critiques[0]
                lines.append(f"\n⚠️ **常见思维陷阱**：{crit.get('student_misconception')}")
                lines.append(f"📢 **P 老师老师当堂纠错**：{crit.get('teacher_refutation')}")
                lines.append(f"> 🎙️ **原话警示**：“{crit.get('quote')}”")
                lines.append(f"🛡️ **破解锦囊**：{crit.get('counter_strategy')}\n")
            else:
                lines.append("\n政治理论选项做错，绝大多数不是因为背不下来，而是做题时盲目相信‘语感顺口’！必须回文严格比对修饰词和主谓宾先后关系。\n")

        lines.extend([
            "---",
            "",
            "### 🔑 【P 老师名师总结】",
            f"> “{self.lib.profile.get('classic_quotes', ['以谁为牵引？是以经济体制改革为牵引！'])[0]}”",
            ""
        ])

        return "\n".join(lines)
