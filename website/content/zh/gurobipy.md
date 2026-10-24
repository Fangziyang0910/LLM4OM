gurobipy 直接构建 Gurobi 原生模型。它适合希望使用原生变量、约束、矩阵表达与求解诊断的工作流；实际求解需要部署环境中可用的 Gurobi 许可。

## 模型与引擎的关系

选择 gurobipy 就是在使用 Gurobi 的模型对象与原生引擎。标量表达和矩阵接口都属于同一个 `gp.Model`，可以按数据结构选择合适写法。

生产、运输、选址等 LP/MILP 是常见起点。其他原生二次、锥或更复杂表达应同时核对安装版本、求解器能力和所用方法的问题范围，不因选择 SDK 就假设所有组合都成立。

## 完整生产模型

```python
import gurobipy as gp
from gurobipy import GRB

def build_model(data):
    model = gp.Model("production")
    a = model.addVar(lb=0, vtype=GRB.INTEGER, name="A")
    b = model.addVar(lb=0, vtype=GRB.INTEGER, name="B")
    model.setObjective(3*a + 2*b, GRB.MAXIMIZE)
    model.addConstr(2*a + b <= 8, name="cutting")
    model.addConstr(a + 2*b <= 8, name="finishing")
    return model
```

代码不调用 `optimize()`。平台执行后应得到A=3、B=2、收益13。矩阵形式可以使用 `MVar`，但命名、维度和矩阵行列含义仍需保留。

## 查看与导出方案

结果页展示命名变量、目标值、求解状态和实际后端。上例可以直接核对 A、B 的产量；使用矩阵变量时，可通过索引名称阅读各分量，导出完整方案后继续做业务分析。

```demo
production
```

在交互例中调整容量与需求，可以查看条件变化后的生产方案。正式运行的过程、模型和结果会一并保存，便于复查和比较。

## 无解时怎样利用 IIS

在案例中加入 `B≥5`，仅装配约束 `A+2B≤8` 与非负域就已冲突。支持的线性 Gurobi 路径可生成 IIS，指出一组不能共同满足的约束或界。

IIS 列出一组不可约冲突约束或界，供用户定位需要调整的业务条件。用命名约束能让证据更容易对应到题面，详见[无解与冲突](../conflicts/)。

## 许可与常见失败

检查实际错误是许可缺失、环境不匹配、规模限制还是模型问题。容器使用 `GRB_LICENSE_FILE` 指向可只读挂载的离线许可文件；路径与部署步骤见[后端与许可证](../backends/)。

## 使用建议与资料

已有合适 Gurobi 环境、希望保留原生接口和冲突证据时可选此库。尚无许可而先学习线性建模时，可从 [Pyomo](../pyomo/) 或 [PuLP](../pulp/) 的开放后端开始。参考 [Gurobi Python API](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/overview.html)。
