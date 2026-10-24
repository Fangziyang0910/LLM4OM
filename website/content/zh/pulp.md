PuLP 面向线性与混合整数规划。它用变量、线性求和和带方向的约束表达问题，适合生产、运输、预算和分配等可以写成线性关系的任务。

## 什么叫线性

`3A+2B` 和 `2A+B≤8` 是线性的，因为系数是已知常数。平方损失或范数等表达可使用下文链接的CVXPY等库。

二元变量仍可在线性模型中表达开关。例如“选中工厂才能生产”可以在具有合理上界时写成 `production ≤ capacity × open`，其中 capacity 是常数、open 是二元决策。

## 完整生产模型

```python
import pulp

def build_model(data):
    model = pulp.LpProblem("production", pulp.LpMaximize)
    a = pulp.LpVariable("A", lowBound=0, cat="Integer")
    b = pulp.LpVariable("B", lowBound=0, cat="Integer")
    model += 3*a + 2*b, "profit"
    model += 2*a + b <= 8, "cutting"
    model += a + 2*b <= 8, "finishing"
    return model
```

第一条没有比较符号的表达式是目标；后面的比较表达式是约束。约束名应唯一。平台负责调用 CBC 或明确选择的兼容后端，代码不调用 `model.solve()`。

## 默认后端与接口

默认是 `PULP_CBC_CMD`。平台通过 PuLP 原生 `listSolvers/getSolver` 发现其他后端，保留 Python、命令行和动态库接口的原生标识，不把它们混成一个名字。

行式代数写法和列式 `LpConstraintVar` 都返回 `LpProblem`。可按问题的数据组织方式选择写法。

## 查看和调整结果

上例 A=3、B=2、收益13。结果页显示变量、目标值和实际后端；可以导出完整数据，也可以从当前方案调整容量或最低需求。

```demo
production
```

在交互例中修改切割容量或 B 的最低需求，查看新方案，并下载当前方案的 CSV。平台中的对应操作见[调整条件](../revisions/)和[场景比较](../scenarios/)。

## 常见问题与选型

连续域是默认行为之一，整件产量要明确 `cat="Integer"`；二元选择用 `cat="Binary"`。变量名、目标方向、每条资源约束都要核对。变量乘积报错时，可根据表达式结构选择相应的建模库。

希望使用更广的代数建模结构可查看 [Pyomo](../pyomo/)；需要凸范数、二次损失可查看 [CVXPY](../cvxpy/)；逻辑和全局约束可查看 [CPMpy](../cpmpy/)。原生接口见 [PuLP 官方文档](https://coin-or.github.io/pulp/technical/pulp.html)。
