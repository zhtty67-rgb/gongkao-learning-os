# Gongkao Learning OS 接口摘要

修订：2026-10-04。本文是重点接口摘要，示例数量不是正式库状态。当前源码完整路由、请求 Schema、required 和响应声明见 [路由清单](generated/API_ROUTES.md)、[OpenAPI](generated/openapi.json)。时间、源码版本及 SHA-256 见 [生成清单](generated/manifest.json)。重新生成：`.venv/Scripts/python.exe scripts/export_document_contracts.py`；运行进程是否匹配须另行核实。

- **默认基础路径 (Base URL)**：`http://127.0.0.1:8000`
- **协议约定**：通常为 UTF-8 JSON；`POST /api/importer/upload` 使用 `multipart/form-data`（question_file 必填文件，answer_file 可选文件，title 可选表单字段），浏览器自动生成 boundary。
- **安全与幂等**：
  - 作答提交及特定评分按各自幂等规则处理；教学动作使用 request_id 与 revision，笔记编辑可带 expected_version。不能假设所有写接口都有相同保护。
  - 全真模考期间（`EXAM` 模式），所有 AI 辅导与提示接口（`/hint`, `/diagnose`, `/explain`, `/followup`）强制返回 HTTP 403 `EXAM_MODE_LOCKED`。

---

