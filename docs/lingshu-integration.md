# 灵枢（DSH 生态）可选适配器

> 主次关系：**公考 MCP 服务是核心接入面**（见 [mcp-server.md](mcp-server.md)），
> 本页的两个组件都是**可选适配层**——不装不影响任何功能，按需启用。

```
公考系统 → 公考 MCP 服务 → 支持该服务的 AI 客户端（通用，核心）
                        ↳ DSH 插件 = 自动挂载配置壳（可选）
公考系统 ⇄ 同步桥接器 ⇄ 灵枢记忆库 dsh-memory（可选，双向窄通道）
  ├─ 正向：知识树/掌握度/作答摘要 → 脑（公考为真源）
  └─ 反向：脑端 agent 原生记忆 → user_notes（只写这一张表）
```

## 适配器一：DSH 插件壳（`dsh-plugin/`）

只是安装配置外壳：cordis overlay 用 `@deepseek-ai/dsh-mcp-client` 拉起同一个
`gongkao_mcp` stdio 服务 + 挂载 SKILL.md。不装它，任何 MCP 客户端仍可直连。

```powershell
$env:GONGKAO_LEARNING_OS_ROOT = 'D:\gong\gongkao-learning-os'
dsh plugin --profile <name> add file:./dsh-plugin   # 必须带 file: 路径，
                                                    # 否则会误装 npm 上的同名包
# 在 profile package.json 的 dsh.profile.bundles 加入 gongkao-learning-os-dsh
dsh --profile <name> --dump-config   # 应出现 mcp-gongkao / skill-gongkao
```

**验证状态（诚实口径）**：已在 scratch profile `gktest` 完成「安装 + 组合配置
验证」（`--dump-config` 可见完整挂载）。**未做**：真实 DSH 会话内 boot 与 AI
调用验证——需要 profile 配好 LLM provider 后人工进行。插件内路径默认 Windows
venv 布局，POSIX 需设 `GONGKAO_PYTHON`。

## 适配器二：灵枢脑镜像（`backend/app/lingshu_bridge/` + `scripts/sync_lingshu_memory.py`）

把学习状态单向写入 dsh-memory 白盒认知图（structural=知识树骨架 /
knowledge=考点掌握态 / contextual=作答摘要），供挂了灵枢脑的 agent 直接
`mdcg_recall`。公考库永远不被反向写入。

- 桥接客户端：按 lingshu `world/brain_store.py` 协议自写（禁 import lingshu
  包——其 `__init__` 会装 sys.meta_path 守卫污染本进程）。所有脑 I/O 收敛在
  `client.py` 单模块，dsh-memory 1.0 破坏性变更只改这里。
- CCG 六要素门禁（实证）：content 必须含 `# 功能名/生效条件/子功能/执行/验证
  方式/不适用条件` 六行，缺一 REJECT；同步用 `content_kind='text'`（合法值
  `['ccg_marks','code','hyperedge','image_desc','permission','text','work_done','work_wip']`）。
- 凭据：recorder 令牌（层限 knowledge/contextual/structural…）；明文只出现
  一次，`LINGSHU_TOKEN_FILE` 指明文文件。无凭据 = guest 只读。
- 安全推进三步：dry-run → scratch（`--memory-root work/lingshu-scratch/probe2`）→
  真实脑根。**真实脑根镜像已于 2026-10-25 执行完毕**：`%USERPROFILE%\.dsh\.dsh-memory\data\mdcg`
  （DSH 插件默认脑根），写入 61 structural + 17 knowledge + 1 contextual = 79 条全
  ACCEPT，既有 12 条 contextual 原样保留（总 91 节点），`mdcg_recall` 三问全中。

### 真实脑根运行手册（复跑增量同步）

```powershell
# 前置：dsh-memory 检出 + 已签发的 recorder 令牌（见下）
$env:MDCG_AUX_ROOT     = '<仓库>/work/lingshu-real/credroot'
$env:LINGSHU_TOKEN_FILE= '<仓库>/work/lingshu-real/token-plain.txt'
$env:LINGSHU_MEMORY_ROOT = "$HOME\.dsh\.dsh-memory\data\mdcg"
$env:LINGSHU_DSH_MEMORY_PATH = '<你的 dsh-memory 检出路径>'
# Windows 写入拦截（见下）→ 同步驱动也用系统 python 跑：
<系统 python 或 venv python> scripts/sync_lingshu_memory.py
```

增量口径：水位 `data/lingshu_sync_state.json`；任一条写入失败**不推进水位**，
排查后重跑即可覆盖同一区间。

### Windows 写入拦截（真实根踩坑，重要）

