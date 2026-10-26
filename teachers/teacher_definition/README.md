# 协作组定义判断教师模型（Teacher Definition Agent）

基于协作组公考定义判断课程（蜈蚣效应加课、理论大课、定义总结分段切片）与官方《判断理论讲义（上册）》提炼出的独立可解释讲题智能体。

## 模块信息与教师身份

- **教师标识**：`teacher_definition`
- **教师名称**：协作组定义判断主讲团队
- **所属模块**：判断推理 · 定义判断
- **课程来源**：协作组25下半年判断推理（DEF01 蜈蚣效应加课、DEF02 理论大课、DEF03 综合总结课定义切片）
- **官方教材**：【判断理论讲义（上册）】.pdf、3 份配套 PPTX 课件、讲义拆分副本
- **分段归属说明**：第3讲《定义类比图推总结2》为综合总结课，按任务书严格分段归属，仅保留定义判断段落（DEF03.txt），类比与图推内容彻底剔除，杜绝串模。

## 知识资产与统计

| 资产类型 | 数量 | 存储路径 | 说明 |
|---|---:|---|---|
| 教学规则 (Policies) | 5 | `library/policies_full.json` | 覆盖被定义词拆解、主体客体要素、法官思维、防贪多嚼不烂、博弈失衡模型 |
| 课堂案例 (QuestionCases) | 3 | `library/question_cases_full.json` | 蜈蚣效应、体育赛事赞助、诉前财产保全等真题全推演 |
| 纠偏实录 (CritiqueCases) | 3 | `library/critique_cases_full.json` | 课堂学生泛化效应、混淆商业赞助与公益捐赠、忽视法律程序客观硬伤实录 |
| 教师画像 (Profile) | 1 | `profile/teacher_profile.json` | 协作组团队定义判断教学风格与五步讲题规范 |

## 评测与审计指标

- **逼真度终审（final_audit.py）**：11 条 source quote 逐字回查 100% 精确匹配通过，Schema 错误 0，Verdict: **PASS**。
- **留出集评测（holdout_eval.py）**：
  - 条件判断准确率：**100.0%**
  - 边界反例覆盖度：**100.0%**
  - 步骤完整性得分：**100.0%**
  - 逻辑推理准确率：**100.0%**
  - 引用准确性：**100.0%**
  - 总评：**PASS**

## 本地讲题引擎用法

```bash
cd D:\gong\teacher_definition
python runtime/run_explain.py --input sample/input_definition_sample.json
```
