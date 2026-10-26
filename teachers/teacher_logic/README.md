# L 老师逻辑判断教师模型（Teacher Logic Agent）

基于协作组公考L 老师逻辑判断 13 讲课程逐字稿（清洗后约 36 万字）与官方《判断理论讲义（上册）》提炼出的独立可解释讲题智能体。

## 模块信息与教师身份

- **教师标识**：`teacher_logic`
- **教师名称**：L 老师（协作组公考判断推理主讲）
- **所属模块**：判断推理 · 逻辑判断
- **课程来源**：协作组25下半年判断推理（13讲：LOGIC01~LOGIC13）
- **官方教材**：【判断理论讲义（上册）】.pdf、13 份配套 PPTX 课件、讲义拆分副本

## 知识资产与统计

| 资产类型 | 数量 | 存储路径 | 说明 |
|---|---:|---|---|
| 教学规则 (Policies) | 24 | `library/policies_full.json` | 覆盖归因论证、三圈质疑、搭桥与前提、翻译推理、真假话分析等 |
| 课堂案例 (QuestionCases) | 13 | `library/question_cases_full.json` | 逐讲典型真题推演链，含 entry_features 与 law_located |
| 纠偏实录 (CritiqueCases) | 13 | `library/critique_cases_full.json` | 课堂学生错选、伪他因混淆、主观脑补等真实纠偏实录 |
| 教师画像 (Profile) | 1 | `profile/teacher_profile.json` | L 老师教学风格、核心原则与十步讲题规范 |

## 评测与审计指标

- **逼真度终审（final_audit.py）**：50 条 source quote 逐字回查 100% 精确匹配通过，Schema 错误 0，Verdict: **PASS**。
- **留出集评测（holdout_eval.py）**：
  - 条件判断准确率：**100.0%**
  - 边界反例覆盖度：**100.0%**
  - 步骤完整性得分：**100.0%**
  - 逻辑推理准确率：**100.0%**
  - 引用准确性：**100.0%**
  - 总评：**PASS**

## 本地讲题引擎用法

```bash
cd D:\gong\teacher_logic
python runtime/run_explain.py --input sample/input_logic_sample.json
```
