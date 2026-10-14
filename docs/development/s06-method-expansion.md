# 自然语言方法与 OR-Tools 扩展

日期：2026-10-14。当前交付范围是本机后端、Web和LP/MILP。接口由[插件契约](../plugin-contracts.md)维护，固定源码与方法差异在本记录中说明。

## 输入与工作台

用户输入自然语言描述，可选上传业务数据。OptiMUS主入口不再要求用户制作params／labels文件。已有参数化CLI配置仍可显式提供两个数据ID；原optimus_inline插件保留用于已有配置，Web只显示一个OptiMUS入口。

Web显示五个研究方法：OptiMUS、CoE、OptiTree、OR-LLM-Agent、AutoFormulation。Direct和Feedback Repair明确标为项目基线，分别用于单次生成和公开反馈修正，不作为论文方法计数。人工辅助修订继续独立标记。

## 实际支持

| 方法／产物 | HiGHS | Gurobi | OR-Tools／SCIP |
|---|---|---|---|
| 项目基线：严格LPIR／Pyomo工厂 | 支持 | 支持 | 支持 |
| AutoFormulation：严格LPIR | 支持 | 支持 | 支持 |
| OptiMUS、CoE、OptiTree、OR-LLM-Agent：原生gurobipy脚本 | — | 支持 | — |

OR-Tools通过现有Pyomo Backend接入可信MPSolver／SCIP，支持连续变量、整数变量和二元变量的LP/MILP。它保留常数项、变量界、约束方向和原始目标方向。结果记录OR-Tools版本与实际SCIP引擎、终止状态、原始决策值及请求选项。没有CP-SAT、路由或非线性支持声明；原生Gurobi代码不自动转换成OR-Tools代码。

安装完整本机开发依赖：

```bash
uv sync --locked --extra dev --extra solve --extra gurobi --extra ortools --extra search
uv run --locked --all-extras python scripts/build_worker_image.py
```

ortools extra包含OR-Tools；search extra包含AutoFormulation使用的Z3。Worker构建沿用原有脚本、镜像和隔离执行入口。

## 固定来源与适配差异

### OptiTree

