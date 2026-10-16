# 执行与求解

本文说明当前执行路径和限制。求解器选择见 [README](../../README.md#求解器)，接口与数值字段见[执行契约](../contracts/execution.md)。

## 三条代码路径

| 路径 | 输入与构建 | 可选求解器 |
|---|---|---|
| 严格 IR | GroundedLPIR 经确定性编译，形成 Pyomo 工厂 | HiGHS、Gurobi、OR-Tools/SCIP |
| Pyomo 工厂 | 方法生成 `build_model(data)`，导出受支持的线性实例 | HiGHS、Gurobi、OR-Tools/SCIP |
| gurobipy 工厂或声明的原生脚本 | 导出 MPS 和决策映射，由新 SDK 对象读取 | Gurobi |

模型工厂只构建模型。声明的原生脚本可以包含求解调用；平台仍由可信收集器读取导出实例，独立求解并获取解、目标和终止状态。代码打印的目标、退出码或自报状态不能代替求解证据。

默认 Pyomo 路径覆盖全部七种方法。Direct 和 Feedback Repair 选择 `output_mode: native_gurobipy` 时，必须同时选择 `llm4om.model_backends.gurobipy`、`llm4om.solvers.gurobi` 和容器执行器。OptiMUS、CoE、OptiTree、OR-LLM-Agent 根据所选后端生成 Pyomo 或 gurobipy 工厂。AutoFormulation 只输出严格 IR，使用 Pyomo 后端。

自由文本和 LaTeX 不直接进入编译器。五元素表述需要伴随严格 IR，或由方法生成代码。工厂导出视图保留提取来源，不能据此推断源代码或原问题的语义等价。

## 依赖与预检

```bash
uv sync --locked --all-extras
uv run --locked --all-extras python scripts/build_worker_image.py
uv run --locked llm4om doctor --config examples/specs/gurobi.yaml
```

依赖版本以 [pyproject.toml](../../pyproject.toml) 和 `uv.lock` 为准。HiGHS 的锁定版本与 OR-Tools 所带 ABI 匹配，避免原生符号冲突；依据见[上游问题](https://github.com/google/or-tools/issues/5246)。

容器求解使用 Worker 内的依赖，宿主不必安装未使用的数值 SDK。缺 Docker、镜像、插件或许可证时，在生成前报告原因，不自动改为本机执行。

Gurobi 的运行探测只验证实际环境。`size_limited` 表示已观察到规模限制；微型求解成功不代表具有完整学术或商业许可证。许可证和相关身份信息留在私有环境。

## 数学与数值范围

当前接受单目标线性 LP/MILP、连续/整数/二元变量、有限系数和支持的变量界。严格 IR 保留目标常数、约束常数、目标方向及重复线性项的数学含义。

Pyomo 工厂拒绝非线性、开放或非区间变量域、固定变量、未知活动组件和不完整决策映射。gurobipy 路径拒绝二次、非线性、多目标、SOS、PWL 和半连续等未支持结构。

HiGHS 适配器检查实际数值阈值。可能被视为无穷的界、被忽略的矩阵系数和过小目标系数会被拒绝，并记录 `unsupported_numeric_range`。平台不隐式缩放问题。Gurobi 的有限界和归一化右侧值要求绝对值小于 `1e20`。

OR-Tools 使用 MPSolver/SCIP。`time_limit_s` 向上取整为毫秒；零值直接返回时间限制。未知 bound 和 gap 保持 `null`。这条路径没有接入 CP-SAT 或路径规划。

## 容器边界

Worker 使用只读根目录、无网络、非特权用户和显式资源限制。公开输入只读挂载；LLM 密钥、隐藏评测材料和 Docker socket 不进入生成代码环境。

| 限制 | 当前行为 |
|---|---|
| CPU、内存、进程数 | Docker 资源配额；内存与 swap 上限相同 |
| 总时间 | 从创建准备开始计时，超时终止 Worker |
| 输出 | stdout/stderr 合计限额，超限后停止并排空管道 |
| 工厂构建 | 隔离子进程导出实例；父进程校验并独立求解 |
| 结果来源 | 使用可信 SDK API，不接受工厂 stdout 伪造结果 |
| 清理失败 | 保存容器身份和诊断，不改写成成功 |

`trusted_local` 用于显式选择的严格 IR 可信执行，不执行生成工厂源码。当前完整隔离验证环境是 Linux。设计原因见 [ADR-0005](../adr/0005-factory-collector-isolation.md)。

## 结果解释

`termination` 与 `has_primal_solution` 分别保存。时间耗尽可以有解，也可以无解。没有 primal 时，解引用和目标为 `null`。原始状态、有效选项、求解耗时、可用 bound/gap 与证据来源随记录保存。

CPU 和内存是执行资源测量，不代表包含 LLM 的完整运行成本。未采集值为 `null`。模型最优与原问题正确性分别判断，见[评测协议](../evaluation.md)。
