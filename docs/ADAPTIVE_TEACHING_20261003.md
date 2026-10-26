# Adaptive Teaching 增量实施记录（2026-10-03）

## 使用入口

启动现有后端与前端后打开 `/teaching`，选择正式技能、输入学习目标。首页增加“自适应教学”入口；失败的 REVIEW 结果提供重新检查前置知识的入口。刷新可恢复本浏览器最近一次会话。

目前只开放题池足够的正式行测技能；缺少已核验题的目标明确显示未就绪。自由填写目标描述用于教学背景，目标归属必须由用户选择既有 Skill，不自动创造新技能。申论沿用原有 Learner Model，本次未扩展申论技能体系。

## 审计与复用决定

审计涵盖迁移、题目与 Skill 绑定、Attempt、mastery_state、exposure、Error Attribution、Tutor/Assessor、Hint Ladder、review/FSRS、CAT/MAP、Exam Mode、前端 quiz/review/framework 及既有测试。实际库原有 5268 题、660 知识节点、17 个正式技能，迁移 29；`learning_relations` 已支持 prerequisite，但未录入关系。没有新建知识体系或第二套 mastery。

| 既有能力 | 接入方式 |
|---|---|
| Skill / Knowledge Node | 仅使用 active 正式 Skill，要求已核验题及既有 mastery 映射 |
| prerequisite | 复用 learning_relations，source 是前置，target 是依赖方；递归拓扑追踪 |
| Attempt | 每次检查使用原有 sessions/session_questions/attempts |
| Mastery | 调用 rebuild_mastery；局部 boundary 标记只决定路径，不是掌握度 |
| Error Attribution | 独立 Assessor 判断缺口，调用现有 record_error_event |
| Tutor | 每轮一个概念与一个独立例题；复用知识检索、证据采用与引用校验 |
| Assessor | 只接收独立检查、原始回答、评分标准及候选正式技能，不接收 Tutor 对话 |
| Hint Ladder | 原有四级提示；提示暴露留痕，通过辅助题不能直接放行 |
| CAT / MAP | 复用能力估计与题目信息量选择核验题，优先未见过的题 |
| FSRS / Review Queue | 调用原有 rebuild_reviews；复习失败仍影响原 mastery |
| Exam Mode | 原有 require_ai_allowed；另检查所有活跃 EXAM，异步模型返回后再次检查 |

## 状态流与失败路径

`PROBE → PLAN → TEACH_NODE → CHECK → UPDATE → COMPLETE`

新目标先检查直接前置与目标本身，结合选择题、自由回忆或开放应用回答。直接前置失败时才向更深层前置探查，避免从基础重新教学。目标已通过的节点可跳过。教学只呈现一个节点、一个概念、一个必要例题；检查题与例题分离，未通过时不展开后续节点。

CHECK 的原始回答与实际评分结果、置信度、归因、判定时答案及评分标准存入教学事件。自由回答以 Assessor 结论映射到既有 Attempt 的 canonical 正误字段；原文仍完整保留。选择题正误以核验答案为准。置信度不足时拒绝提交，不污染学习事实。

失败分别处理 current_node、prerequisite_gap、other_skill。只有候选正式技能且可靠的诊断才允许插入节点；未知技能不能 fallback。插入时保存返回栈，补前置通过后返回原节点，使用新的例题与独立检查。提示或答案暴露之后必须完成新的独立检查。

每次有效检查更新既有 mastery、错误覆盖、学习阶段与 FSRS。失败的 REVIEW 可重新开始 PROBE；不强制自动打开 AI 会话。完成时清空当前节点。模型调用在数据库写事务外执行；提交时复核 revision、Exam hard lock 与题目版本，避免长调用造成锁库或过期写入。request_id 幂等，同 revision 竞争返回 409。计时截止于用户提交，模型评估耗时不计入答题时间。

## 数据库与 API

迁移 `030_adaptive_teaching.sql`：

- 新增 adaptive_teaching_sessions：关联原 sessions、goal Skill、phase、revision、路径状态。
- 新增 adaptive_teaching_events：关联 session 与 Attempt，保存原始检查事实；session/request_id 与 session/revision 唯一。
- learning_relations 增加 INSERT/UPDATE prerequisite 防环触发器。
- 只录入一条经审慎确认的关系 `growth → two_period`；其他前置关系需逐条审核后添加。
- 不新增 Skill、题库、mastery 或复习调度表。

正式库迁移前使用 SQLite backup 保存一致备份；迁移后 questions、learning_skills、knowledge_nodes、attempts 的计数和全行 SHA256 完全一致，外键与完整性检查通过。本地备份与日志位于 `work/adaptive-teaching-20261003/`，不提交个人数据。

| API | 用途 |
|---|---|
| GET /api/teaching/goals | 正式技能与可用题数、就绪状态 |
| POST /api/teaching/sessions | skill_id、goal、可选 review_attempt_id |
| GET /api/teaching/sessions/{id} | 恢复阶段、局部节点、现有 mastery 与复习安排 |
| POST /api/teaching/sessions/{id}/actions | advance / answer / hint，必须提供 revision 与 request_id |
| POST /api/teaching/prerequisites | 既有 Skill 的前置关系及 basis，拒绝环 |
| GET /api/teaching/review/{attempt_id} | 失败 REVIEW 对应的合法目标 |

