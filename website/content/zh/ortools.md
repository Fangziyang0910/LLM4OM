OR-Tools 是包含多种原生求解接口的工具集。平台只提供一个 OR-Tools 建模库选项，具体接口由生成代码和所选后端确定。

## 支持的路径

| 接口 | 常见任务 |
|---|---|
| MPSolver、MathOpt、ModelBuilder | 线性、整数及各接口支持的数学规划 |
| CP-SAT / CpModel | 整数、布尔、逻辑与离散排程 |
| Routing | 车辆路径与访问顺序 |
| 原生 Constraint Solver | 约束与搜索模型 |
| 最大流、最小费用流、线性指派、背包 | 对应的图和组合优化问题 |

## 在平台中选择

选择 OR-Tools，后端列表按实际原生支持情况提供。比如 `CP_SAT` 对应 CP-SAT，`ROUTING` 对应 Routing，`HIGHS` 可以使用 MathOpt。默认 MPSolver 参考使用 SCIP。

CP-SAT 使用整数或布尔变量，不支持原样的连续决策。LP 后端遇到整数模型时，平台会报错，不让接口默默求解连续松弛。

## 原生模型的返回

普通数学模型返回其原生对象。Routing 还需 `RoutingIndexManager`；最大流还需 source/sink；原生 Constraint Solver 需要变量和可选目标；背包需要 values、weights、capacities。平台文档记录各返回结构，不需要另选“接口配置”。

## 结果与资料

Routing 的短时启发式解通常记为 `feasible`，只有原生状态证明最优时才记为 `optimal`。图算法和可满足性问题的目标语义也应按其原生结果阅读。

官方入口：[Python 指南](https://developers.google.com/optimization/introduction/python)、[CP-SAT](https://developers.google.com/optimization/cp/cp_example)、[Routing](https://developers.google.com/optimization/routing/vrp)和[MathOpt](https://developers.google.com/optimization/math_opt)。
