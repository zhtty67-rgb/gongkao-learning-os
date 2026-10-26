# 数据库一致性备份与恢复 SOP

修订：2026-10-04。实现为 `scripts/database_snapshot.py`；演练为 `scripts/verify_backup_recovery_sop.py`。备份不包含题图、教材、配置及 Knowledge Hub 数据。

## 在线逻辑备份

核对实际 GONGKAO_DB_PATH，未配置时为下例路径。所有参数必须是绝对路径，目标文件名每次唯一。从仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe scripts/database_snapshot.py backup --source 'D:\gong\gongkao-learning-os\data\gongkao.db' --destination 'D:\gong\gongkao-learning-os\data\backups\gongkao_20261004_010000.db'
```

脚本检查源文件存在，用 mode=ro 打开，以 SQLite Backup API 创建事务一致快照，拒绝覆盖已有备份。验证 integrity_check、foreign_key_check、迁移记录、必要业务表和非空题库/技能；输出表计数供核对基线。空库即使完整性为 ok 也会被拒绝。在线备份计数以快照为准，不要求与持续变化的源库逐时一致。

随快照保存时间、源码 commit、工作区差异、迁移 SHA-256、表计数及快照哈希。版本 30 须确认 030_adaptive_teaching.sql 的结构，见 [兼容说明](MIGRATION_COMPATIBILITY.md)，数字本身不能证明兼容。

## 离线恢复

1. 停止 API、导入、测试与所有数据库连接。--connections-stopped 由操作者确认，脚本不能可靠探测其他进程；未停不得执行。
2. 核对备份、待运行源码、迁移内容及配置匹配。目标主文件须存在；丢失主文件或损坏备份需要单独处理。
3. 执行下方命令。脚本不打开旧目标、不做 checkpoint，先归档主库及存在的 -wal、-shm 整组到新建 incident 目录。物理现场用于诊断，不把主文件单独当逻辑备份。Windows 关闭连接时 SQLite 可能自行 checkpoint；归档保存的是归档时文件组，不要为此额外打开原库。
4. 用 Backup API 创建目标文件系统内的唯一临时文件，校验并刷盘；归档后移除旧旁文件，以 os.replace 替换主文件，再校验目标。主文件替换是原子的，旁文件处理与替换不是一项原子事务，必须全程保持连接关闭；中断后保持停机，利用现场副本重新处理。

```powershell
.\.venv\Scripts\python.exe scripts/database_snapshot.py check --source 'D:\gong\gongkao-learning-os\data\backups\gongkao_20261004_010000.db'
# 所有连接已停止；incident 目录必须尚不存在
.\.venv\Scripts\python.exe scripts/database_snapshot.py restore --source 'D:\gong\gongkao-learning-os\data\backups\gongkao_20261004_010000.db' --target 'D:\gong\gongkao-learning-os\data\gongkao.db' --incident 'D:\gong\gongkao-learning-os\data\backups\incident_20261004_020000' --connections-stopped
```

无需先 checkpoint 现场。诊断 WAL 或尝试 checkpoint 应在保存后的另一份工作副本上做，保留原物理镜像。

## 版本、差量与派生状态

旧快照会使备份后新增作答、笔记、曝光离开主库。保存现场后在副本比较 Attempt ID、笔记版本与计数，记录无法读取或定量的部分；不自动合并或伪造作答。升级先在副本验证当前迁移；回滚需匹配已验证的代码和配置。

不要启动新版 API 来检查旧快照：lifespan 会自动迁移并重建 Mastery / FSRS。启动前只读检查，启动后复核迁移水位、17 技能、学习事实和健康接口。

POST /api/projections/rebuild 只重建 error_overlay、learning_stages，返回 `{"status":"ok","rebuilt":["error_overlay","learning_stages"]}`，不重建 mastery_state 或 review_cards。独立入口为 rebuild_mastery(db)、rebuild_reviews(db)。下面仅在隔离副本执行：

```powershell
@'
from backend.app.db import connect
from backend.app.domain.mastery import rebuild_mastery
from backend.app.domain.review import rebuild_reviews
from backend.app.domain.learning_framework import rebuild_error_overlay, rebuild_learning_stage
with connect(r'D:\gong\gongkao-learning-os\work\recovery-copy.db') as db:
    db.execute('BEGIN IMMEDIATE')
    rebuild_mastery(db)
    rebuild_reviews(db)
    rebuild_error_overlay(db)
    rebuild_learning_stage(db)
'@ | .\.venv\Scripts\python.exe -
```

按同一事务先更新 Mastery / FSRS，再更新依赖投影。本轮在临时库验证独立入口和接口返回范围；正式库未执行重建。跨版本重放需要 [架构](../ARCHITECTURE.md) 所列输入。

## 隔离演练

```powershell
.\.venv\Scripts\python.exe scripts/verify_backup_recovery_sop.py
```

演练使用系统临时目录、当前 001～030 迁移和原创学习记录，验证错误路径、空库、备份保护、归档、替换和恢复表内容。结果见 [修订记录](DOCUMENT_AUDIT_REPAIR_20261004.md)。历史发布的配套版本要求见 [发布手册](../release/20261001/RELEASE_AND_ROLLBACK_GUIDE.md)。