所有新增接口继续受 AI token 中间件及 Exam hard lock 约束。前台不显示完整 DAG，不暴露核验题答案或隐藏 rubric。

## 验收与运行证据

新增后端测试覆盖完整插入返回闭环、mastery/FSRS 与失败复习反向更新、直接前置探测顺序、递归与环、辅助暴露、低置信度、模型失败、幂等与并发、模型调用期间进入模考、token guard、计时与模拟数据隔离。

Playwright 独立临时库完成：growth 的选择题与回忆通过、目标失败、跳过已掌握前置、教 two_period、CHECK 指出基期缺口、插入 growth、补前置通过、返回 two_period、通过、查看现有 mastery 与 Review Queue；包含刷新恢复和移动端检查。受控 fixture Assessor 的评分依据写在测试服务中，仅用于隔离验收，生产没有替换真实 Assessor。mock provider 的评估明确保存为 DEMO/valid_for_stats=0。

真实配置模型另外完成一次增长率自由回忆评估与一次单节点教学，均成功；教材服务不可用时明确显示“无采用的教材证据”，未捏造引用。该小样本只说明调用与格式闭环可运行，不证明教学效果或归因准确率。

测试结果见文末最终核验表。全套浏览器运行入口：`scripts/run_adaptive_browser_acceptance.ps1`，分别执行既有、复盘、地图、题组与教学配置。地图的离线包装只对 synthetic e2e 节点返回未映射，用于复现无教材映射状态；不修改生产知识服务。

以下为首轮实施时的历史结果，收尾后的完整结果见后面的“最终收尾验收”。

| 首轮检查 | 实际结果 |
|---|---|
| 全量 pytest | 458 passed / 16 failed / 6 skipped；480 项全部收集运行，失败集合与修改前对照完全一致 |
| 新增闭环 + 迁移生命周期 + 隔离题组 | 18 passed（包含 14 个教学测试） |
| 原 Playwright 配置 | 10 passed / 10 failed / 1 skipped；修改前副本相同结果 |
| 原复盘专项 | 1 failed：旧“本题复盘”文案选择器 |
| 原地图专项，生产构建 | 10 passed / 2 failed：原页面文案与旧断言不一致；未修改此模块 |
| 题组浏览器 | 1 passed，正式库之外的临时五题 fixture |
| 教学浏览器 | 1 passed，完整补前置返回闭环、刷新与移动端，实际更新原投影和 FSRS |
| TypeScript / production build | 通过，产物包含 /teaching |
| 正式数据库迁移 30 | 全行校验一致，foreign_key_check / integrity_check 通过 |
| 真实模型最小验证 | 2 次调用成功；不代表教学质量评估 |

后端 8000 健康接口与前端 3000 `/teaching` 返回 200。首次检查发现正式库有 4 场 2026-09-24 起保留的 active EXAM，教学按 hard lock 返回 403。用户随后说明从未进行模考，并授权继续处理。审计发现四场均无 Attempt，各挂 4241 题，符合旧测试残留特征。

已先保存 SQLite 一致备份，再仅关闭这四场空会话；sessions 使用现有 completed 状态，exam_records 记录关闭时间，earned_score 保持 NULL，不伪造交卷成绩，不删除试卷。题目、技能、全部作答、mastery_state 和 review_cards 的全行 SHA256 校验前后一致，外键与完整性检查通过。记录与备份位于 `work/adaptive-teaching-20261003/stale-exam-*.json`、`before-stale-exam-closure.db`。

处理后 active EXAM 为 0，教学目标 API 返回 200，17 个正式技能中 15 个题池就绪；真实生产页面的“开始自适应学习”按钮可用，验证未创建模拟学习作答。再运行教学后端测试 14 项全部通过，包含真正活跃模考仍须禁止 AI 的测试。服务进程与本地日志保存在 work 目录。

## 既有问题及边界

- 首轮存在的发布快照、Hub 环境与浏览器回归问题已在最终收尾中修复，详情见下节；历史结果保留用于追溯。
- 首次全量运行发现旧题组测试直接指向正式库，产生 5 条测试作答。已备份原始记录，仅标记这 5 条为 AUTO_TEST/valid_for_stats=0 并重建派生投影，原答案保留；新增 conftest 使此旧测试以后使用临时副本。数据库现共 471 条，其中这 5 条不计学习统计。
- 题池耗尽时返回明确 409，保留状态等待补充已核验题；不循环重复同一题伪造独立掌握证据。
- 目前仅四个技能有专门的自由回忆标准，其余使用题目原解析支持开放应用检查；前置 DAG 只录入一条经审核关系。
- 图像依赖题的自由回答缺少视觉证据时应拒绝低置信度评估；本次没有建设多模态批改系统。
- 已有统计模型是原模型，不因一次学习通过宣称长期掌握；AI 误判可能影响既有投影，仍需人工抽样核验。
- 收尾提交同时保存已存在且当前运行依赖的组卷、教师引导复盘、节点教师、移动端样式、配置和对应测试；原 HEAD 缺少 compose_practice_questions 等依赖的问题已解决。与闭环无关的题库导入/修复脚本仍保留在原工作区，不混入提交。个人数据库、教材、教师资产和密钥仍需单独恢复。

