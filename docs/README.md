# 文档导航

使用平台从 [README](../README.md) 开始。

| 内容 | 文档 |
|---|---|
| 启动、配置模型、求解问题 | [README](../README.md) |
| 模块、方法接口、沙箱和运行记录 | [架构](architecture.md) |
| 各方法流程、固定来源和适配差异 | [建模方法](methods.md) |
| 架构取舍 | [ADR 索引](adr/README.md) |
| 领域术语 | [GLOSSARY](../GLOSSARY.md) |
| 开发环境、测试和规范 | [CONTRIBUTING](../CONTRIBUTING.md)、[CODING_STANDARDS](../CODING_STANDARDS.md) |

工作项使用 GitHub Issues。代理按任务读取[工作项约定](agents/issue-tracker.md)、[领域文档约定](agents/domain.md)和[技能路由](agents/workflow.md)。

## 研究资料

[参考资料库](references/README.md)提供论文、代码和数据链接。[资料核验说明](references/search-log.md)说明来源和读取范围。

论文元数据在 `references/catalog.json` 中维护。修改后运行 `python3 scripts/render_references.py` 重新生成资料页和 BibTeX。
