# -*- coding: utf-8 -*-
"""Material Analyzer：启发式材料分析（纯规则，无模型调用）。

输出：
- 逐句切分与句型分类（总结句/规范表述/描述性语言/案例细节）
- 动宾短语候选
- 逻辑关系标记（并列/因果/转折/限定）
- 限定词与抽象热词登记（供教师 Agent 做范围与热词检查）
"""

import re

# 动词库（机关公文高频动词）
VERB_BANK = [
    "建立", "健全", "完善", "加大", "加强", "落实", "开展", "组织", "制定", "出台",
    "推行", "推进", "实施", "鼓励", "引导", "支持", "监督", "考核", "宣传", "培训",
    "招募", "设立", "成立", "开设", "搭建", "整合", "规范", "整治", "改善", "提升",
    "提高", "优化", "拓宽", "畅通", "创新", "引入", "推广", "动员", "排查", "走访",
    "公示", "统筹", "规划", "投入", "打造", "组建", "配备", "划定", "签订", "吸纳",
]

# 限定词库（范围检查用）
QUALIFIERS = ["部分", "某些", "个别", "一些", "多数", "少数", "有些", "一度", "初步", "试点", "逐步", "基本", "主要", "大多"]

# 描述性语言标记
DESCRIPTIVE_MARKERS = [
    "上午", "下午", "当天", "一天", "这天", "这天,", "九点", "十点", "凌晨", "深夜",
    "排起长队", "笑着", "哭着", "笑着说", "说道", "念叨", "赶来", "走进", "来到",
    "掏出", "拿出", "递给", "抹泪", "叹气", "愣住", "锅里", "桌上",
]

# 因果/转折/并列连接词
CAUSAL = ["因此", "由于", "因为", "导致", "造成", "使得", "从而", "以至于", "于是"]
ADVERSATIVE = ["但是", "却", "然而", "不过", "可是", "反而"]
PARALLEL = ["、", "；", "同时", "此外", "另外", "一是", "二是", "三是", "首先", "其次", "再次"]

# 抽象品质词（主观推断检查）
ABSTRACT_QUALITY = [
    "奉献精神", "无私", "大公无私", "廉洁奉公", "爱岗敬业", "高尚", "品格", "情操",
    "责任感", "使命感", "初心", "情怀", "担当精神", "大局意识", "牺牲精神", "崇高",
]

# 假大空热词（材料无依据禁用）
MACRO_SLOGAN = [
    "产业融合", "深度融合", "一二三产业融合", "多元化发展", "一体化", "赋能", "抓手",
    "闭环", "内生动力", "顶层设计", "可持续发展", "高质量发展", "数字化转型",
    "全链条", "新质生产力", "智慧化", "精细化管理",
]

# 变化题结构标记
CHANGE_MARKERS = ["原来", "现在", "之前", "之后", "过去", "如今", "从前", "曾经"]

SENT_SPLIT = re.compile(r"(?<=[。！？；])")


def split_sentences(text):
    sents = [s.strip() for s in SENT_SPLIT.split(text) if s.strip()]
    return sents if sents else [text.strip()]


def classify_sentence(sent):
    """返回 (句型, 标记列表)。句型：summary / normative / descriptive / example / neutral"""
    marks = []
    has_dialog = bool(re.search(r"[“\"][^”\"]{4,}[”\"]", sent))
    has_desc_marker = any(m in sent for m in DESCRIPTIVE_MARKERS)
    has_verb = any(v in sent for v in VERB_BANK)
    has_causal = any(c in sent for c in CAUSAL)
    has_adv = any(a in sent for a in ADVERSATIVE)
    has_qualifier = [q for q in QUALIFIERS if q in sent]
    has_abstract = [w for w in ABSTRACT_QUALITY if w in sent]
    has_slogan = [w for w in MACRO_SLOGAN if w in sent]

    if has_dialog or (has_desc_marker and not has_verb):
        stype = "descriptive"
    elif len(sent) <= 30 and has_verb and not has_desc_marker:
        stype = "summary"
    elif has_verb:
        stype = "normative"
    elif has_causal or has_adv:
        stype = "normative"
    else:
        stype = "example"

    if has_causal:
        marks.append("因果")
    if has_adv:
        marks.append("转折")
    if any(p in sent for p in PARALLEL):
        marks.append("并列")
    if has_qualifier:
        marks.append("限定:" + "|".join(has_qualifier))
    if has_abstract:
        marks.append("品质词:" + "|".join(has_abstract))
    if has_slogan:
        marks.append("热词:" + "|".join(has_slogan))
    return stype, marks


