# 架构决策

ADR 保留改变成本较高、需要解释取舍的决定。当前行为和字段分别见[架构](../architecture.md)与[接口契约](../plugin-contracts.md)。

| 决策 | 主题 |
|---|---|
| [0001](0001-dual-artifact-paths.md) | 严格 IR 与原生代码共存 |
| [0002](0002-oracle-isolation.md) | 公开反馈与隐藏参考评测材料隔离 |
| [0003](0003-independent-plugin-axes.md) | 方法、LLM、建模后端和求解器独立配置 |
| [0004](0004-formulation-and-code.md) | 分开 Formulation 与 Code |
| [0005](0005-factory-collector-isolation.md) | 隔离模型构建与可信结果收集 |
| [0006](0006-modeling-process-replaces-candidate.md) | 用建模过程、阶段产物和公开检查组织运行 |
