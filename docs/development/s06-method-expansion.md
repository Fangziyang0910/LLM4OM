# 自然语言方法与可组合求解器

日期：2026-10-14。当前范围是本机后端、Web和LP/MILP。接口由[插件契约](../plugin-contracts.md)维护；架构选择见[独立配置](../adr/0003-independent-plugin-axes.md)。本文记录当前方法编排、来源与验收。

## 目标与输入

用户输入自然语言描述，可选上传业务数据，独立选择方法、LLM与求解器。研究方法集成其核心编排和阶段提示思路，论文的原始代码API不成为平台限制。完整论文复现不属于当前交付目标。

Web显示OptiMUS、CoE、OptiTree、OR-LLM-Agent、AutoFormulation五个研究方法。Direct与Feedback Repair是单次生成与公开反馈修正两个项目基线。OptiMUS不要求额外params／labels文件；已有两个显式公开数据ID和optimus_inline插件ID仍可使用。CoE可读取已有公开输入契约，最终实现遵循平台的模型工厂契约。

## 实际支持

| 方法／产物 | HiGHS | Gurobi | OR-Tools／SCIP |
|---|---|---|---|
| Direct、Feedback Repair：严格LPIR／Pyomo工厂 | 支持 | 支持 | 支持 |
| AutoFormulation：严格LPIR | 支持 | 支持 | 支持 |
| OptiMUS、CoE、OptiTree、OR-LLM-Agent：Pyomo工厂 | 支持 | 支持 | 支持 |
| 四个提示流程：可选gurobipy工厂 | — | 支持 | — |

默认使用已有Pyomo Backend，三个Solver读取它的受支持模型。OR-Tools使用可信MPSolver／SCIP求解LP/MILP，保留常数项、变量界和目标方向。Gurobi也可使用原生gurobipy Backend。当前未接入CP-SAT、路由、非线性或原生OR-Tools代码Backend。

Backend在Manifest.capabilities.code_generation中声明representation_kind与instruction。应用把已预检的Backend、Solver身份和后端要求作为MethodContext.code_target提供给方法。共享代码提示将这些要求与方法的阶段提示组合；方法没有按Solver ID编写分支。选择gurobipy时提示要求构建Gurobi变量，选择Pyomo时要求构建Pyomo变量。生成代码只构建模型，平台使用所选Solver求解。

复用FactoryCodeProposal、ModelHandle和候选assess／select路径，不增加执行器、转换服务或新方法profile。四个提示流程使用factory_candidates/0.1.0与native_formulation；代码修复保留原数学表述并记录父候选。每次评估占一个Solver slot，最终选择复用已有结果。不可行或无界属于Solver结果，不因缺少数值答案自动触发代码修复。所有预算、截止时间和隔离规则沿用已有资源接口。

## 方法的编排与提示

| 方法 | 保留的核心编排与提示思路 |
|---|---|
| OptiMUS | 提取参数、识别目标、提取并核对约束；逐条约束建模并维护变量和辅助约束；形成目标数学表述；代码组装与公开执行错误修复 |
| CoE | 协调者动态选择专家；专家共享评论；reducer形成最终数学模型与代码；失败时按反向专家顺序定位原因，把修订评论带入下一轮 |
| OptiTree | 逐层匹配问题类型；检索最具体匹配节点的建模思路；按实际数据实例化数学模型与目标代码；公开反馈调试 |
| OR-LLM-Agent | 独立数学建模代理先完成模型；代码代理落实所选目标；有界执行错误调试 |
| AutoFormulation | 参数、决策变量、目标、等式与不等式五层MCTS；假设生成与自评；UCT选择、奖励回传、严格LPIR等价剪枝与公开求解评估 |

各方法独立编写阶段提示，保留来源中的任务划分、角色职责和关键约束。共享部分仅是公开输入、调用记录、目标代码契约、候选执行与修复。方法仍独立决定流程、搜索和选择。

## 固定来源与适配

