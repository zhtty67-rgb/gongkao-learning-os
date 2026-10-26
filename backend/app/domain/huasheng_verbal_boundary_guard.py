# -*- coding: utf-8 -*-
"""花生十三·言语理解与表达教师前置模块边界检查器（反例复核增强版）。

核心原则：
1. 花生十三专精于行测言语理解与表达（片段阅读/中心理解、逻辑填空/成语实词辨析、语句表达/排序填入、篇章阅读）。
2. 严格拦截明确跨模块任务：
   - 资料分析计算（增长率/基期/比重/平均数等公式测算与表格计算）；
   - 数量关系运算（工程/行程/概率/方程求解等数学应用题）；
   - 申论大作文/议论文全篇写作、公文起草、脱离材料自编对策。
3. 精准语言对象与背景豁免（语义解耦）：
   - 剥离被引用/讨论的词语：引号内（“...”、“...”等）出现的短语系语言分析对象，非行动指令；
   - 纯词语辨析/关系探讨（如“快慢和早晚是什么关系”、“‘起草通知’与‘撰写通知’有什么区别”）正常放行；
   - 区分题干材料与作答指令：阅读文段中叙述性背景（如“技术人员通过计算增长率判断行业趋势”）属于材料客观内容，非计算指令，正常放行；
   - 题型标签不得覆盖用户指令：即使题型标为中心理解或逻辑填空，若题干或用户输入包含明确计算/代写命令，一律严格拦截；
   - 复合混合消息无死角排查：即便前半段是正常词义追问，若后半段夹带计算或写作命令（如“另外请撰写一篇1000字议论文”或“顺便计算同比增幅”），一律严格拦截；
   - 局部否定精确消除：否定短语仅消除自身，绝不跨标点/连词吞噬后续肯定式违规请求（如“不要计算增长率，求同比增幅”或“不要写通知，帮我写倡议书”坚决拦截）。
4. 在 ModuleTeacherService 的 explain_question、explain_current_question 与 get_teacher_context_for_review 统一实行前置拦截。
"""

import re
from typing import Dict, Any, Optional, Tuple

# 1. 引用短语屏蔽函数：剥离引号内被讨论/引用的词语，避免语言要素触发误拦
def mask_quoted_phrases(text: str) -> str:
    def repl(m):
        inner = m.group(1)
        # 短词语/成语引用（<= 25字）且内部非直接代写/计算命令时，替换为中性占位符
        if len(inner) <= 25 and not any(cmd in inner for cmd in ("请帮我写", "请计算", "代写大作文")):
            return " __QUOTED_EXPR__ "
        return m.group(0)
    return re.sub(r'[“\"‘\'【]([^”\"’\'】\n]+)[”\"’\'】]', repl, text)

# 2. 纯词语辨析/关系比较模式
COMPARE_PATTERN = re.compile(
    r'(?:__QUOTED_EXPR__|\b[\w\u4e00-\u9fa5]{1,10})\s*(?:与|和|跟|及|、)\s*(?:__QUOTED_EXPR__|\b[\w\u4e00-\u9fa5]{1,10})\s*(?:在|是什么|有哪些)?\s*(?:什么关系|什么区别|区别是什么|不同是什么|怎么区分|怎么辨析|如何区分|如何辨析|有何不同|词义区别|用法区别)'
)

# 3. 子句边界切分正则（支持中英文标点及转折/递进/并列连词）
CLAUSE_SPLIT = re.compile(
    r'[，,。；;！!？?\n]+|(?=(?:另外|顺便|同时|但是|但|然而|不过|可是|却|反而))'
)

# 4. 局部否定短语前缀正则
NEGATION_PREFIX = re.compile(
    r'^(?:不需要|如果不需要|不要|不用|无需|不必|禁止|严禁|不能|并非|不|切勿)\s*(?:让您|让你|你|您|去|进行|做)?\s*(?:去|进行|做)?'
)

# 5. 肯定式资料分析与数学计算指令正则
MATH_IMPERATIVE_CMD = re.compile(
    r'(?:^|另外|顺便|同时|但是|但|然而|并且|并|且|请|帮我|给我)?\s*(?:请|帮我|给我)?\s*(?:计算|求|测算|算一下|算算|算出|算)\s*.{0,25}?(?:增长率|同比|环比|基期|现期|两期比重|比重差|比重|平均数|倍数|百分点|数值|增幅|降幅|差值|数据|出生率)'
    r'|(?:根据|依据|按照)\s*.{0,15}?(?:表格|图表|数据|资料)\s*.{0,10}?(?:计算|求出|测算|算)'
    r'|(?:工程|任务|工作|施工).{0,15}?(?:需要多少天|多少天|几天完成|多少时间|合作天数)'
    r'|(?:工程问题|行程问题|相遇追及|流水行船|十字交叉|排列组合).{0,15}?(?:计算|合作天数|多少天|求出|概率)'
    r'|(?:求|列|解)\s*方程'
)

# 6. 肯定式申论大作文与公文起草指令正则
ESSAY_IMPERATIVE_CMD = re.compile(
    r'(?:以.{1,35}为(?:题|题目|主题|副题))\s*.{0,25}?(?:写|撰写|起草|构思|作答)\s*.{0,10}?(?:\d{3,4}字)?\s*.{0,10}?(?:一篇|大作文|议论文|文章|作文)'
    r'|(?:^|另外|顺便|同时|但是|但|然而|并且|并|且|请|帮我|给我|替我|代|请帮我)\s*(?:帮我|给我|替我|请)?\s*(?:写|撰写|起草|代写|拟写|输出|生成)\s*.{0,25}?(?:大作文|申论大作文|议论文|申论作文|范文|倡议书|通知|通报|公文|发言稿|讲话稿|公开信|请示|工作方案|文章|作文)'
    r'|(?:脱离材料|不看材料|凭空)\s*.{0,15}?(?:自编对策|提对策|写对策)'
)


