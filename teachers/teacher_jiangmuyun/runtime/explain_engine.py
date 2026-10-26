# -*- coding: utf-8 -*-
"""W 老师文段分析核心运行时引擎。"""

import re
from pathlib import Path
from typing import Dict, Any, List

from library import load_profile, load_policies, load_question_cases, load_critique_cases

# 严禁越界的任务关键词正则
ESSAY_PATTERN = re.compile(r"(议论文|大作文|写一篇(文章|短文|作文)|文章写作|分论点|拟定题目|自拟标题)")
OFFICIAL_DOC_PATTERN = re.compile(r"(公文|公开信|倡议书|宣传稿|通知|发言稿|讲话稿|汇报材料|工作方案|编者按|广播稿)")
FULL_PAPER_PATTERN = re.compile(r"(整卷评分|整套题目|全卷批改|模考评分|整卷作答)")
FREE_COUNTERMEASURE_PATTERN = re.compile(r"(脱离材料.*对策|不看材料.*建议|万能对策|自由发挥.*对策|脱离给定资料)")

# 文段分析关联特征词
CAUSAL_WORDS = ["因此", "由于", "因为", "导致", "造成", "使得", "从而", "以至于", "于是"]
TRANSITION_WORDS = ["但是", "然而", "却", "不过", "可是", "反而"]
PARALLEL_WORDS = ["同时", "此外", "另外", "一是", "二是", "三是", "首先", "其次", "再次", "一方面", "另一方面", "；"]
PROGRESSIVE_WORDS = ["不仅", "而且", "更进一步", "进而", "甚至"]
QUALIFIERS = ["部分", "某些", "个别", "一些", "多数", "少数", "特定时期", "县域范围内", "初步", "试点", "逐步"]