- OptiMUS：[仓库](https://github.com/teshnizi/OptiMUS)，提交e182e9ef5841605c2a7e87467021fd83522b6484。当前变体optimus-clause_math-configured_code/0.2.0。固定源文件保留用于提示与流程考察，不再启动源码子进程或执行固定main忠实度对照。公开参数改为默认从描述提取；去重与覆盖核对放入约束提取提示，代码按配置生成。
- CoE：考察提交afb89bf602690ea621f13a23c42722f20f653a43，当前变体coe-expert_reduce-public_reflection-configured_code/0.2.0。保留七类专家、动态路由、reducer与反向归因；使用真实候选执行反馈，移除prob_*调用驱动和额外生成测试参数。reducer显式提供数学表述；失败修订会进入下一轮，耗尽后不会声称成功。
- OptiTree：[仓库](https://github.com/MIRALab-USTC/OptiTree)，提交2e70ecfd0a3c8e9c0c16d36d7d498a7344cfdec9。当前变体optitree-fixed_ds_tree-configured_code/0.2.0。固定DeepSeek思路树包含320个节点，保留原字节、MIT许可与hash。提示只投影problem_type、description、reason_flow，不读取已解训练例或进行树训练。所选代码目标覆盖模板中的原API。
- OR-LLM-Agent：[仓库](https://github.com/bwz96sco/or_llm_agent)，提交5dccdaab89ab91c3cb28066fe849423dc124d287。当前变体or_llm_agent-configured_math-code-debug/0.2.0。保留数学模型、代码、调试三阶段；采用一层有界调试，使用配置模型与Backend／Solver。
- AutoFormulation：[仓库](https://github.com/jumpynitro/AutoFormulator)，提交52148018d04de23dc2d36d4281eb6244c2a42ffc，论文为[ICML 2025 Autoformulation](https://proceedings.mlr.press/v267/astorga25a.html)。当前变体autoformulation-bounded_mcts-grounded_lpir-smt/0.1.0。五阶段MCTS与语义奖励保持独立；完整数值LPIR用Z3证明等价才剪枝，不执行LLM生成的符号Python。未知等价结果保留，无效叶子记诊断和零奖励后继续搜索。

每次运行保存源提交、变体、阶段回复、提示hash、实际模型调用、目标Backend／Solver、候选与反馈。四个提示流程未提供内部续跑checkpoint；已完成结果可恢复，不重复LLM或Solver工作。原生脚本资源仍用于已有人工修订路径。

## 依赖与验收

```bash
uv sync --locked --all-extras
uv run --locked --all-extras python scripts/build_worker_image.py
```

HiGHS使用highspy1.12.0，与OR-Tools9.15捆绑版本一致，避免同一进程的原生符号冲突。依据见[上游问题](https://github.com/google/or-tools/issues/5246)与[OR-Tools9.15依赖](https://github.com/google/or-tools/releases/tag/v9.15)。两种库加载顺序均已真实求解。

2026-10-14公共SDK验收已通过七个自动方法×三个Solver的21个组合，以及四个提示流程×gurobipy／Gurobi的4个组合。使用确定性HTTP Provider与真实隔离Solver，每个组合得到手算目标13。默认路径每次候选仅一条Solver调用；OR-LLM-Agent执行错误修复后得到13，父候选、修复账本和已完成resume不重复求解均通过。工程fixture验证组合与流程。

此前扩展已完成真实官方DeepSeek调用：OR-LLM-Agent与OptiTree经原脚本路径、AutoFormulation经OR-Tools均得到13。该历史证据保留，但不作为当前新代码路径的验收。凭据和运行日志只保留在本机临时工作区，不提交版本控制。

当前代码路径的真实外部模型验收使用配置的官方DeepSeek／deepseek-flash，四个改动方法均完成并得到目标13：OptiMUS→Pyomo／HiGHS（8次请求，32673 tokens），CoE→Pyomo／OR-Tools（3次，15113 tokens），OptiTree→Pyomo／Gurobi（3次，5609 tokens），OR-LLM-Agent→gurobipy／Gurobi（2次，7000 tokens）。运行ID分别为d52abc813770479a95275e6d8e84d0de、db33b677862b4bd3b426097f371390c8、6693f46919d74983949f8b6ae8c7a46e、4f811e5462dd49fdac81657536a5d9a5。记录保存在本机临时验收工作区。

完整回归443项，442项通过；唯一失败是仍按原CoE脚本契约编写的安装插件夹具，该夹具更新为新工厂输出后复测通过。新增的12项阶段／恢复检查通过，涵盖Reviewer提示职责、合法不可行结果不触发代码修复，以及三种Solver的已完成执行崩溃恢复。故障注入重现并修复了OR-Tools恢复时误用HiGHS证据来源的问题。当前共有445个测试入口；新增两个边界检查包含在上述聚焦验收中。

mypy检查54个源码模块通过；345文件仓库检查、引用检查、前端构建通过。临时Web与实际8767页面均通过五个研究方法×三个Solver选择及数学表述展示。最终wheel／sdist构建、独立基础安装、34插件发现、离线运行通过；75个包内源码、固定资源和前端文件与工作区逐字节一致。两类Worker镜像已更新。实现代码净减少504行；未增加新执行层或依赖。本机Web已更新，五条运行和1262个历史文件保持原字节。
