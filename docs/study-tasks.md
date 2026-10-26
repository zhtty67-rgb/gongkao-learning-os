# 资料转学习任务（P1 最小闭环）

把已有讲义/逐字稿/教材整理为**有出处的知识卡 + 自查题**，走「生成草稿 → 预览修订
→ 确认发布 → 自查作答」流程。入口：前端 `/study`（学习任务）；API 前缀
`/api/study`。

## 数据与纪律

- 表：`study_task_sets` + `study_tasks`（migration 048）。
- **溯源不可伪造**：草稿生成时服务端先采集证据池（节点 `metadata_json.course_sources`
  本地逐字稿[sha256+字符区间] + Knowledge Hub 证据[document/page/block locator]），
  模型输出只允许引用证据下标（`source_index`），provenance 由服务端映射；任务集
  `provenance.evidence` 保留完整证据清单可核验。
- **三类内容明确标注**（`source_kind`）：`original_excerpt` 原文摘录 / `ai_summary`
  AI 整理 / `ai_generated` AI 自编题；前端以色签区分。
- **与正式统计隔离**：全程不写 attempts/mastery/review；自查完成只落
  `study_tasks.status='done'` 与 `result_json`（含参考答案回显）。理解验证以正式
  作答为准——这是刻意设计（FSRS 与题目强耦合，见下）。
- 不创建 LearningSkill，不绑定技能；只按 knowledge_node 关联。

## 生成路径

| 路径 | 依赖 | 内容 |
| --- | --- | --- |
| AI 草稿（默认） | 模型网关 + 证据 | 摘录卡（≤证据数）+ AI 卡 2-4 + 自查题 2-3 |
| 仅原文摘录（`excerpt_only`） | 零模型 | 摘录卡（最长 8 条；资料更多时全部出处仍进证据清单） |

模型不可用 / Hub 离线 → 明确状态返回（`model_unavailable` / 降级仅本地证据），
可重试；原文摘录路径永远可用。

## FSRS 决策（核对结论）

`review_cards.question_id` 为 PK+FK（mig 003）、事件 FK 锁死 attempts、评级依赖判分
与 `estimated_seconds`、`due_reviews` JOIN 题面——**知识卡不进现行 FSRS**。若后续
要卡片复习，需独立卡片调度表（非 questions FK），另议。

## API

`POST /api/study/sets/generate {node_id, excerpt_only}` → `{status: ok|model_unavailable|no_evidence, set_id}`
`GET /api/study/sets[?node_id=&status=]`、`GET /api/study/sets/{id}`（含 tasks）
`PATCH/DELETE /api/study/tasks/{id}`（仅草稿）
`POST /api/study/sets/{id}/publish|archive`
`POST /api/study/tasks/{id}/answer {answer, understood?}` / `.../skip {reason?}`
`GET /api/study/nodes/{node_id}/summary`（供面板/今日入口）

## 已执行验证（2026-10-25/26）

- 单测 10 项全绿（`tests/test_study_tasks.py`）：证据采集/溯源映射/状态机/统计
  隔离断言（attempts 与 mastery_evidence 零变化）/API 全流程/降级路径。
- **真实章节闭环**（正式库副本 `work/study-acceptance/`，零污染正式库）：政治理论
  节点 107 条真实逐字稿资料 → 摘录卡取最长 8 条（全部出处留痕）→ 发布 → 作答 →
  进度 1/8，attempts 不变、mastery_evidence 保持 728。
- **真实 Hub 通路**：拉起 Hub API 后对 `quant_equation_ratio`（和差倍比与方程法）
  采集到《四海·数量关系第一讲随堂笔记》6 条真实证据（页码 p2 + block locator）。
- AI 生成路径：stub 网关单测通过；**真实模型未验证**（本机模型代理 8045 离线），
  模型可用后经页面一键可试，失败路径已有明确状态与重试入口。

## 已知限制

- AI 草稿质量依赖模型与证据质量；自查题为理解应用型，非判分题。
- Hub 证据目前仅覆盖已绑定节点（数量关系 2 节点）；政治课走本地 course_sources。
- 任务集发布后内容锁定（修订=归档重生成）；不提供 FSRS 调度。