def _check_single_text(text: str) -> Tuple[bool, str]:
    """逐子句语义检查单段文本是否包含跨模块命令。"""
    if not text:
        return True, ""
    masked = mask_quoted_phrases(text)
    clauses = [c.strip() for c in CLAUSE_SPLIT.split(masked) if c.strip()]
    for clause in clauses:
        # 1. 检查是否为纯词义对比探讨（且不包含后续指令）
        if COMPARE_PATTERN.search(clause) and not re.search(r'(?:写|撰写|起草|代写|计算|算|求)\s*.{0,10}?(?:一篇|一份|增长率|增幅|大作文|议论文|倡议书)', clause):
            continue
        # 2. 检查是否为被否定子句
        if NEGATION_PREFIX.search(clause):
            continue
        # 3. 检查是否命中数学/资料分析命令
        if MATH_IMPERATIVE_CMD.search(clause):
            # 排除材料叙述性介词短语（如：技术人员通过计算增长率判断行业趋势）
            if re.search(r'(?:通过|利用|在|关于|由于|经过|作为).{0,5}?(?:计算|测算)', clause) and not re.search(r'^(?:请|帮我|给我|求|顺便|另外)', clause):
                continue
            return False, "DATA_ANALYSIS_OR_MATH_CALCULATION"
        # 4. 检查是否命中申论/公文代写命令
        if ESSAY_IMPERATIVE_CMD.search(clause):
            return False, "ESSAY_OR_OFFICIAL_DOC_WRITING"

    return True, ""


def check_huasheng_verbal_boundary(
    question_stem: str = "",
    question_type: str = "",
    student_text: str = "",
    options: Optional[Any] = None,
    explanation: str = ""
) -> Dict[str, Any]:
    """统一检查针对花生十三言语理解教师的请求是否越界。

    返回 dict:
    {
        "allowed": bool,
        "reason": str,
        "message": str
    }
    """
    qtype = (question_type or "").strip()
    stem = (question_stem or "").strip()
    student = (student_text or "").strip()
    exp = (explanation or "").strip()

    # 1. 检查题型是否为纯外部学科（题型标签不能覆盖用户指令，但题型本身声明非言语时需拦截）
    external_types = ("资料分析", "数量关系", "申论大作文", "申论写作", "文章写作", "公文写作")
    verbal_keywords = ("言语", "逻辑填空", "中心理解", "片段阅读", "语句表达", "篇章阅读", "主旨", "词义")
    if any(m in qtype for m in external_types):
        if not any(v in qtype for v in verbal_keywords):
            return {
                "allowed": False,
                "reason": "OUT_OF_SCOPE_QUESTION_TYPE",
                "message": (
                    f"【教师职责边界提示】花生十三专精于行测【言语理解与表达】模块。当前题型为‘{qtype}’，"
                    "属于非言语学科领域。资料分析请前往四海资料分析教学团队，申论文章请前往周泰然老师。"
                )
            }

    # 2. 全量审查各字段（stem、student_text、explanation），题型标签不得覆盖明确指令
    for text_to_check in (stem, student, exp):
        allowed, reason = _check_single_text(text_to_check)
        if not allowed:
            if reason == "DATA_ANALYSIS_OR_MATH_CALCULATION":
                return {
                    "allowed": False,
                    "reason": reason,
                    "message": (
                        "【教师职责边界提示】当前请求包含具体的资料分析数据测算或数理计算指令。花生十三是言语理解名师，不负责行测数理公式推导与表格算数。"
                        "涉及增长率、比重、基期量或数学工程问题，请前往【四海资料分析教学团队】或【四海数量关系教学团队】。"
                    )
                }
            elif reason == "ESSAY_OR_OFFICIAL_DOC_WRITING":
                return {
                    "allowed": False,
                    "reason": reason,
                    "message": (
                        "【教师职责边界提示】当前请求包含撰写申论千字大作文、起草公文通知或脱离材料自编对策的指令。"
                        "言语理解侧重于客观文段理解与词义辨析，不提供主观文章大作文代写与公文拟写服务。申论文章写作请前往名师【周泰然】处。"
                    )
                }

    return {
        "allowed": True,
        "reason": "ALLOWED",
        "message": "任务符合言语理解与表达职责范围。"
    }


def build_rejection_report(reason: str, message: str) -> str:
    """构建花生风格的职责边界拒绝与重定向说明 Markdown 报告。"""
    return (
        "# 🎙️ 花生十三 · 言语理解名师：服务职责边界提示\n\n"
        "我的同学们，打住！都把笔放下，抬头看黑板：\n\n"
        f"**{message}**\n\n"
        "---\n\n"
        "### 💡 花生十三建议指引：\n"
        "- 📊 **资料分析公式与数据计算**：涉及增长率、两期比重差、基期量或速算，请前往【四海资料分析教学团队】；\n"
        "- 🔢 **数量关系数学运算**：涉及工程问题特值法、行程追及、十字交叉浓度计算，请前往【四海数量关系教学团队】；\n"
        "- 📝 **申论千字大作文与公文起草**：涉及政论大作文立意写作、公文格式拟写或自编宏观对策，请前往申论名师【周泰然】；\n"
        "- 📖 **言语理解题目与复盘**：只要是文段中心理解、对策识别、细节判断、语句排序、逻辑填空成语实词辨析，随时交给我，咱们直击本质、秒出梦中情答！"
    )
