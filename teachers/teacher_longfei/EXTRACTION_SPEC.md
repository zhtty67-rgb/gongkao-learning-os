# G 老师图推教师模型 · 提取规范（子代理必读）

你的任务：从G 老师图推课程逐字稿中提取"教师政策（方法论规则）"与"课堂案例"，写入指定 JSON 文件。
这是"炼老师"流水线，**忠实度高于一切**。提取时强制遵守以下宪法：

## 炼老师宪法（违反任何一条即废件）

1. **只从一手逐字稿提取**。不得补充你自己的图推知识、不得"帮他补全"理论体系。
   老师没讲的规律，哪怕你觉得重要，也不许写。
2. **规则分三级 status**：
   - `explicit`：老师明确说过（"一笔画要看出头端点"）；
   - `inferred`：老师没一句概括，但 ≥2 个独立案例/片段支持同一规则（reasoning 里写明证据来自哪两处）；
   - `hypothesis`：单次出现且你不确定的泛化，宁可不写。
3. **每条规则必须带 `source[].quote` 课堂原话**，从逐字稿中**逐字复制**（可用"..."截取中段，但复制部分必须与原文逐字一致，审计脚本会做子串校验）。
   quote 只收"教学内容"，寒暄、休息、招生宣传、班次介绍一律不收。
4. **单题技巧不得上升为普遍规则**：只对某类图成立的写进 `applies_to`/`identification_features` 限定。
5. **老师前后冲突时**：两条都写，各带 source，`reasoning` 里注明 `conflict`，不得擅自统一。
6. **不收集**口头禅、语气词、人格评价、个人经历（除非直接影响方法论，如"我阅卷经验"）。
7. **图形必须用老师的口头描述**：逐字稿没有画面，老师说到什么程度你就写到什么程度；
   描述不了的维度写 `"unknown"`，**严禁自行想象补画图形细节、严禁编造题号/年份**。

## 图推领域适配

- 提取对象是"怎么看图、怎么定位规律、怎么排除干扰、怎么提速"，不是申论那种批改规则。
- G 老师方法论的核心线索（仅供你组织 `category`，不是允许你补充的内容）：
  规律维度（线/面/点角/元素等）、识别特征→规律定位的观察顺序、出题人心态与干扰项设计、
  百大图形案例、立体（展开图/三视图/截面/拼合）、考场策略与秒杀技巧。
- 出题人视角的话（"出题人为什么这么画"）是G 老师方法论的重要部分，属 `category: "命题思路"`。

## TeacherPolicy schema（policies/policies_{PREFIX}.json，数组）

```json
{
  "policy_id": "LONGFEI_POL_{PREFIX}_001",
  "teacher_id": "teacher_longfei",
  "name": "规则短名（如：一笔画识别——出头端点计数）",
  "status": "explicit",
  "category": "规律-线|规律-面|规律-点角|规律-元素|立体-展开图|立体-三视图|立体-截面|立体-拼合|解题流程|命题思路|考场策略|其他",
  "trigger": "什么样的图形特征/题型特征触发这条规则",
  "rule": "规则正文（老师的方法原意，不添加你自己的表述习惯之外的新内容）",
  "reasoning": "老师给的理由/出题人心态；inferred 时写明≥2处证据位置",
  "identification_features": ["看到什么信号想这条规律（逐字稿中老师教的识别特征）"],
  "applies_to": ["一段式|两组式|九宫格|分类分组|空间重构|三视图|截面图|立体拼合|通用"],
  "must_preserve": ["应用时必须保留的关键约束"],
  "may_remove": [],
  "forbidden_transformations": ["老师明确警告的错误思路/易错点"],
  "positive_example": {"input": "老师举的图形/题（口头描述）", "preferred": "老师怎么解", "reason": "为什么对"},
  "negative_example": {"input": "同上或老师举的反例", "bad_output": "错误思路", "reason": "老师批评的点"},
  "source": [{"course": "{PREFIX}", "segment_id": "任意稳定小写标识", "quote": "课堂原话，逐字复制"}],
  "confidence": 1.0
}
```

字段取舍：`must_preserve/may_remove` 若确无对应内容可为空数组，其余字段必填。
每讲政策量级参考：理论讲（ZJ01-03）约 6-12 条；百大图形/刷题讲 2-6 条；答疑讲 0-4 条。**没有就不硬凑**。

## QuestionCase schema（cases/question_cases_{PREFIX}.json，数组）

```json
{
  "question_id": "LONGFEI_QC_{PREFIX}_001",
  "teacher_id": "teacher_longfei",
  "title": "一句话概括本题（如：两组式，线条数递增）",
  "source_exam": "老师口述的题目来源，没说就写\"课堂讲解题\"",
  "question_format": "一段式|两组式|九宫格|分类分组|空间重构|三视图|截面图|立体拼合|unknown",
  "figure_description": "按图序/选项逐一转述老师的口头图形描述，没描述到的维度标 unknown",
  "options": {"A": "口头描述或留空", "B": "", "C": "", "D": ""},
  "answer": "老师教的答案（如未明说写 unknown）",
  "analysis": {
    "entry_features": ["G 老师第一眼抓的识别特征"],
    "law_located": "定位到的规律",
    "verification": "验证与排除干扰项的过程",
    "key_points": ["关键推理步骤"]
  },
  "teacher_reasoning": "G 老师完整推理链的忠实转述（可用课堂原话拼接）",
  "technique_policies": ["命中的规则名（如'一笔画识别'），本讲内能对上的才写"],
  "source": [{"course": "{PREFIX}", "quote": "讲解起始处原话，逐字复制"}]
}
```

每讲案例量级：刷题讲（WB/LT刷题课）8-20 道；理论讲 3-8 道；讲不完的完整题宁可少收，**质量优先**。
同一题老师分多轮讲完的合并为一条。

## CritiqueCase schema（cases/critique_cases_{PREFIX}.json，数组）

学生卡壳/错选/错误说法 + 老师当场纠正的课堂实录：

```json
{
  "case_id": "LONGFEI_CC_{PREFIX}_001",
  "teacher_id": "teacher_longfei",
  "question": "关联的题（对应 question_id 或一句话题面）",
  "student_error_snippet": "学生的错误选择/说法（老师转述的也要收，注明'学生说'）",
  "error_type": "规律误判|特征漏看|干扰项陷阱|思维僵化|立体想象错误|粗心失误|其他",
  "diagnosis": "老师指出的错因（忠实转述）",
  "severity": "high|medium|low",
  "remedy_instruction": "老师给的纠正方法",
  "source_quote": {"course": "{PREFIX}", "quote": "纠正片段原话，逐字复制；找不到合适原话可省略此字段"}
}
```

## 输出与自检

- 每讲三个文件：`policies/policies_{PREFIX}.json`、`cases/question_cases_{PREFIX}.json`、`cases/critique_cases_{PREFIX}.json`。
  某类确无内容写 `[]`。UTF-8，合法 JSON（写完后用 python -c json.load 自检一遍）。
- 自检：每条 quote 在对应 `{PREFIX}.txt` 逐字稿中做子串查找（把"..."两边分别查）；查不到的必须修正或删除。
- 分组说明（如有）写在最后一条回复里，不写入 JSON。
