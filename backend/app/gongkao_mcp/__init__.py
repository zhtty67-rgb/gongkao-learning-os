"""公考学习系统 MCP 只读网关（stdio）。

对灵枢/DSH 生态暴露学习状态的只读工具面：掌握度、FSRS 到期复习、错题本、
知识树、个人笔记与名师讲题。协议为行分隔 JSON-RPC 2.0（MCP stdio），零第三方
依赖，与服务端实现 md_cg/mcp_server.py 的分帧与错误语义保持一致。

安全边界：数据库以 ``file:...?mode=ro`` URI 打开，本网关对公考库只读；
``gk_ask_teacher`` 是唯一有外部成本的工具（LLM 讲题），须显式 use_llm=true。
"""
