# G 老师图推讲题智能体（Teacher Longfei Agent）

从协作组公考G 老师老师 41 讲图推课程逐字稿（约 124 万字）中"炼"出的可解释讲题智能体：结构化规则库 + 课堂真题案例库 + 纠偏实录库 + 纯本地讲题 Runtime。

> 来源：`C:\Users\86155\Documents\Codex\2026-10-02\plugin-computer-use-openai-bundled\outputs\G 老师教师模型语料`（3 门课、41 份字幕 .doc（OOXML）、5 份讲义 PDF）
> 方法：沿用 `teacher_feiyang` / `teacher_zhanzhang` 的"原始课程 → 规则 → 案例 → 教师画像 → 校验"流水线
> 原则：**只从一手逐字稿提取、每条规则可反查原话、引擎不发明G 老师没讲过的规律**

## 课程与讲次编码

| 编码 | 课程 | 讲数 | 内容 |
|---|---|---:|---|
| ZJ01–ZJ11 | 2026 平面图形推理筑基先行班 | 11 | 线/面+点角/元素 3 讲理论 + 7 讲百大图形 + 联考真题致用加课 |
| WB01–WB17 | 2026 平面图推精讲500题 | 17 | 13 讲真题刷题 + 2 讲G 老师原创题 + 2 讲答疑 |
| LT01–LT13 | 2026 立体图推理论刷题班 | 13 | 展开图/三视图/截面/立体拼合四模块（LT03/LT04 为 LT02 重播分段，验证为真子集，已记空） |

## 目录结构

```text
teacher_longfei/
│   └── ../transcripts_manifest.json
├── reference/            # 讲义 PDF 原件 + pdf_text/ 可提取文本
│   └── pdf_text/         # 筑基/500题讲义文本可提取；立体讲义为纯扫描图（0 字符，未 OCR）
├── policies/             # 按讲次拆分的 TeacherPolicy（41 个 JSON）
├── cases/                # 按讲次拆分的 QuestionCase / CritiqueCase（82 个 JSON）
├── library/              # 合并去重后的全量库（Runtime 优先加载）
│   ├── policies_full.json          # 419 条方法规则
│   ├── question_cases_full.json    # 574 道课堂讲题案例
│   ├── critique_cases_full.json    # 327 条学生纠偏实录
│   └── consolidation_report.json
├── profile/teacher_profile.json    # 教师认知画像
├── evals/final_fidelity_audit.json # 逼真度审计（schema + 全量 quote 逐字回查）
├── runtime/              # 讲题引擎（纯本地，零 API）
│   ├── library.py            # 知识库加载与特征短语索引
│   ├── explain_engine.py     # 检索（政策/相似真题/纠偏）+ 报告合成
│   └── run_explain.py        # CLI 入口
├── sample/               # 演示输入（取自真实课堂题：平面一笔画/点修正、立体截面镂空）
├── out/                  # 讲题报告输出
├── scripts/              # 流水线脚本（unpack/consolidate/final_audit）
└── EXTRACTION_SPEC.md    # 提取规范（子代理用的宪法+schema）
```

## 讲题 Runtime 用法

```bash
cd D:\gong\teacher_longfei
python runtime/run_explain.py --input sample/input_flat_yibihua.json --out out/report_flat.md
python runtime/run_explain.py --input sample/input_stereo_section.json --out out/report_section.md
```

输入 JSON（图形必须是**文字描述**，图推引擎不看图）：

```json
{
  "question_format": "一段式|两组式|九宫格|分类分组|空间重构|三视图|截面图|立体拼合|unknown",
  "figure_description": "逐图/逐选项的文字描述（越细检索越准）",
  "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
  "student_reasoning": "学生自己的思路或所选答案（可选，触发纠偏检索）",
  "focus": "手工指定的关注点（可选）"
}
```

输出（Markdown）：
1. **先对齐颗粒度**：命中的"解题流程"类政策（G 老师的看图顺序）
2. **规律定位候选**：按识别特征命中度排序的规则（含规则正文、命中特征、易错警告）
3. **相似课堂真题**：QuestionCase 检索（识别特征→定位规律→课堂答案）
4. **易错与纠偏提醒**：学生有思路时检索 CritiqueCase（错因+纠正）
5. **诚实声明**：检索边界与语料限制

## 与申论教师模型的差异

飞扬/站长是**批改智能体**（规则检查器诊断学生作答）；G 老师是**讲题智能体**（图形题无法程序化"批改"，价值在方法论检索与推理链示范）：
- Policy 增加 `category`（规律-线/面/点角/元素、立体-展开图/三视图/截面/拼合、解题流程、命题思路、考场策略）与 `identification_features`（"看到什么信号想什么规律"）；
- QuestionCase 以 `figure_description`（老师口头描述的忠实转述，未描述维度标 unknown）替代图形本体，附 `analysis.entry_features / law_located / verification` 推理链；
- CritiqueCase 收课堂学生错选/卡壳与G 老师当场纠正（error_type + diagnosis + remedy_instruction）。

## 数据流水线

```text
讲义/*.pdf ──(pymupdf；立体为扫描图跳过)──▶ reference/pdf_text/*.txt
        │
        ├─(LLM 提取，按 EXTRACTION_SPEC.md 宪法，41 讲并行)─▶ policies/*.json + cases/*.json
        │
        └─(scripts/consolidate.py 合并去重)─▶ library/*_full.json + consolidation_report.json
                                             │
                                    runtime/ 讲题引擎 ◀── sample/ 输入
scripts/final_audit.py ──▶ evals/final_fidelity_audit.json（schema + quote 逐字回查，当前 PASS）
```

## 炼老师宪法（提取时强制遵守）

1. 只从一手逐字稿提取，不得补充模型自己的图推知识；
2. 规则三级：`explicit` / `inferred`（≥2 处独立证据）/ `hypothesis`（宁可不写）；本次提取全部为 explicit；
3. 每条规则必须带 `source.quote` 课堂原话，审计脚本做逐字子串回查；
4. 单题技巧不上升为普遍规则（`applies_to` + `identification_features` 限定）；
5. 老师前后冲突时双写保留（如异形体例题先说选 A 后说选 B、课堂当场改答案处），不擅自统一；
6. 不收集口头禅、语气、人格评价；
7. 图形只用老师口头描述，严禁自行想象补画、严禁编造题号/年份。

## 已知边界（诚实声明）

- 图形推理题目本体是图形，语料中只有老师的口头描述：案例库 `figure_description` 忠实转述口头描述，**不能据此还原图形**；描述不了的维度标 `unknown`；
- 部分题G 老师课堂未报答案或口述不清，`answer` 如实标 unknown（未按讲义反推补填）；
- 立体讲义 PDF 为纯扫描图未 OCR（逐字稿已完整覆盖课程内容，讲义仅作题目对照）；
- 讲题引擎为确定性检索：识别特征短语命中驱动，图形描述越细检索越准；引擎不做图形理解、不输出G 老师没讲过的规律；
- 500题班每讲约 25 题按"推理链完整度"收录约 20 道，一笔带过的送分题未收（其方法论已并入对应政策）。