本机存在按进程链的写入拦截：**venv 内的 python.exe（或其子孙进程）写
`C:\Users\<用户>\*` 一律 Errno 13**（bash/系统 python 直跑不受影响）。因此：
- 写真实脑根的整条进程链必须用**系统 python**（`LINGSHU_BRAIN_PYTHON` 指定
  脑端服务解释器；同步驱动本身也用系统 python 跑，`queries.py` 已把
  fsrs/fastapi 依赖改为惰性导入，同步器纯标准库）。
- gongkao MCP 网关不受影响（只读、不写 C 盘）。
- 另外：aux 目录名不能叫 `aux`（Windows 保留设备名，md_cg 路径守卫会拒绝），
  本仓用 `credroot`；同步凭据库与用户 `~/.mdcg` 隔离（`work/lingshu-real/`，
  gitignore 已盖）。

**验证状态**：真实脑根 79/79 ACCEPT、`mdcg_recall` 三问全中、集成测试
（`LINGSHU_INTEGRATION=1` 门控）5/5。增量水位已建立（2026-10-08T13:31Z）。

### 沙箱/受限环境必读

- md_cg 服务端 aux 根默认 `~/.mdcg`；在写入受限的环境（如 ZCode Bash 沙箱）会
  **无限卡死握手**（不是慢）——必须设 `MDCG_AUX_ROOT` 指向可写目录。客户端
  超时 ≥180s（冷启动 ~6s：数据面迁移 + 522 项代校验）。
- 服务端只认 `MDCG_TOKEN` 明文串；`MDCG_TOKEN_FILE` 是凭据库
  （`<aux>/_tokens.json`），不是明文文件。客户端带 token 且 aux 被重定向时，
  会自动把 `MDCG_TOKEN_FILE` 指到 `<aux>/_tokens.json`，否则令牌校验失败、
  服务拒绝启动。

### 幂等与水位

条目带快照日期 + 稳定 tag（`gongkao:node:<code>`）；重复同步同一节点会产生
新条目（生效条件声明「以最新同步为准」，由脑端遗忘/整并收敛）。水位存
`data/lingshu_sync_state.json`（gitignore）。

## 反向同步（`--backsync`，脑 → 公考笔记）

把脑端 **agent 原生记忆**（你在 DSH/灵枢会话里 agent 写入的反思/建议/心法）
回流进公考 `user_notes`，在复盘/笔记页可见。方向纪律与边界：

- **只写 `user_notes` 一张表**（`note_type=dialogue_clipping`，复用
  `domain/notes.create_or_update_note` 的版本控制），绝不碰
  attempts/mastery/review——学习状态本体永远以公考库为唯一真源。
- **层白名单**：默认仅 `knowledge,self`（agent 精炼记忆）。`contextual` 默认
  排除——DSH 的 dsh-memory-hook 会把每条用户消息原样落入该层，整层导入等于
  把聊天记录灌进笔记（实测真实脑 12 条全是日常对话）。`anchor` 硬禁（脑端
  核心身份）。需要时 `--backsync-layers knowledge,self,contextual` 显式放开。
- **回声环双保险**：正向镜像带 `gongkao:source:gongkao` tag（过滤①）+ 六要素
  模板特征行「数据来自公考学习系统」（tag 被脑端整并丢弃后兜底过滤②）。
- **幂等双保险**：状态映射（brain 节点 id → note id）+ 库内按
  `source_message_id` 复原映射（状态文件丢失也不重复导入已导条目）。
- 溯源：`source_message_id`=脑节点 id，`metadata_json.origin=lingshu_brain`
  （含 layer/tags/created_at）。`source_type` 受 CHECK 约束只能取 `manual`，
  灵枢来源以 metadata 为准。
- 水位语义：`backsync.last_created_at`（脑端 created_at epoch）；脑端后续编辑
  不重导（按 created_at 增量）。

```powershell
# dry-run（只打印候选）
python scripts/sync_lingshu_memory.py --backsync --dry-run
# 执行（反向读写都在本机仓库/库上，venv python 即可，无需系统 python）
python scripts/sync_lingshu_memory.py --backsync
```

2026-10-25 实测：真实脑根 knowledge 层 17 条全为正向镜像（回声过滤全数排除），
self 为空 → 首次回流 0 条；管道与过滤在真实数据上验证通过。你与 DSH agent
对话产生的原生记忆积累后，重跑即自动入笔记。

## 测试

- `tests/test_lingshu_bridge_sync.py`：同步计划/六要素/水位单元 + env 门控真脑端集成。
- `tests/test_gongkao_mcp_server.py`：协议与工具面（服务本体，见 mcp-server.md）。