## 目录
1. [系统监控与仪表盘 (System & Dashboard)](#1-系统监控与仪表盘)
2. [单选题训练流 (Quiz Practice Flow)](#2-单选题训练流)
3. [错因归因与 AI 助教答疑追问 (Errors & AI Tutor Follow-up)](#3-错因归因与-ai-助教答疑追问)
4. [FSRS 间隔复习调度 (Review Flow)](#4-fsrs-间隔复习调度)
5. [学情建模与错因分析 (Mastery & Analytics)](#5-学情建模与错因分析)
6. [自适应选题与学习计划 (Adaptive Practice & Plans)](#6-自适应选题与学习计划)
7. [全真模考与 CAT 自适应测验 (Exam & CAT Mode)](#7-全真模考与-cat-自适应测验)
8. [学习框架与技能拓扑 (Learning Framework & Skills)](#8-学习框架与技能拓扑)
9. [申论工作台与双引擎批改 (Shenlun Domain)](#9-申论工作台与双引擎批改)
10. [题库导入与发布门禁 (Question Importer Pipeline)](#10-题库导入与发布门禁)

---

## 1. 系统监控与仪表盘

### `GET /api/health`
- **职责**：系统健康检查与题库体量探针。
- **响应载荷**：
  ```json
  {
    "status": "ok",
    "questions": 6547
  }
  ```

### `GET /api/dashboard`
- **职责**：学习仪表盘全局综合指标汇聚。
- **响应载荷**：
  ```json
  {
    "metrics": {
      "attempt_count": 199,
      "accuracy": 0.724,
      "timed_accuracy": 0.68,
      "average_elapsed_ms": 48200,
      "mastery": 0.765,
      "high_confidence_errors": 12,
      "hint_dependency": 0.08
    },
    "weakest": {
      "id": "skill-growth",
      "name": "两期比重比较",
      "mastery_score": 0.38
    },
    "recommendation": "建议优先复习判断推理模块中的定义判断弱项"
  }
  ```

### `GET /api/daily-goal`
- **职责**：每日 500 题冲刺进度与分项完成度。

### `POST /api/projections/rebuild`
- **职责**：事务中重建 `error_overlay`、`learning_stages`，返回 `{"status":"ok","rebuilt":["error_overlay","learning_stages"]}`。不会重建 Mastery / FSRS，独立入口见 [SOP](DATABASE_BACKUP_AND_RESTORE_SOP.md)。

---

## 2. 单选题训练流

### `POST /api/quiz/session`
- **职责**：创建新的单选题刷题会话。
- **请求体**：
  ```json
  {
    "size": 50
  }
  ```
- **响应载荷**：
  ```json
  {
    "id": "sess-39f201b1-..."
  }
  ```

### `GET /api/quiz/{sid}`
- **职责**：获取会话状态、当前待作答题目或最近一次提交的结果。

### `GET /api/quiz/{sid}/next`
- **职责**：推进取下一题。服务端实时打上计时时间戳 `started_at`，并在未提交时屏蔽标准答案与解析。
- **响应载荷**：
  ```json
  {
    "done": false,
    "attempt_id": "att-47120a...",
    "mode": "PRACTICE",
    "started_at": "2026-09-25T10:00:00.000Z",
    "server_now": "2026-09-25T10:00:00.200Z",
    "question": {
      "id": "q-10023",
      "module": "资料分析",
      "stem": "2023年该省轻工业增加值同比增长约______",
      "stem_assets": [],
      "options": {
        "A": "8.4%",
        "B": "10.2%",
        "C": "12.6%",
        "D": "15.1%"
      },
      "estimated_seconds": 60,
      "source": "2024年国考行政职业能力测验"
    }
  }
  ```

### `POST /api/quiz/{sid}/answer`
- **职责**：提交题目作答。服务端进行确定性判分，扣除有效暂停时间，不可变写入 `attempts`。
- **请求体**：
  ```json
  {
    "attempt_id": "att-47120a...",
    "selected_answer": "B",
    "confidence": 0.8,
    "changed_answer": false,
    "paused_ms": 0
  }
  ```
- **响应载荷**：
  ```json
  {
    "id": "att-47120a...",
    "question_id": "q-10023",
    "correct": false,
    "selected_answer": "B",
    "answer": "C",
    "confidence": 0.8,
    "elapsed_ms": 52300,
    "explanation": "【解析】根据已知条件，先求基期量...",
    "ai_explanation": null
  }
  ```

### `POST /api/quiz/{sid}/hint`
- **职责**：请求四级阶梯启发提示（`1~4`）。提交后自动禁用。
- **请求体**：
  ```json
  {
    "attempt_id": "att-47120a...",
    "requested_level": 1
  }
  ```

---

## 3. 错因归因与 AI 助教答疑追问

### `POST /api/attempts/{attempt_id}/error`
- **职责**：考生人工记录或修改错因。
- **请求体**：
  ```json
  {
    "error_type": "reading_error",
    "explanation": "看漏了题干中的“不包括”限定词"
  }
  ```

### `GET,POST /api/attempts/{attempt_id}/diagnose`
- **职责**：触发独立评估器（Assessor），由 AI 给出客观错因诊断与置信度。
- **响应载荷**：
  ```json
  {
    "error_type": "reading_error",
    "error_label": "审题偏差",
    "confidence": 0.88,
    "cause": "审题时混淆了现期与基期的比较要求",
    "recommended_intervention": "做题时用笔圈出时间限定副词",
    "citation": "《资料分析高分必刷》第32页"
  }
  ```

### `GET,POST /api/attempts/{attempt_id}/explain`
- **职责**：调用 AI Tutor 生成结构化深度复盘。
- **响应载荷**：包含 `core_concept`（核心考点）、`step_by_step`（分步推导）、`common_pitfalls`（易错陷阱）与 `recommended_action`（下一步动作）。

### `POST /api/attempts/{attempt_id}/followup`（核心追问接口）
- **职责**：针对当前试题、做错选项或已生成的错因诊断，向专职 AI 助教发起深度追问。
- **请求体**：
  ```json
  {
    "question": "为什么不能选B？我在第二步算出来是负数",
    "diagnosis": {
      "error_type": "reading_error",
      "error_label": "审题偏差",
      "cause": "审题时混淆了现期与基期",
      "recommended_intervention": "注意题干时间限定词"
    }
  }
  ```
- **响应载荷**：
  ```json
  {
    "id": "msg-8f12a34...",
    "user_message_id": "msg-12b45c...",
    "attempt_id": "att-47120a...",
    "role": "assistant",
    "content": "【AI 助教解答】：针对你的疑问...\n1. **第二步列式分析**：...\n2. **为什么B选项是陷阱**：...",
    "created_at": "2026-09-25T10:05:32.120Z"
  }
  ```

### `GET /api/attempts/{attempt_id}/followups`
- **职责**：获取指定作答记录的所有历史追问对话流（有序列表）。

---

## 4. FSRS 间隔复习调度

### `GET /api/review/status`
- **职责**：检查当前是否有到期复习卡片，返回 `due_count` 与活跃复习会话信息。

### `GET /api/review/due`
- **职责**：拉取已到期卡片清单（支持 `limit` 分页参数）。

### `POST /api/review/session`
- **职责**：创建基于到期题目的复习会话。

---

## 5. 学情建模与错因分析

### `GET /api/mastery`
- **职责**：获取全量 84 个考点节点的 Beta-Bernoulli 掌握度评分、正负证据数与刷题进度。

### `GET /api/analytics/errors`
- **职责**：获取 10 维错因分布直方图、未归因错题计数与错因事件流。

### `GET /api/analytics/calibration`
- **职责**：五档置信度真实准确率校准曲线与 Brier 分数分析。

---

## 6. 自适应选题与学习计划

### `POST /api/practice/adaptive/session`
- **职责**：开启自适应训练会话（根据学情薄弱点、复发错题动态调整出题概率）。
- **请求体**：`{"limit": 10}`

### `GET /api/practice/adaptive/{sid}/audit`
- **职责**：查看自适应选题的算法打分决策轨迹。

---

## 7. 全真模考与 CAT 自适应测验

### `POST /api/exam/start`
- **职责**：开启限时闭卷模拟考试（全真计时，硬锁定 AI 提示与答案检索）。
- **请求体**：
  ```json
  {
    "time_limit_seconds": 7200,
    "question_count": 100
  }
  ```

### `POST /api/exam/{sid}/submit`
- **职责**：模考交卷，结算成绩单（`earned_score`, `accuracy`, `correct_count`），同时解除 AI 锁定以支持试卷复盘。

---

## 8. 学习框架与技能拓扑

- `GET /api/learning-framework`：获取学习框架版本与技能总览。
- `GET /api/learning-skills/tree`：以树状形式返回 17 个固化 `LearningSkill`。
- `GET /api/learning-skills/{id_or_code}`：查询单个技能的详细信息。
- `GET /api/learning-skills/{id_or_code}/errors`：查询针对该特定技能犯错的历史错题清单。
- `GET /api/knowledge-nodes/{node_id}/questions`：按考点节点拉取题目（支持已掌握、曾做错过滤）。

---

## 9. 申论工作台与双引擎批改

- `POST /api/shenlun/session`：创建/恢复申论作答；可选 material_id，daily=true 按每日任务续写或新建，默认 false 保留旧恢复行为。每日目标 API 的 shenlun 字段返回每日1道的独立完成进度，见 [每日申论](SHENLUN_DAILY_TASK_20261004.md)。
- `POST /api/shenlun/draft`：实时暂存考生写作草稿。
- `POST /api/shenlun/submit`：提交申论作答。
  - 先保存作答与版本（answer_hash），再按教师执行本地疑点检测并提交诊断；
  - apply_semantic_review 结合材料、规则与证据执行模型语义复核，经程序核验后为 reviewed；不可用或不合规为 unavailable，疑点仍待确认（旧记录可为 legacy）；
  - 五维参考评分独立执行，同一会话和 answer_hash 复用已有评分；失败通过 assessment_error 表达，不丢失答案和教师反馈。本地疑点命中不能直接当作确认错误。
- `GET /api/shenlun/teacher/{session_id}`：获取当前教师诊断（含语义复核状态）；多教师及追问见补充接口。
- `GET /api/shenlun/mastery`：申论五维能力雷达图数据。

---

## 10. 题库导入与发布门禁

- `POST /api/importer/upload`：上传试卷 PDF 或图片。
- `POST /api/importer/jobs`：创建试卷解析作业。
- `GET /api/importer/jobs`：列出导入作业进度。
- `POST /api/importer/jobs/{job_id}/process`：后台异步运行抽取、匹配答案与考点候选分类。
- `GET /api/importer/jobs/{job_id}/review`：拉取需要人工介入核验的异常试题草稿队列。
- `POST /api/importer/drafts/{draft_id}/review`：人工核验通过或修订试题草稿。
- `POST /api/importer/jobs/{job_id}/publish`：通过严格门禁后，一键正式发布入库。


## 11. 新增能力与错误边界

| 接口 | 关键输入/输出 |
|---|---|
| `GET /api/teaching/goals` | goals 提供技能和 ready 状态 |
| `POST /api/teaching/sessions` | skill_id、goal 必填，review_attempt_id 可选；返回会话视图 |
| `GET /api/teaching/sessions/{sid}` | 恢复会话视图 |
| `POST /api/teaching/sessions/{sid}/actions` | action=advance/answer/hint、revision、request_id 必填；answer、confidence、hint_level 依动作使用 |
| `POST /api/teaching/prerequisites` | prerequisite_skill_id、target_skill_id、basis 必填；成环返回 409 |
| `GET /api/teaching/review/{attempt_id}` | 返回错误复习可用教学目标 |
| `GET /api/notes` / `GET /api/notes/{note_id}` | 列表或笔记详情 |
| `POST /api/notes` | 创建/编辑；已有笔记 note_id、expected_version 用于并发控制，内容/关联字段见 Schema |
| `DELETE /api/notes/{note_id}` | 删除笔记，返回 status、id |
| `POST /api/attempts/{attempt_id}/clip-message` | 收藏消息；message_content、message_role 等见 Schema |
| `GET/POST /api/attempts/{attempt_id}/guided-review` | 获取/推进引导复盘；POST action、request_id 必填，可带 message、answer，动作枚举和长度见 Schema |
| `POST /api/attempts/{attempt_id}/review-cause` | 保存用户归因与说明 |
| `GET /api/shenlun/{session_id}/teacher/{teacher_id}/followups` | 指定教师追问记录 |
| `POST /api/shenlun/{session_id}/teacher/{teacher_id}/followup` | question 必填，可带 user_attribution、intent；关联答案版本 |

请求校验通常为 422，目标不存在通常为 404；EXAM AI hard lock 为 403；教学修订冲突、题池耗尽、前置成环等为 409。具体 detail 与适用入口以实现为准，不承诺所有写接口同样幂等。OpenAPI 部分成功响应为通用 object，业务错误未全部显式声明，不能代替业务错误说明。

当前导出保留 GET/POST 共用 diagnose、explain 处理器的两个重复 operationId 警告；方法/路径清单仍完整。生成 SDK 前须处理 operationId 唯一性，本轮未改变运行接口。
