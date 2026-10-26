# 公考 MCP 服务（核心接入面）

公考学习系统对外的主接入面是一个**标准 MCP stdio 服务**（Model Context
Protocol），与 DSH/灵枢解耦——任何支持 MCP 的客户端都能直连，无需 DSH 插件。

```
公考系统（gongkao.db，物理只读）
   └─ 公考 MCP 服务（backend/app/gongkao_mcp + scripts/gongkao_mcp_server.py）
        ├─ 任意 MCP 客户端直连（ZCode / Claude Desktop / Cursor / Cline / …）
        ├─ DSH 插件（可选，自动挂载壳，见 dsh-plugin/）
        └─ 灵枢脑镜像（可选，单向写出，见 scripts/sync_lingshu_memory.py）
```

## 启动

```powershell
# Windows（仓库自带 venv）
D:\gong\gongkao-learning-os\.venv\Scripts\python.exe D:\gong\gongkao-learning-os\scripts\gongkao_mcp_server.py

# POSIX（venv 在 .venv/bin/python3）
<repo>/.venv/bin/python3 <repo>/scripts/gongkao_mcp_server.py

# 诊断面（不起服务，打印工具清单）
... gongkao_mcp_server.py --show-tools
```

启动器自带 `sys.path` 装配，客户端**无需设置 PYTHONPATH/cwd**。环境变量：

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `GONGKAO_DB_PATH` | `<repo>/data/gongkao.db` | 数据库路径（一律只读打开） |
| `GONGKAO_API_BASE` | `http://127.0.0.1:8000` | 后端地址（仅 `gk_ask_teacher use_llm=true` 用） |
| `PYTHONUTF8` / `PYTHONIOENCODING` | 建议显式 `1` / `utf-8` | Windows 中文安全 |

## 协议兼容性

协议层（`backend/app/gongkao_mcp/protocol.py`）按官方规范实现生命周期：

- **版本协商**：支持 `2024-11-05 / 2025-03-26 / 2025-06-18 / 2025-11-25`；请求版本在
  支持集内则原样回显，否则回最新支持版（由客户端裁决）。四个版本间本服务
  工具面（tools/call + text content）无破坏性差异。
- **初始化门禁**：`initialize` 之前的带 id 请求回 `-32002`（`ping`/`shutdown` 例外）。
- 错误分级 `-32700/-32600/-32602/-32601/-32603`，工具执行错误以 `isError` 结果
  返回（非协议错误）；坏行不杀进程。

**已验证客户端**（真实握手 → 列工具 → 调工具，2026-10-25）：

| 客户端 | 版本 | 结果 |
| --- | --- | --- |
| 官方 python-sdk（`mcp` 包，经 Hub venv 1.6.0） | 1.6.0 | PASS（5 步全过，协商 2024-11-05） |
| 官方 Node SDK（`@modelcontextprotocol/sdk`） | latest | PASS（4 步全过） |
| ZCode 内置 MCP 客户端 | — | 已挂载（`~/.zcode/cli/config.json`，启动器形态）；会话内实测待重启后确认 |

复跑：`<有mcp的python> scripts/compat_mcp_client_check.py`（详见脚本 docstring）。

## 各客户端挂载

通用片段见 [`mcp/gongkao.mcp.json`](../mcp/gongkao.mcp.json)（标准
`mcpServers` 形状，多数客户端直接可用）：

| 客户端 | 配置位置 |
| --- | --- |
| ZCode | `~/.zcode/cli/config.json` → `mcp.servers`（已挂） |
| Claude Desktop | `claude_desktop_config.json` → `mcpServers` |
| Cursor / Cline / 通用 | 项目或全局 `mcp.json` → `mcpServers` |
| DSH/灵枢 | 可选：`dsh-plugin/`（`dsh plugin add file:./dsh-plugin` + bundles 启用） |

## 工具面（9 个，全部只读）

`gk_overview / gk_mastery / gk_due_reviews / gk_wrong_book / gk_knowledge_tree /
gk_node_detail / gk_recent_attempts / gk_notes / gk_ask_teacher`。
唯一有外部成本的是 `gk_ask_teacher use_llm=true`（LLM 讲题），默认零成本本地
教师检索。模块名用库内真实命名（`言语理解/逻辑判断/…/申论`）。

## 测试

- `tests/test_gongkao_mcp_server.py`：版本协商、初始化门禁、坏行韧性、
  工具面、子进程 stdio 端到端。
- `scripts/compat_mcp_client_check.py`：真实官方 SDK 客户端验证（见上表）。
