CVXPY 用表达式与数学规则构造优化问题。它适合凸二次、锥优化等模型；平台也识别 DGP 和 DQCP 模式。

## 建模规则

通常用符合 DCP 规则的表达式建立模型。DGP 需要相应的正值与几何规划结构，DQCP 需要满足其准凸规则。平台根据返回的 `Problem` 判断模式，不靠忽略规则来强行求解。

常见表达包括 `sum_squares`、`norm`、`quad_form` 和矩阵乘法 `@`。不要对符号变量使用 Python 的 `if`、`max` 或依赖变量值的流程。

## 选择后端

AUTO 沿 CVXPY 原生 solver_path 尝试已安装的兼容后端，并记录实际引擎。显式指定后端失败时不替换。

| 后端示例 | 需要注意 |
|---|---|
| OSQP | 连续凸二次目标与线性约束，不处理其他锥或整数域 |
| Clarabel、SCS | 各自支持的连续锥模型 |
| MOSEK 等 | 依模型类型、安装和许可证检查能力 |

整数与布尔变量需要兼容的混合整数后端，不能通过选择 CVXPY 就默认交给连续求解器。

## 代码与结果

`build_model(data)` 返回 `cvxpy.Problem`，平台负责实际求解。结果保留原生状态与数值精度含义。当前平台不为 CVXPY 提供 IIS/MUS 冲突解释。

## 官方资料

参阅 [CVXPY 后端说明](https://www.cvxpy.org/tutorial/solvers/)、[DGP](https://www.cvxpy.org/tutorial/dgp/)和[DQCP](https://www.cvxpy.org/tutorial/dqcp/)。是否可执行以当前沙箱的后端列表和实际求解为准。