def extract_verb_phrases(sent):
    """抽取动宾短语候选：动词后截取至多 10 字的宾语。"""
    phrases = []
    for v in VERB_BANK:
        start = 0
        while True:
            idx = sent.find(v, start)
            if idx == -1:
                break
            tail = sent[idx + len(v): idx + len(v) + 10]
            # 截到标点为止
            obj = re.split(r"[，。；、！？,;]", tail)[0]
            if 1 <= len(obj) <= 10:
                phrases.append(v + obj)
            start = idx + len(v)
    return phrases


def analyze_material(material_paragraphs):
    """material_paragraphs: list[str]。返回结构化分析结果。"""
    result = {
        "paragraphs": [],
        "summary_sentences": [],
        "descriptive_sentences": [],
        "verb_phrases": [],
        "all_qualifiers": [],
        "material_hotwords": [],
        "material_qualitywords": [],
    }
    for p_idx, para in enumerate(material_paragraphs, 1):
        sents = split_sentences(para)
        p_info = {"index": p_idx, "structure": "single", "sentences": []}
        if len(sents) >= 3:
            first_type, _ = classify_sentence(sents[0])
            rest_types = [classify_sentence(s)[0] for s in sents[1:]]
            if first_type in ("summary", "normative") and rest_types.count("example") + rest_types.count("descriptive") >= 2:
                p_info["structure"] = "总分"
        for s_idx, sent in enumerate(sents, 1):
            stype, marks = classify_sentence(sent)
            vp = extract_verb_phrases(sent)
            s_info = {
                "p": p_idx,
                "i": s_idx,
                "text": sent,
                "type": stype,
                "marks": marks,
                "verb_phrases": vp,
            }
            p_info["sentences"].append(s_info)
            if stype == "summary":
                result["summary_sentences"].append(s_info)
            elif stype == "descriptive":
                result["descriptive_sentences"].append(s_info)
            result["verb_phrases"].extend(vp)
            for m in marks:
                if m.startswith("限定:"):
                    result["all_qualifiers"].extend(m[3:].split("|"))
                elif m.startswith("热词:"):
                    result["material_hotwords"].extend(m[3:].split("|"))
                elif m.startswith("品质词:"):
                    result["material_qualitywords"].extend(m[3:].split("|"))
        result["paragraphs"].append(p_info)
    result["verb_phrases"] = list(dict.fromkeys(result["verb_phrases"]))
    result["all_qualifiers"] = sorted(set(result["all_qualifiers"]))
    result["material_hotwords"] = sorted(set(result["material_hotwords"]))
    result["material_qualitywords"] = sorted(set(result["material_qualitywords"]))
    return result


if __name__ == "__main__":
    demo = [
        "上午9点不到，老马工作室的门口已经排起了长队。“我们小区消防栓不出水、电梯天天出故障，您可得给评评理。”老马笑着掏出随身带着的笔和本，开始了一天的调解工作。",
        "老马是街道首席调解员，做了30年的调解工作。去年，老马接待群众600多人次。接待群众是门“技术活”，不仅要真诚待人，还得对政策烂熟于心。",
        "老马给自己立下了接待群众的24字规矩：起立迎接，请坐倒水，倾听记录，交流引导，解决问题，出门相送。",
    ]
    import json

    print(json.dumps(analyze_material(demo), ensure_ascii=False, indent=1)[:2200])
