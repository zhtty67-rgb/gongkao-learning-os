# 验证记录索引

修订：2026-10-04。以下按实施时间、源码与环境区分；历史结果已查到日志，不表示本轮重新执行。个人库、资产和本地 work 证据不随 Git 分发。commit 表示相应保存版本，测试针对该阶段工作区；无法追溯全部运行时输入的记录不补造。

| 日期/阶段 | 源码基线 | 环境与范围 | 结果和限制 | 证据 |
|---|---|---|---|---|
| 2026-10-01 发布 | bdddae8 / v2026.10.01 | 本机发布前冻结 406 Attempt，迁移21→28 | 52 项发布检查、11 项页面/API HTTP；未重跑所有测试和真实批改准确率 | [发布记录](../release/20261001/RELEASE_NOTES.md)；data/backups/release_live_20261001_221938/final_release_result.json |
| 2026-10-03 教学首轮 | 教学实施首轮工作区，详见实施记录 | 新教学及既有配置对照 | 458通过/16失败/6跳过属历史结果；不得当作收尾结果 | [教学记录](ADAPTIVE_TEACHING_20261003.md)；work/adaptive-teaching-20261003/pytest-full.xml |
| 2026-10-03 教学收尾 | d02cba7 保存源码 | 本机工作区、Hub 与历史归档就绪 | 485通过/1跳过（USE_REAL_AI 未开启）；本轮仅核对原日志 | work/adaptive-teaching-20261003/pytest-final.xml、pytest-final.log |
| 2026-10-03 独立源码目录 | 收尾暂存源码导出，后保存为 d02cba7 | 同机独立目录，不复制个人库，仍使用外部 Hub/配置教师资产 | 480通过/6跳过：5项缺历史 baseline.db、1项未开启外部模型审计；不代表新机器免配置 | work/adaptive-teaching-20261003/pytest-clean-source.xml、pytest-clean-source.log |
| 2026-10-03 浏览器收尾 | d02cba7阶段工作区 | 五套隔离浏览器配置 | 36通过：普通21、复盘1、地图12、题组1、教学1；后续笔记2与复盘1为另次复查，勿重复相加 | work/adaptive-teaching-20261003/browser-acceptance-final.log、browser-notes-compatibility.log、browser-review-compatibility.log |
| 2026-10-03 真实模型教学 | d02cba7阶段工作区 | 临时库、deepseek-flash、脚本回答 | 完整补前置返回路径，7 Attempt/7卡片；曾有结构验证失败，重验成功；未证明教学效果/归因准确率 | work/adaptive-teaching-20261003/real-loop-smoke.json；[边界](ADAPTIVE_TEACHING_20261003.md) |
| 2026-10-03 类型/构建 | 教学收尾工作区与暂存源码目录 | TypeScript、生产构建 | 两份通过；个人教材/配置另行保存 | 教学记录；work/adaptive-teaching-20261003/typecheck-final.log |
| 2026-10-03 材料图修复 | 88aa73b保存源码 | 后端、隔离资料分析浏览器、正式图只读访问 | 496通过/1外部模型跳过，资料分析浏览器1通过，图片HTTP568次通过；不代替全部题图质量审计 | [材料图记录](PASSAGE_IMAGE_REPAIR_20261003.md)；work/passage-images-20261003/pytest.xml、verification.json、playwright-group.log |
| 2026-10-04 文档审计修复 | 起点88aa73b，当前工作区 SHA-256 见生成清单 | 临时迁移库、注册路由（不进 lifespan）、隔离恢复演练与相关回归 | 本轮实际结果见修订记录；未重启服务、未认证正式库数量、未跑模型效果测试 | [修订记录](DOCUMENT_AUDIT_REPAIR_20261004.md)、[源码指纹](generated/manifest.json)；work/document-audit-20261004/ |

最新正式运行入口按 [当前状态](../CURRENT_STATE.md) 与 [运维](OPERATIONS.md) 核对。接口/表结构静态契约见 [API](generated/API_ROUTES.md)、[Schema](generated/DATABASE_SCHEMA.md)，不能用旧升级包的另一份 030 解释当前系统。
