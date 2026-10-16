# 开发文档

开发环境和修改流程见 [CONTRIBUTING](../../CONTRIBUTING.md)。本目录按当前功能组织说明，不维护开发阶段日志。

| 文档 | 内容 |
|---|---|
| [运行指南](runs.md) | CLI/SDK、离线运行、恢复、澄清和派生编辑 |
| [建模方法](methods.md) | 编排、提示组合、来源与变体 |
| [LLM 配置](llm.md) | 供应商、模型目录、私有设置和代理 |
| [执行与求解](solvers.md) | IR、模型工厂、求解器与容器边界 |
| [Benchmark 与评测数据](benchmarks.md) | 内置题面、评测快照、批量实验 |
| [Web 工作台](web.md) | 页面职责、HTTP 边界和前端构建 |
| [测试指南](testing.md) | 聚焦检查、完整回归和浏览器测试 |
| [支持验证](validation.md) | 保留的真实接入证据及其适用范围 |

字段定义见[接口契约](../plugin-contracts.md)，系统职责见[架构](../architecture.md)，指标定义见[评测协议](../evaluation.md)。工作项在 GitHub Issues 中跟踪。

## 30 天轮换开发任务

三位同学依次接手，每人 10 天。每阶段验收后集成到 `main`，下一位从该版本继续。

| 执行人 | 周期 | 任务书 |
|---|---|---|
| 同学 A | 第 1—10 天 | [前端重构与用户流程完善](assignments/01-frontend.md) |
| 同学 B | 第 11—20 天 | [核心抽象复核与两种建模方法接入](assignments/02-abstractions-methods.md) |
| 同学 C | 第 21—30 天 | [两个求解器接入与全平台验收](assignments/03-solvers-acceptance.md) |

新增方法中只固定 LLMOPT，另一种方法及两个求解器由执行人选型。任务书用于分发和交接，具体规格、bug 和完成状态仍在 GitHub Issues 跟踪。
