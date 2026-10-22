# 用户选择代码写法，写法决定求解器

## 背景

[0007](0007-langchain-minimal-core.md) 让代码只构建模型，Worker 把模型导出为 MPS 再交给求解器。这样“写代码用的库”（建模后端）和“求解用的引擎”（求解器）成为两个独立选项。

建模的实际链条是：数学模型 → 代码 → 求解。方法产出的是代码，所以用户要选的是代码写法，求解器由写法决定。拆成两个选项的问题：

- 概念多了一层，后端不对应建模问题中的任何东西。
- 出现不自然的组合。例如 gurobipy 代码交给 HiGHS 求解，仍要先用 gurobipy 建模，因此受 Gurobi 受限许可证的规模限制。
- MPS 只能表达线性和二次模型，约束规划（CP）的全局约束无法表达。
- 唯一的收益是“同一份代码换求解器”，研究中很少需要。

## 决定

- 用户选择代码写法。每种写法对应一个求解器：Pyomo → HiGHS，gurobipy → Gurobi，OR-Tools `pywraplp` → SCIP，CPMpy → OR-Tools CP-SAT。
- 代码定义 `build_model(data)` 并返回模型对象。Worker 用该写法自己的接口求解，由平台统一设置时限并读取结果。CPMpy 模型可以没有目标，此时是可满足性问题。
- 方法用 `Method.languages` 声明支持的写法；不声明表示全部支持。服务端拒绝不支持的组合，前端只列出支持的写法。原提示要求 (MI)LP 的方法（OptiMUS、CoE、OptiTree、OR-LLM-Agent、AutoFormulation）只支持三种 MILP 写法。
- 原提示针对某个库的方法按写法选择方言。gurobipy 方言保留上游原文。
- 删除 `Backend`、MPS 导出和请求中的 `backend`、`solver` 字段，改为 `language`。

## 取舍

- 换求解器需要重新生成代码。
- Pyomo 和 CPMpy 是建模层，这里各自固定一个求解器，不暴露它们的多求解器选择，避免重新出现“写法 × 求解器”两个维度。
- CPMpy 会把高层约束分解成 CP-SAT 支持的形式，语义等价，效率可能低于原生 `cp_model`。选它是因为代码更接近数学表述。是否改用原生 `cp_model`，应由 CP 问题上的对比实验决定。

## 后续

v0.41 按同一规则增加两种写法：PuLP → CBC（MILP，PuLP 自带 CBC），CVXPY → Clarabel（连续凸优化，不接受整数变量）。MILP 写法因此是四种。
