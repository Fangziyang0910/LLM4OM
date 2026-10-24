PuLP 用简洁的代数表达式建立线性与混合整数规划模型。它适合用成本、数量和资源约束描述的 LP/MILP 问题。

## 支持的表达

平台识别 `LpProblem`，支持按行添加目标与约束，也支持使用 `LpConstraintVar` 的列式建模。这些写法属于同一个建模库。

变量可以是连续、整数或二元。约束和目标保持线性，不直接相乘两个决策变量。问题有非线性关系时，应选择相应的表达方式或其他库，而不是让代码忽略它。

## 在平台中选择

选择 PuLP，默认后端是 CBC，原生 ID 为 `PULP_CBC_CMD`。平台使用 PuLP 原生 listSolvers/getSolver，实际后端不限于 CBC；Python、命令行和动态库接口保留各自的 ID。

## 代码与检查

`build_model(data)` 返回 `LpProblem`，不直接调用 `solve()`。按行写法中，首先添加的无比较符表达式成为目标；约束名称应唯一，使用稳定的名称便于解释与核对。

检查整数类别、上下界、目标方向和参数单位。有效求解状态来自原生后端；依赖缺失、后端不兼容或许可错误会保留实际原因。

## 官方资料

参阅 [PuLP 建模 API](https://coin-or.github.io/pulp/technical/pulp.html)和[后端 API](https://coin-or.github.io/pulp/technical/solvers.html)。具体 API 以部署锁定的版本为准，升级依赖后需重新检查实际后端。
