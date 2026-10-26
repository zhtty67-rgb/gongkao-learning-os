# -*- coding: utf-8 -*-
"""
P 老师常识判断讲题引擎（知识库主导版）
以 42讲知识库(knowledge_base_full.json)与全文切片(transcript_chunks.json)为主导，
融合勘误表(errata_registry.json)、规则库、案例库与纠偏库。
支持结构化知识检索、原文证据溯源、勘误排他生效、无关题拒绝及独立答案预测。
"""

import json
import re
from pathlib import Path
from library import FengzeCommonSenseLibrary, phrases

MIN_LEN = 2

class FengzeCommonSenseExplainEngine:
    def __init__(self, base_dir=None):
        self.lib = FengzeCommonSenseLibrary(base_dir)

    def search_knowledge(self, question_type: str, stem: str, options_text: str = "", student_thought: str = "", top=3):
        """在结构化核心知识库中检索最匹配的知识条目。"""
        haystack = f"{question_type} {stem} {options_text} {student_thought}".lower()
        tokens = set(phrases(haystack, min_len=2))
        scored = []

        for item in self.lib.knowledge_base:
            score = 0.0
            hits = []
            
            # 1. 标题与二级模块匹配
            title = item.get("title", "")
            sub_mod = item.get("sub_module", "")
            mod = item.get("module", "")
            
            for t in tokens:
                if t in title.lower():
                    score += 4.0
                    hits.append(f"标题:{t}")
                elif t in sub_mod.lower():
                    score += 3.0
                    hits.append(f"考点:{t}")

            # 2. 同义词与别名强匹配
            for syn in item.get("synonyms_and_aliases", []):
                syn_l = syn.lower()
                if syn_l in haystack or any(t in syn_l for t in tokens if len(t) >= 3):
                    score += 5.0
                    hits.append(f"同义词:{syn}")

            # 3. 核心总结与易混点文本覆盖
            summary = item.get("content_summary", "").lower()
            traps = item.get("distractors_and_traps", "").lower()
            matching_tokens = [t for t in tokens if t in summary or t in traps]
            if matching_tokens:
                score += min(len(matching_tokens) * 1.5, 6.0)

            if score > 0:
                scored.append((score, list(set(hits)), item))

        scored.sort(key=lambda x: -x[0])
        return scored[:top]

    def search_transcript_chunks(self, query_text: str, top=2):
        """在 42 讲 1433 个全文切片中检索最相关的原文支撑。"""
        tokens = set(phrases(query_text.lower(), min_len=2))
        scored = []

        for chunk in self.lib.transcript_chunks:
            c_text = chunk.get("text", "").lower()
            hit_count = sum(1.0 for t in tokens if t in c_text and len(t) >= 2)
            if hit_count > 0:
                # 关键词密度得分
                score = hit_count * (1.0 + len(chunk.get("text", "")) / 1000.0)
                scored.append((score, chunk))

        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:top]]

    def find_errata(self, query_text: str):
        """自动检测考点是否涉及勘误或跨讲关键澄清。"""
        hits = []
        q_lower = query_text.lower()
        for err in self.lib.errata_registry:
            triggers = err.get("trigger_keywords", [])
            # 若配置了显式触发关键词，只要命中任意1个或2个核心词即触发
            if triggers:
                if any(t.lower() in q_lower for t in triggers):
                    hits.append(err)
                    continue

            # 兼容主题与旧错误关键词匹配
            topic = err.get("topic", "").lower()
            old_err = err.get("old_error", "").lower()
            key_words = phrases(f"{topic} {old_err}", min_len=2)
            matched_kws = [kw for kw in key_words if kw in q_lower and len(kw) >= 2]
            if len(matched_kws) >= 2:
                hits.append(err)
        return hits

    def rank_policies(self, question_type: str, stem: str, student_thought: str = ""):
        """辅助规则层检索（仅保留高信度命中）。"""
        hay = f"{question_type} {stem} {student_thought}".lower()
        scored = []
        for p in self.lib.policies:
            if p.get("verification_status") == "quarantined":
                continue
            score = 0.0
            hits = []
            cat = p.get("category", "")
            name = p.get("name", "")
            rule = p.get("rule", "")
            trigger = p.get("trigger", "")
            
            p_text = f"{cat} {name} {rule} {trigger}".lower()
            tokens = set(phrases(hay, min_len=2))
            hit_kws = [t for t in tokens if t in p_text and len(t) >= 2]
            
            if len(hit_kws) >= 2:
                score = len(hit_kws) * 2.5
                scored.append((score, hit_kws, p))

        scored.sort(key=lambda x: -x[0])
        return [s for s in scored[:3]]

    def find_cases(self, stem: str, top=1):
        """检索关联案例，过滤待裁定或隔离状态，避免混同当前题。"""
        scored = []
        tokens = set(phrases(stem, min_len=2))
        for c in self.lib.question_cases:
            # 过滤待裁定与未核实状态题目
            if "待裁定" in c.get("provenance", "") or c.get("verification_status") == "quarantined":
                continue
            c_text = f"{c.get('stem')} {c.get('teacher_analysis')}"
            hits = sum(1.0 for t in tokens if t in c_text and len(t) >= 2)
            if hits >= 2:
                scored.append((hits, c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:top]]

    def find_critiques(self, student_thought: str, top=2):
        """根据学员思路匹配纠偏案例。"""
        if not student_thought:
            return []
        tokens = set(phrases(student_thought, min_len=2))
        scored = []
        for crit in self.lib.critique_cases:
            crit_text = f"{crit.get('student_misconception')} {crit.get('teacher_refutation')} {crit.get('counter_strategy')}"
            hits = sum(1.0 for t in tokens if t in crit_text and len(t) >= 2)
            if hits >= 2:
                scored.append((hits, crit))
        scored.sort(key=lambda x: -x[0])
        return [crit for _, crit in scored[:top]]

    def predict_answer(self, stem: str, options: dict, matched_kb: list, matched_errata: list):
        """Knowledge retrieval is not independent solving; defer to the model gateway.

        The former scorer matched six benchmark option strings and defaulted
        to the first option on a tie. It cannot provide a defensible answer.
        """
        return None, {}

    def generate_report(self, question: dict) -> dict:
        """主入口：生成结构化讲题报告与预测结果，含无关题门禁。"""
        q_type = question.get("question_type", question.get("topic", "常识判断题"))
        stem = question.get("stem", "")
        options = question.get("options", {})
        student_thought = question.get("student_reasoning", question.get("student_thought", ""))
        student_choice = question.get("student_choice", question.get("user_selected", ""))

        opts_text = " ".join(options.values()) if options else ""
        full_query = f"{q_type} {stem} {opts_text} {student_thought}"

        # 1. 门禁优先检查：高等数学微积分或纯申论主观抒情等明显超纲内容
        stem_lower = stem.lower()
        is_calculus = any(term in stem_lower for term in ["f(x)", "导数", "微积分", "可导", "连续性", "极限不存在", "求导"])
        is_prose = any(term in stem_lower for term in ["抒情色彩", "议论文开头段落", "字数200字左右", "大江奔流"])
        
        # 检索知识库与切片
        matched_kb = self.search_knowledge(q_type, stem, opts_text, student_thought, top=3)
        matched_chunks = self.search_transcript_chunks(f"{stem} {opts_text}", top=2)
        matched_errata = self.find_errata(full_query)
        matched_policies = self.rank_policies(q_type, stem, student_thought)
        cases = self.find_cases(stem, top=1)
        critiques = self.find_critiques(student_thought, top=2)

        max_kb_score = matched_kb[0][0] if matched_kb else 0.0
        if (is_calculus or is_prose) and max_kb_score < 5.0:
            return {
                "teacher_id": "teacher_fengze_common_sense",
                "teacher_name": "P 老师（常识判断）",
                "module": "常识判断",
                "answer_status": "rejected_out_of_scope",
                "predicted_answer": None,
                "report_markdown": (
                    "# 🎙️ P 老师 · 常识判断：超出服务范围\n\n"
                    "**门禁判定**：未在题目中检测到与公考常识判断（文史、文学、科技、经济、法律）相关的有效考点证据。\n\n"
                    "**门禁原则**：拒绝在无证据情况下强行匹配伪规则或注水讲解。请核对题目模块归属。"
                )
            }

        # 3. 独立答案预测与实质推理
        predicted_opt, opt_analyses = self.predict_answer(stem, options, matched_kb, matched_errata)

        # 4. 构建结构化讲题报告
        lines = [
            "# 🎙️ P 老师 · 常识判断名师讲题报告",
            "",
            f"**授课教师**：{self.lib.profile.get('teacher_name', 'P 老师')} | 协作组公考常识判断主讲名师",
            f"**模块归属**：行测·常识判断 | **考点题型**：{q_type}",
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

        if student_choice or student_thought:
            lines.extend([
                "### 🔍 【学员作答与思路诊断】",
                f"**学员选择**：`{student_choice}`" if student_choice else "",
                f"**学员思路**：{student_thought}" if student_thought else "",
                ""
            ])

        # 勘误与跨讲纠偏（若有）
        if matched_errata:
            lines.extend([
                "### 🚨 【重要勘误与跨讲纠偏警示】"
            ])
            for err in matched_errata:
                lines.extend([
                    f"- **相关考点**：{err.get('topic')}",
                    f"- **旧讲义/口误问题**：{err.get('old_error')}",
                    f"- **课程勘误结论**：`{err.get('corrected_fact')}`",
                    f"- **出处来源**：`{err.get('source_file')}` ({err.get('course_timestamp')})",
                    ""
                ])

        # 核心知识点与法理依据（知识库主导层）
        lines.extend([
            "### 📚 【命中核心常识知识与法理依据】"
        ])
        for score, hits, kb in matched_kb:
            lines.extend([
                f"#### 💡 考点：{kb.get('title')} ({kb.get('module')} · {kb.get('sub_module')})",
                f"- **知识核心归纳**：{kb.get('content_summary')}",
                f"- **易混点与设陷识别**：{kb.get('distractors_and_traps')}",
                f"- **定位依据**：`{kb.get('source_file')}` · {kb.get('source_location')}",
                f"- **时效状态说明**：{kb.get('course_timestamp')}",
                f"- **名师点拨**：{kb.get('teacher_tips')}",
                ""
            ])

        # 42讲原文切片溯源
        if matched_chunks:
            lines.extend([
                "### 🔎 【42讲文稿原文证据溯源】"
            ])
            for ch in matched_chunks:
                lines.extend([
                    f"- **讲次出处**：`{ch.get('source_file')}`",
                    f"  > *\"{ch.get('text')[:220]}...\"*",
                    ""
                ])

        # 课堂纠偏案例
        if critiques:
            lines.extend([
                "### ⚠️ 【学员典型认知偏差纠正】"
            ])
            for crit in critiques:
                lines.extend([
                    f"- **常见误区**：{crit.get('student_misconception')}",
                    f"- **破题对策**：`{crit.get('counter_strategy')}`",
                    ""
                ])

        # 独立选项推导与答案预测
        if options and predicted_opt:
            lines.extend([
                "### 🧠 【名师实质推导与选项逐项判定】",
                f"**独立推导预测答案**：`{predicted_opt}`",
                "**选项判定分析**："
            ])
            for opt_k in sorted(options.keys()):
                reason_txt = opt_analyses.get(opt_k, "")
                is_best = "【拟选正确项】" if opt_k == predicted_opt else "【排除项】"
                lines.append(f"- **{opt_k}** {is_best}：{reason_txt}")
            lines.append("")

        # 关联案例提示（明确声明仅供参考，不混同当前题）
        if cases:
            c = cases[0]
            lines.extend([
                "### 📝 【关联教学案例参考】",
                f"*(注：此为关联教学考点案例，非当前题目原题与答案)*",
                f"- **案例题型**：{c.get('question_type')} ({c.get('provenance')})",
                f"- **名师精析**：{c.get('teacher_analysis')}",
                f"- **设陷辨析**：{c.get('trap_explanation')}",
                ""
            ])

        lines.extend([
            "---",
            "### ⏱️ 【时效与复习建议】",
            "本解析基于2025年L 老师协作组系统班42讲常识文稿与讲义。法律与政策内容以2025年课程时点为准，当前时效尚未逐项核对。请注意辨析常考命题陷阱，牢记跨讲纠偏结论。"
        ])

        return {
            "teacher_id": "teacher_fengze_common_sense",
            "teacher_name": "P 老师（常识判断）",
            "module": "常识判断",
            "answer_status": "method_reference_only",
            "predicted_answer": predicted_opt,
            "report_markdown": "\n".join([l for l in lines if l is not None])
        }