来源：[官方仓库](https://github.com/MIRALab-USTC/OptiTree)，提交`2e70ecfd0a3c8e9c0c16d36d7d498a7344cfdec9`。阅读范围为template_retrieve.py中的final_template、template_reduce，以及template_opt.py中的reason和reason_run。

保留逐层类型匹配、终止于最具体可匹配节点、检索该节点的建模思路、实例化问题并按执行反馈调试的流程。固定官方DeepSeek思路树包含320个节点；原始文件、MIT许可和逐文件hash保留在optitree_source。

本平台独立编写提示词。提示只投影problem_type、description和reason_flow，不读取example_application中的已解训练样例。生成阶段要求显式返回该问题的数学表述和代码；原实现的自由文本／代码输出格式相应改变。树只读，不调用使用参考解的dynamic_adjustment训练流程。模型、预算、资源、代码收集与重试上限由平台配置，因此这是固定树的推理适配，不是论文性能复现。

### OR-LLM-Agent

来源：[官方仓库](https://github.com/bwz96sco/or_llm_agent)，提交`5dccdaab89ab91c3cb28066fe849423dc124d287`。阅读范围为or_llm_eval_async_resilient.py的async_generate_math_model、async_generate_and_run_gurobi_code、async_generate_or_code_solver和async_or_llm_agent。

启用数学建模→代码生成→公开执行错误调试三个阶段。保留原数学表述和各次代码／反馈，调试受方法上限与共享max_repairs双重约束。通过已有隔离Worker执行，独立Gurobi收集器重求解；不信任生成代码打印的目标值。

提示词独立编写，不复制上游代码。采用单一有界调试循环，未保留上游额外的“无数值答案／多次失败后再次反思”外层循环；不可行模型不会因缺少数值答案自动被改成可行模型。使用配置的外部模型而非固定论文模型。实际来源和差异写入每次运行的fidelity-report.json。

### AutoFormulation

来源：[AutoFormulator仓库](https://github.com/jumpynitro/AutoFormulator)，提交`52148018d04de23dc2d36d4281eb6244c2a42ffc`；论文为[ICML 2025 Autoformulation](https://proceedings.mlr.press/v267/astorga25a.html)。阅读范围为MCTS_used.py的五阶段定义、_select_prior、_uct_select、_back_propagate和rollout，以及utils_diff.py的等价过滤。

独立实现参数→决策变量→目标→等式约束→不等式约束五层搜索。每层分别调用假设生成器与自评器，按UCT选择路径；完整叶子转换成严格LPIR，经真实Solver评估，再用公共语义自评产生奖励并回传。保存完整搜索树、访问数、奖励、剪枝、候选和最终选择，不按不同候选的目标值大小排序。

相同部分假设按JSON内容去重。完整LPIR用Z3证明可行域和目标函数等价后才剪枝；未知结果保留两个候选。与上游不同，SMT剪枝位于完整数值LPIR层，不执行LLM生成的符号Python；变量ID／域必须相同，未实现变量重命名等价。提示、表示、默认分支数和rollout数改变；使用分数自评，未实现上游成对排序／Bradley–Terry选项。它是公开输入的有界MCTS变体，不是源码逐字复现。

## 验收

新增检查覆盖真实OR-Tools连续／整数模型、常数项、不可行与无界状态；自然语言OptiMUS；OR-LLM-Agent的分阶段调试；OptiTree的真实树检索及未知类型拒绝；AutoFormulation的不同分支、奖励回传、语义选择和SMT等价／非等价区分。

公共SDK集成测试使用确定性HTTP Provider和真实容器Solver，三种新增方法从自然语言描述生成、执行并保存结果。工程fixture不构成真实LLM效果或论文指标复现。2026-10-14，三个公共SDK集成用例全部通过：自然语言输入，无额外参数文件，真实Gurobi／OR-Tools均得到手算目标13。OR-LLM-Agent用例额外验证执行失败后修复与独立收集。

真实外部模型检查使用已配置的官方DeepSeek接口与deepseek-flash，三种方法均完成并得到目标13：OR-LLM-Agent为2次请求、8799 tokens；OptiTree为3次请求、6486 tokens；AutoFormulation为12次请求、25193 tokens（1个rollout）。对应run_id分别为57e66b509ff240098becb8631c68aaf9、9317b018fa6f410eabe586b47a864530、78ab79f239f5471d9b632c74f268b131。记录位于本机临时验收工作区，凭据、问题运行记录和模型原始日志不提交版本控制。

HiGHS与OR-Tools共存时使用highspy 1.12.0，与OR-Tools 9.15捆绑的HiGHS版本一致。原highspy 1.15.1会在同一进程导入OR-Tools时触发原生符号冲突；上游问题见[google/or-tools#5246](https://github.com/google/or-tools/issues/5246)，版本依据见[OR-Tools 9.15依赖说明](https://github.com/google/or-tools/releases/tag/v9.15)。已验证两种库加载顺序均能真实求解，未增加执行模块或平台适配层。

AutoFormulation的无效LPIR叶子通过公共候选评估记录诊断并取得零奖励；搜索继续探索其他分支，不因一个无效候选终止整次搜索。

最终回归共455项，454项通过；仅旧Executor用例依赖本机预装插件而失败。该用例现按其他插件测试的方式自行构建并安装临时夹具，SDK依赖范围同步至0.37，独立复测通过。求解器、库加载顺序和搜索失败分支的36项聚焦检查通过；mypy检查55个源码模块通过；Web起点、异步状态、模型展示和新增方法／求解兼容性检查通过。

最终wheel／sdist构建与独立基础安装通过，34个插件可发现，离线产物流程通过；wheel源码、固定资源及前端文件与工作区逐字节一致。两类Worker镜像已按兼容依赖构建。本机8767服务已更新，五条运行记录和1262个历史文件保持原字节；真实页面的研究方法选择、兼容性过滤和数学表述展示通过。
