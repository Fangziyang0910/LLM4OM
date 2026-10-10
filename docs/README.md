# LLM4OM 文档体系

文档修订：0.4.0；日期：2026-10-08。当前交付包含调研、需求与设计，以及 [S01 离线切片](development/s01-offline-run.md)、[S02-A 真实求解](development/s02-highs.md)、[S02-B 参数化工厂](development/s02b-factory.md)、[S03 方法发现／预检](development/s03-plugins.md)、[S04-A 容器执行](development/s04-container.md)、[S04-B 取消／恢复](development/s04-resume.md)、[S05-A 真实文本 LLM](development/s05-provider.md)及 [S07-A NL4Opt 导入／评测](development/s07-nl4opt.md)。

LLM4OM 面向自动优化建模研究者和开发者。核心用例是输入自然语言问题与数据，选择建模方法和兼容求解配置，获得可检查的建模输出与求解结果。Benchmark 在同一流程上组织批量实验。

## 1. 从研究认识到软件实现

| 阶段 | 文档 | 主要回答 | 交付边界 |
|---|---|---|---|
| 文献调研 | [研究综述](research-landscape.md)、[参考资料](references/README.md) | 领域已有任务、方法、表示与评测如何组织？ | 区分论文描述、源码观察和本项目推断 |
| 需求说明 | [1.0 需求规格](requirements/v1.0.md)的产品定义、用户与场景 | 为谁解决什么问题？ | 固定产品目标与 1.0 范围 |
| 需求分析 | [需求分析](requirements/analysis.md) | 哪些领域对象和约束决定设计？ | 解释需求来源、优先级、取舍与依赖 |
| 软件需求规格 | [1.0 需求规格](requirements/v1.0.md)的 FR/NFR | 必须观察到什么行为？ | 可测试要求，保持稳定编号 |
| 领域建模 | [GLOSSARY](../GLOSSARY.md) | 同一个词在论文与接口中表示什么？ | 中英文术语及必要概念区分 |
| 系统架构 | [架构设计](architecture.md) | 职责如何划分，控制和数据如何流动？ | 模块、依赖、部署与关键取舍 |
| 详细设计 | [详细设计](detailed-design.md)、[接口契约](plugin-contracts.md) | 每条流程具体怎样执行？ | 时序、输入输出、不变量与错误处理 |
| 科研评测 | [评测协议](evaluation.md) | 怎样比较方法，结论依赖什么证据？ | 样本、指标、预算、复现与诊断 |
| 开发与验证 | [开发计划](implementation-plan.md)、[验收清单](acceptance.md) | 按什么顺序实现，怎样确认完成？ | 纵向切片与需求追踪 |
| 决策维护 | [决策记录](decisions-and-open-questions.md)、[ADR](adr/0001-dual-artifact-paths.md) | 为什么选择当前设计？ | 已确认目标、工程默认值、待验证事项 |

建议先读需求分析与研究综述，再读需求规格、架构和详细设计。开发某个模块时同时读其接口契约与验收场景。

## 2. 文档责任与变更规则

产品范围以需求规格为准；数据对象与接口以插件契约为准；指标语义以评测协议为准。其他文档解释这些约定，不重新定义同一字段。出现冲突时记录并修正，不能借文档优先级掩盖冲突。

文档修订号与接口、IR、配置、评测协议版本分别管理。当前文档修订号为 0.4.0；核心对象／配置／Manifest 草案为 0.2.0，GroundedLPIR 为 0.1.0，评测协议为 v0.1。增加说明不代表平台发行或已通过验收。

变更链为：用户目标／新证据 → 需求分析 → FR/NFR → 架构／契约／详细设计 → 示例与验收 → 实现与真实验证。常规实现选择可以直接进行。改变问题类型、方法行为或评测口径时，必须更新这条链中受到影响的内容。

## 3. 领域表述与实现表述

研究说明优先使用自动优化建模（automated optimization modeling）、表述阶段（Formulation）、代码阶段（Code）、数学表述（mathematical formulation）、模型表示（model representation）、数据绑定（data binding）、求解反馈（solver feedback）和基准评测（benchmark evaluation）。

接口文档再将这些概念映射为 `ModelingMethod`、`ModelArtifact`、`ModelBackend`、`SolverBackend` 等对象。Registry、Worker、namespace 等词只用于解释实现机制，不用它们替代领域问题。

