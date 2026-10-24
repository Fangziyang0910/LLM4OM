CPMpy 用有限域整数、布尔和全局约束描述离散决策。数组表达适合人员、日期、机器和任务等索引结构，`AllDifferent`、`Element`、`Cumulative` 等约束可以直接表达常见规则。

## 全局约束怎样简化模型

三辆车分别服务三家门店，每家恰好一辆。可以让 `destination[i]` 表示车辆 i 的门店编号，用一条 `AllDifferent(destination)` 表达三辆车去不同门店。费用通过门店编号从各车的费用行中读取。

这是一个有限整数选择问题：变量域为0到2，每个值都有具体门店含义。CPMpy 将这些表达交给原生后端进行约束求解。

## 完整指派模型

```python
import cpmpy as cp

def build_model(data):
    cost = cp.cpm_array([[4, 8, 6], [7, 3, 9], [5, 6, 2]])
    destination = cp.intvar(0, 2, shape=3, name="destination")
    model = cp.Model(cp.AllDifferent(destination))
    model.minimize(sum(cost[i, destination[i]] for i in range(3)))
    return model
```

默认使用 OR-Tools CP-SAT。最优为车辆0→门店0、车辆1→门店1、车辆2→门店2，费用为 `4+3+2=9`。在模型中加入 `destination[1] != 1` 后，最优费用为17。

## 表达、编译与计算

```mermaid
flowchart LR
  Rules["整数域、逻辑、全局约束"] --> Model["CPMpy Model"]
  Model --> Native["原生后端转换"]
  Native --> Solver["CP / SAT / SMT / MIP 等路径"]
  Solver --> Result["变量赋值与状态"]
```

平台支持 `cp.Model` 和原生 SolverInterface。后端来自 `SolverLookup` 与已安装子求解器。默认 `ortools`；其他可用路径以运行设置显示为准。

## 常用规则写法

| 业务规则 | CPMpy 表达思路 |
|---|---|
| 任务分配到不同机器 | AllDifferent |
| 选择编号后读取相应费用 | 数组以变量索引，使用 Element 类表达 |
| A 成立时必须满足 B | `a.implies(b)` |
| 多任务共享容量 | Cumulative |
| 只需找到满足规则的方案 | 构建无目标的 Model |

每个整数变量需要有限上下界，布尔变量表达是否选择。数据中的工时或费用使用一致整数单位，可使逻辑与数量关系保持清晰。

## 冲突分析与结果使用

平台的 CPMpy 路径支持 MUS 冲突证据，可把互不相容的约束映射回业务要求。为规则保留清楚名称与索引，便于在[无解与冲突](../conflicts/)中阅读。

查看 `destination[0]` 等变量时，配合公式中的门店编号表解释其业务含义。完整变量可以导出；在对话中也可查询某辆车的选择或继续变更可用门店。

## 选型与官方资料

有限域、逻辑、互斥和全局约束较多时，可以从 CPMpy 开始。需要连续数量时可查看 [Pyomo](../pyomo/)；车辆路径接口见 [OR-Tools](../ortools/)。原生模型与后端见 [CPMpy 官方说明](https://cpmpy.readthedocs.io/en/latest/solvers.html)。
