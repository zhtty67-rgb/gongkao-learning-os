# -*- coding: utf-8 -*-
"""
L 老师·言语理解与表达 讲题引擎（HuashengVerbalExplainEngine）
集成L 老师三三五五文段分析、二六四二二二选项心法与逻辑填空双轨法则，
实现高保真规则召回、案例匹配、学生思路纠偏与真实模型网关讲题生成。
"""

import os
import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, List, Any, Optional

from library import HuashengVerbalLibrary, phrases

MIN_LEN = 2

class HuashengVerbalExplainEngine:
    def __init__(self, base_dir=None):
        self.lib = HuashengVerbalLibrary(base_dir)
        self._init_gateway()

    def _init_gateway(self):
        """尝试初始化主系统 ModelGateway。"""
        self.gateway = None
        try:
            # 尝试引入 gongkao-learning-os 的 backend
            backend_dir = Path("D:/gong/gongkao-learning-os/backend")
            if backend_dir.exists() and str(backend_dir) not in sys.path:
                sys.path.insert(0, str(backend_dir))
            from app.ai.gateway import ModelGateway
            self.gateway = ModelGateway()
        except Exception:
            self.gateway = None

    def rank_policies(self, question_type: str, stem: str, student_thought: str = ""):
        """根据题干特征、题型与学生思路检索最相关的花生言语策略规则。"""
        hay = f"{question_type} {stem} {student_thought}".lower()
        scored = []
        for p in self.lib.policies:
            score = 0.0
            hits = []
            cat = p.get("category", "")
            name = p.get("name", "")
            trigger = p.get("trigger", "")
            conditions = p.get("conditions", "")
            rule = p.get("rule", "")

            # 题型匹配
            if question_type:
                q_clean = question_type.replace("题", "").strip()
                if q_clean and (q_clean in cat or q_clean in name or q_clean in trigger or q_clean in conditions):
                    score += 5.0
                    hits.append(f"题型:{question_type}")

            # 核心行文结构与语言信号特征加权
            feature_weights = [
                ("对策表达", ["必须", "应该", "应当", "需要", "务必", "只有", "前提", "关键", "离不开", "不妨", "可以尝试", "刻不容缓", "必由之路", "对策"]),
                ("转折弱转折", ["但是", "然而", "却", "不过", "实际上", "其实", "反之", "反而"]),
                ("因果结构", ["因此", "所以", "导致", "造成", "因而", "致使", "之所以", "原因", "成因"]),
                ("并列双主体", ["此外", "另外", "同时", "一方面", "企业与政府", "科学与人文", "新文化与新文学", "并列"]),
                ("科普总分", ["研究表明", "科学家发现", "实验显示", "机制", "生理", "科普"]),
                ("新闻新发现", ["最新", "新发现", "新成果", "日前", "通报", "首次"]),
                ("由大引小", ["不例外", "也是如此", "世界上", "我国", "其中"]),
                ("断桥填入", ["填入横线", "画横线处", "断桥", "承上启下"]),
                ("排序分堆", ["排序", "①", "②", "③", "④", "分堆", "顶真"]),
                ("甚至递进", ["甚至", "进而", "更", "递进", "抓舌头"]),
                ("反义对比", ["不是", "而是", "相比于", "整体", "片面"]),
                ("务实实效", ["务实", "实效", "效果", "落实"]),
                ("细节时态", ["相符", "不相符", "正确的一项", "不正确的一项", "细节", "偷换", "已然", "未然"]),
                ("揣摩意图", ["意在", "目的", "意图", "公众", "消费者", "受众"]),
                ("侧重点辨析", ["侧重", "侧重点", "源远流长", "博大精深", "历久弥新", "连绵不绝", "辨析", "束手无策", "一筹莫展"]),
                ("双对象语境", ["本末倒置", "舍本逐末", "喧宾夺主", "因小失大", "得不偿失", "南辕北辙", "背道而驰", "初衷", "主次"]),
                ("程度反差成败", ["适得其反", "事与愿违", "恰恰相反", "功亏一篑", "功败垂成", "失之交臂", "前功尽弃"]),
                ("意象搭配动词", ["泥沼", "牢笼", "窠臼", "桎梏", "藩篱", "羁绊", "束缚", "铭刻", "镌刻", "搭配", "搭配的动词"]),
                ("固定热门搭配", ["固定搭配", "热门", "波澜壮阔", "发展史", "史诗", "征程", "应接不暇"]),
                ("800词积累方法", ["800词", "成语", "实词", "积累", "人民网", "例句", "生僻", "品", "语感", "逻辑填空", "选词"])
            ]

            for feat_name, kws in feature_weights:
                if any(kw in hay for kw in kws):
                    if any(kw in cat or kw in name or kw in trigger or kw in conditions or kw in rule for kw in kws):
                        score += 3.5
                        hits.append(feat_name)

            for token in set(phrases(name, MIN_LEN)):
                if token.lower() in hay:
                    score += 2.0
                    hits.append(token)

            if score > 0:
                scored.append((score, list(set(hits)), p))

        scored.sort(key=lambda x: -x[0])
        return [s for s in scored[:4]]

    def find_cases(self, stem: str, top=2, verified_only: bool = True):
        """根据题干相似度检索真实课堂经典案例。
        verified_only: 仅注入已通过原卷/随堂笔记逐字核验全字段的官方真题案例，
        19道课堂口述重构案例严格隔离，不得作为官方全字段案例注入模型。
        """
        scored = []
        tokens = set(phrases(stem, MIN_LEN))
        for c in self.lib.question_cases:
            if verified_only and c.get("verification_status") != "source_text_verified":
                continue
            c_text = f"{c.get('stem')} {c.get('analysis')}"
            hits = sum(1.0 for t in tokens if t in c_text)
            if hits > 0:
                scored.append((hits, c))
        scored.sort(key=lambda x: -x[0])
        return [c for _, c in scored[:top]]

    def find_critiques(self, student_thought: str, top=2):
        """根据学生错误思路检索针对性纠偏案例。"""
        if not student_thought:
            return []
        tokens = set(phrases(student_thought, MIN_LEN))
        scored = []
        for crit in self.lib.critique_cases:
            crit_text = f"{crit.get('error_manifestation')} {crit.get('root_cause')} {crit.get('remediation_strategy')}"
            hits = sum(1.0 for t in tokens if t in crit_text)
            if hits > 0:
                scored.append((hits, crit))
        scored.sort(key=lambda x: -x[0])
        return [crit for _, crit in scored[:top]]

    async def _call_llm_generation(self, prompt: str) -> Optional[str]:
        """通过主系统 ModelGateway 调用真实模型生成讲解。"""
        if not self.gateway:
            return None
        try:
            from app.ai.schemas import Message
            res = await self.gateway.generate(
                task_type="tutor_explanation",
                messages=[Message(role="user", content=prompt)]
            )
            return res.text
        except Exception as e:
            return None

    def generate_report(self, question: dict) -> str:
        """主入口：生成L 老师言语讲题报告。"""
        q_type = question.get("question_type", question.get("topic", "言语理解题"))
        stem = question.get("stem", "")
        options = question.get("options", [])
        correct_answer = question.get("correct_answer", question.get("answer", ""))
        student_thought = question.get("student_reasoning", question.get("student_thought", ""))
        student_choice = question.get("student_choice", "")

        matched_policies = self.rank_policies(q_type, stem, student_thought)
        cases = self.find_cases(stem)
        critiques = self.find_critiques(student_thought)

        # 尝试调用真实模型进行富文本名师生成
        prompt = self._build_prompt(q_type, stem, options, correct_answer, student_choice, student_thought, matched_policies, cases, critiques)
        llm_output = None
        if self.gateway:
            try:
                llm_output = asyncio.run(self._call_llm_generation(prompt))
            except Exception:
                llm_output = None

        if llm_output and len(llm_output.strip()) > 100 and not llm_output.startswith("【AI 助教解答】"):
            return llm_output

        # 本地兜底高保真模板
        return self._build_local_fallback(q_type, stem, options, correct_answer, student_choice, student_thought, matched_policies, cases, critiques)

    def _build_prompt(self, q_type, stem, options, correct_answer, student_choice, student_thought, policies, cases, critiques) -> str:
        options_text = ""
        if isinstance(options, list):
            options_text = "\n".join(options)
        elif isinstance(options, dict):
            options_text = "\n".join([f"{k}. {v}" for k, v in options.items()])

        rules_desc = ""
        for score, hits, p in policies:
            rules_desc += f"- 【{p['name']}】({p['policy_id']}): {p['rule']}\n  课堂原话: \"{p['quote']}\"\n  操作步骤: {'; '.join(p.get('steps', []))}\n  边界禁区: {p.get('boundaries', '')}\n\n"

        critiques_desc = ""
        for cr in critiques:
            critiques_desc += f"- 典型误区: {cr['error_manifestation']}\n  错因透视: {cr['root_cause']}\n  花生纠偏: \"{cr['teacher_critique']}\"\n  纠偏策略: {cr['remediation_strategy']}\n\n"

        cases_desc = ""
        for c in cases:
            cases_desc += f"- 经典案例: {c['name']} (答案: {c['answer']})\n  分析: {c['analysis']}\n  课堂原声: \"{c['teacher_quote']}\"\n\n"

        return f"""你现在是公考言语理解名师【L 老师】。请以L 老师的真实课堂授课口吻（风趣幽默、接地气、强调行文结构与内在逻辑、崇尚‘梦中情答’、直击本质、坚决反对四个选项挨个扒拉的对付式做题），为考生提供一份极具针对性、条理清晰的逐题深度解析。

【题目信息】
- 题型: {q_type}
- 题干:
{stem}
- 选项:
{options_text}
- 官方参考答案: {correct_answer}
- 学生作答选择: {student_choice or '未提供'}
- 学生原始思考/错因: {student_thought or '学生暂未提供具体思路'}

【可引用的L 老师言语核心心法与原话 Quote】
{rules_desc or '三三五五文段分析法（说理类看对策/科普类看全概括/新闻稿以新为重）；二六四二二二选项心法；逻辑填空双轨法则。'}

【可参考的真实课堂案例与警示】
{critiques_desc}
{cases_desc}

【讲题报告结构要求】
请严格按照以下五个模块输出 Markdown 格式讲题报告，语气完全代入L 老师（如‘我的同学们’、‘梦中情答’、‘对付选项’、‘傻瓜式对策’等）：
# 🎙️ L 老师 · 言语理解与表达名师精讲
## 一、 文段结构拆解与题型定调
（分析文段属于说理类、科普类还是新闻稿；属于前对策、分总、并列分分还是二层结构；指出文段的骨架脉络）
## 二、 L 老师解题心法与‘梦中情答’
（明确引用上面的规则与课堂原话 Quote，指出读完这道文段，正确答案必须具备什么样的特征，为什么这就是‘梦中情答’）
## 三、 四个选项对比剖析与精准排除
（逐一分析A、B、C、D四个选项，说明正确项为什么完美，排除项为什么是‘对付’、‘片面’、‘杂糅’、‘绝对化’或‘无中生有’）
## 四、 针对学生思路的专属错因诊断与纠偏
（结合学生的实际选择和思路，指出其思维瓶颈在何处，比如强加对策、弱转折断章取义、断桥只看半句等，并给出纠正心法）
## 五、 启发式追问与变式巩固
（抛出一个直击本题核心思维的针对性问题，引导学生思考文段结构，检验是否真正吃透方法论）
"""

    def _build_local_fallback(self, q_type, stem, options, correct_answer, student_choice, student_thought, policies, cases, critiques) -> str:
        lines = [
            "# 🎙️ L 老师 · 言语理解与表达名师精讲",
            f"**主讲名师**：L 老师（言语理解与表达）",
            f"**题型定位**：{q_type}",
            f"**题干切片**：{stem[:120]}{'...' if len(stem) > 120 else ''}",
            "",
            "## 一、 文段结构拆解与核心规则"
        ]

        if policies:
            for score, hits, p in policies:
                lines.append(f"### 💡 【{p['name']}】 (`{p['policy_id']}`)")
                lines.append(f"- **核心心法**：{p['rule']}")
                lines.append(f"- **课堂原话 Quote**：> \"{p['quote']}\"")
                lines.append(f"- **解题步骤**：")
                for st in p.get("steps", []):
                    lines.append(f"  - {st}")
                lines.append(f"- **避坑防线**：{p['boundaries']}")
                lines.append("")
        else:
            lines.append("记住L 老师的核心原则：主旨题是基石，读完文段必须看出行文结构，不要四个选项挨个扒拉找毛病，心中要有‘梦中情答’！\n")

        lines.append("## 二、 核心解析与选项剖析")
        lines.append(f"- **参考答案**：【{correct_answer}】")
        lines.append("- **解题精要**：文段结构清晰，抓住核心骨架后，正确选项自然浮出水面。选项设置中，排除项多出自例子、背景铺垫，或犯了片面、杂糅、过度衍生对策等六有误毛病；而正确选项是对主旨的精准同义替换。")
        lines.append("")

        if critiques and student_thought:
            lines.append("## 三、 针对学生思路的专属纠偏")
            for cr in critiques:
                lines.append(f"### ⚠️ 警惕误区：{cr['name']}")
                lines.append(f"- **学生典型表现**：{cr['error_manifestation']}")
                lines.append(f"- **错因根源剖析**：{cr['root_cause']}")
                lines.append(f"- **花生老师原声纠偏**：> \"{cr['teacher_critique']}\"")
                lines.append(f"- **实战改进策略**：{cr['remediation_strategy']}")
                lines.append("")

        lines.append("## 四、 启发式追问与复盘心法")
        lines.append("- **思考追问**：这道题如果让你给别人讲明白，你会怎么给对方拆解它的第一句话和最后一句话的关系？如果是并列文段，你有没有漏掉另一个主体？")
        lines.append("- **复盘心法**：复盘要远比多刷几道题有用得多，把结构想透彻，做题才能拥有势如破竹的‘确定感’！")
        return "\n".join(lines)
