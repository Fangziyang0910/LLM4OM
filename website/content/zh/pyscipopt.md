PySCIPOpt 直接使用 SCIP 的原生模型，支持线性、整数以及非线性约束。它适合需要在同一个模型中组织离散决策与原生非线性表达的任务。

## 非线性目标怎样表达

当前原生接口使用线性目标。可引入辅助变量 t，把待最小化的非线性成本放到约束中：`cost(x)≤t`，再最小化 t。这种 epigraph 形式保留目标含义，也让模型符合接口。

下面用连续分配案例：最小化到目标 `(1,2)` 的平方距离，总资源为2。辅助变量 `loss` 对应目标成本。

## 完整原生模型

```python
from pyscipopt import Model

def build_model(data):
    model = Model("allocation")
    x = model.addVar(name="x", lb=0, vtype="C")
    y = model.addVar(name="y", lb=0, vtype="C")
    loss = model.addVar(name="loss", lb=0, vtype="C")
    model.addCons(x + y <= 2, name="resource")
    model.addCons((x-1)**2 + (y-2)**2 <= loss, name="loss_definition")
    model.setObjective(loss, "minimize")
    return model
```

平台使用 SCIP 求解，应得到接近 x=0.5、y=1.5、loss=0.5 的数值。误差按求解容差阅读。代码返回 Model，求解由平台完成。

## 辅助变量如何进入求解

```mermaid
flowchart LR
  Cost["非线性成本表达式"] --> Link["cost ≤ loss"]
  Link --> Obj["线性目标：min loss"]
  Obj --> SCIP["SCIP 原生模型求解"]
  SCIP --> Values["原决策与辅助变量"]
```

最大化收益时，对应的 hypograph 方向为 `t≤reward(x)`，再最大化t。目标方向决定辅助约束的方向，代码中应使用有业务意义的变量名。

## 变量、索引与矩阵

`vtype="C"` 表示连续，`"I"` 表示整数，`"B"` 表示二元。标量表达和矩阵接口最终都返回 `pyscipopt.Model`。数据可从完整附件解析，再按产品、时间或网络索引建立变量。

对离散和非线性混合问题，选择支持该问题范围的建模方法；实际运行设置记录库、后端与方法，便于回看完整组合。

## 结果阅读与后续操作

结果中辅助变量也属于模型的一部分。可导出全部变量，并在公式中说明哪些是业务决策、哪些是成本或逻辑辅助量。调整资源或固定某些离散决策后，通过[调整条件](../revisions/)建立新方案比较。

同一个连续二次案例的几何解释和操作演示见 [CVXPY](../cvxpy/)。原生 API 与矩阵建模见 [PySCIPOpt Model](https://pyscipopt.readthedocs.io/en/stable/api/model.html)和[矩阵教程](https://pyscipopt.readthedocs.io/en/stable/tutorials/matrix.html)。
