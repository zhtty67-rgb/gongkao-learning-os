# -*- coding: utf-8 -*-
"""江牧云·文段分析教师范围门禁检查器（全系统统一）。

核心原则：
江牧云专精于给定资料的文段精读、结构拆解、逻辑关系梳理与要点提炼。
严格禁止大作文/议论文写作、公文格式起草、整卷模考评分与全篇答题模板、脱离材料自编对策。
在全部入口（诊断、模型语义审查、模块教学、追问等）实行统一门禁拦截。

意图与范围约束设计：
1. 任务意图主要由题干指令(question_stem)、学生提问/追问(student_text)及题型(question_type)决定；
2. 给定资料(material_text)作为客观文本，包含“通知”“分论点”“方案”等词汇属客观内容，不得作为越界判定依据；
3. 严格识别否定句与范围约束（如“不要写公文”“仅分析文段”），避免误拦截合法文段分析。
"""

import re
from typing import Dict, Any

# 1. 否定/限制短语（否定越界请求或明确声明仅做文段分析）
NEGATION_ESSAY = re.compile(
    r"(不要|不用|无需|不必|禁止|严禁|绝不|不能|并非|不|切勿)\s*(代写|撰写|起草|输出|生成|写|成篇)?\s*(大作文|作文|议论文|文章)"
)
NEGATION_DOC = re.compile(
    r"(不要|不用|无需|不必|禁止|严禁|绝不|不能|并非|不|切勿)\s*(代写|撰写|起草|拟写|生成|输出|套用|写)?\s*(公文格式|公文套话|公文|通知|倡议书|发言稿|应用文)"
)
NEGATION_FREE = re.compile(
    r"(不要|不用|无需|不必|禁止|严禁|绝不|不能|并非|不|切勿)\s*(脱离材料|自编对策|凭空编造|自由发挥|脱离给定资料)"
)

# 2. 议论文/大作文起草特征正则（动词 + 目标成果）
ESSAY_WRITE_INTENT = re.compile(
    r"(写|起草|撰写|代写|输出).{0,15}(一篇|完整)?.{0,10}(大作文|议论文|申论作文|申论大作文|文章|作文|范文)"
    r"|(以.{1,35}为(题|题目|主题|副题)).{0,25}(写|撰写|起草|构思|作答).{0,10}(一篇|大作文|议论文|文章|作文)"
    r"|(拟定|自拟).{0,6}(题目|标题).{0,25}(展开论述|写|撰写|成篇|完篇)"
    r"|(分论点.{0,10}(展开论述|写作|成文|代写|成篇))"
)

# 3. 公文/应用文起草特征正则（动词 + 公文文体 / 格式构成要素）
OFFICIAL_DOC_WRITE_INTENT = re.compile(
    r"(起草|拟写|撰写|代写|帮我写|生成|写一份|写一篇).{0,30}(公文|公开信|倡议书|宣传稿|通知|发言稿|讲话稿|汇报材料|工作方案|编者按|广播稿|通报|请示|函|请柬)"
    r"|(按照|符合|遵循|具备).{0,10}公文格式.{0,25}(起草|拟写|撰写|写作|生成|作答)"
    r"|(公文格式.{0,15}(包含|要求)?.{0,10}(主送机关|发文机关|发文日期|落款))"
)

# 4. 整卷模考/全篇模板特征正则
FULL_PAPER_INTENT = re.compile(
    r"(整卷|全卷|整套试卷|整套题|整套题目).{0,10}(评分|批改|模考|批阅|打分)"
    r"|(整卷评分|全卷批改|模考评分)"
    r"|(标准作答模板|全卷模板|整套题目的标准作答模板|全篇答题模板)"
)

# 5. 脱离材料自编对策特征正则
FREE_COUNTERMEASURE_INTENT = re.compile(
    r"(脱离材料|不看材料|不用管材料|抛开材料|脱离给定资料|不看给定的任何材料|不依赖材料).{0,25}(对策|建议|发挥|构想|政策)"
    r"|(凭空|主观自由发挥|自由发挥|自编|万能).{0,15}(构想|提出|写出|给我写)?\s*\d*条?.{0,10}(万能对策|宏观政策建议|对策|建议)"
    r"|(万能对策)"
)


