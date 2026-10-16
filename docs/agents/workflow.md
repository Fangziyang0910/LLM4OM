# 技能路由

按当前任务读取对应技能。开发规则由 [CONTRIBUTING](../../CONTRIBUTING.md)和 [CODING_STANDARDS](../../CODING_STANDARDS.md)维护。

| 任务 | 技能 | 结果 |
|---|---|---|
| 理解论文、API 或源码 | research | 来源、读取范围与可迁移认识 |
| 统一领域词或记录取舍 | domain-modeling | GLOSSARY 或 ADR |
| 改善模块接口 | codebase-design | 职责、输入输出和真实变化边界 |
| 验证交互或状态模型 | prototype | 回答具体设计问题的原型 |
| 整理已讨论的需求 | to-spec | 用户行为、取舍、验收和范围 |
| 拆分工作项 | to-tickets | 纵向任务和实际阻塞关系 |
| 实施明确功能 | implement / implement-spec | 可观察行为与检查 |
| 分类 GitHub 请求 | triage | 类别与状态 |
| 验证非平凡行为 | tdd | 公共入口上的失败/通过循环 |
| 排查难复现故障 | diagnosing-bugs | 复现、根因和回归证据 |
| 整理模块边界 | improve-codebase-architecture | 已存在复杂性的改进 |
| 修改代理读取的文档 | writing-for-agents | 清晰触发、单一来源和按需引用 |
| 审阅变更 | code-review | 规范与任务要求两路结论 |
| 编写 PR 或交接 | pr / handoff | 变化、证据和剩余条件 |

这些技能按任务调用。仓库已有 Matt 技能配置，无需重复初始化。当前工作不经过所有技能，也不为常规选择添加审批。

修改领域或架构时先读[领域约定](domain.md)。GitHub 操作先读[工作项约定](issue-tracker.md)，分类状态时再读[标签映射](triage-labels.md)。具体设计和验证按[文档导航](../README.md)读取。
