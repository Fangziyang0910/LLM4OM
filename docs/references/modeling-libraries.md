# 建模库、官方接口与求解后端

本平台只有九个建模库选项。用户可指定原生后端，默认 AUTO；库内 API 由代码表达，平台识别返回的模型，不设接口选项。后端能力以安装版本的原生适配器为准，不把文档中的名称直接当成已经可执行的功能。

## 官方依据与接口范围

| 库 | 支持的原生 API | 官方依据 |
|---|---|---|
| Pyomo | Algebraic：ConcreteModel、实例化后的 AbstractModel；Kernel | [建模](https://pyomo.readthedocs.io/en/stable/explanation/modeling/index.html)、[Kernel](https://pyomo.readthedocs.io/en/stable/api/pyomo.kernel.html)、[求解接口](https://pyomo.readthedocs.io/en/stable/explanation/experimental/solvers.html) |
| gurobipy | 标量/表达式；矩阵；均返回 Model | [Python API](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/overview.html)、[MVar](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/mvar.html) |
| OR-Tools | MPSolver、MathOpt、CpModel、ModelBuilder、Routing、原生 Constraint Solver、最大流、最小费用流、线性指派、背包 | [Python 概览](https://developers.google.com/optimization/introduction/python)、[MathOpt](https://developers.google.com/optimization/math_opt)、[CP-SAT](https://developers.google.com/optimization/cp/cp_example)、[Routing](https://developers.google.com/optimization/routing/vrp)、[网络流](https://developers.google.com/optimization/flow/maxflow)、[背包](https://developers.google.com/optimization/pack/knapsack)、安装包的公开 Python 模块 |
| CPMpy | Model；直接 SolverInterface | [两种接口与后端](https://cpmpy.readthedocs.io/en/latest/solvers.html) |
| PuLP | 行式代数；列式 LpConstraintVar；均返回 LpProblem | [建模 API](https://coin-or.github.io/pulp/technical/pulp.html)、[后端 API](https://coin-or.github.io/pulp/technical/solvers.html) |
| CVXPY | DCP、DGP、DQCP；均返回 Problem | [后端与求解模式](https://www.cvxpy.org/tutorial/solvers/)、[DGP](https://www.cvxpy.org/tutorial/dgp/)、[DQCP](https://www.cvxpy.org/tutorial/dqcp/) |
| PySCIPOpt | 标量/表达式；矩阵；均返回 Model | [Model API](https://pyscipopt.readthedocs.io/en/stable/api/model.html)、[矩阵 API](https://pyscipopt.readthedocs.io/en/stable/tutorials/matrix.html) |
| CasADi | Opti NLP、Opti Conic、nlpsol、qpsol、conic | [官方文档](https://web.casadi.org/docs/)、[插件 API](https://web.casadi.org/python-api/) |
| coptpy | 标量/表达式；矩阵；均返回 Model | [Python 接口](https://guide.coap.online/copt/en-doc/pythoninterface.html) |

标量、矩阵或列式接口可以使用同一个原生模型类型；平台分别提供相应的代码参考，不另造数学表达语言。Pyomo 的 GDP、DAE 等模型组件仍属于其代数接口；Gurobi、SCIP 和 COPT 的原生约束与表达式仍在各自 Model 内使用。这些写法不需要单独的注册表或兼容矩阵。

## 原生后端发现

`GET /api/options` 只返回九个库。`GET /api/backends` 在实际 Sandbox 中读取一次原生注册表，按“库 → 后端”返回标识、可用状态和原因。服务进程缓存此结果；修改依赖或许可部署后重启服务。

- Pyomo：从 SolverFactory 读取执行引擎适配器，包括传统、APPSI、新接口与持久化变体。GDPopt、MindtPy 等分解算法与 SciPy 方程求根器不作为执行引擎列出。Kernel 自动使用支持其模型类型的默认后端 CBC；明确选择的插件按原生行为执行。
- CPMpy：从 SolverLookup 读取全部基础后端，并通过原生接口列出已安装的子求解器；包括 CP、SAT、SMT、MIP、MaxSAT 和知识编译器。`pysdd` 不提供原生 solve 时限，由沙箱外层时限负责停止。
- PuLP：使用 listSolvers/getSolver，不仅限于 CBC。Python、命令行与动态库接口分别保留原生标识。
- CVXPY：使用原生 SOLVERS 与 installed_solvers，显式传入所选后端。AUTO 使用 CVXPY 的 solver_path，依次尝试已安装的兼容后端，结果保存实际引擎。DGP 使用 gp=True，DQCP 使用 qcp=True。
- OR-Tools：MPSolver 使用 SupportsProblemType；MathOpt 使用 SolverType；ModelBuilder 使用 solver_is_supported。Routing、CP-SAT、Constraint Solver、图算法和背包使用各自原生入口及算法枚举。
- CasADi：从 CasadiMeta.plugins 读取 Nlpsol/Conic 插件，并在隔离子进程中调用 has_nlpsol/has_conic 检查加载。插件库可加载不表示其商业许可证已经验证；插件特定的配置仍由原生 API 解释。
- gurobipy、PySCIPOpt、coptpy 的原生 Model 分别使用 Gurobi、SCIP、COPT。它们拥有多个建模接口，不代表可以把任意其他引擎装到其 Model 后面。

明确选择的后端不自动替换。MPSolver 使用原生 protobuf 迁移到所选引擎，不走跨库的通用模型转换。LP 后端遇到整数模型直接报错，防止原生接口默默求解连续松弛。不是每一个后端都支持某个接口所能表达的全部问题；模型不兼容时保留原生错误并交给方法处理。

## build_model 返回约定

通常返回原生模型。以下入口还需要求解参数：

| 接口 | 返回 |
|---|---|
| OR-Tools Routing | `{"model": RoutingModel, "manager": RoutingIndexManager}` |
| OR-Tools Constraint Solver | `{"model": Solver, "variables": [IntVar, ...]}`；优化时另给 `objective: IntVar`、`sense: "min"/"max"`；可选原生 `search: DecisionBuilder` |
| OR-Tools 最大流 | `{"model": SimpleMaxFlow, "source": int, "sink": int}` |
| OR-Tools 最小费用流 | SimpleMinCostFlow；最大流优先时返回 `{"model": model, "maximize_flow": True}` |
| OR-Tools 背包 | `{"values": [...], "weights": [[...], ...], "capacities": [...]}`；Worker 创建所选原生 KnapsackSolver 并调用 init |
| CasADi nlpsol/qpsol/conic | `{"problem": 原生符号问题或稀疏结构, "arguments": 原生数值参数, "solver": 可选插件名, "options": 可选插件配置}`；结果按原生向量顺序使用 `x[i]` |
| CasADi Opti | Opti；Conic 模式返回 `{"model": opti, "solver": "qrqp"}`；可另带 options |

Routing 的短时启发式结果记为 feasible；只有原生状态证明最优时记为 optimal。NLP 的局部最优和局部不可行保留局部含义，不与全局证书混用。

## 请求、记录与旧数据

```python
state = run_problem(problem, language="ortools", solver="CP_SAT")
```

运行配置保存 language、solver；求解结果保存实际 solver。方法的 languages 声明库范围。旧 pywraplp 请求解析为 OR-Tools/SCIP，旧 cvxpy_osqp、cvxpy_scs、cvxpy_mosek 解析到同一个 CVXPY 库的对应后端。旧记录本身不迁移或改写。

## 安装与验证

Worker 11 安装多个开放后端、商业 Python SDK，以及 CBC、GLPK、MiniZinc 和 Java 运行时。官方接口可调用、插件已安装、商业许可可用是不同条件；缺少程序、驱动或许可证的条目保留不可用原因。GPU 和需单独部署的商业运行时不会因为出现在注册表中就被标为已经验证。

CVXPY 1.8 的 GLOP/PDLP 适配器要求 OR-Tools <9.15，而主 OR-Tools 9.15 与 HiGHS 1.12 的 ABI 需要保持匹配。因此 Worker 为这两个 CVXPY 后端单独安装 OR-Tools 9.14，仅对应进程使用它；不修改第三方版本检查。其余接口继续使用主版本。

`tests/test_modeling_interfaces.py` 与既有沙箱测试覆盖三十个入口的实际构建、求解和数值结果，同时验证旧标识解析、错误后端、整数域和启发式状态。确定性接口测试、真实 Docker 回归和真实 LLM 生成验证分别记录，不能相互代替。
