# 架构决策

ADR 保留改变成本较高、需要解释取舍的决定。当前行为见[架构](../architecture.md)。

| 决策 | 主题 | 状态 |
|---|---|---|
| [0001](0001-dual-artifact-paths.md) | 严格 IR 与原生代码共存 | 被 0007 取代 |
| [0002](0002-oracle-isolation.md) | 公开反馈与隐藏参考评测材料隔离 | 有效 |
| [0003](0003-independent-plugin-axes.md) | 方法、LLM、建模后端和求解器独立配置 | 部分被 0008 取代：后端与求解器合并为代码写法 |
| [0004](0004-formulation-and-code.md) | 分开 Formulation 与 Code | 有效 |
| [0005](0005-factory-collector-isolation.md) | 隔离模型构建与可信结果收集 | 被 0007 取代 |
| [0006](0006-modeling-process-replaces-candidate.md) | 用建模过程、阶段产物和公开检查组织运行 | 被 0007 取代 |
| [0007](0007-langchain-minimal-core.md) | 以 LangChain 运行时和最小核心重建平台 | 有效；代码契约部分被 0008 取代，运行记录部分被 0009 取代 |
| [0008](0008-code-language.md) | 用户选择代码写法，写法决定求解器 | 有效 |
| [0009](0009-langgraph-server.md) | 用 LangGraph 服务器运行、推送和保存运行 | 有效；运行上下文与设置部分被 0010 取代 |
| [0010](0010-llm-presets.md) | 运行只选择预设模型，密钥不离开服务器 | 有效 |
| [0011](0011-docker-compose-deployment.md) | 整套服务用 Docker Compose 部署 | 有效 |
