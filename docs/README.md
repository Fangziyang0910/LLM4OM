# 文档导航

使用平台从[项目介绍与使用指南](../README.md)开始。开发规范、领域定义和研究资料按下表查阅。

| 任务 | 文档 |
|---|---|
| 启动页面、配置模型、求解问题 | [README](../README.md) |
| 使用 CLI/SDK、取消、恢复、修改运行 | [运行指南](development/runs.md) |
| 了解方法编排和适配差异 | [建模方法](development/methods.md) |
| 配置供应商、模型目录和密钥 | [LLM 配置](development/llm.md) |
| 选择后端、求解器和执行方式 | [执行与求解](development/solvers.md) |
| 维护内置题库、导入评测数据 | [Benchmark 与评测数据](development/benchmarks.md) |
| 修改前端或 Web 接口 | [Web 工作台](development/web.md) |
| 安装开发环境、运行检查 | [贡献指南](../CONTRIBUTING.md)、[测试指南](development/testing.md) |
| 查询实际验证范围 | [支持验证](development/validation.md) |

## 设计与规范

| 内容 | 唯一维护位置 |
|---|---|
| 领域术语 | [GLOSSARY](../GLOSSARY.md) |
| 产品范围与可测试要求 | [需求规格](requirements/v1.0.md) |
| 系统职责与数据流 | [架构](architecture.md) |
| 流程时序与不变量 | [详细设计](detailed-design.md) |
| 字段、接口和版本语义 | [接口契约](plugin-contracts.md) |
| 正确性、指标与分母 | [评测协议](evaluation.md) |
| 验收场景与需求映射 | [验收清单](acceptance.md) |
| 需要保留的架构取舍 | [ADR 索引](adr/README.md) |
| 代码与文档写法 | [开发规范](../CODING_STANDARDS.md) |

概览只解释能力和使用入口。字段定义在契约中维护，术语定义在 GLOSSARY 中维护。变更时更新对应来源及受影响的示例和测试。

工作项和功能规格使用 GitHub Issues。代理按任务读取[工作项约定](agents/issue-tracker.md)、[领域文档约定](agents/domain.md)和[技能路由](agents/workflow.md)。

## 研究资料

[研究综述](research-landscape.md)比较任务、方法和评测机制。[参考资料库](references/README.md)提供论文、代码和数据链接。[源码考察](references/source-inspection.md)记录固定提交及实际观察。[资料核验说明](references/search-log.md)说明来源和读取范围。

论文元数据与阅读范围在 `references/catalog.json` 中维护。资料页和 BibTeX 由工具生成。上游论文的成绩与本项目的接入验证分别报告。
