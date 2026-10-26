# 教师统计修复与调用验证

核验日期：2026-10-04（Asia/Shanghai）。项目：`D:/gong/gongkao-learning-os`。

## 修复结果

- 行测教师列表与画像接口统一读取当前知识库，按加载门槛计算数量，分别返回 total、active、quarantined、unverified。
- 文件缺失、JSON 格式错误返回统计 errors 与未知数量（null），避免把读取失败显示成有效资产为零。
- 画像的 active_policies_count、active_cases_count 在加载时按当前库覆盖，避免旧画像把隔离记录计为有效资产；飞扬、站长也采用当前库统计。
- 逻辑配置的 question_cases_count 从 0 修正为 157。
- 历史 library_report、fidelity_audit、holdout_evaluation 保留原样，并在 API 明确标注其为历史快照，不作当前数量依据。
- 未恢复隔离记录，未改数据库结构，未在正式库添加测试学习记录。

有效资产统计：

| 模型 | 规则 | 题目案例 | 纠错案例 |
|---|---:|---:|---:|
| teacher_logic | 24 | 157 | 0 |
| teacher_definition | 5 | 39 | 0 |
| teacher_quant | 28 | 73 | 0 |
| teacher_data | 30 | 43 | 0 |
| teacher_longfei | 418 | 574 | 0 |
| teacher_feiyang | 123 | 62 | 68 |
| teacher_zhanzhang | 83 | 42 | 44 |

龙飞题目案例为来源核验的课堂口述片段；数量不代表全部图形信息完整或每个片段均参与当前题检索。当前五个行测模型的纠错资产不用于学生错误诊断。

## 验证结果

运行以下 7 个测试文件：test_teacher_asset_statistics.py、test_module_teachers_api.py、test_module_teachers_safety.py、test_module_teachers_review_and_followup.py、test_shenlun_teacher.py、test_shenlun_teacher_followup.py、test_shenlun_teacher_ai_review.py。

结果：55 passed；仅有 FastAPI/Starlette 现有弃用警告。验证包含陈旧配置、隔离/未核验过滤、损坏文件、知识库更新后统计刷新，以及七个教师资产和教师链路。相关修改的 git diff --check 通过。

真实模型网关探针共完成 11 次 generate 调用：

- 行测六个讲题探针通过 6/6：逻辑逆否、定义判断、数量工程与选项换位、资料增长量与负增长比重。
- 龙飞完整文字图形描述的一笔画题通过，选 A；没有据此验证图片理解能力。
- 飞扬、站长在临时数据库中均完成本地诊断、真实语义批改（reviewed）及带教师引用的追问。
- 临时验证库 foreign_key_check 为零异常。所有实际调用使用非 mock 模型网关。
- 调用期间发生主模型结构校验失败后的回退，以及输出截断后的加长重试；最终探针通过，不代表首次调用全部成功。

这些是针对性链路探针，不是全量准确率评测，不改变现有 PARTIAL 覆盖状态。

## 在线生效状态

8000、8001 在验证时仍返回旧接口结构（没有新的 asset_statistics），需要重启加载源码。

用户明确授权启动临时后端并逐个重启后，启动临时 8002 服务的命令仍被自动执行策略拒绝（blocked by policy；无具体原因）。没有启动临时服务，也没有停止现有服务。因此，本次源码修复和验证已完成，在线生效尚未完成。

运行环境允许启动服务后，应先验证临时端口的健康、五个教师列表/画像统计；随后保持原有环境变量和数据库路径，依次重启 8000、8001。逐个检查 /api/health 与 /api/module-teachers，确认统计及画像一致。不要仅凭进程启动就认定在线修复生效。

## 变更与证据

项目变更：

- backend/app/domain/teacher_asset_stats.py（新增）
- backend/app/domain/module_teacher_service.py
- backend/app/domain/shenlun_teacher/engine/library.py
- backend/app/config/module_teachers.json
- tests/test_teacher_asset_statistics.py（新增）

任务证据目录：`C:/Users/<用户>/Documents/Codex/2026-10-04/chatgpt-work-learning-os-work-work/teacher-repair-stage`。

- real_teacher_verification.json：真实调用输出、引用与探针结果。
- real-teacher-verification.db：隔离的申论验证库。
- original_module_teacher_service.py、original_shenlun_library.py、original_module_teachers.json：修复前原件。
- verify_real_teachers.py：验证脚本，仅在任务目录生成临时库与报告。

本次未提交 Git，未覆盖项目中其他已有改动。

## 2026-10-05 在线恢复补充

用户报告“继续追问”无响应。核实到运行中的 8000 后端仍使用旧版 GuidedReviewInput，action 枚举缺少 followup，而当前前端已提交此操作；最新源码本身已支持 followup。

先在临时 8002 后端验证新版接口、同一道题的教学状态及健康检查，再重启正式 8000 后端。通过 3003 前端代理核验：该题 stage=complete，available_actions 包含 followup；逻辑案例数为157，健康接口返回正常。临时8002已停止；8001在本次开始时未运行，未额外启动。

验证：test_guided_teacher_review.py 与 test_teacher_asset_statistics.py 共10项通过；Playwright unified-review.spec.ts 浏览器测试1项通过，覆盖点击继续追问、收到回复和刷新恢复。浏览器测试使用隔离数据库，未写入正式学习记录。

此前“在线生效尚未完成”的状态现已更新：当前8000已加载教师统计修复和追问支持。此问题无需修改按钮或再次生成教师语料。
