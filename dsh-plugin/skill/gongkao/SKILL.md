---
name: gongkao
description: >
  查询用户的公考学习状态：模块/考点掌握度、FSRS 到期复习、错题本与错因分布、
  知识树、个人笔记与名师讲题。当用户问到「我的掌握度/薄弱点/该复习什么/这道题
  怎么讲/我的错题/我的笔记」等学习状态问题时使用本技能。数据来自公考学习系统
  的只读 MCP 网关（gongkao server，gk_* 工具族）。
version: 0.1.0
license: MIT
---

# 公考学习系统只读网关

通过 `gongkao` MCP server 的 `gk_*` 工具查询学习状态。所有工具只读；
`gk_ask_teacher` 带 `use_llm: true` 时会调用后端 LLM 讲题（有成本），默认仅做
本地教师方法检索（零成本）。

## 工具速查

| 场景 | 工具 |
| --- | --- |
| 总览（掌握度/今日目标/薄弱点/到期数） | `gk_overview` |
| 某模块或考点的掌握度（Beta 后验/证据数/提示依赖） | `gk_mastery {module?, node?, limit?}` |
| 今天该复习什么（FSRS 到期卡片） | `gk_due_reviews {limit?}` |
| 错题本与十维错因分布 | `gk_wrong_book {module?, limit?}` |
| 知识树浏览（~660 节点） | `gk_knowledge_tree {module?, depth?}` |
| 单考点深览（绑题/错因/最近作答） | `gk_node_detail {node}` |
| 最近作答流（信心/提示层级/耗时） | `gk_recent_attempts {limit?, only_wrong?, module?}` |
| 个人笔记检索 | `gk_notes {node?, question_id?, module?}` |
| 名师方法参考（可显式升 LLM 讲题） | `gk_ask_teacher {question_id?, stem?, module?, use_llm?}` |

## 使用约定

- 模块名用库里真实命名：`言语理解 / 逻辑判断 / 类比推理 / 定义判断 / 图形推理 /
  立体图推 / 数量关系 / 资料分析 / 常识判断 / 政治理论 / 申论`。
- `node` 参数接受 knowledge_node_code（如 `gongkao.xingce.reasoning.translate`）、
  code 或 id。
- 学习状态是隐私数据：仅在用户本人会话中呈现，不要主动外发。
- 脑端镜像：学习状态亦已镜像进灵枢脑（dsh-memory，tag 前缀 `gongkao:`），
  可用 `mdcg_recall` 直接召回；本网关的读数永远是权威真源。
