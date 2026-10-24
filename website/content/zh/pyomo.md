Pyomo 适合用接近数学公式的方式表达优化模型。产品、工厂、日期等集合可以成为索引，目标和约束围绕这些索引组织，便于将业务规则与代码逐项对应。

## 先看数学模型

生产案例决定整件产量 A、B，最大化 `3A+2B`，满足切割 `2A+B≤8` 与装配 `A+2B≤8`。正确整数最优为 A=3、B=2、收益13。

若产品可以分割，只需在正确业务前提下改为连续域，但结果会变为 A=B=8/3、收益40/3。变量域本身就是业务规则的一部分。

## 完整平台代码

```python
import pyomo.environ as pyo

def build_model(data):
    model = pyo.ConcreteModel()
    model.products = pyo.Set(initialize=["A", "B"])
    profit = {"A": 3, "B": 2}
    model.x = pyo.Var(model.products, domain=pyo.NonNegativeIntegers)
    model.profit = pyo.Objective(
        expr=sum(profit[p] * model.x[p] for p in model.products),
        sense=pyo.maximize,
    )
    model.cutting = pyo.Constraint(expr=2*model.x["A"] + model.x["B"] <= 8)
    model.finishing = pyo.Constraint(expr=model.x["A"] + 2*model.x["B"] <= 8)
    return model
```

这里没有 `solve()`。平台拿到模型后选择后端、求解并读取命名变量。附件版可通过 `json.loads(data['production.json'])` 读取完整参数，再建立相同结构，见 [BIND](../bind/)。

## 从表达式到求解

```mermaid
flowchart LR
  Sets["集合、参数与变量域"] --> Expressions["目标与约束表达式"]
  Expressions --> Model["Pyomo 原生模型"]
  Model --> Backend["兼容后端：如 HiGHS"]
  Backend --> Values["命名变量与求解状态"]
```

Pyomo 通过原生适配器连接兼容后端。平台支持 ConcreteModel、实例化后的 AbstractModel 和 Kernel。代数模型通常默认 HiGHS，Kernel 默认使用兼容的 CBC。

## 常见表达错误

不要在构建时用 `pyo.value(x)` 判断未知变量，也不要写 `if x > 0` 来决定是否添加约束。应使用二元变量、指示逻辑或适合的数学改写。否则会把决策过程提前当成已知数值。

逐索引约束要检查索引集合；需要跳过某个索引时使用 `pyo.Constraint.Skip`。AbstractModel 必须先实例化，不能返回尚未绑定数据的抽象模板。

## 怎样核对结果

查看 `x[A]`、`x[B]`，代回两条资源约束，检查利润与单位。再确认实际后端与整数域。若显式选了不兼容引擎，平台保留错误，不为得到数值而替换成连续模型。

```demo
production
```

## 选型与资料

规则适合代数与索引表达、希望保持数学结构清楚时，可从 Pyomo 开始。纯线性小模型也可用 [PuLP](../pulp/)；逻辑和全局约束较多时查看 [CPMpy](../cpmpy/)；光滑非线性可比较 [CasADi](../casadi/)。接口细节见 [Pyomo 官方建模文档](https://pyomo.readthedocs.io/en/stable/explanation/modeling/index.html)。
