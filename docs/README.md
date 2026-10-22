# 文档导航

第一次使用，从 [README](../README.md) 开始。

| 我想…… | 文档 |
|---|---|
| 了解平台、快速启动 | [README](../README.md) · [English](../README.en.md) |
| 用工作台、命令行或 Python 求解问题 | [使用指南](user-guide.md) |
| 部署给课题组或团队使用 | [部署指南](deployment.md) |
| 修改代码、接入新方法、发布版本 | [开发指南](../CONTRIBUTING.md) · [开发规范](../CODING_STANDARDS.md) |
| 理解模块、方法接口、沙箱和运行记录 | [架构](architecture.md) |
| 了解各方法的流程、固定来源和适配差异 | [建模方法](methods.md) |
| 了解重要的架构取舍 | [ADR 索引](adr/README.md) |
| 查术语 | [GLOSSARY](../GLOSSARY.md) |
| 看版本变化 | [CHANGELOG](../CHANGELOG.md) |
| 报告安全问题 | [SECURITY](../SECURITY.md) |

工作项使用 GitHub Issues。代理按任务读取[工作项约定](agents/issue-tracker.md)、[领域文档约定](agents/domain.md)和[技能路由](agents/workflow.md)。

## 研究资料

[参考资料库](references/README.md)提供论文、代码和数据链接。[资料核验说明](references/search-log.md)说明来源和读取范围。

论文元数据在 `references/catalog.json` 中维护。修改后运行 `python3 scripts/render_references.py`，重新生成资料页和 BibTeX。

## 图片

`assets/` 中有 README 和使用指南用的横幅、截图和演示动图。更新方法见[开发指南](../CONTRIBUTING.md#文档)。
