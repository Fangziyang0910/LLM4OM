# 按任务选择技能

这是任务路由。规范与完成条件由 [CONTRIBUTING](../../CONTRIBUTING.md)和 [CODING_STANDARDS](../../CODING_STANDARDS.md)维护；按任务读取相关技能的完整指令。

## 任务入口

| 当前工作 | 使用技能 | 需要留下的结果 |
|---|---|---|
| 理解文献、API 或上游实现 | research | 来源、读取范围、固定版本及可迁移认识 |
| 确定领域词或架构决定 | domain-modeling | glossary 的规范定义或简短 ADR |
| 设计模块接口、寻找接缝 | codebase-design | 小 Interface、完整职责、真实变化维度 |
| 尚不确定交互或状态模型 | prototype | 回答具体设计问题的可丢弃原型 |
| 将已讨论想法变为功能规格 | to-spec | 用户行为、取舍、测试入口、范围 |
| 将规格拆为可执行工作项 | to-tickets | 纵向切片、验收与真正的阻塞关系 |
| 领取／实施已明确的工作 | implement、implement-spec | 从可执行前沿选择任务，交付可观察行为 |
| 分类或澄清 GitHub 请求 | triage | 一个类别、一个状态、技能要求的 AI 声明 |
| 新非平凡行为或修复 | tdd | 公共入口上的逐步 red → green |
| 难复现错误或性能退化 | diagnosing-bugs | 复现、可区分解释、根因修复及回归证据 |
| 寻找模块变深的机会 | improve-codebase-architecture | 当前复杂性与实际接口改进，不预建空层 |
| 修改代理常读文件 | writing-for-agents | 常驻约束精简、触发清楚、按需读取 |
| 用户请求审阅变更 | code-review | Standards 与 Spec 两路结果 |
| 用户请求 PR 或工作交接 | pr、handoff | 变更证据、剩余工作与可恢复上下文 |

这些技能按任务调用，不要求每次修改经过所有阶段。未提供某个技能时使用现有规范完成已授权工作，并说明受影响的步骤。显式调用的技能要求展示草案或审批时，遵循其具体要求与当前会话授权。

## 阅读分支

- 用户问题与方法：glossary → 相关 FR → DD-01/02 → 两阶段契约与验收；阶段取舍见 ADR-0004。
- 插件、建模表示与求解：相关 ADR → DD-03/04/05 → 能力、错误和状态契约。
- 实验、恢复与入口：评测协议 → DD-06/07/08 → 相应 AC 与切片依赖。
- GitHub 操作：先读 [issue tracker](issue-tracker.md)；triage 再读 [label mapping](triage-labels.md)。

当前仓库没有平台实现。研究文档、设计 fixture 和维护工具的完成状态分别报告。
