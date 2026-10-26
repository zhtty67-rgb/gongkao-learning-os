# gongkao-learning-os-dsh

公考学习系统的 DSH 插件壳：把「公考 MCP 只读网关」（`backend/app/gongkao_mcp`）
以 MCP stdio 客户端形态挂进 DSH/灵枢 profile，并附带使用技能（SKILL.md）。
这只是**可选安装外壳**——任何 MCP 客户端都可不经本插件直连同一服务
（见 `docs/mcp-server.md`）。

## 前置

1. 公考学习系统已检出，且 `.venv` 可用（`python scripts/gongkao_mcp_server.py --show-tools` 能跑通）。
2. 设置环境变量：
   - `GONGKAO_LEARNING_OS_ROOT`：仓库根绝对路径（必需）
   - `GONGKAO_PYTHON` / `GONGKAO_DB_PATH` / `GONGKAO_API_BASE`：可选覆盖
     （POSIX 环境必须设 `GONGKAO_PYTHON`；默认命令按 Windows venv 布局）

## 安装（本机 profile）

```powershell
dsh plugin --profile <name> add file:./dsh-plugin
# 在 profile package.json 的 dsh.profile.bundles 里加入 gongkao-learning-os-dsh
```

## 验证状态（2026-10-25）

- ✅ 已验证：scratch profile `gktest` 安装 + `--dump-config` 组合配置
  （`mcp-gongkao` / `skill-gongkao` 正确入层）；被挂载的 MCP 服务本身已通过
  官方 python-sdk 与 Node SDK 真实客户端验证（见 `docs/mcp-server.md`）；
  学习状态已镜像进真实灵枢脑根（见 `docs/lingshu-integration.md`）。
- ⏳ 未验证：DSH 真实会话内 AI 调用。CLI 侧（headless/codexpp profile）实测被
  `MISSING_CREDENTIAL: llm-deepseek` 挡住——需要先在 web Models 页存
  DEEPSEEK_API_KEY 或 `export DEEPSEEK_API_KEY`。配好后一条命令即可复验：
  ```powershell
  $env:GONGKAO_LEARNING_OS_ROOT = 'D:\gong\gongkao-learning-os'
  dsh --profile headless --patch dsh-plugin\session-check-overlay.yml `
    "调用 gk_overview 并用两句话汇报总作答数/正确率/掌握度/到期复习数"
  ```
  （overlay 样板在 `work/lingshu-real/gongkao-session-overlay.yml`，或装好
  插件后直接用 headless 之外的日常 profile 会话验证工具面出现 9 个 `gk_*`。）

## 边界

- 网关对 `gongkao.db` 物理只读（`file:...?mode=ro`）。
- 学习状态镜像进灵枢脑由 `scripts/sync_lingshu_memory.py` 独立完成（单向），
  本插件不写脑端。
- 生态发布（npm/测评站/dsh-bounty）尚未执行，需作者决定。
