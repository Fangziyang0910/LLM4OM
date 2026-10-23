# 架构决策

ADR 保留改变成本较高、需要解释取舍的决定。当前行为见[架构](../architecture.md)。

| 决策 | 主题 | 状态 |
|---|---|---|
| [0004](0004-formulation-and-code.md) | 分开 Formulation 与 Code | 有效 |
| [0007](0007-langchain-minimal-core.md) | 以 LangChain 运行时和最小核心重建平台 | 有效；代码契约部分被 0008 取代，运行记录部分被 0009 取代 |
| [0008](0008-code-language.md) | 用户选择代码写法，写法决定求解器 | 库与后端绑定规则被 0013 取代 |
| [0009](0009-langgraph-server.md) | 用 LangGraph 服务器运行、推送和保存运行 | 有效；运行上下文与设置部分被 0010 取代，中断记录部分被 0012 取代 |
| [0010](0010-llm-presets.md) | 运行只选择预设模型，密钥不离开服务器 | 有效 |
| [0011](0011-docker-compose-deployment.md) | 整套服务用 Docker Compose 部署 | 有效 |
| [0012](0012-run-records.md) | 固定运行配置，用原生 Store 保留中断进度 | 有效 |
| [0013](0013-modeling-libraries.md) | 九个建模库与原生求解后端 | 有效 |
| [0014](0014-requirements-conversation.md) | 需求对话与建模方法通过问题文本交接 | 有效 |
| [0015](0015-plan-conversation.md) | 方案对话读取固定结果，明确变更交回平台图 | 有效 |
