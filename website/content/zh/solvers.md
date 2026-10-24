建模库负责表达数学模型，求解后端负责计算。先判断问题的变量与约束，再选择能表达并求解它们的组合。

## 九个建模库

| 建模库 | 常见用途 | 默认或原生引擎 |
|---|---|---|
| [Pyomo](../pyomo/) | 代数形式的线性、整数与其他优化模型 | 代数模型通常用 HiGHS；Kernel 默认 CBC |
| [gurobipy](../gurobipy/) | Gurobi 原生模型与矩阵建模 | Gurobi |
| [OR-Tools](../ortools/) | LP/MIP、CP-SAT、路径、网络流等 | 按原生接口选择 |
| [CPMpy](../cpmpy/) | 有限域整数、布尔和全局约束 | OR-Tools CP-SAT |
| [PuLP](../pulp/) | 线性与混合整数规划 | CBC |
| [CVXPY](../cvxpy/) | 凸优化、锥模型、DGP/DQCP | 按原生兼容路径选择 |
| [PySCIPOpt](../pyscipopt/) | SCIP 原生线性、整数、非线性约束 | SCIP |
| [CasADi](../casadi/) | 光滑非线性与插件支持的其他模型 | Opti NLP 默认 Ipopt |
| [coptpy](../coptpy/) | COPT 原生线性、整数、凸二次与锥模型 | COPT |

## 怎样选择组合

生产、运输等 LP/MILP 可以从 Pyomo 或 PuLP 的开放后端开始；离散排班和逻辑约束可考虑 CPMpy 或 OR-Tools CP-SAT；凸二次或锥模型可查看 CVXPY；光滑非线性可查看 CasADi。具体选择还取决于方法范围与安装环境。

选择 CPMpy 不会使连续决策变成合法整数决策。选择一个 LP 后端也不会放松整数域；平台会报告不兼容，而不是静默求解连续松弛。

## AUTO 与显式后端

AUTO 使用该库和模型的原生选择逻辑。运行设置列出当前沙箱中的后端及可用原因。显式选择后端后，失败不会自动替换成其他引擎；最终结果记录实际使用的求解器。

库内 API 由生成代码表达，平台识别原生模型。OR-Tools 的 MPSolver、MathOpt、CP-SAT 和 Routing 等不是四个额外的建模库选项。

## 代码如何交给平台

通常，代码定义 `build_model(data)`，构建并返回原生模型。平台负责求解，代码不直接调用 solve 或打印方案。Routing、网络流和部分 CasADi 接口还需返回管理器、源汇或数值参数，详见各库文章与[原生接口说明](https://github.com/Fangziyang0910/LLM4OM/blob/main/docs/references/modeling-libraries.md)。

后端列表中的名称、成功加载插件和具备可用商业许可是不同条件。安装与许可证见[求解后端](../backends/)。