def check_jiangmuyun_boundary(
    question_stem: str = "",
    question_type: str = "",
    student_text: str = "",
    material_text: str = ""
) -> Dict[str, Any]:
    """统一检查针对江牧云教师的请求是否越界。

    返回 dict:
    {
        "allowed": bool,
        "reason": str,
        "message": str
    }
    """
    qtype = (question_type or "").strip()
    # 否定仅作用于被否定的短语，不能让同一请求中的其他越界指令跳过检查。
    # 两个字段分别清理，避免跨字段拼接形成一个虚假的否定短语。
    def positive_instruction(text: str) -> str:
        for pattern in (NEGATION_ESSAY, NEGATION_DOC, NEGATION_FREE):
            text = pattern.sub(" ", text)
        return text

    instruction_text = " \n ".join(
        positive_instruction(text or "") for text in (question_stem, student_text)
    ).strip()

    # 1. 大作文/议论文检查
    if qtype in ("文章写作", "申论大作文", "议论文"):
        return {
            "allowed": False,
            "reason": "ESSAY_WRITING_OUT_OF_SCOPE",
            "message": (
                "【范围约束提示】江牧云·文段分析教师专精于给定资料的文段精读、结构拆解、逻辑关系梳理与要点提炼。"
                "大作文/议论文写作、分论点构思与全文代写属于越界任务，超出此模块范围。本系统禁止生成大作文，建议转交专门的申论文章写作教学教师。"
            )
        }
    if ESSAY_WRITE_INTENT.search(instruction_text):
        return {
            "allowed": False,
            "reason": "ESSAY_WRITING_OUT_OF_SCOPE",
            "message": (
                "【范围约束提示】江牧云·文段分析教师专精于给定资料的文段精读、结构拆解、逻辑关系梳理与要点提炼。"
                "大作文/议论文写作、分论点构思与全文代写属于越界任务，超出此模块范围。本系统禁止生成大作文，建议转交专门的申论文章写作教学教师。"
            )
        }

    # 2. 公文/应用文检查
    if qtype in ("公文题", "应用文", "公文写作"):
        return {
            "allowed": False,
            "reason": "OFFICIAL_DOC_OUT_OF_SCOPE",
            "message": (
                "【范围约束提示】江牧云·文段分析教师专精于材料文段的客观信息提取与逻辑梳理。"
                "公文格式（标题、主送机关、发文日期、倡议呼吁等文体套话）属于越界任务，超出此模块范围。本系统严禁混入公文起草，建议转交公文与应用文专属教师。"
            )
        }
    if OFFICIAL_DOC_WRITE_INTENT.search(instruction_text):
        return {
            "allowed": False,
            "reason": "OFFICIAL_DOC_OUT_OF_SCOPE",
            "message": (
                "【范围约束提示】江牧云·文段分析教师专精于材料文段的客观信息提取与逻辑梳理。"
                "公文格式（标题、主送机关、发文日期、倡议呼吁等文体套话）属于越界任务，超出此模块范围。本系统严禁混入公文起草，建议转交公文与应用文专属教师。"
            )
        }

    # 3. 整卷评分/整套题目检查
    if qtype in ("整卷模考", "整卷作答", "整套试卷") or FULL_PAPER_INTENT.search(instruction_text):
        return {
            "allowed": False,
            "reason": "FULL_PAPER_OUT_OF_SCOPE",
            "message": (
                "【范围约束提示】江牧云·文段分析教师专精于具体材料段落的文段精读、结构拆解、逻辑关系梳理与核心要点提炼。"
                "整卷模考评分与全篇整题模板作答属于越界任务，超出此模块范围。建议转交专门的模考阅卷或全卷评估教师。"
            )
        }

    # 4. 脱离材料自编对策检查
    if FREE_COUNTERMEASURE_INTENT.search(instruction_text):
        return {
            "allowed": False,
            "reason": "FREE_COUNTERMEASURE_OUT_OF_SCOPE",
            "message": (
                "【范围约束提示】江牧云·文段分析教师专精于给定材料的客观信息提取，严格秉承“尊重材料、依托材料”原则。"
                "脱离给定资料主观自由发挥编造对策属于越界任务，超出此模块范围。请提供具体材料文本以供提炼。"
            )
        }

    return {"allowed": True}