class JiangmuyunExplainEngine:
    def __init__(self, base_dir: Path = None):
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent
        self.profile = load_profile(self.base_dir)
        self.policies = load_policies(self.base_dir)
        self.question_cases = load_question_cases(self.base_dir)
        self.critique_cases = load_critique_cases(self.base_dir)

    def check_guardrails(self, text: str) -> Dict[str, Any]:
        """检查请求是否超出W 老师文段分析专属范围。"""
        t = text or ""
        if ESSAY_PATTERN.search(t):
            return {
                "allowed": False,
                "reason": "ESSAY_WRITING_OUT_OF_SCOPE",
                "message": "【范围约束提示】W 老师·文段分析教师专精于给定资料的文段精读、结构拆解、逻辑关系梳理与要点提炼。大作文/议论文写作、分论点构思与全文代写超出此模块范围。本系统禁止生成大作文，建议转交专门的申论文章写作教学教师。"
            }
        if OFFICIAL_DOC_PATTERN.search(t):
            return {
                "allowed": False,
                "reason": "OFFICIAL_DOC_OUT_OF_SCOPE",
                "message": "【范围约束提示】W 老师·文段分析教师专精于材料文段的客观信息提取与逻辑梳理。公文格式（标题、主送机关、发文日期、倡议呼吁等文体套话）超出此模块范围。本系统严禁混入公文起草，建议转交公文与应用文专属教师。"
            }
        if FULL_PAPER_PATTERN.search(t):
            return {
                "allowed": False,
                "reason": "FULL_PAPER_OUT_OF_SCOPE",
                "message": "【范围约束提示】W 老师模块只处理具体材料段落的文段分析，不提供整卷模考评分与全篇整题模板作答。"
            }
        if FREE_COUNTERMEASURE_PATTERN.search(t):
            return {
                "allowed": False,
                "reason": "FREE_COUNTERMEASURE_OUT_OF_SCOPE",
                "message": "【范围约束提示】文段分析严格秉承“尊重材料、依托材料”原则，严禁脱离给定资料主观自由发挥编造对策。请提供具体材料文本以供提炼。"
            }
        return {"allowed": True}

    def analyze_passage(self, material_text: str, question: str = "") -> Dict[str, Any]:
        """执行文段深度拆解与名师规则匹配。"""
        # 1. 越界门禁检查
        guard = self.check_guardrails(f"{question} {material_text}")
        if not guard["allowed"]:
            return {
                "status": "REJECTED_OUT_OF_SCOPE",
                "rejection": guard,
                "teacher_id": "teacher_jiangmuyun",
                "teacher_name": self.profile.get("name", "W 老师·文段分析")
            }

        # 2. 以句子为最小分析单位进行句段拆解
        raw_paras = [p.strip() for p in (material_text or "").splitlines() if p.strip()]
        if not raw_paras and material_text.strip():
            raw_paras = [material_text.strip()]

        paragraphs_analysis = []
        all_sentences = []
        found_transitions = []
        found_causals = []
        found_parallels = []
        found_progressives = []
        found_qualifiers = []

        for p_idx, para in enumerate(raw_paras):
            sents = [s.strip() for s in re.split(r"(?<=[。！？；])", para) if s.strip()]
            all_sentences.extend(sents)

            p_trans = [w for w in TRANSITION_WORDS if w in para]
            p_causal = [w for w in CAUSAL_WORDS if w in para]
            p_paral = [w for w in PARALLEL_WORDS if w in para]
            p_prog = [w for w in PROGRESSIVE_WORDS if w in para]
            p_qual = [w for w in QUALIFIERS if w in para]

            found_transitions.extend(p_trans)
            found_causals.extend(p_causal)
            found_parallels.extend(p_paral)
            found_progressives.extend(p_prog)
            found_qualifiers.extend(p_qual)

            # 段落结构判定
            summary_head_markers = ["指出", "明确", "做法", "推进", "建设", "实施", "建立", "健全", "体系", "坚持", "探索"]
            summary_tail_markers = ["总结", "根本", "核心", "关键", "表明", "成效", "保障"]
            has_summary_head = (len(sents) > 1 and len(sents[0]) <= 40 and any(k in sents[0] for k in summary_head_markers)) or (len(sents) == 1 and len(sents[0]) <= 40 and any(k in sents[0] for k in summary_head_markers))
            has_summary_tail = len(sents) > 1 and len(sents[-1]) <= 40 and any(k in sents[-1] for k in summary_tail_markers)

            structure_type = "并列展开"
            if len(sents) == 1 and has_summary_head:
                structure_type = "总括句独立成段"
            elif has_summary_head and has_summary_tail:
                structure_type = "总分总结构"
            elif has_summary_head:
                structure_type = "总分结构（段首总括）"
            elif has_summary_tail:
                structure_type = "分总结构（段末总结）"
            elif p_trans:
                structure_type = "转折推进结构"

            paragraphs_analysis.append({
                "para_index": p_idx + 1,
                "sentence_count": len(sents),
                "structure_type": structure_type,
                "summary_sentence": sents[0] if has_summary_head else (sents[-1] if has_summary_tail else None),
                "transitions": list(set(p_trans)),
                "causals": list(set(p_causal)),
                "parallels": list(set(p_paral)),
                "progressives": list(set(p_prog)),
                "qualifiers": list(set(p_qual))
            })

        # 3. 统计高频重复词
        stop_words = {"我们", "可以", "这个", "通过", "进行", "以及", "没有", "因为", "所以", "但是", "材料", "问题", "过程", "由于", "导致", "从而", "实现"}
        raw_clean = re.sub(r"[^\u4e00-\u9fa5]", " ", material_text)
        word_freq = {}
        for token in raw_clean.split():
            # 统计2-4字词
            for l in [2, 3, 4]:
                for i in range(len(token) - l + 1):
                    sub = token[i:i+l]
                    if sub not in stop_words and len(sub) >= 2:
                        word_freq[sub] = word_freq.get(sub, 0) + 1
        high_freq_concepts = sorted([w for w, c in word_freq.items() if c >= 2], key=lambda x: (word_freq[x], len(x)), reverse=True)[:5]

        # 4. 匹配W 老师名师核心规则
        matched_policies = []
        for policy in self.policies:
            pid = policy.get("policy_id", "")
            if pid == "jmy_policy_001":
                matched_policies.append(policy)
            elif pid == "jmy_policy_002" and high_freq_concepts:
                matched_policies.append(policy)
            elif pid == "jmy_policy_003" and any(p["summary_sentence"] for p in paragraphs_analysis):
                matched_policies.append(policy)
            elif pid == "jmy_policy_011" and found_transitions:
                matched_policies.append(policy)
            elif pid == "jmy_policy_012" and found_causals:
                matched_policies.append(policy)
            elif pid == "jmy_policy_013" and found_parallels:
                matched_policies.append(policy)

        # 5. 匹配易错纠偏提醒
        matched_critiques = []
        for crit in self.critique_cases:
            if found_qualifiers and crit.get("error_type") == "SCOPE_EXPANSION":
                matched_critiques.append(crit)
            elif any(p["summary_sentence"] for p in paragraphs_analysis) and crit.get("error_type") == "POOR_STRUCTURE":
                matched_critiques.append(crit)
            elif crit.get("error_type") == "OVER_ABSTRACTION":
                matched_critiques.append(crit)

        return {
            "status": "SUCCESS",
            "teacher_id": "teacher_jiangmuyun",
            "teacher_name": self.profile.get("name", "W 老师·文段分析"),
            "pedagogy_tagline": "以句子为最小分析单位，去粗取精，找到被重复的内容，理顺逻辑关系",
            "analysis_stats": {
                "paragraph_count": len(raw_paras),
                "sentence_count": len(all_sentences),
                "high_freq_repeated_concepts": high_freq_concepts,
                "qualifiers_found": list(set(found_qualifiers)),
                "has_causal_logic": bool(found_causals),
                "has_transition_logic": bool(found_transitions),
                "has_parallel_logic": bool(found_parallels)
            },
            "paragraphs": paragraphs_analysis,
            "matched_policies": matched_policies[:4],
            "critique_warnings": matched_critiques[:2]
        }

    def generate_report(self, input_data: Dict[str, Any]) -> str:
        """生成详细 Markdown 格式讲题与文段分析报告。"""
        question = input_data.get("question") or input_data.get("stem") or ""
        material = input_data.get("material") or input_data.get("material_text") or ""
        if isinstance(material, list):
            material = "\n".join(material)

        res = self.analyze_passage(material, question)

        if res.get("status") == "REJECTED_OUT_OF_SCOPE":
            rej = res["rejection"]
            return f"""# W 老师·文段分析教师：服务受限说明

**教师身份**：{res['teacher_name']}
**任务判定**：超出文段分析范围（{rej['reason']}）

---

### 限制说明与处理建议
{rej['message']}

> **特别声明**：本模块遵从严格的职责边界约束，坚决不暗中调用通用大模型代写非文段分析内容。
"""

        stats = res["analysis_stats"]
        lines = [
            f"# W 老师·文段分析诊断与精读报告",
            f"",
            f"**授课名师**：{res['teacher_name']}",
            f"**教学指导思想**：{res['pedagogy_tagline']}",
            f"",
            f"---",
            f"",
            f"## 一、文段结构与骨干信息透视",
            f"- **分析规模**：共拆解 {stats['paragraph_count']} 个自然段，细分切入 {stats['sentence_count']} 个独立分析句单元。",
            f"- **高频被重复概念（核心主旨抓手）**：{', '.join(stats['high_freq_repeated_concepts']) if stats['high_freq_repeated_concepts'] else '未出现高频词重复，重在段落单点提取'}",
            f"- **范围限定词识别**：{', '.join(stats['qualifiers_found']) if stats['qualifiers_found'] else '无特殊范围限定词'}",
            f"",
            f"## 二、逐段逻辑脉络梳理",
        ]

        for p in res["paragraphs"]:
            p_desc = f"### 第 {p['para_index']} 段：{p['structure_type']}"
            lines.append(p_desc)
            lines.append(f"- **独立句数**：{p['sentence_count']} 句")
            if p["summary_sentence"]:
                lines.append(f"- **总括/总结句提取**：`{p['summary_sentence']}`")
            if p["transitions"]:
                lines.append(f"- **转折连词**：{', '.join(p['transitions'])}（转折之后是核心重点）")
            if p["causals"]:
                lines.append(f"- **因果关联**：{', '.join(p['causals'])}（理顺因果，切勿因果倒置）")
            if p["parallels"]:
                lines.append(f"- **并列要素**：{', '.join(p['parallels'])}（多项并列需均衡提炼）")
            lines.append("")

        lines.append("## 三、W 老师核心方法论指导")
        for policy in res["matched_policies"]:
            lines.append(f"### 【{policy['name']}】（规则ID: {policy['policy_id']}）")
            lines.append(f"- **核心规则**：{policy['rule']}")
            lines.append(f"- **底层原理**：{policy['reasoning']}")
            lines.append(f"- **名师原话 Quote**：`\"{policy['source'][0]['quote']}\"`")
            lines.append("")

        if res["critique_warnings"]:
            lines.append("## 四、名师课堂纠偏警示")
            for crit in res["critique_warnings"]:
                lines.append(f"- **典型错误类型**：`{crit['error_type']}`")
                lines.append(f"  - **学生常见误区**：{crit['student_error_snippet']}")
                lines.append(f"  - **江老师诊断指正**：{crit['diagnosis']}")
                lines.append(f"  - **纠偏改进动作**：{crit['remedy_instruction']}")
                lines.append("")

        return "\n".join(lines)
