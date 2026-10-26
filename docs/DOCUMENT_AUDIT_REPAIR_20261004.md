# 公考项目文档审计修复记录

日期：2026-10-04（北京时间）。项目：D:/gong/gongkao-learning-os。依据另一个“公考项目审计”会话的 12 项发现。起点源码 HEAD：88aa73bd28bb27e8b02626e4c4e7990413efa8fe；工作区原有题库导入脚本与其他未提交文件已保留。本轮更新文档和辅助验证脚本，未改动学习核心、正式数据库、服务进程或旧 zip 原件。

## 逐项处理

| 发现 | 修复结果 | 对应文件 |
|---|---|---|
| F01 两套030冲突 | 明确当前教学基线与旧学习循环包结构不同；禁止直接安装和绕过哈希保护，后续整合需新迁移及双路径副本验证 | docs/MIGRATION_COMPATIBILITY.md；旧包根目录、delivery、implementation 的 CURRENT_REPOSITORY_INCOMPATIBLE.md |
| F02 重建承诺错误 | API和SOP限定 error_overlay / learning_stages；给出独立 Mastery / FSRS 的事务重建入口并验证 | docs/API_REFERENCE.md、docs/DATABASE_BACKUP_AND_RESTORE_SOP.md |
| F03 备份恢复缺口 | 绝对路径、已存在只读源、业务表/迁移/非空题库检查、禁止覆盖；先保存现场文件组，校验同盘临时逻辑快照后替换 | scripts/database_snapshot.py、scripts/verify_backup_recovery_sop.py、SOP；历史发布手册标注新操作入口 |
| F04 当前与历史混杂 | 顶部唯一最新依据表；10-01改称历史快照；README/运维区分3003记录入口与3000默认启动，并给出恢复步骤 | CURRENT_STATE.md、README.md、docs/OPERATIONS.md |
| F05 API不完整 | 改为摘要，补教学、笔记、引导复盘、多教师追问及错误边界；上传明确multipart；生成全部98个方法/路径与Schema | docs/API_REFERENCE.md、docs/generated/API_ROUTES.md、openapi.json |
| F06 数据字典过时 | 从当前001～030及现有兼容补列生成完整DDL/字段/索引/触发器；39业务表+1迁移表、0视图，不冒充正式库统计 | docs/DATABASE_DICTIONARY.md、docs/generated/DATABASE_SCHEMA.md |
| F07 事实/重放表述过强 | 区分原作答、校准、可维护题库/映射、版本状态与投影；列明算法、题库、映射、元数据、模型证据、排除与FSRS策略依赖 | ARCHITECTURE.md、数据库字典 |
| F08 权重/错因不一致 | 从代码生成1/0.65/0.45/0.25/0；10规范编码与5兼容码分列，保留历史值 | docs/generated/CONSTANTS.md |
| F09 申论说明过时 | 对齐先保存答案→本地疑点→模型语义复核→独立五维评分；注明版本、pending/reviewed/unavailable、失败保留与追问 | docs/API_REFERENCE.md |
| F10 SPEC旧开工要求 | 旧聊天全文归档并明确不作当前指令；当前SPEC提炼有效原则、约束优先关系与阶段对应 | SPEC.md、docs/history/SPEC_V01_SOURCE.md |
| F11 决策编号重复 | 多教师引擎改为DEC-0015；DEC-0013继续指追问，保留主题限定的旧别名；已扫描现有引用 | DECISIONS.md |
| F12 导航与验证无统一索引 | 新增按日期/源码/环境/范围/证据组织的索引，区分485、480、496、36等历史结果和跳过原因 | docs/README.md、docs/VERIFICATION_INDEX.md |

## 本轮实际验证

- 从当前源码注册路由导出 OpenAPI，不进入 lifespan、不启动服务、不调用模型。共98个HTTP方法/路径组合；请求上传类型、字段与约束可追溯。
- 在临时空库执行当前001～030迁移，得到39业务表+1迁移表，0视图；integrity_check=ok，foreign_key_check无异常。manifest.json保留生成时间、起点commit及逐文件SHA-256；git HEAD不等于所有未提交工作区内容，以指纹核对。
- 隔离恢复演练通过：5道原创题、17技能、1条基线Attempt、17条mastery_state、1张复习卡；备份后另加作答及内容修改，现场保留2条Attempt，恢复回1条且题库/作答/Mastery/卡片与快照逐行一致。
- 独立rebuild_mastery/rebuild_reviews调用通过；HTTP重建接口返回范围准确且Mastery/卡片内容保持一致。
- 错误源路径不创建空库，空数据库拒绝，已存在备份不覆盖；保存现场主文件后校验临时文件并替换通过。此演练不模拟断电/跨进程竞态；连接排空是操作者前提，原子性仅涵盖主文件替换。
- 相关回归：18 passed（test_migration_017、test_migrations_lifecycle、test_historical_migration_cutoff、test_learning_framework），本轮实际执行；日志和JUnit见work/document-audit-20261004/pytest.log及pytest.xml。
- 94个本地文档链接均存在，15个决策编号唯一，生成源码指纹无漂移；上传multipart声明及迁移编号唯一性检查通过，结果保存于work/document-audit-20261004/document-check.json。

## 范围与保留限制

本轮没有重新认证正式库数量、实时服务健康、全量浏览器、全量后端、真实模型效果或整个升级包整合兼容性。历史通过数已按日志及实施记录分列，不替代当前版本全量验收。3003是最新实施记录入口，本轮没有重启3000或切换服务。

OpenAPI导出保留FastAPI既有的两项重复operationId警告（GET/POST共用diagnose、explain处理器）；方法/路径统计完整，生成SDK前须处理唯一性。测试工具还有Starlette/httpx与typing弃用警告，本轮无测试失败。未为了文档对齐扩大重建接口写范围或增加新学习结构。

旧zip与manifest原件未改写，旁置限制说明防止误用；真正整合旧功能属于后续独立开发，本次只修复审计指出的兼容说明缺失。
