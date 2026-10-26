# 公考 Learning OS · 部署指南（脱敏发布包）

本包为脱敏发布版：**不包含任何 API 密钥与个人学习记录**。题库、知识树、
名师模型等教学资产完整保留。首次部署请按以下步骤操作。

## 环境要求

- Windows 10/11
- Python 3.11 及以上（开发验证版本 3.14）
- Node.js 20 及以上（含 npm）
- 无需 Docker；知识检索（Knowledge Hub）为可选组件，见下文“知识检索”。

## 部署步骤

1. 双击 `1-Install.bat`：创建 Python 虚拟环境、安装后端依赖、
   安装并构建前端（首次约几分钟）。
2. 双击 `2-Start.bat`：启动后端 (:8000) 与前端 (:3000)，并自动打开浏览器。
3. 打开 **系统设置** 页（导航栏最右侧“设置”，或直接访问
   <http://127.0.0.1:3000/settings>）：
   - 在 AI 模型网关下填入你的 OpenAI 兼容服务地址（base_url）、
     API 密钥与模型名，点击“测试连接”确认可用后“保存全部设置”。
   - 保存立即生效（热重载），并持久化到本机 `data/settings.json`，
     重启后依然生效；该文件不会随本包分发，属于你的私密配置。
4. 开始使用：<http://127.0.0.1:3000>

## 配置优先级说明

系统设置页保存的 `data/settings.json` > `model_config.toml` >
环境变量（AI_API_KEY / AI_BASE_URL 等）。未保存任何设置时行为与原版一致。

## 知识检索（可选）

教学讲解的证据检索默认连接本机 Knowledge Hub 服务
（KNOWLEDGE_HUB_BASE_URL，默认 127.0.0.1:8200）。本包不含 Hub；未部署时
相关讲解自动降级（诚实提示证据不可用），AI 讲题与教师模型不受影响。
如需启用，参照 universal-knowledge-hub 项目单独部署，或在系统设置页把
provider 切为 `disabled` 关闭检索提示。

## 本包内容

- `backend/` FastAPI 服务（含申论教师知识库，随包内置）
- `frontend/` Next.js 前端（含系统设置页）
- `data/gongkao.db` 题库主库（已清除个人学习数据）
- `data/assets/` 题目与解析配图
- `teachers/` 行测名师模型运行时（teacher_alimujiang, teacher_data, teacher_definition, teacher_fengze_common_sense, teacher_fengze_politics, teacher_huasheng_verbal, teacher_jiangmuyun, teacher_logic, teacher_longfei, teacher_quant）
- `model_config.toml` 模型策略骨架（api_key 已清空，请用设置页配置）
- `1-Install.bat` / `2-Start.bat` 一键安装与启动

## 数据库说明

`data/gongkao.db` 已清空 35 张个人数据表
（作答、复习调度、笔记、掌握度、导入工作数据等），题目、知识树、
技能绑定与申论资料完整保留。应用启动时会自动执行 schema 迁移。

## 已知脱敏项清单

1. 所有模型 `api_key` 已从 `model_config.toml` 移除；
   本机反向代理地址（127.0.0.1:8045）已置空。
2. 个人学习数据全部清空（见上）。
3. 开发过程产物（测试、修复脚本、日志、备份库、构建缓存）未包含。
