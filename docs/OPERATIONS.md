# 日常维护

以下是本机运行与版本保存说明。操作正式升级或回滚时，另读 [发布手册](../release/20261001/RELEASE_AND_ROLLBACK_GUIDE.md)。

## 启动与访问

材料图修复记录的前端入口为 `http://127.0.0.1:3003`，启动脚本默认是 3000；旧 3000 进程需重启加载新增图片，两者连接同一后端。默认本机地址：后端 `http://127.0.0.1:8000`，Knowledge Hub `http://127.0.0.1:8200`。

日常启动可使用项目 `scripts/start-backend.ps1` 与 `scripts/start-frontend.ps1`。前端脚本先构建再启动；服务正在运行时不要在同一个运行目录重复构建，升级时先停前端或使用独立目录。

只供本机访问、依赖已就绪时，分别在两个终端运行：

```powershell
# 项目根目录；启动时会应用尚未执行的迁移
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

```powershell
# frontend 目录；已有匹配源码的生产构建时直接启动
npm.cmd exec -- next start --hostname 127.0.0.1 --port 3003
```

首次生产构建或源码更新后，在前端停止时运行 `npm.cmd --prefix frontend run build`。开发调试使用 `npm.cmd --prefix frontend run dev`，不能把开发服务当成本机已验收的生产版本。

Knowledge Hub 是相邻的独立项目，运行方式见其 README。同机集成使用 8200，避免与学习后端的 8000 冲突。先启动 PostgreSQL、Qdrant、MinIO，再启动 Hub API；新资料入库还需要 Worker。API 检索健康不代表 Worker 正在处理新资料。

## 三项日常检查

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8200/api/v1/health
Invoke-RestMethod http://127.0.0.1:8000/api/knowledge/health
```

学习 API 应返回 `status=ok`；Hub 应报告 `retrieval_ready=true`，数据库和向量索引连接正常；学习系统的知识 provider 应为 `knowledge_hub`。

需要核对实际教材检索时，按需调用 `http://127.0.0.1:8000/api/knowledge/quality`。进程能打开、能返回教材和教材能支持当前回答是三个不同层次。质量探针通过也不表示所有考点均已入库。

## 本地配置

| 配置 | 用途 |
|---|---|
| `GONGKAO_DB_PATH` | 后端数据库路径；未指定时使用项目 `data/gongkao.db` |
| `KNOWLEDGE_PROVIDER` | 正常集成为 `knowledge_hub`；`fixture` 仅用于明确启用的演示 |
| `KNOWLEDGE_HUB_BASE_URL` | Hub 地址，本机通常为 `http://127.0.0.1:8200` |
| `frontend/.env.local` 的 `API_BASE_URL` | 前端同源 API 转发地址；修改后重新构建 |
| 根目录 `model_config.toml` | 本地模型、预算及凭据配置，已被 Git 忽略 |

2026-10-01 发布时本机 STRONG 的 `max_tokens` 为 8192。换环境要单独同步预算和凭据，不能假定 GitHub 已包含配置。未配置真实模型时，代码默认 provider 可能为 `mock`；页面出现 AI 回复不等于真实模型已接通。不要把含密钥的配置或请求日志提交到仓库。

## 保存源码版本和个人数据

源码保存到 GitHub；数据使用 SQLite Backup API 创建一致性快照，见 [备份与恢复 SOP](DATABASE_BACKUP_AND_RESTORE_SOP.md)。还应保存题图、教材资产、本地配置，以及 Hub 的 PostgreSQL 和对象存储数据；Qdrant 是可重建索引。SQLite 备份不包含这些外部文件。

并行开发时先检查 `git status`，只暂存本任务文件，不使用 `git add .`、强制重置或强制推送。提交后推送到明确的分支，发布标签固定指向已保存的版本，不用移动旧标签表示新版本。

2026-10-01 上线标签是 `v2026.10.01`，后续整理在 `release/2026-10-01` 分支。主工作区可能仍有其他会话的改动；本地 `HEAD`、GitHub 默认分支和正在运行的代码不能自动视为同一版本。

## 常见情况

- 页面还是旧内容：按 CURRENT_STATE 核对端口（材料图修复记录为 3003），再刷新；源码更新还需匹配的构建和服务重启。
- 原解析为空：先查题目是否已导入解析，不能用 AI 文本冒充教材解析。
- Hub 离线：先检查 Docker 和 Hub 健康接口；学习系统应显示资料暂不可用。
- 模型批改慢或失败：保留已保存答案，查看明确错误后重试失败环节；不要连续提交制造重复任务。
- 恢复旧备份：会丢失备份后新增数据；先保存现场，并核对代码与数据库版本。


## 恢复默认前端端口 3000

确认无其他前端构建正在进行，关闭占用 3000 的旧前端，在独立终端从根目录运行 scripts/start-frontend.ps1（重新构建并启动默认 3000）。验证 /quiz 和材料图片后更新 CURRENT_STATE 当前入口，再关闭临时 3003。只停止已核实的本项目前端进程。本轮仅修订步骤，没有执行服务切换。
