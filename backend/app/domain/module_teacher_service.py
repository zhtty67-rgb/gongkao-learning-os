# -*- coding: utf-8 -*-
"""
行测四模块独立名师智能体服务层（ModuleTeacherService）：
负责逻辑判断、定义判断、数量关系、资料分析四个独立教师模型的发现、配置管理、画像读取与讲题分发。
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional
from .teacher_asset_stats import teacher_asset_stats, current_teacher_profile

CONFIG_FILE = Path(__file__).resolve().parent.parent / "config" / "module_teachers.json"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def resolve_base_dir(raw: str) -> Path:
    """教师目录：绝对路径原样使用；相对路径相对项目根解析（打包部署形态）。"""
    path = Path(raw)
    return path if path.is_absolute() else (PROJECT_ROOT / path)

MODULE_TEACHER_ID_MAP = {
    "逻辑判断": "teacher_logic",
    "定义判断": "teacher_definition",
    "数量关系": "teacher_quant",
    "资料分析": "teacher_data",
    "图形推理": "teacher_longfei",
    "立体图推": "teacher_longfei",
    "文段分析": "teacher_jiangmuyun",
    "材料分析": "teacher_jiangmuyun",
    "言语理解与表达": "teacher_alimujiang",
    "言语理解": "teacher_alimujiang",
    "言语": "teacher_alimujiang",
    "花生言语": "teacher_huasheng_verbal",
    "花生十三言语": "teacher_huasheng_verbal",
    "花生·言语": "teacher_huasheng_verbal",
    "花生十三（言语理解与表达）": "teacher_huasheng_verbal",
    "政治理论": "teacher_fengze_politics",
    "政治": "teacher_fengze_politics",
    "冯泽政治理论": "teacher_fengze_politics",
    "冯泽·政治理论": "teacher_fengze_politics",
    "冯泽政治": "teacher_fengze_politics",
    "常识判断": "teacher_fengze_common_sense",
    "常识": "teacher_fengze_common_sense",
    "文史常识": "teacher_fengze_common_sense",
    "历史常识": "teacher_fengze_common_sense",
    "文学常识": "teacher_fengze_common_sense",
    "科技常识": "teacher_fengze_common_sense",
    "经济常识": "teacher_fengze_common_sense",
    "法律常识": "teacher_fengze_common_sense",
    "法律": "teacher_fengze_common_sense",
    "宪法": "teacher_fengze_common_sense",
    "民法": "teacher_fengze_common_sense",
    "刑法": "teacher_fengze_common_sense",
    "行政法": "teacher_fengze_common_sense",
    "冯泽常识": "teacher_fengze_common_sense",
    "冯泽·常识": "teacher_fengze_common_sense",
    "冯泽常识判断": "teacher_fengze_common_sense",
    "冯泽·常识判断": "teacher_fengze_common_sense",
}

class ModuleTeacherService:
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or CONFIG_FILE
        self._config = self._load_config()
        self._cache = {}

    def _load_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            return {"teachers": {}}
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def resolve_teacher_id_for_module(self, module: str, preferred_teacher_id: Optional[str] = None) -> Optional[str]:
        """根据题目模块名称解析对应的教师标识，支持显式指定优先教师。"""
        if preferred_teacher_id and preferred_teacher_id in self._config.get("teachers", {}):
            return preferred_teacher_id
        if not module:
            return None
        aliases = {
            "数量": "数量关系",
            "逻辑": "逻辑判断",
            "定义": "定义判断",
            "资料": "资料分析",
            "图推": "图形推理",
            "立体图推": "立体图推",
            "立体": "立体图推",
            "文段": "文段分析",
            "材料": "材料分析",
            "言语": "言语理解与表达",
            "言语理解": "言语理解与表达",
            "片段阅读": "言语理解与表达",
            "逻辑填空": "言语理解与表达",
            "语句表达": "言语理解与表达",
            "篇章阅读": "言语理解与表达",
            "花生言语": "花生言语",
            "花生十三言语": "花生言语",
            "花生·言语": "花生言语",
            "政治": "政治理论",
            "时政": "政治理论",
            "党和国家方针政策": "政治理论",
            "马原": "政治理论",
            "马克思主义基本原理": "政治理论",
            "新思想": "政治理论",
            "冯泽政治理论": "政治理论",
            "冯泽·政治理论": "政治理论",
            "常识": "常识判断",
            "文史": "常识判断",
            "文史常识": "常识判断",
            "历史常识": "常识判断",
            "文学常识": "常识判断",
            "科技常识": "常识判断",
            "经济常识": "常识判断",
            "法律常识": "常识判断",
            "法律": "常识判断",
            "宪法": "常识判断",
            "民法": "常识判断",
            "刑法": "常识判断",
            "行政法": "常识判断",
            "冯泽常识": "常识判断",
            "冯泽·常识": "常识判断",
            "冯泽常识判断": "常识判断",
            "冯泽·常识判断": "常识判断",
        }
        return MODULE_TEACHER_ID_MAP.get(aliases.get(module.strip(), module.strip()))

    def get_teacher_context_for_review(
        self,
        module: str,
        stem: str,
        explanation: str = "",
        user_selected: str = "",
        student_thought: str = "",
        preferred_teacher_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """
        为交互式复盘与 AI 追问提供对应名师的知识切片、规则与纠偏警示。
        毫秒级纯本地检索，无外部调用。
        """
        tid = self.resolve_teacher_id_for_module(module, preferred_teacher_id=preferred_teacher_id)
        if not tid:
            return None
        tcfg = self._config.get("teachers", {}).get(tid)
        if not tcfg or not tcfg.get("enabled", True):
            return None

        # 江牧云·文段分析教师范围门禁：模块复盘入口统一越界拦截
        if tid == "teacher_jiangmuyun":
            from .shenlun_teacher.engine.boundary_guard import check_jiangmuyun_boundary
            guard = check_jiangmuyun_boundary(
                question_stem=stem,
                student_text=f"{explanation} {user_selected} {student_thought}"
            )
            if not guard["allowed"]:
                return {
                    "teacher_id": tid,
                    "teacher_name": tcfg.get("name", "江牧云·文段分析"),
                    "author": tcfg.get("author", "江牧云"),
                    "module": "文段分析",
                    "out_of_scope_rejected": True,
                    "rejection_reason": guard["reason"],
                    "signature_advice": guard["message"],
                    "policies": [],
                    "critique": None,
                    "context_role": "out_of_scope_guard",
                    "diagnosis_status": "rejected"
                }

        # 花生十三·言语理解与表达教师范围门禁：模块复盘入口统一越界拦截
        if tid == "teacher_huasheng_verbal":
            from .huasheng_verbal_boundary_guard import check_huasheng_verbal_boundary
            guard = check_huasheng_verbal_boundary(
                question_stem=stem,
                student_text=f"{explanation} {user_selected} {student_thought}"
            )
            if not guard["allowed"]:
                return {
                    "teacher_id": tid,
                    "teacher_name": tcfg.get("name", "花生十三（言语理解与表达）"),
                    "author": tcfg.get("author", "花生十三"),
                    "module": "言语理解与表达",
                    "out_of_scope_rejected": True,
                    "rejection_reason": guard["reason"],
                    "signature_advice": guard["message"],
                    "policies": [],
                    "critique": None,
                    "context_role": "out_of_scope_guard",
                    "diagnosis_status": "rejected"
                }

        base_dir = resolve_base_dir(tcfg["base_dir"])
        if tid not in self._cache:
            lib_dir = base_dir / "library"
            policies = json.loads((lib_dir / "policies_full.json").read_text(encoding="utf-8")) if (lib_dir / "policies_full.json").exists() else []
            critiques = json.loads((lib_dir / "critique_cases_full.json").read_text(encoding="utf-8")) if (lib_dir / "critique_cases_full.json").exists() else []
            profile = json.loads((base_dir / "profile" / "teacher_profile.json").read_text(encoding="utf-8")) if (base_dir / "profile" / "teacher_profile.json").exists() else {}
            self._cache[tid] = {
                "policies": policies,
                "critiques": critiques,
                "profile": profile,
            }

        data = self._cache[tid]
        policies = data["policies"]
        critiques = data["critiques"]
        profile = data["profile"]

        # 针对题干与解析进行特征匹配
        search_haystack = f"{stem} {explanation}".lower()
        if tid == "teacher_longfei" and "奇度" in search_haystack:
            search_haystack += " 奇点"
        if not stem.strip():
            return None
        topics = {
            "翻译推理": ("如果", "只有", "除非", "逆否", "充分", "必要", "推出"),
            "真假话": ("真话", "假话", "说谎"),
            "归因论证": ("导致", "归因", "实验", "因果", "患病"),
            "工程": ("工程", "单独", "合作", "完工"),
            "行程": ("路程", "速度", "行程", "追及", "相遇"),
            "溶液": ("溶液", "浓度", "盐水"),
            "比重": ("比重", "占比", "占总", "所占"),
            "平均": ("平均", "人均", "户均"),
            "排列": ("排列", "组合", "概率"),
            "对策": ("必须", "应该", "应当", "需要", "务必", "唯有", "对策", "当务之急", "关键在于", "措施", "做法", "构建", "建立", "探索"),
            "转折": ("但是", "然而", "却", "不过", "实际上", "其实", "反之", "反而"),
            "因果": ("因此", "所以", "导致", "造成", "因而", "致使", "之所以"),
            "反面论证": ("如果不", "若不", "否则", "一旦"),
            "并列": ("此外", "另外", "同时", "一方面", "兼顾"),
            "细节": ("相符", "不相符", "正确的一项", "不正确的一项"),
        }

        # 1. 检索 Top 2 命中规则
        scored_policies = []
        for p in policies:
            if p.get("verification_status") == "quarantined":
                continue
            score = 0.0
            cat = p.get("category", "").lower()
            name = p.get("name", "").lower()
            trigger = p.get("trigger", "").lower()
            # Specific phenomena are not generic definition methods.
            if tid == "teacher_definition" and "蜈蚣效应" in p.get("rule", ""):
                if not any(feature.lower() in search_haystack for feature in p.get("identification_features", []) if feature):
                    continue
            if tid == "teacher_logic" and "削弱" in name:
                if any(word in stem for word in ("支持", "加强")) and not any(word in stem for word in ("削弱", "质疑", "反驳")):
                    continue
            if tid == "teacher_quant" and "给效率型" in name and not re.search(r'效率比|效率.{0,8}[：:]|效率.{0,8}比例', search_haystack):
                continue

            # 类别与核心主题匹配
            if cat and (cat in search_haystack or any(w in search_haystack for w in ["比重", "工程", "行程", "溶液", "归因", "质疑", "定义", "速算", "文段", "主旨", "结构", "逻辑", "总结", "重复", "启示", "理解", "观点"] if w in cat)):
                score += 8.0
            for feat in p.get("identification_features", []):
                if feat and feat.lower() in search_haystack:
                    score += 4.0
            for kw in re.split(r"[——\s]+", name):
                if kw and len(kw) >= 2 and kw in search_haystack:
                    score += 3.0
            if trigger and any(w in search_haystack for w in ["比重", "增长", "工程", "实验", "定义", "文段", "材料", "总结"] if w in trigger):
                score += 2.0
            for topic, terms in topics.items():
                if topic in cat and any(term in search_haystack for term in terms):
                    score += 8.0
            if tid == "teacher_definition" and cat in {"被定义词拆解", "核心要素拆解", "圈词避坑原则"}:
                score += 4.0
            if tid == "teacher_jiangmuyun":
                if any(k in search_haystack for k in ("文段", "材料", "主旨", "逻辑", "结构", "总分", "并列", "转折", "因果", "总结", "重复", "启示", "理解", "观点")):
                    score += 6.0
            if tid == "teacher_alimujiang":
                cond_txt = f"{p.get('conditions', '')} {p.get('trigger', '')} {p.get('name', '')} {p.get('quote', '')}"
                hit_tokens = [w for w in ("必须", "应该", "需要", "如果", "但是", "然而", "因此", "所以", "相符", "不相符", "排序", "填空", "指代", "比喻", "成语", "对策", "转折", "因果", "并列", "反面论证", "主旨", "文段", "意在", "强调") if w in search_haystack and w in cond_txt]
                if hit_tokens:
                    score += 4.0 * len(hit_tokens)
                elif any(k in search_haystack for k in ("转折", "因果", "对策", "并列", "反面论证", "细节", "排序", "填空", "代词", "比喻", "成语", "篇章", "主旨", "文段", "语义", "意在", "强调", "相符")):
                    score += 6.0
                else:
                    score += 4.5
            if tid == "teacher_huasheng_verbal":
                cond_txt = f"{p.get('conditions', '')} {p.get('trigger', '')} {p.get('name', '')} {p.get('quote', '')} {p.get('rule', '')}"
                hit_tokens = [w for w in ("必须", "应该", "需要", "对策", "转折", "因果", "并列", "反面论证", "主旨", "文段", "意在", "强调", "相符", "断桥", "填入", "排序", "分堆", "双主体", "科普", "新闻", "甚至", "递进", "务实", "实效", "傻瓜式", "梦中情答", "片面", "杂糅", "历程", "意图", "侧重", "辨析", "固定搭配", "搭配", "生僻", "积累", "泥沼", "桎梏", "藩篱", "窠臼", "羁绊", "束缚", "南辕北辙", "背道而驰", "本末倒置", "得不偿失", "适得其反", "功亏一篑", "波澜壮阔", "铭刻", "镌刻", "成语", "实词") if w in search_haystack and w in cond_txt]
                if hit_tokens:
                    score += 4.0 * len(hit_tokens)
                elif any(k in search_haystack for k in ("对策", "转折", "因果", "并列", "反面论证", "细节", "排序", "填空", "成语", "选词", "主旨", "文段", "语义", "意在", "强调", "相符", "甚至", "递进", "辨析", "积累")):
                    score += 6.0
                else:
                    score += 4.5
            if tid == "teacher_fengze_politics":
                cond_txt = f"{p.get('conditions', '')} {p.get('trigger', '')} {p.get('name', '')} {p.get('quote', '')} {p.get('rule', '')} {p.get('category', '')}"
                hit_tokens = [w for w in ("改革", "三中全会", "新质生产力", "中国式现代化", "高质量发展", "经济工作会议", "政府工作报告", "中央一号文件", "第一性", "唯物", "唯心", "矛盾", "主要矛盾", "主要方面", "量变", "质变", "否定之否定", "实践", "认识", "真理", "社会存在", "生产力", "生产关系", "上层建筑", "商品", "价值", "剩余价值", "创业带动就业", "以制度建设为主线", "以进促稳", "先立后破", "赤字率", "两重", "两新", "农业强国", "教育强国") if w in search_haystack and w in cond_txt]
                if hit_tokens:
                    score += 4.0 * len(hit_tokens)
                elif any(k in search_haystack for k in ("政治", "哲学", "马原", "新思想", "时政", "三中全会", "改革", "现代化", "生产力", "矛盾", "实践", "真理", "商品", "价值", "工作报告", "中央一号文件")):
                    score += 6.0
                else:
                    score += 4.5
            if tid == "teacher_fengze_common_sense":
                cond_txt = f"{p.get('conditions', '')} {p.get('trigger', '')} {p.get('name', '')} {p.get('quote', '')} {p.get('rule', '')} {p.get('category', '')}"
                hit_tokens = [w for w in ("商鞅", "推恩令", "宗法", "嫡长子", "三省六部", "军机处", "建安风骨", "山水田园", "边塞诗", "工业革命", "珍妮纺纱机", "蒸汽机", "非遗", "春节", "元宵节", "牛顿", "维生素", "空间站", "需求价格弹性", "薄利多销", "恩格尔", "基尼系数", "公共物品", "通货膨胀", "准备金", "宪法宣誓", "一府一委两院", "国务院", "行为能力", "善意取得", "脱手物", "定金", "违约金", "借款利息", "正当防卫", "紧急避险", "未遂", "中止", "自首", "立功", "抢劫", "行政许可", "行政处罚", "行政复议", "举证责任") if w in search_haystack and w in cond_txt]
                # 严格证据门禁：必须命中具体考点特征词才计分；无明确考点匹配则不给分，不注入无关规则
                if hit_tokens:
                    score += 4.0 * len(hit_tokens)
            if tid == "teacher_longfei":
                policy_text = f"{cat} {name} {trigger}"
                if any(term in name and term not in search_haystack for term in ("阴影", "六面体", "四面体", "三视图", "截面", "黑白", "笑脸")):
                    continue
                for feature in ("一笔画", "奇点", "奇度", "对称", "旋转", "翻转", "平移", "封闭", "截面", "三视图", "公共边", "公共点", "六面体", "四面体", "叠加", "黑白", "连通"):
                    if feature in search_haystack and feature in policy_text:
                        score += 5.0
            if score >= 4.0:
                scored_policies.append((score, p))
        scored_policies.sort(key=lambda x: -x[0])
        top_pols = [p for _, p in scored_policies[:2]] if scored_policies else []
        if not top_pols:
            return None

        # Classroom error examples are not evidence of this student's error.
        # A separate, validated attempt diagnosis must establish that relationship.

        # 3. 抽取名师代表性金句与考场策略
        ts = profile.get("teaching_style", {})
        if isinstance(ts, dict):
            principles = ts.get("core_principles", [])
        elif isinstance(ts, list):
            principles = ts
        elif isinstance(ts, str):
            principles = [ts]
        else:
            principles = []
        principles = principles or profile.get("pedagogy_principles", [])
        signature_advice = principles[0] if principles else "先抓题干核心条件，严格依照老师口诀与排他要素解题。"

        return {
            "teacher_id": tid,
            "teacher_name": tcfg.get("name"),
            "author": tcfg.get("author"),
            "module": tcfg.get("module"),
            "policies": [
                {
                    "policy_id": p.get("policy_id"),
                    "name": p.get("name"),
                    "rule": p.get("rule") or ("；".join(p.get("steps", []))),
                    "category": p.get("category"),
                    "forbidden_transformations": p.get("forbidden_transformations", []),
                    "source": p.get("source", []), "author_teacher": p.get("author_teacher", tcfg.get("author")),
                    "status": p.get("status")
                }
                for p in top_pols
            ],
            "critique": None,
            "signature_advice": signature_advice,
            "context_role": "method_reference", "diagnosis_status": "not_assessed"
        }

    def list_teachers(self) -> Dict[str, Any]:
        """返回已启用的四模块独立教师列表。"""
        out = []
        for tid, tcfg in self._config.get("teachers", {}).items():
            if tcfg.get("enabled", True):
                stats = self._asset_statistics(tid, tcfg)
                out.append({
                    "teacher_id": tid,
                    "name": tcfg.get("name"),
                    "module": tcfg.get("module"),
                    "author": tcfg.get("author"),
                    "courses_count": tcfg.get("courses_count"),
                    "policies_count": stats["assets"]["policies"]["active"],
                    "question_cases_count": stats["assets"]["question_cases"]["active"],
                    "critique_cases_count": stats["assets"]["critique_cases"]["active"],
                    "asset_statistics": stats,
                    "description": tcfg.get("description")
                    ,"coverage_status": tcfg.get("coverage_status"), "quality_scope": tcfg.get("quality_scope")
                })
        return {"teachers": out}

    def _asset_statistics(self, teacher_id: str, config: dict) -> dict:
        is_shenlun = teacher_id in ("teacher_jiangmuyun",)
        is_transcript = teacher_id in ("teacher_longfei", "teacher_jiangmuyun")
        return teacher_asset_stats(resolve_base_dir(config["base_dir"]) / "library",
                                   shenlun=is_shenlun,
                                   transcript_cases=is_transcript)

    def get_teacher_profile(self, teacher_id: str) -> Dict[str, Any]:
        """读取指定教师的认知画像与资产统计。"""
        tcfg = self._config.get("teachers", {}).get(teacher_id)
        if not tcfg:
            raise ValueError(f"未找到教师标识为 '{teacher_id}' 的独立教师配置")
        if not tcfg.get("enabled", True):
            raise ValueError("教师已停用")
        base_dir = resolve_base_dir(tcfg["base_dir"])
        profile_file = base_dir / "profile" / "teacher_profile.json"
        rep_file = base_dir / "library" / "consolidation_report.json"
        audit_file = base_dir / "evals" / "final_fidelity_audit.json"
        eval_file = base_dir / "evals" / "holdout_evaluation.json"

        profile_data = json.loads(profile_file.read_text(encoding="utf-8")) if profile_file.exists() else {}
        rep_data = json.loads(rep_file.read_text(encoding="utf-8")) if rep_file.exists() else {}
        audit_data = json.loads(audit_file.read_text(encoding="utf-8")) if audit_file.exists() else {}
        eval_data = json.loads(eval_file.read_text(encoding="utf-8")) if eval_file.exists() else {}
        stats = self._asset_statistics(teacher_id, tcfg)
        current_config = {**tcfg, **{f"{kind}_count": stats["assets"][kind]["active"]
                                   for kind in ("policies", "question_cases", "critique_cases")}}

        return {
            "teacher_config": current_config,
            "profile": current_teacher_profile(profile_data, stats),
            "asset_statistics": stats,
            "historical_report_scope": "library_report, fidelity_audit and holdout_evaluation are saved snapshots, not current asset counts",
            "library_report": rep_data,
            "fidelity_audit": audit_data,
            "holdout_evaluation": eval_data
        }

    def explain_question(self, teacher_id: str, question_payload: Dict[str, Any]) -> Dict[str, Any]:
        """调用指定教师的纯本地确定性讲题引擎，生成结构化讲题报告。"""
        tcfg = self._config.get("teachers", {}).get(teacher_id)
        if not tcfg:
            raise ValueError(f"未找到教师标识为 '{teacher_id}' 的独立教师配置")
        if not tcfg.get("enabled", True):
            raise ValueError("教师已停用")
        question_payload = dict(question_payload)
        stem = question_payload.get("stem") or question_payload.get("definition_body") or question_payload.get("figure_description", "")
        if not isinstance(stem, str) or not stem.strip():
            raise ValueError("请提供完整题干 stem 或定义正文 definition_body")
        if teacher_id == "teacher_definition":
            question_payload.setdefault("definition_body", stem)
        if not isinstance(question_payload.get("options", {}), dict):
            raise ValueError("options 必须为选项对象")
        if teacher_id == "teacher_longfei":
            context = self.get_teacher_context_for_review("图形推理", question_payload.get("figure_description") or stem)
            lines = ["# 龙飞图形推理方法参考", stem, "", "以下为字幕方法参考，适用条件须另行核验，不是本题答案或学生错因。"]
            for policy in (context or {}).get("policies", []):
                lines.extend([f"\n**{policy['name']}**（{policy['policy_id']}）",policy['rule']])
                for source in policy.get("source", []):
                    lines.append(f"来源：{source['file']}，行{source['line_start']}—{source['line_end']}")
            if not context:lines.append("未命中足够相关的方法，请提供可核验的完整图形描述。")
            return {"teacher_id":teacher_id,"teacher_name":tcfg['name'],"module":tcfg['module'],"report_markdown":"\n".join(lines),"answer_status":"method_reference_only"}
        if teacher_id == "teacher_jiangmuyun":
            from .shenlun_teacher.engine.boundary_guard import check_jiangmuyun_boundary
            guard = check_jiangmuyun_boundary(
                question_stem=stem,
                question_type=question_payload.get("question_type", ""),
                student_text=str(question_payload.get("student_answer", "") or question_payload.get("student_thought", "")),
                material_text=str(question_payload.get("material", ""))
            )
            if not guard["allowed"]:
                report_lines = [
                    "# 江牧云·文段分析教师：服务受限说明",
                    "",
                    f"**教师身份**：{tcfg['name']}",
                    f"**任务判定**：超出文段分析范围（{guard['reason']}）",
                    "",
                    "---",
                    "",
                    "### 限制说明与处理建议",
                    guard["message"]
                ]
                return {
                    "teacher_id": teacher_id,
                    "teacher_name": tcfg["name"],
                    "module": tcfg["module"],
                    "report_markdown": "\n".join(report_lines),
                    "out_of_scope_rejected": True,
                    "rejection_reason": guard["reason"],
                    "answer_status": "rejected_out_of_scope"
                }
        if teacher_id == "teacher_huasheng_verbal":
            from .huasheng_verbal_boundary_guard import check_huasheng_verbal_boundary, build_rejection_report
            guard = check_huasheng_verbal_boundary(
                question_stem=stem,
                question_type=question_payload.get("question_type", ""),
                student_text=str(question_payload.get("student_answer", "") or question_payload.get("student_thought", "")),
                options=question_payload.get("options"),
                explanation=str(question_payload.get("explanation", ""))
            )
            if not guard["allowed"]:
                report_text = build_rejection_report(guard["reason"], guard["message"])
                return {
                    "teacher_id": teacher_id,
                    "teacher_name": tcfg["name"],
                    "module": tcfg["module"],
                    "report_markdown": report_text,
                    "out_of_scope_rejected": True,
                    "rejection_reason": guard["reason"],
                    "answer_status": "rejected_out_of_scope"
                }
        base_dir = resolve_base_dir(tcfg["base_dir"])
        runtime_script = base_dir / tcfg.get("runtime_cli", "runtime/run_explain.py")
        if not runtime_script.exists():
            raise FileNotFoundError(f"教师 '{teacher_id}' 的 Runtime 脚本未找到: {runtime_script}")

        # 写入临时输入文件
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as tf:
            json.dump(question_payload, tf, ensure_ascii=False)
            tmp_in = tf.name

        try:
            cmd = [sys.executable, str(runtime_script), "--input", tmp_in]
            child_env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
            proc = subprocess.run(cmd, cwd=str(base_dir), capture_output=True, text=True, encoding="utf-8", env=child_env, timeout=30)
            if proc.returncode != 0:
                raise RuntimeError(f"教师讲题引擎执行失败: {proc.stderr}")
            report_text = proc.stdout.strip()
            return {
                "teacher_id": teacher_id,
                "teacher_name": tcfg.get("name"),
                "module": tcfg.get("module"),
                "report_markdown": report_text,
                "answer_status": "method_reference_only"
            }
        finally:
            try:
                Path(tmp_in).unlink(missing_ok=True)
            except Exception:
                pass

    async def explain_current_question(self, teacher_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Reuse the application's model gateway and support gates for this question.

        The local CLI is a source-backed method reference, not an answer oracle.
        """
        from ..ai import Message, get_model_gateway
        from .interactive_assessor import StepExplanationSchema
        from .review_context import verify_explanation_support

        reference = await asyncio.to_thread(self.explain_question, teacher_id, payload)
        if reference.get("out_of_scope_rejected"):
            return reference
        options = payload.get("options", {})
        if not options:
            reference["answer_status"] = "insufficient_options"
            return reference
        stem = payload.get("stem") or payload.get("definition_body") or payload.get("figure_description", "")
        if teacher_id == "teacher_longfei":
            description = payload.get("figure_description", "")
            descriptive_stem = any(word in stem for word in ("奇度", "奇点", "一笔画", "连通", "端点", "对称轴", "旋转", "六面体", "四面体", "公共边", "三视图"))
            if not description and (not descriptive_stem or re.search(r'<img|/api/.*image|data:image',stem)):
                reference["answer_status"] = "insufficient_figure_description"
                return reference
            if description:stem += "\n图形描述：" + description
        tcfg = self._config["teachers"][teacher_id]
        context = self.get_teacher_context_for_review(tcfg["module"], stem)
        gateway = get_model_gateway()
        try:
            result = await gateway.generate(
                task_type="tutor_explanation", schema=StepExplanationSchema, model_policy="BALANCED",
                messages=[
                    Message(role="system", content="解答当前公考题，逐项核查真实选项，给出推导与最终选项。answer_verification最后必须写故选A/B/C/D之一。数值列式的等号只用于精确值，四舍五入或截位结果必须用≈。教师方法仅作参考；不能把课堂例题答案当成本题答案，不能凭选择字母诊断错因。条件不足时说明缺口。引用只可用给出的来源，不得虚构页码或教师原话。"),
                    Message(role="user", content=json.dumps({"current_question": payload, "teacher_methods": context}, ensure_ascii=False)),
                ],
            )
            if result.provider_name == "mock":
                reference["answer_status"] = "model_unavailable"
                return reference
            data = result.data.model_dump()
            provided_answer = payload.get("answer", "")
            check = verify_explanation_support(data, {"stem": stem, "module": tcfg["module"],
                "standard_answer": provided_answer, "authoritative_explanation": payload.get("explanation", "")})
            answer_text = re.sub(r"[*`#]", "", data["answer_verification"])
            selected = re.findall(r"(?:正确答案[为是]|答案[为是]|故选|选择|选)\s*[:：]?\s*([ABCD])", answer_text)
            if not data["derivation_steps"] or not selected or selected[-1] not in options:
                check.issues.append("未提供本题有效选项结论和推导")
            if provided_answer and (not selected or selected[-1] != provided_answer.strip().upper()):
                check.issues.append("结论与提供的参考答案不符")
            if check.issues:
                reference.update(answer_status="validation_failed", validation_issues=check.issues)
                return reference
            steps = "\n".join(f"{i+1}. {step}" for i, step in enumerate(data["derivation_steps"]))
            reference.update(report_markdown=f"# 当前题讲解\n\n{stem}\n\n" + "\n".join(f"{k}. {v}" for k,v in options.items())
                + f"\n\n**解法**：{data['method_name']}\n\n{steps}\n\n**答案核对**：{data['answer_verification']}\n\n"
                + reference["report_markdown"],
                answer_status="checked_against_provided_answer" if provided_answer else "model_answer_unverified",
                selected_answer=selected[-1], model_provider=result.provider_name, explanation=data)
            return reference
        except Exception:
            # An unavailable model never turns a retrieved case's answer into this answer.
            reference["answer_status"] = "model_unavailable"
            return reference