“软件接口抽象”与“参数化优化模型”分开表达。数学模型的 abstract/concrete 区分见 [GLOSSARY](../GLOSSARY.md)；论文、代码与数据引用见参考资料。文档中的研究结论必须有来源，平台设计选择则明确写为本项目选择。

## 4. 按任务读取与维护

| 任务 | 下一份文档 | 完成证据 |
|---|---|---|
| 单问题与方法策略 | [DD-01/02](design/modeling-methods.md) | 公共运行入口、五元素、Code 实现、阶段来源与选择理由 |
| 插件、表示、数据和求解 | [DD-03/04/05](design/execution.md) | 兼容路径、绑定、真实状态与结果 |
| 实验、恢复与界面 | [DD-06/07/08](design/experiments-and-interfaces.md) | 冻结 manifest、恢复记录、同一应用入口 |
| 技能与工作项 | [贡献流程](../CONTRIBUTING.md)、[任务路由](agents/workflow.md) | 规格、纵向切片、阻塞项与 review |
| 全仓库维护 | [规范](../CODING_STANDARDS.md)、[整理记录](repository-audit.md) | 当前可执行检查与逐文件覆盖 |

参考资料的元数据和注释在 catalog 维护，资料页与 BibTeX 生成。正文综述负责比较机制与设计依据；检索记录负责出处与读取限制；源码记录负责固定提交观察。

S06-A 微型真实 Gurobi／native 路径与限制见 [实现记录](development/s06-gurobi.md)。

S07-B/C 的固定数据格式与参考可用性见 [来源考察](development/s07-benchmark-research.md)；此记录不是已集成声明。

S06-B 的固定上游行为见 [OptiMUS 源码研究](development/s06b-optimus-source.md)；开发实现、本机 reference tape 及剩余真实验收见 [实现记录](development/s06b-optimus.md)。

S06-C 的固定角色路由、反思与原生函数输出见 [CoE 源码研究](development/s06c-coe-source.md)；此记录不宣称方法已经接入。

S05-B 的协议与现有服务可用性见 [Anthropic Messages 考察](development/s05b-anthropic-research.md)；实际 Provider 接入见 [S05-B](development/s05b-messages.md)。

MAMO 固定优化问题导入及数值比较的开发实现与实际证据见 [S07-C](development/s07-mamo.md)。

NLP4LP 的公开描述／具体 JSON 参数与私有参考分离、实际来源和验收见 [S07-B](development/s07-nlp4lp.md)。

原问题独立解检查、参考质量与有限反例探测见 [S07-D](development/s07-checkers.md)。

CoE流程与真实模型、独立原问题检查的开发证据见 [S06-C](development/s06-coe.md)。

角色模型覆盖／共享资源与实际支持见 [S05-D1](development/s05-role-models.md)。

公共候选评估、修正来源链和执行复用见 [S05-C1](development/s05-public-candidates.md)。

有界反馈修正方法、数学变化与 Code-only 来源复用见 [S05-C2](development/s05-feedback-repair.md)。

澄清、确认／修订分离及不可变派生运行见 [S05-D2](development/s05-clarification.md)。

独立文本Provider的注册、预检、实际协议与身份恢复见 [S03-C1](development/s03-provider-registry.md)。

Task／Evaluator的共同注册、评分身份与导入密封见 [S03-C2](development/s03-task-registry.md)。

独立Compiler的共同注册、Worker包预检与源码／映射身份见 [S03-C3a](development/s03-compiler-registry.md)。

Backend／Solver共同注册的开发状态与实际路径见 [S03-C3b](development/s03-solver-registry.md)。

DataLoader的共同注册、原始数据与有限视图分别记录，见 [S03-C4](development/s03-data-loader.md)。

本地单问题工作台的功能、启动命令与真实运行见 [S09-A](development/s09-web.md)。

批量冻结任务、实验矩阵、继续执行与公共报告见 [S08](development/s08-benchmark.md)。

网页批量提交、进度、逐样本比较与公共导出见 [S09-B](development/s09-batch-web.md)。

人工辅助修订、父历史和编辑预算见 [S09-C](development/s09-assisted-edits.md)。

三方法共同公开输入与接入比较见[S08-B](development/s08-common-input.md)。

Web同时运行、应用进程隔离与合作取消见[S09](development/s09-process-isolation.md)。

本机1000任务性能与100任务故障证据见[S08-C](development/s08-load-acceptance.md)。

Reporter的注册、四格式呈现与公开结果重试见[S03](development/s03-reporters.md)。
