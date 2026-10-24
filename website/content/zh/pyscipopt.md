PySCIPOpt 是 SCIP 的原生 Python 接口。平台识别它返回的 Model，支持标量、表达式与矩阵写法。

## 适合的模型

SCIP 原生模型可以表达混合整数线性模型，以及其支持的非线性约束。与 OR-Tools 中的 SCIP 线性接口相比，直接使用 PySCIPOpt 可以表达更多 SCIP 原生结构。

这种表达能力仍受实际版本和模型类型限制。选择一个只支持 LP/MILP 的建模方法，不会因为使用 PySCIPOpt 就自动得到非线性建模流程。

## 在平台中选择

选择 PySCIPOpt，原生后端为 SCIP。它的 Model 不会切到任意其他引擎。代码定义 `build_model(data)` 并返回模型，不调用 `optimize()`。

## 非线性目标怎样表达

原生目标要求线性表达。非线性目标需要辅助变量和方向正确的 epigraph/hypograph 约束。例如最小化平方表达式时，可以用辅助变量承接该表达式上界，再最小化辅助变量。应核对这种转换是否保留原问题含义。

变量下界也要明确：允许负值的连续决策不能意外使用默认非负下界。求解状态与目标值由实际 SCIP 运行返回。

## 官方资料

参阅 [PySCIPOpt Model API](https://pyscipopt.readthedocs.io/en/stable/api/model.html)、[非线性表达式](https://pyscipopt.readthedocs.io/en/stable/tutorials/expressions.html)和[矩阵接口](https://pyscipopt.readthedocs.io/en/stable/tutorials/matrix.html)。
