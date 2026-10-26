"""灵枢脑（dsh-memory）桥接：把公考学习状态镜像进白盒 md 认知图。

设计约束（见 plans/公考适配灵枢）：
- 不 import lingshu 包（其 __init__ 会安装 sys.meta_path 守卫污染本进程导入链）；
  按 lingshu/world/brain_store.py 的协议自写最小客户端。
- 所有脑 I/O 收敛在本包——dsh-memory 0.9.x → 1.0 破坏性变更只改这里。
- 写入一律走 MCP 工具（cg op=write / mdcg_remember），不直写 md 文件，
  尊重 CCG 六要素门禁与 _index.json 一致性。
"""
