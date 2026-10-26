# Gongkao Learning OS · 公考学习系统

本地优先的公考学习系统：做题、查看原解析、AI 复盘、记录感悟，再根据学习记录安排训练和复习。


## 对灵枢 / DSH 生态的接入点

本系统对外的主接入面是一个**标准 MCP stdio 服务**，与 DSH/灵枢解耦——任何支持 MCP 的客户端都能直连，无需安装插件。

```
公考系统（gongkao.db，物理只读）
   └─ 公考 MCP 服务（9 个 gk_* 只读工具）
        ├─ 任意 MCP 客户端直连（ZCode / Claude Desktop / Cursor / …）
        ├─ DSH 插件壳（可选，dsh-plugin/，自动挂载）
        └─ 灵枢脑同步（可选，单向 dsh-memory）
```

- **MCP 工具**：`gk_overview / gk_mastery / gk_due_reviews / gk_wrong_book /
  gk_knowledge_tree / gk_node_detail / gk_recent_attempts / gk_notes / gk_ask_teacher`
  （掌握度、FSRS 到期复习、错题本与十维错因、知识树、个人笔记、名师方法检索）
- **启动**：`python scripts/gongkao_mcp_server.py`（自带 sys.path，无需 PYTHONPATH）
- **协议**：版本协商（2024-11-05 / 2025-03-26 / 2025-06-18 / 2025-11-25）、
  初始化门禁、标准错误分级；已通过官方 python-sdk 1.6.0 与 Node SDK 真实客户端握手验证
- **可选**：`dsh-plugin/` 一键挂进 DSH profile；`scripts/sync_lingshu_memory.py`
  把知识树/掌握度/作答摘要单向写入 [dsh-memory](https://github.com/FuRongJun-1999/dsh-memory)
  白盒认知图（CCG 六要素门禁），并支持把脑端 agent 原生记忆反向回流为学习笔记

详见 [docs/mcp-server.md](docs/mcp-server.md)、[docs/lingshu-integration.md](docs/lingshu-integration.md)。

## 数据边界

仓库只含源码与题库结构；`data/gongkao.db` 中 35 张个人数据表（作答、笔记、掌握度、
复习卡、学习任务、教学对话等）在发布前已全部清空。教师语料（`teachers/`）与题图资产
（`data/assets/`）不随仓库发布。

## 当前版本

2026-10-04 对齐文档审计 12 项发现，见 [修订记录](docs/DOCUMENT_AUDIT_REPAIR_20261004.md)、[验证索引](docs/VERIFICATION_INDEX.md)。旧升级包不可直接用于当前版本，见 [迁移兼容](docs/MIGRATION_COMPATIBILITY.md)。

2026-10-03 增量加入 [Adaptive Teaching 学习闭环](docs/ADAPTIVE_TEACHING_20261003.md)，入口 `/teaching`；复用原有技能、作答、掌握度与复习调度。正式库迁移 **30**，Docker 与 Knowledge Hub 已恢复；完整后端及浏览器回归结果见实施记录。以下 10-01 发布信息保留用于追溯。

2026-10-01 已在本机上线，正式数据库迁移到 **28**。上线源码已保存到 GitHub 的 [v2026.10.01](https://github.com/zhtty67-rgb/gong/tree/v2026.10.01) 标签（`bdddae8`）；后续文档整理见 [release/2026-10-01 分支](https://github.com/zhtty67-rgb/gong/tree/release/2026-10-01)。

GitHub 保存源码；数据库、个人作答和笔记、教材资产及密钥保存在本地。只下载仓库不能恢复完整个人学习环境。实际核验范围见 [当前状态](CURRENT_STATE.md)。

## 日常使用

当前入口为 [学习首页](http://127.0.0.1:3000)，每日申论3道小题；[申论工作台](http://127.0.0.1:3000/shenlun)已启用题本排版。运行与验证见 [每日申论记录](docs/SHENLUN_DAILY_TASK_20261004.md)。

| 入口 | 用途 |
|---|---|
| `/quiz` | 行测训练，提交后看答案、原解析和复盘 |
| `/review` | 到期复习 |
| `/teaching` | 探测知识边界、逐节点教学、补前置并回到原目标 |
| `/dashboard` | 学习统计与错题记录 |
| `/framework` | 知识地图与关联学习记录 |
| `/shenlun` | 阅读材料、作答、保存梳理笔记、查看教师反馈 |
| `/notes` | 搜索、整理个人笔记和收藏的复盘内容 |
| `/exam` | 模考；答题期间禁止 AI 辅助 |

原解析、AI 分析与个人笔记分别保存。AI 可以提出建议，用户可以确认或纠正；AI 不覆盖教材原解析或原始作答事实。详见 [系统分工与学习流程](docs/PROJECT_GUIDE.md)。

## 启动（Windows PowerShell）

本机已有依赖和配置时，在项目根目录的两个终端分别运行：

```powershell
# 后端
.\scripts\start-backend.ps1
```

```powershell
# 前端：构建后启动生产模式
.\scripts\start-frontend.ps1
```

两个脚本不负责启动 Knowledge Hub。知识库需单独启动其依赖与 API，详见 [日常维护](docs/OPERATIONS.md)。本机桌面启动器如仍存在，也可用于启动整套服务；它是本机配套文件，不包含在本仓库中。

脚本默认允许局域网访问；只需本机访问时使用维护说明中的本机启动命令。重启电脑后需重新启动服务。

首次安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements.lock.txt
npm.cmd --prefix frontend ci
```

配置、教材资产和数据库需另行准备。后端启动会自动应用缺失迁移；升级现有学习环境前先做一致性备份。

## 文档入口

- [文档导航](docs/README.md)：按使用、维护、开发和历史记录查找说明。
- [当前状态](CURRENT_STATE.md)：已上线内容、实际核验范围与限制。
- [架构边界](ARCHITECTURE.md)：学习系统与 Knowledge Hub 的职责。
- [发布记录](release/20261001/RELEASE_NOTES.md)与[发布/回滚手册](release/20261001/RELEASE_AND_ROLLBACK_GUIDE.md)。
- [路线图](ROADMAP.md)：当前优先事项与历史阶段规划。

## 开发与验证

Python 命令从项目根目录运行。测试应使用隔离数据库，不能把正式库设置为测试数据库。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
npm.cmd --prefix frontend run typecheck
npm.cmd --prefix frontend run build
# 首次浏览器测试需在 frontend 目录安装 Playwright Chromium
npm.cmd --prefix frontend run test:e2e
```

接口以运行服务的 [后端接口文档](http://127.0.0.1:8000/docs) 为准；表结构以 `backend/migrations/` 为准。历史报告中的通过数量只证明对应版本的验收，不能当作最新版本的测试结果。

协作开发前阅读 [AGENTS.md](AGENTS.md)；修改前端还需阅读 [frontend/AGENTS.md](frontend/AGENTS.md)。提交时仅包含本任务文件，保留其他会话的改动。