## 最终收尾验收

Docker Desktop 的报错涉及 Windows 无法访问旧 AF_UNIX socket。停止安装目录内的 Docker 进程，将运行目录与仅含 socket 的 secrets-engine 目录改名保留，重新启动；未执行 factory reset，未删除容器卷。Docker Server 29.8.0 正常响应，原 postgres/qdrant/minio 数据卷继续使用，Hub 健康接口返回 retrieval_ready=true。

旧 2026-10-01 发布测试改用一致的发布前归档数据库 `release/20261001/baseline.db`（忽略、不提交），或环境变量 `GONGKAO_RELEASE_20261001_BASELINE_DB`。修复演练明确迁移到 28，避免合法的后续 029 分类修正破坏历史发布口径；原题数、作答数、答案和清单的精确断言保留。生产 migrate 默认仍应用全部迁移，并拒绝历史演练降级已更新的数据库。

补充 5 个回归用例：显式 mock 禁用真实 fallback、三种结构化任务不被旧对话关键词误分派、单节点教学从核验例题取得模块并进行受证据门控的模块重试。另补迁移截止/恢复/拒绝降级用例。旧题组、笔记和复盘测试改为独立数据，保留原断言。新检出 schema 没有旧本机 code/description 辅助列时，笔记使用正式 knowledge_node_code，复盘可从现有 metadata_json 读取定义，不加新知识表。

浏览器回归更新实际交互路径与当前文案，并继续检查真实请求、持久化和统计：普通训练不再提前获取下一题组；发布请求包含 job_id；错因请求尚未完成时失焦的补充说明会等待保存。地图空绑定用例改用从未缓存的节点，避免把缓存命中误当成未请求。

| 最终检查 | 实际结果 |
|---|---|
| 全量后端（本机归档与 Hub 就绪） | 485 passed / 1 skipped / 0 failed；跳过项为 USE_REAL_AI 未开启的专用外部模型审计 |
| 仅暂存源码导出的独立目录 | 480 passed / 6 skipped / 0 failed；5 个历史归档依赖用例无本机 baseline.db，另 1 个外部模型审计未开启；其余断言全部执行 |
| 汇总浏览器验收 | 36 passed：原配置 21、复盘 1、生产地图 12、题组 1、教学 1；五套配置顺序运行 |
| 单节点及隔离回归 | 新回归 5、历史迁移 1、旧笔记/复盘独立数据 22 项分别通过，均纳入完整测试集 |
| 真实检索质量 | 17 项通过，纳入完整测试；在线/离线/超时、错主题与严格引用身份均覆盖 |
| TypeScript / 生产构建 | 通过；正式工作区与仅从暂存源码导出的独立目录分别通过，包含 /teaching |
| 真实模型完整闭环 | deepseek-flash 实际 Tutor / Assessor 成功完成跳过、失败诊断、插入、返回与通过；7 Attempt、7 FSRS 卡片 |
| 正式数据 | 5268 题、17 Skill、471 Attempt、660 mastery_state、430 review_cards；启动前后内容哈希一致，迁移 30、完整性与外键通过 |

真实模型演练使用脚本回答与临时数据库，没有向正式库写模拟学习证据。growth 为 3 次证据、mastery 0.8；two_period 为 4 次证据、mastery 1/3，先前错答继续影响原投影。路径通过不会把长期掌握度设为 100%。真实模型曾出现一次结构输出验证失败，状态未误推进，随后重新验证完整路径成功；不能据此保证模型每次稳定或证明教学效果。此次真实教学示例未采用教材引用，依据题目原解析，未将检索命中冒充已证明的支撑。

证据保存在 `work/adaptive-teaching-20261003/`：pytest-final.xml/log、browser-acceptance-final.log、real-loop-smoke.json、formal-before/after.json、生产页面可开始的截图及各服务日志。工作区外部配置、归档数据库和资产不进入 Git。

独立源码目录没有复制个人数据库或旧 work 审计数据库；测试仍在同一台机器上使用外部 Hub 和按配置找到的教师资产。它证明核心源码与迁移依赖已完整保存，不表示另一台未配置机器可自动恢复个人教材和学习记录。最后兼容复查的笔记浏览器 2 项、复盘浏览器 1 项也通过。

## 推荐下一步

下一步对真实错答样本开展 prerequisite/current_node/other_skill 的独立归因评估，再逐条审核前置关系、扩充自由回忆 rubric 和独立题池。保持 17 Skill 契约，不为覆盖率虚构依赖或教材引用。
