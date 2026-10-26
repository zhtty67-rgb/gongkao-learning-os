# Gongkao Learning OS 数据库字典

修订：2026-10-04。当前 001～030 迁移在隔离新库生成 **39 张业务表 + 1 张迁移表，0 个视图**；不代表正式库本机额外兼容字段/表。完整字段、类型、默认值、主键序号、CHECK、UNIQUE、外键、索引、触发器见 [Schema 字典](generated/DATABASE_SCHEMA.md)，源码版本及 SHA-256 见 [清单](generated/manifest.json)。生成包含 db.py 的现有兼容补列，本次未新增迁移。

## 数据与维护权限

| 类别 | 代表表 | 边界 |
|---|---|---|
| 原始作答 | attempts、attempt_followups | 不覆盖原答案、原判分、时间和信心；校准、可信度排除遵循专用字段与审计流程 |
| 可维护内容和关联 | questions、question_passages、knowledge_nodes、question_knowledge_map、question_skill_bindings | 经核验可修订内容/映射；保存来源、版本及修复前快照，保持 17 Skill |
| 归因与模型证据 | error_events、error_skill_bindings、interactive_diagnoses、shenlun_teacher_diagnoses | 记录来源、规则/模型版本和用户反馈，允许实现规定的版本与状态推进，不称整表永久不可变 |
| 笔记和答案版本 | user_notes、shenlun_sessions、shenlun_teacher_diagnoses、shenlun_assessments | 笔记可维护且有版本控制；申论诊断保存 answer_text，评分及诊断按 answer_hash 关联；没有独立 shenlun_answer_versions 表 |
| 派生统计 | mastery_evidence、mastery_state、review_cards、review_events、error_overlay、learning_stages | 按现有函数重建，不由模型直接改聚合结果 |
| 教学编排 | adaptive_teaching_sessions、adaptive_teaching_events、learning_relations | 030_adaptive_teaching.sql；复用学习核心，前置环由触发器约束 |
| 系统迁移 | schema_migrations | version、applied_at；数字不能区分不同 030 的结构 |

后续迁移覆盖曝光、计时可信度、互动复盘、申论版本、笔记、判分校准与教学；完整字段从生成字典核查，不沿用迁移 13 的旧清单。

## 重放与常量

重放依赖作答及有效判分、题库预计耗时、映射/权重、节点 metadata、归因证据、统计排除规则、Mastery 算法、FSRS 版本/参数及 rating policy。保留同一输入和算法才能复现，不承诺仅提供 attempts 就跨版本复现，见 [架构](../ARCHITECTURE.md)。

提示与错因常量从代码生成，见 [常量表](generated/CONSTANTS.md)：hint_level 0～4 成功证据乘数为 **1 / 0.65 / 0.45 / 0.25 / 0**；10 个规范错因、5 个兼容码分别标注，不删除历史值。confidence 为 0.2、0.4、0.6、0.8、1.0；有效错误且 confidence >= 0.8 为高信心错误。

## 更新与版本核查

从根目录执行 `.venv/Scripts/python.exe scripts/export_document_contracts.py`，仅在临时库迁移、注册源码路由导出，不进入 lifespan、不读取正式库、不调用模型。双 030 见 [兼容说明](MIGRATION_COMPATIBILITY.md)，独立重建与恢复见 [SOP](DATABASE_BACKUP_AND_RESTORE_SOP.md)。
