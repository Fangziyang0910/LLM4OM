# 代表性系统的源码考察

考察日期：2026-10-08。以下提交用于复查本次观察，不是平台已经集成或通过真实测试的声明。源码仅在临时目录读取，未将上游实现或数据复制进本仓库。

## 1. 固定考察提交与范围

| 项目 | 固定提交 | 实际读取 |
|---|---|---|
| LLM4AD | `ffb6acf64497be93932c98d25369352efd3865cf` | README、LICENSE、base/sample.py、base/evaluate.py、method/eoh/eoh.py |
| OptiMUS main | `59e8d99653459b40361f618eafdc91eee3a85ebb` | README、LICENSE、main.py、execute_code.py；分支列表 |
| OptiMUS optimus-v0.3 | `e182e9ef5841605c2a7e87467021fd83522b6484` | 文件树、main.py、execute_code.py、parameters.py |
| ORPilot | `d153a680aaecd3f90e8466f77259bd8275bd6216` | README、LICENSE、workflow/graph.py、models/ir.py、codegen/ir_compiler.py、solver/base.py、solver/registry.py |
| Chain-of-Experts | `afb89bf602690ea621f13a23c42722f20f653a43` | README、文件树、conductor.py、evaluator.py、run_exp.py；本轮补读 main.py、experts/programming_expert.py |

使用 `git clone --depth=1 --filter=blob:none --no-checkout` 获取提交与目录，再按文件选择读取。没有安装依赖、运行方法、加载检索数据库或执行生成代码。本表不是完整代码审计；数据目录名称可观察，未据此确认全部样本内容。

## 2. LLM4AD：小接口承载方法差异

