# 迁移兼容与旧升级包隔离

修订：2026-10-04。当前基线为本仓库 `030_adaptive_teaching.sql`，创建 adaptive_teaching_sessions、adaptive_teaching_events 和前置关系防环触发器。旧 2026-10-02 基线学习循环升级包的 `030_learning_cycle.sql` 是另一套结构：question_families、learning_interventions、learning_verifications、shenlun_evidence_versions 等。

两者都登记 schema_migrations.version=30；migrate 按数字判断已执行，不能通过改文件名执行另一份 030。**旧升级包不可直接应用当前仓库**；安装器哈希漂移拒绝应保留，不绕过、不删除当前 030、不伪造迁移记录。旧目录与 zip 保留为历史交付，相邻 CURRENT_REPOSITORY_INCOMPATIBLE.md 标注本限制；本次不改写包与安装器。

之后整合旧功能，应以当前教学基线审查重叠与数据权限，选择届时未占用的新迁移号（本次未引入迁移），分别在当前 030 与旧 030 的副本设计并验证升级路径，记录表/字段前提、迁移文件名及 SHA-256、源码版本、完整性/外键、17 Skill 和学习事实保持。仅改 SQL 编号不能证明兼容。

当前源码/迁移指纹见 [生成清单](generated/manifest.json)。正式库应只读核对版本与结构，不能用旧交付反推正式环境。
