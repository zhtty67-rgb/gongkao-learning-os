# 资料分析材料图修复（2026-10-03）

用户反馈题图显示整页，而非对应题目。当前练习的江苏 2016 年 A 类 117、118 题属于该问题。

## 原因与实际修复

旧导入程序将整个 PDF 页面作为材料图，并按页面数量、题库中剩余题目的顺序近似分组。材料跨页时混入相邻题目；被排除的题目又使后续五题分组错位。

本次沿用 `questions.passage_id` 和 `question_passages.assets_json`，按原题本的材料标题、原始题号和实际坐标裁切。材料止于本组首道子题之前，保留跨页文字及图表，排除下一组内容与页眉页脚。图像按 2.5 倍渲染，前端原有放大功能继续可用。

- 花生资料分析：120 组材料。
- 江苏资料分析：78 组材料。
- 共 198 组、284 张材料图片；修正 83 道题的材料关联。
- 恢复江苏 2018 C、2019 C、2020 C、2022 A 的第 4 组材料，共新增 4 条已有表中的记录。没有 Schema 或 migration 变化。
- 江苏 2022 C 的住房公积金题，原 C 卷误排为原油图表。经题干、选项和图表核对，使用同年 A 卷的同题住房公积金材料，并将来源文档指向 A 卷。人工核验边界记录在 `scripts/reviewed_passage_boundaries_20261003.json`，绑定来源 PDF 的 SHA-256。

没有更改题干、选项、答案、解释、题目指纹或既有学习记录。没有新增 API、前端架构、掌握度模型或知识体系。

## 工具与备份

`scripts/repair_passage_images.py` 默认生成裁切图和审计计划，不写数据库。只有 `--apply` 会备份数据库并在单个事务中更新材料及关联。并发修改通过原值比较阻止覆盖，任一冲突会回滚整批写入。备份已经存在时拒绝覆盖，可指定新的 `--work-dir`。

示例（仓库根目录，PowerShell）：

```powershell
.venv\Scripts\python scripts/repair_passage_images.py --sources 'D:\BaiduNetdiskDownload\刷题题本' --family huasheng --dependency-site 'D:\gong\universal-knowledge-hub\.venv\Lib\site-packages'
```

支持 `jiangsu` / `huasheng` 两类来源；需要原 PDF 和现有 PDFium、Pillow，扫描题本另需 RapidOCR。原 PDF、原整页图、个人数据库和新图片按既有规则不纳入 Git。

本次备份与可审计计划保存在：

- `work/passage-images-20261003/jiangsu/before.db`：本次修复前的完整数据库。
- `work/passage-images-20261003/jiangsu-final/before.db`：江苏补齐分组前的备份。
- `work/passage-images-20261003/huasheng/before.db`：花生材料更新前的备份。
- 各目录下的 `plan.json` 包含原字段、实际来源、裁切框、图片路径及关联修正。
- `verification.json`、`pytest.xml`、`pytest.log`、`playwright-group.log`：验证结果。

## 实际验证

- 新增 11 项单元与数据库集成测试：边界定位、跨页材料、表格小数误识、嵌套小标题、缺失/歧义拒绝、原始五题分组、数据库备份、并发冲突整批回滚、新材料记录及学习事实保留。
- 完整后端测试：496 passed，1 skipped；跳过项为未启用的真实外部模型测试。
- 既有资料分析 Playwright 流程：1 passed，覆盖材料显示、放大、五题作答与结算复盘。
- 正式题库 284 个图片地址在前端和后端分别验证，568 次请求全部返回有效图片。
- 正式界面使用真实材料数据、拦截学习接口的只读检查通过；2016 A 第 1 组显示一张 1364 × 351 的材料裁切图，没有整页和相邻题目。截图为 `work/passage-images-20261003/quiz-material-fixed.png`；此检查没有新增 Attempt。
- 修复前后比较：除材料表和题目材料关联外，其余数据库表完全一致；题目其余字段完全一致。外键检查无异常，SQLite integrity_check 为 ok。

## 运行状态与范围

Next.js 正式进程启动时枚举公共图片，旧 3000 进程不能立即识别新增文件。自动审批拒绝停止并重启旧进程，因此已在 3003 启动同一个项目，继续连接原 8000 后端及原题库。可从 3003 恢复原 session；3000 需要由用户重启后识别新图片。没有创建另一套学习系统或数据库。

本次覆盖资料分析材料图；未宣称完成所有图形推理、数量关系单题图的质量审计。题干和解释的既有 OCR 错字、题本自身的其他错误仍需逐题核验。后续批量导入应使用本次坐标/题号核验工具检查材料，避免再次运行旧的整页材料修复脚本覆盖已校正图片。
