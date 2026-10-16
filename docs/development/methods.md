# 建模方法

方法负责组织推理、生成、修正和选择。LLM 提供生成能力；建模后端构建模型；求解器执行数值优化。这些职责分别配置，字段见[方法契约](../contracts/methods.md)。

## 编排与代码目标

平台将已预检的建模后端、求解器和代码要求放入 `MethodContext.code_target`。生成代码的路径将共享代码提示与各方法的阶段提示组合，要求生成对应的 `build_model(data)` 工厂。工厂只构建模型，平台校验后调用所选求解器。严格 IR 路径由方法生成数值模型，再调用确定性编译器，不要求 LLM 生成工厂代码。

四个研究提示流程使用 `factory_checked/0.2.0`，保留 `native_formulation` 和生成代码。AutoFormulation 使用 `grounded_checked/0.2.0`，输出五元素表述和严格 LPIR。Direct 与 Feedback Repair 的配置必须显式给出 `output_mode`，可选 `lp_ir/python_factory/native_gurobipy`。Web 预设使用 `lp_ir`，其他模式按能力声明选择对应的单次或公开检查流程。

| 方法 | 当前编排 | 适配要点 |
|---|---|---|
| Direct | 联合生成五元素与严格 IR，或生成模型工厂 | 项目基线，一次生成后执行 |
| Feedback Repair | 生成、公开检查、有界修正、最终选择 | 支持澄清；代码修正可以复用原表述 |
| OptiMUS | 提取参数、目标和约束，逐条建模，组装与调试代码 | 从描述提取参数；`params_data_id/labels_data_id` 为可选公开输入 |
| CoE | 动态专家路由、共享评论、reducer 汇总、反向归因 | 汇总器提供表述与代码；修订意见进入下一轮 |
| OptiTree | 逐层匹配类型树，读取建模思路，实例化与调试 | 使用固定树的公开思路，不读取已解训练例 |
| OR-LLM-Agent | 数学建模、目标代码生成、有界调试 | 模型与代码角色分开，执行反馈进入调试 |
| AutoFormulation | 五层 MCTS、自评、UCT 选择、奖励回传和公开检查 | 用 Z3 证明完整数值 LPIR 等价后才剪枝；未知结果保留 |

完整兼容组合见 [README](../../README.md#求解器)。原生代码的后端限制仍由能力预检确定。

## 固定来源与变体

| 方法 | 上游固定提交 | 本项目变体 |
|---|---|---|
| OptiMUS | [e182e9e](https://github.com/teshnizi/OptiMUS/tree/e182e9ef5841605c2a7e87467021fd83522b6484) | `optimus-clause_math-configured_code/0.2.0` |
| CoE | [afb89bf](https://github.com/xzymustbexzy/Chain-of-Experts/tree/afb89bf602690ea621f13a23c42722f20f653a43) | `coe-expert_reduce-public_reflection-configured_code/0.2.0` |
| OptiTree | [2e70ecf](https://github.com/MIRALab-USTC/OptiTree/tree/2e70ecfd0a3c8e9c0c16d36d7d498a7344cfdec9) | `optitree-fixed_ds_tree-configured_code/0.2.0` |
| OR-LLM-Agent | [5dccdaa](https://github.com/bwz96sco/or_llm_agent/tree/5dccdaab89ab91c3cb28066fe849423dc124d287) | `or_llm_agent-configured_math-code-debug/0.2.0` |
| AutoFormulation | [5214801](https://github.com/jumpynitro/AutoFormulator/tree/52148018d04de23dc2d36d4281eb6244c2a42ffc) | `autoformulation-bounded_mcts-grounded_lpir-smt/0.1.0` |

这些实现保留核心编排和阶段提示思路，并使用配置的通用 LLM。它们没有复现论文的完整训练、数据或运行条件。AutoFormulation 的论文来源为 [ICML 2025](https://proceedings.mlr.press/v267/astorga25a.html)。

OptiMUS 不再启动固定上游 `main` 做忠实度对照。约束去重和覆盖核对由提取提示完成。`optimus_inline` 保留为同一自然语言流程的别名。

CoE 使用独立编写的提示。固定源码未提供可确认的顶层许可，平台没有复制其实现。当前流程保留七类专家、动态路由和反向归因，移除了 `prob_*` 函数驱动及额外测试参数生成。

OptiTree 固定树包含 320 个节点，保留原字节、MIT 许可和哈希。提示只投影 `problem_type`、`description` 和 `reason_flow`。配置的代码目标覆盖原思路中的 API 要求。

## 公开检查与修正

方法通过 `resources.check` 请求平台构建、执行和求解，再用 `resources.select` 保存最终选择。每次检查使用共享预算；最终选择复用已保存结果，不再求解一次。

代码修正保留原数学表述引用，记录父检查和原因。数学修正生成新的表述。四个研究提示流程将合法的不可行或无界结果视为求解结论，不因没有数值答案而自动触发代码调试。

Feedback Repair 在缺少可行解时仍可继续修正，直到预算或流程结束。最终优先选择合法且具有可信可行解的检查结果，再比较阶段完整性和顺序。它不比较不同模型的自报目标，也不访问隐藏答案。解码失败与传输失败分别记账。

五个研究方法均未声明内部续跑检查点。已完成阶段和结果由核心恢复；未完成推理需要显式派生重跑。验证入口见[测试指南](testing.md)，实际接入证据见[支持验证](validation.md)。
