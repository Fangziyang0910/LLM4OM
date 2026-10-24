CPMpy 用整数、布尔与全局约束表达离散决策。排班、指派、逻辑规则以及无目标的可满足性问题都可以采用这种表达方式。

## 建模范围

变量是有限域整数或布尔量，不提供连续变量。数据中的小数可以在保持数学含义的前提下缩放为整数；连续决策不能仅靠取整来替代。

常见全局约束包括 `AllDifferent`、Element、Table 和 Cumulative。是否能直接使用某个约束，仍取决于后端的原生支持或转换能力。

## 在平台中选择

选择 CPMpy，默认后端为 OR-Tools CP-SAT，原生 ID 为 `ortools`。平台从 SolverLookup 读取基础后端与已安装子求解器，可能包含 CP、SAT、SMT、MIP、MaxSAT 等路径。以当前部署的可用状态为准。

## 代码与结果

`build_model(data)` 返回 `cp.Model` 或原生 `SolverInterface`，不直接调用 solve。模型可以只有约束，没有优化目标；此时找到合法赋值是可满足性结果，目标值可以为空。

不可行模型可通过 MUS 提供不能同时满足的约束，供平台解释。解释需要实际证据，不是每个不可行状态都会自动产生业务诊断。

## 官方资料

参阅 [CPMpy 求解器文档](https://cpmpy.readthedocs.io/en/latest/solvers.html)。后端安装、变量域和诊断支持分别检查；不要把某个插件注册为已知后端，理解为本机已可运行。
