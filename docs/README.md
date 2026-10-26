# 项目文档导航

第一次了解项目先读 [首页](../README.md)，确认运行版本再读 [当前状态](../CURRENT_STATE.md)。

| 需求 | 文档 |
|---|---|
| 每日申论任务与完成口径 | [每日申论](SHENLUN_DAILY_TASK_20261004.md) |
| 按日期、源码、环境查看验证 | [验证索引](VERIFICATION_INDEX.md) |
| 文档审计问题修复 | [本轮修订记录](DOCUMENT_AUDIT_REPAIR_20261004.md) |
| 材料图修复与入口 3003 | [材料图记录](PASSAGE_IMAGE_REPAIR_20261003.md) |
| 双 030 与旧升级包限制 | [迁移兼容](MIGRATION_COMPATIBILITY.md) |
| 自适应教学、前置插入、迁移 30 与测试边界 | [Adaptive Teaching 实施记录](ADAPTIVE_TEACHING_20261003.md) |
| 理解做题、复盘、笔记与知识库怎样配合 | [系统分工与学习流程](PROJECT_GUIDE.md) |
| 查看数量关系45个新增节点的整理及同步结果 | [数量导图补充整理](QUANT_MAP_CURATION_20261001.md) |
| 启动、配置、检查服务、保存版本 | [日常维护](OPERATIONS.md) |
| 备份与恢复个人数据 | [数据库备份与恢复](DATABASE_BACKUP_AND_RESTORE_SOP.md) |
| 查看 2026-10-01 上线内容与当时核验范围 | [发布记录](../release/20261001/RELEASE_NOTES.md) |
| 正式升级或准备回滚 | [发布与回滚手册](../release/20261001/RELEASE_AND_ROLLBACK_GUIDE.md) |
| 理解两个项目的技术边界 | [架构](../ARCHITECTURE.md) |
| 查接口与数据结构 | [接口摘要](API_REFERENCE.md)、[数据库字典](DATABASE_DICTIONARY.md)；以运行服务 `/docs` 和迁移 SQL 为准 |
| 确认开发约束 | [开发说明](../AGENTS.md)、[前端说明](../frontend/AGENTS.md) |
| 查看下一步优先事项 | [路线图](../ROADMAP.md) |

## 历史记录的使用方式

`CURRENT_STATE.md` 顶部描述最新核实状态，其下保留历史过程。根目录阶段报告、系统审计、知识检索修复报告与 `evals/` 文件均是特定时间、特定版本的记录，用于追溯，不自动代表当前服务状态或模型准确率。

遇到文档冲突，先核对版本、迁移记录和运行接口。历史阶段的勾选与测试数不能代替实际核验。新的说明应写明日期和证据范围。
