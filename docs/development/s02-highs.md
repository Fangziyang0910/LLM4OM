# S02-A：严格 LPIR 编译与真实 HiGHS 求解

日期：2026-10-09。已实现的纵向切片，工作项为 [GitHub Issue #1](https://github.com/Fangziyang0910/LLM4OM/issues/1)。字段由 [插件契约](../plugin-contracts.md)维护，发布范围见 [验收清单](../acceptance.md)，后续任务见 [开发计划](../implementation-plan.md)。

## 使用与实际支持范围

在仓库根目录执行，使用 Python 3.11／3.12：

```bash
uv sync --locked --extra dev --extra solve
uv run --locked --extra solve llm4om run --problem examples/specs/problem.json --config examples/specs/solve.yaml
```

CLI 返回 `status=completed` 和运行目录。SDK 使用同一 `run_problem(problem, config)` 入口，省略 `offline=True`。运行目录中的 report、SolveResult 与 solution 分别提供摘要、原始／归一化状态及原变量 ID 的解向量。完整安装只在选择真实求解时需要 `solve` extra；基础安装仍能执行 [S01 离线回放](s01-offline-run.md)。

| 阶段 | 当前路径 | 来源与范围 |
|---|---|---|
| Formulation | Mock direct、five_element＋grounded_lp 0.1.0 | 人工 fixture，不是外部 LLM 生成 |
| Code | lp_ir_to_pyomo → python_factory | 严格 LP/MILP 的确定性编译，关联源表述／IR、symbol map 和数据 hash |
| 构建／Solve | Pyomo 6.10.1 → highspy 1.15.1 | Pyomo 标准线性表示转换到 HiGHS 原生 API，结果直接抽取 |
| 执行 | 显式 trusted_local | 同进程执行平台编译产物；container 请求不自动降级 |
| 评估 | 公开结构与编译检查 | semantic_validation=not_available |

编译器保留常数、目标方向、连续／整数／二元域、界和重复项。未知变量、重复 ID、非线性字段、非有限数值和矛盾边界在 Code 阶段拒绝。原变量不参与目标或约束时也保留。没有原变量的常数模型使用固定为零的内部变量，symbol map 显式标明且不出现在业务解向量中。

`build_model(data)` 当前是固定数据 revision 的 grounded 工厂；数值来自已校验 IR，data 参数不执行重新绑定。参数化工厂与换数据行为归 S02-B。自由文本／LaTeX 不直接传给编译器；原生用户代码与 LLM 代码尚不接入执行。

HiGHS 的数值阈值会把超大有限界解释为无穷、忽略极小矩阵系数。适配器读取原生阈值并拒绝这些输入，保存 unsupported_numeric_range，避免模型被静默改变。阈值与有效容差随结果保存，不进行隐式缩放。

## 运行证据与失败语义

运行目录增加 `model.py`、CodeArtifact、symbol map、BuildArtifact、ExecutionResult、SolveResult 及可用时的 solution。编译前快照与最终候选分别存储，事件中的旧引用保持有效。environment-lock 保存真实 Python／依赖版本；执行计划按实际阶段记录资源状态。Candidate 在执行后选中，bundle 的 final_candidate_id 为 001；失败时不选择最终候选。

`completed` 表示执行完成；是否 optimal、infeasible、unbounded 或 time_limit 由 SolveResult 单独判断。没有可行 primal 时，solution_ref 与 objective_value 为 null。解、目标、原始状态、求解时间、MIP bound／gap、选项与 evidence_origin 来自原生 API。没有采集的 CPU／峰值内存为 null；同进程执行没有子进程 exit_code。

可选依赖缺失和零 Solver 预算在 Mock 回放前拒绝。非法 IR 不调用 Solver。原生数值 admission 失败仍保存已编译代码与失败 ExecutionResult；存储 OSError 保留 SDK／CLI 原有边界。solver_calls 计适配器调用尝试，external_llm_requests 为 0。time_limit_s 由 HiGHS 执行；总墙钟、内存限制、取消／恢复与容器隔离仍归 S04，当前不声称执行这些限制。

## 验证依据

测试使用公开 CLI 和 compile_ir／solve_highs 接口，真实加载 Pyomo／HiGHS；没有 mock Solver 或编造 SolveResult。

- 生产 MILP：A=3、B=2、目标 13；LP 松弛：A=B=8/3、目标 40/3。预期来自 [独立数学依据](../../examples/README.md#2-数学问题)。
- 目标／约束常数、最小化负目标、重复线性项、整数实数边界、二元域与常数模型均有微型真实求解。
- infeasible 与 unbounded 分别保留原始终止状态；非法结构／数值范围、可选依赖缺失、预算 admission 和失败产物有公共回归。
- 运行引用、hash、阶段来源、报告与最终候选通过 CLI 检查；完整环境、构建和独立审阅结果见 [校验记录](../spec-validation.md)。

实现核对已安装 Pyomo 6.10.1 的 generate_standard_repn 与 highspy 1.15.1 API，并参考 [HiGHS Python 文档](https://ergo-code.github.io/HiGHS/dev/interfaces/python/)。没有引入上游源码副本或商业许可证。

本切片不宣称真实 LLM 自动建模、一般语义等价、Gurobi、容器、time_limit 的有解／无解完整验收、论文方法或 benchmark 已实现。
