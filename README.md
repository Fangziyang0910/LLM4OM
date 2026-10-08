# LLM4OM

**自动优化建模集成平台 · A modular platform for automated optimization modeling**

LLM4OM 将自动建模方法、LLM、任务与数据、建模产物、求解后端和基准评测接入同一个可扩展框架，作为通用智能优化平台的 1.0。

**LLM4OM = Large Language Models for Optimization Modeling**，其中 `4` 表示 `for`，`OM` 表示 `Optimization Modeling`，与 LLM4AD 的命名方式对应。名称由用户于 2026-10-08 确定；GitHub 仓库名采用 `LLM4OM`，未来 Python 包名、命令名与插件命名空间采用 `llm4om`。

完整项目标题：**LLM4OM: A Unified Platform for Automated Optimization Modeling with Large Language Models**。

## 当前状态

本仓库目前包含 **1.0 需求与设计基线**，尚未实现平台。文档里的命令、接口、目录和示例是开发目标，不代表已可运行；不提供未经实验验证的性能或准确率承诺。

GitHub 仓库当前为私有，项目按未来开源协作设计，采用 Apache-2.0。私有可见性与开源许可证分别管理；本次初始化不发布公开版本。

## 1.0 目标

- 可插拔接入自动建模方法与不同 LLM，二者独立配置。
- 将自然语言、表格数据和任务配置规范化为统一问题输入。
- 输出可检查的数学模型、代码、假设、需求映射和执行证据。
- 同时支持结构化 LP/MILP IR 和已有方法的原生代码产物。
- 统一调度求解、隔离执行、预算控制、反馈修正与批量评测。
- 保留问题、插件、数据、模型、配置和运行轨迹的版本与来源。

1.0 的可靠执行范围是 **LP/MILP**；通用扩展接口不等于已经支持任意优化问题。后续版本可以增加非线性、约束规划、不确定性优化、算法选择和算法设计。

## 阅读顺序

| 文档 | 内容 |
|---|---|
| [需求规格](docs/requirements/v1.0.md) | 用户、范围、场景、功能需求、非功能需求与发布标准 |
| [领域术语](CONTEXT.md) | 方法、模型、建模语言、求解器、基准与评估证据的统一定义 |
| [架构设计](docs/architecture.md) | 模块职责、插件接入、数据流、执行与恢复 |
| [插件与数据契约](docs/plugin-contracts.md) | 接口、核心数据结构、能力声明、兼容性与错误语义 |
| [评测协议](docs/evaluation.md) | 正确性层次、分母、容差、预算、公平比较与数据污染控制 |
| [开发计划](docs/implementation-plan.md) | 可独立验收的开发切片、依赖关系与首批适配矩阵 |
| [验收清单](docs/acceptance.md) | 端到端场景、契约测试、发布证据与需求追踪 |
| [相关工作](docs/research-landscape.md) | 参考项目、可借鉴模块、证据与调研限制 |
| [决策与待定项](docs/decisions-and-open-questions.md) | 用户明确要求、设计默认值、后续需确认的事项 |
| [示例规格](examples/README.md) | 一份可手工核验的 MILP 问题、IR、参考解和实验配置 |
| [规格校验记录](docs/spec-validation.md) | 文档链接、编号、JSON/YAML 与手算 fixture 的审阅结果 |

## 预期使用方式

以下是计划中的 CLI，不可在当前文档仓库直接运行：

```bash
llm4om plugins list
llm4om doctor --config experiments/demo.yaml
llm4om run --problem problem.json --config experiments/demo.yaml
llm4om benchmark --config experiments/benchmark.yaml
llm4om resume --run-id RUN_ID
llm4om report --experiment-id EXPERIMENT_ID --format markdown
```

同一内核应能被 Python SDK 和本地 Web 工作台调用。首批内置方法计划为 `direct`、`feedback_repair` 和 `optimus`；专用 ORLM 模型通过 LLM 接口选择，不被错误归类为独立搜索方法。

## 开发约定

每个插件必须声明能力和兼容矩阵，不允许自动降级后仍把结果标成原方法；每个评估结论必须说明证据级别。**求解器报告最优，只表示候选模型被求解，不证明模型符合业务需求。**

从 [开发计划的 S01](docs/implementation-plan.md#s01-统一问题契约与离线纵向流程) 开始。变更功能范围或契约时同步更新规格、示例和验收清单。详细贡献约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。