[LLM 接口源码](https://github.com/Optima-CityU/LLM4AD/blob/ffb6acf64497be93932c98d25369352efd3865cf/llm4ad/base/sample.py)提供 `LLM.draw_sample`／`draw_samples`；[评估接口](https://github.com/Optima-CityU/LLM4AD/blob/ffb6acf64497be93932c98d25369352efd3865cf/llm4ad/base/evaluate.py)包含 `Evaluation.evaluate_program`；[EoH](https://github.com/Optima-CityU/LLM4AD/blob/ffb6acf64497be93932c98d25369352efd3865cf/llm4ad/method/eoh/eoh.py)在方法内部组织采样、评估和种群操作。

本项目借鉴“方法内部复杂、对外入口小”的接口形式。LLM4OM 需要在此之外明确优化模型表示、数据绑定、后端构建、求解状态和独立评测。LLM4AD 的算法分数接口不能直接替代这些对象。本次没有测试其评估隔离效果。

## 3. OptiMUS：论文与版本分支分别锁定

[README](https://github.com/teshnizi/OptiMUS/blob/59e8d99653459b40361f618eafdc91eee3a85ebb/README.md)列出 0.1、0.2、0.3 三篇工作。实际分支有 `optimus-v0.1`、`optimus-v0.2` 和 `optimus-v0.3`，不能只用 main 的 README 推断方法版本。

[0.3 的 main.py](https://github.com/teshnizi/OptiMUS/blob/e182e9ef5841605c2a7e87467021fd83522b6484/main.py)、[执行与调试入口](https://github.com/teshnizi/OptiMUS/blob/e182e9ef5841605c2a7e87467021fd83522b6484/execute_code.py)和参数处理文件被读取；该分支还包含检索数据库与状态处理文件，未加载数据库或做运行验证。

首批 `optimus` 流程适配优先以 0.3 为考察对象。正式接入必须记录对应论文版本、分支、源码提交、检索材料、提示、角色模型、预算与执行修改。若只有改变策略后才能通过共同资源接口运行，使用 variant ID。0.2 的论文结果不归到 0.3 适配器名下。

## 4. ORPilot：可用 IR 不等于默认 IR 路径

[工作流源码](https://github.com/GuangruiXieVT/ORPilot/blob/d153a680aaecd3f90e8466f77259bd8275bd6216/orpilot/workflow/graph.py)写明并构建默认流程：interview → data_collection → param_computation → direct_code_gen → solver_runner → reporter。IR 由可选的 `ir_builder_on_demand` 节点生成。

[IRCompiler.compile](https://github.com/GuangruiXieVT/ORPilot/blob/d153a680aaecd3f90e8466f77259bd8275bd6216/orpilot/codegen/ir_compiler.py)确实具有多目标框架的代码生成分支。因此，准确观察是“该提交有确定性 IR 编译能力，但默认工作流为直接代码生成，IR 可以按需构建”。它不能被简化成所有输入都首先经过 IR 的系统。

[BaseSolver](https://github.com/GuangruiXieVT/ORPilot/blob/d153a680aaecd3f90e8466f77259bd8275bd6216/orpilot/solver/base.py)接收代码和数据；其后端命名覆盖 Pyomo/PuLP 等建模框架。LLM4OM 适配时分别记录建模语言与实际数值求解器。将 ORPilot 整体作为方法适配，其工作流与参数计算留在方法内；平台核心不依赖 LangGraph。以上为接口和流程观察，没有验证各编译分支的正确性。

## 5. Chain-of-Experts：首批专家流程与隐藏评分

[Conductor](https://github.com/xzymustbexzy/Chain-of-Experts/blob/afb89bf602690ea621f13a23c42722f20f653a43/conductor.py)选择参与专家；[Evaluator](https://github.com/xzymustbexzy/Chain-of-Experts/blob/afb89bf602690ea621f13a23c42722f20f653a43/evaluator.py)生成测试输入并检查生成程序的语法／运行异常。这个方法角色与平台的私有 benchmark Evaluator 不同。

[main.py](https://github.com/xzymustbexzy/Chain-of-Experts/blob/afb89bf602690ea621f13a23c42722f20f653a43/main.py)实际组合专家、Conductor 和 Reducer，返回提取代码；LPFileGenerator 在该入口的专家列表中被注释。[ProgrammingExpert](https://github.com/xzymustbexzy/Chain-of-Experts/blob/afb89bf602690ea621f13a23c42722f20f653a43/experts/programming_expert.py)提示明确 LP/MIP，提及 Gurobi，并读取 description／code_example。入口与提示存在不等于生成代码已经通过真实后端验收。

本版 CoE 作为首批方法，主要使用通用外部 LLM。专家路由、协作与反思保留，真实 Formulation／Code 产出分别记录；未能提取的数学表述不补造五元素。

其 `forward` 读取 `problem['description']` 和 `problem['code_example']`。正式接入必须核对每个来源中 code_example 的角色：通用公开示例可以保留；含参考表述或答案的材料必须进入私有评测侧。若改变输入会改变原方法条件，记录为变体，而非声称完全忠实复现。

README 描述的 ComplexOR 发布状态与论文规模不同，平台导入以实际版本和可读取内容为准。本次未运行基准或确认全量题目。

## 6. 接入工作与许可证记录

| 项目 | 本次可观察的许可材料 | 接入时仍需完成 |
|---|---|---|
| LLM4AD | 固定提交的 LICENSE | 按原文本核对适用条款，不能将平台思路借鉴等同于源码复制许可 |
| OptiMUS | main 中的 MIT LICENSE；README 另列 NLP4LP 的研究用途限制 | 代码、数据、检索材料分别核对 |
| ORPilot | 固定提交中的 MIT LICENSE | 检查新增依赖与 benchmark 来源 |
| Chain-of-Experts | 本次文件树未见顶层 LICENSE | 复制或分发实现前明确授权；不影响文献研究与接口设计 |

本次源码考察说明接口形态与适配问题。正式 `verified` 状态仍需真实 Provider/Solver、上游对照、公开输入与私有材料分离、产物提取和预算记录的验收。
