# 插件、接口与数据契约

契约版本：0.1.0，设计规范而非已实现 SDK。本文中的 Python Protocol 为接口草案；类型必须在首个实现切片落实为可序列化、可验证的数据对象，不能复制未定义类型后声称已可运行。

## 1. 所有插件的共同契约

```python
class Plugin(Protocol):
    def describe(self) -> PluginManifest: ...
```

Manifest 字段：

| 字段 | 必需 | 语义 |
|---|---|---|
| `schema_version` | 是 | Manifest 结构版本 |
| `plugin_id` | 是 | 命名空间＋局部 ID，例如 `llm4om.methods.direct` |
| `kind` | 是 | 下节规定的插件种类 |
| `plugin_version` | 是 | SemVer，独立于契约版本 |
| `contract_range` | 是 | 支持的接口版本范围 |
| `display_name`、`description` | 是 | 显示与用途说明 |
| `capabilities` | 是 | 接受／产出类型、问题类型、恢复／工具／执行要求 |
| `config_schema` | 是 | 标准 JSON Schema 形式的配置约束 |
| `dependencies` | 是 | Python 依赖、执行环境、求解器／许可证条件 |
| `source` | 是 | 内置／第三方、上游 URL、固定提交／版本、变体说明；无上游时为 null |

内部 registry 键为 `(kind, plugin_id)`，一次环境不允许相同键的多个活动版本。与内置键冲突必须报错，不能以安装顺序覆盖。entry point 名称规划为 `llm4om.plugins`；加载第三方 Python 包会执行可信插件代码，因此安装／加载与生成代码隔离是两个问题。

### 能力声明与匹配规则

能力是显式枚举或带版本的描述，不使用未定义的 `supports_everything`。最少声明 `problem_types`、`input_artifact_kinds`、`output_artifact_kinds`，并按种类声明 `model_backends`、`solvers`、`llm_features`、`oracle_requirements`、`execution_modes`、`supports_checkpoint`、`supports_clarification`。

缺失能力等于未知，不等于支持。Planner 先验证静态组合，再以无付费默认的 dependency check 验证本机环境。`preflight_ok` 只表示准备条件通过，不能保证运行时服务或模型行为正常。

`problem_type_hint=unknown` 与“插件能力未知”不同：用户可以只提供自然语言。配置显式限定本次允许的目标类型（1.0 为 LP/MILP），Planner 验证方法能产出这些类型，运行后再次核对实际产物类型；无法落入范围时记录 unsupported／needs_input，不借猜测宣称支持新的问题类型。

插件实例由其安装包导出的 factory 接收已验证 config 和声明的资源依赖后创建。初始化不允许隐式发送付费请求；生命周期资源清理由运行层负责，构造失败转换为明确依赖或配置错误。

## 2. 插件接口目录

| 种类 | 最小业务接口 | 调用位置／关键约束 |
|---|---|---|
| `method` | `async run(problem, context) -> MethodOutcome` | 只访问公开问题和 Context；内部搜索策略不泄漏到核心 |
| `llm_provider` | `async complete(request, context) -> LLMResponse` | Gateway 控制凭据、预算、重试和 trace |
| `task_adapter` | `iter_cases(config) -> Iterator[EvaluationCase]` | 导入／调度端；公开输入与 oracle 分开 |
| `data_loader` | `load(ref, schema, context) -> DataView` | 受控数据读取，有限视图和大小限制 |
| `compiler` | `compile(ir, target, context) -> BuildArtifact` | 支持 IR schema 与目标 Backend；不调用 LLM |
| `model_backend` | `load(build, data, context) -> ModelHandle` | Worker 内构建模型；Handle 不跨进程序列化 |
| `solver_backend` | `solve(handle, options, context) -> SolveResult` | Worker 内，仅接收支持的 ModelHandle |
| `evaluator` | `evaluate(case, outcome, context) -> EvaluationResult` | 隐藏评分进程；不能反向泄漏 oracle |
| `executor` | `async execute(request, context) -> ExecutionResult` | 执行安全模式、资源限制、清理与证据 |
| `artifact_store` | `put(value, metadata) -> ArtifactRef` / `get(ref, access) -> bytes` | 内容寻址与访问控制；引用不是任意宿主路径 |
| `reporter` | `render(experiment_result, destination, context) -> ReportRef` | 只读取已形成结果，不重新决定正确性 |

Registry、Planner、预算账本与状态机是 1.0 稳定核心，不为了未来假设把每个内部函数变成公开插件。Executor／Store／Reporter 允许替换，但初期只保证表中小接口。

### 方法接口与 Context

```python
class ModelingMethod(Plugin, Protocol):
    async def run(
        self, problem: PublicProblem, context: MethodContext
    ) -> MethodOutcome: ...

class MethodContext(Protocol):
    llm: LLMGateway
    data: PublicDataGateway
    execution: ExecutionGateway
    artifacts: PublicArtifactAccess
    budget: BudgetView
    cancellation: CancellationToken
    def emit(self, event: MethodEvent) -> None: ...
```

Context 中不存在 Evaluator、EvaluationOracle 或原始完整 EvaluationCase；内部方法不能自行构造 Provider 绕过 Gateway。角色模型选择经 `llm.complete(request, role="critic")` 等请求，由实验配置控制，记录具体角色和模型。

MethodOutcome 的 `status` 为 `candidate_selected | needs_input | failed | exhausted`。包含最终 candidate_id（可空）、公开 candidates 引用、诊断、ClarificationRequest（可空）及 opaque checkpoint（可空）。checkpoint 必须可序列化、版本化；不能 pickle 任意运行对象以假装可移植。

最终候选由方法根据公开证据选择，评分开始前冻结。评估器不得在全部候选中用隐藏正确答案挑选最好结果；若报告 oracle-best，应独立列作诊断指标而非默认成功率。

## 3. 核心对象

### 3.1 ArtifactRef

必需字段：`artifact_id`、`media_type`、`sha256`、`size_bytes`、`namespace`、`relative_path`、`schema_version`（非结构化文件可 null）。路径限定于 ArtifactStore 授权根目录，不接受 `../`、符号链接越界或远程 URL 自动下载。外部下载是 Task／Data Adapter 的显式行为。

Hash 对原始文件字节计算；结构化对象另记录规范化 JSON 哈希，canonicalization 版本也锁定。保留原文，不默默归一化自然语言或浮点数来合并样本。

### 3.2 ProblemSpec / PublicProblem

| 字段 | 类型／必需性 | 约束 |
|---|---|---|
| `schema_version` | string，必需 | 核心对象版本 |
| `problem_id`、`revision` | string，必需 | 样本稳定 ID 与输入修订 |
| `description`、`language` | string，必需 | 原始描述，语言如 `zh-CN` |
| `problem_type_hint` | enum，必需 | `lp | milp | unknown`，更多类型经扩展契约支持 |
| `requirements` | Requirement[]，必需，可空 | `{id, text, category, source_span}`；category 为 objective／domain／constraint／data／other |
| `data_refs` | DataRef[]，必需，可空 | `{data_id, path, format, schema, sha256}`；原始输入 sha256 可空，规范化后必需 |
| `assumptions` | Assumption[]，必需，可空 | `{id, text, origin, status}`，status 为 explicit／proposed／confirmed |
| `source` | object，必需 | 用户输入或 dataset ID／version／split／source_sample_id／license_ref |
| `metadata` | object，可选 | 不包含 oracle 或模型秘密；新增业务字段经版本化 |

`PublicProblem` 是经过路径解析、哈希校验与权限投影的 ProblemSpec。它不增加参考目标或参考代码。Requirement 的 source_span 是原文字符范围或表格定位，不是 LLM 的推测结果。

Assumption 标成 proposed 时必须保留待确认状态；批量不能静默转为 confirmed。描述显式完整的问题无需为了形式化流程强制让人再确认一次。

### 3.3 EvaluationCase / EvaluationOracle

Case 包含公开问题、dataset manifest 引用及私有 `oracle_ref`。Oracle 的可选证据类型：

- `reference_objective`：finite value、sense、参考终止状态、容差与来源。
- `reference_solution`：变量映射及域／单位定义，允许多个等价最优解。
- `independent_checker`：受信任检查器引用、版本、输入输出契约。
- `reference_model`：模型与数据哈希，用于独立重求解或等价检查。
- `properties`：必要性质、明确的数据变换及预期变化。
- `expert_review`：人工标签、说明、评审日期与证据来源。

各字段缺失代表该证据不可用。只有目标值时不得制造参考变量或声称证明可行性。Oracle 的数值和正文不写进给方法的完整配置。

### 3.4 Candidate / ModelArtifact

Candidate 必需：`candidate_id`、`run_id`、`parent_ids`、`sequence_no`、`artifact_ref`、`created_by`、`status`；`created_by` 包含方法／版本／variant_id、call_ids、提示 hash 与角色。状态表达 `proposed | invalid | executed | rejected | selected`，求解终止状态单独保存。

ModelArtifact 必需：

| 字段 | 含义 |
|---|---|
| `artifact_kind` | `lp_ir | python_factory | native_code` |
| `representation_ref` | 实际 IR／代码的引用 |
| `model_backend` | code 路径必需；IR 编译前可 null |
| `problem_ref`、`data_bindings` | 公开问题 revision 与数据哈希 |
| `assumptions`、`requirement_traces` | 声明假设与映射，可空但不能伪造 |
| `diagnostics`、`warnings` | 来源不确定、参数缺失、提取失败等 |
| `provenance` | 调用、方法、上游版本、用户编辑来源 |
| `optional_views` | 数学公式、图形、推断 IR 等补充产物及其证据标签 |

一个方法可以只输出 native code，但必须如实说明无法提供的数学结构。需要数学模型展示时，UI 用明确的“尚未提供／推断视图”表达。

### 3.5 GroundedLPIR 0.1

LPIR 是具体实例模型，支持单目标 min/max、有限实数系数、连续／整数／二元变量、线性等式／不等式。字面常数不能包含 NaN／Infinity，无界界限使用 null。

```text
ModelIR = {
  schema_version, ir_kind="grounded_lp", problem_type="lp"|"milp",
  model_id, problem_id, problem_revision, data_bindings,
  variables: [{id, name, domain, lower_bound, upper_bound, requirement_ids}],
  objective: {sense, expression: LinearExpression, requirement_ids},
  constraints: [{id, expression: LinearExpression, sense, rhs, requirement_ids}],
  assumptions, provenance
}
LinearExpression = {constant: finite-number,
                    terms: [{variable_id, coefficient: finite-number}]}
```

归一化合并重复变量项并保留原始表示引用。变量 ID／约束 ID 唯一；整数边界允许实数输入但不得被无说明截断；二元变量有效域为 {0,1} 与显式边界交集。lower>upper 是非法／显式矛盾诊断，不自动交换。

表达式语义为 `constant + Σ coefficient * variable`，约束比较对象为 rhs。目标常数影响目标值，必须保留；约束常数不能在移项时误改变符号。`problem_type=lp` 不允许 integer／binary 变量。变量单位和需求映射是元信息，不是数学正确性证明。

1.0 未表达的非线性、indicator、SOS、复杂索引与逻辑运算不能塞进自由文本字段再称为可编译。方法可显式线性化为受支持 IR，记录线性化假设与来源；否则走声明能力的原生代码或标 unsupported。

### 3.6 BuildArtifact / ModelHandle

BuildArtifact 包含编译器／版本、源产物 hash、目标 Backend、代码／模型文件引用、数据绑定、symbol_map、诊断与编译配置 hash。编译不改变方法或候选 ID，但生成派生产物 ID。

ModelHandle 仅在 Worker 内持有后端对象、模型类型、变量／约束映射和可导出能力。跨 Worker 传输使用 BuildArtifact／序列化模型及解向量，不能将后端 Python 对象传给核心调度器。

### 3.7 SolveResult / ExecutionResult

SolveResult 必需：`solver_id`、`solver_version`、`model_backend`、`raw_status`、`termination`、`has_primal_solution`、`solution_ref`、`objective_value`、`objective_sense`、`best_bound`、`reported_gap`、`solve_time_s`、`options`、`diagnostics`、`evidence_origin`。

`termination`：`optimal | feasible | infeasible | unbounded | infeasible_or_unbounded | time_limit | interrupted | error | unknown`。objective 和 solution 无解时为 null；time_limit 是否有解由 `has_primal_solution` 决定。gap 优先保留求解器定义；自行计算时记录公式版本和零分母处理。

ExecutionResult 必需：execution_id、mode、status、start/end、exit_code、资源统计、输出截断标记、solve_result_ref（可空）、stdout/stderr 引用、diagnostics。执行成功不推导 termination=optimal；脚本输出的自报数字不能自动视为 trusted extraction。

### 3.8 EvaluationResult

结果包括协议 ID／版本、最终候选 ID、各 CheckOutcome、证据引用、primary outcome、分母归类、错误标签、warnings。每个 CheckOutcome 包含 `status=pass|fail|unknown|not_available|error`、检查器／版本、容差与解释。

主指标必须显式命名，如 `objective_match_rate`；禁止把 objective match 改名为“语义正确率”。完整字段和指标算法见 [评测协议](evaluation.md)。

## 4. LLM 请求、重试与用量

LLMRequest 包含 request_id、role、model_ref、messages、可选 tools、可选 response_schema、generation_options、timeout、metadata。Message 支持 text 与受控数据引用，1.0 不强制多模态。Provider 不支持 tools／JSON schema 时 fail fast；prompt fallback 必须是显式变体配置。

LLMResponse 包含 provider request ID、模型实际标识（可未知）、原始响应引用、标准化消息／工具调用、finish_reason、usage、timing、diagnostics。usage 的 input／output／cached／reasoning token 分别可 null；是否被包含在 total 的语义由 Provider 声明，不能重复计数。成本由版本化定价配置计算，不在源码永久硬编码在线价格。

429、5xx、连接问题可有限退避重试；认证、无效 schema、明确不支持请求不重试。所有真实尝试有独立 attempt_id，是否收费未知时记录 unknown。供应方处理后的超时不能宣称未产生调用成本。

## 5. 预算与候选选择契约

预算字段至少包括 max_llm_attempts、max_total_tokens、max_candidates、max_repairs、max_solver_calls、wall_time_s、max_concurrency。调用／候选／并发 admission 由核心原子计数；多 Agent 共享 run 预算，不能各自重复分配全额。

Token 阈值采用发送前估算＋最大输出预留和响应后结算；估算、未知供应方用量、最后一次调用越界分别报告。调用次数可严格限制，token／费用不能在供应方信息不足时伪称绝对硬上限。新调用必须在剩余预算不足时拒绝；未知结果保守占用预留，不直接当零。

方法可以用候选自身的约束检查、公开 solver 信息或自评来选择候选，不能借隐藏 benchmark 答案选择。选择策略写入 manifest/config；所有候选按记录保留，最终选定后不因评分失败偷偷换另一个。

## 6. 错误、取消与兼容性

统一 PluginError 包含 `code`、`stage`、`message`、`retryable`、`plugin_id`、`run_id`、`candidate_id`、`details_ref`。标准 code：CONFIG_INVALID、CAPABILITY_MISMATCH、DEPENDENCY_MISSING、AUTH_ERROR、RATE_LIMIT、PROVIDER_TIMEOUT、BUDGET_EXHAUSTED、DATA_INVALID、ARTIFACT_INVALID、COMPILATION_ERROR、EXECUTION_TIMEOUT、EXECUTION_OOM、SOLVER_ERROR、ORACLE_UNAVAILABLE、EVALUATION_ERROR、CHECKPOINT_INCOMPATIBLE、CANCELLED。

业务模型 infeasible 是 SolveResult；不自动包装成 SolverError。缺少参考答案是证据 not_available；评估器程序抛异常才是 EVALUATION_ERROR。未知插件异常保留脱敏 traceback 并转为稳定错误，不能使其他 run 退出。

Schema／plugin／IR／protocol 均记录完整版本。旧产物读取经显式迁移并生成新 hash；不原地修改原事件。新增问题类型或指标定义变化必须提升相关 schema／protocol 版本；报告禁止不说明地跨协议合并。

## 7. 接入完成的定义

每个插件交付 Manifest、配置说明、能力矩阵、至少一个成功 fixture、一个不支持或失败 fixture、取消／预算适用性与契约测试。原生方法另外交付上游提交锁、适配差异和复现实验；后端另外交付真实求解记录。此时才能在插件列表中标记 `verified`，而不是仅凭 import 成功。

## 8. ExperimentSpec / RunConfig

实验配置必需字段为 schema_version、experiment_id、task、methods、llm、model_backend、solver、executor、evaluation、budget、repeats、store、reporters。compiler 仅在相应 IR 转换路径必需；roles、sample_selection、cache_policy、allowed_problem_types 为可选配置。默认 allowed_problem_types 为 [lp,milp]。

普通插件选择对象为 `{plugin_id, config}`，config 可为空对象；LLM 选择为 `{provider_plugin_id, model, config}`，solver 为 `{plugin_id, options}`。缺省 config 与 options 仅能使用 Manifest 中明确默认值，不能由插件静默选择模型或求解器。

methods 是方法选择列表；角色 LLM 配置可在 roles 中覆盖默认 llm。1.0 实验可以按显式变体配置展开方法／模型／后端组合，展开后的每个 RunConfig 固定一个实例、方法、资源配置及评测协议，不共享可变插件状态。

task.config 的 oracle_path／私有数据只在 TaskAdapter 与评估端存在。PublicRunConfig 投影去除这些字段、凭据和敏感路径后才传给方法／导出；不是把原始 YAML 直接塞进 Context。配置相对路径以该配置文件所在目录为基准，最终访问仍受对应工作根目录和公开／私有权限控制；示例中 store.root 可解析至仓库 runs，方法的数据引用不允许因此访问该整棵目录。

Budget 的硬计数阈值为非负整数，wall_time_s 为正数；repeats 为正整数；并发至少 1；max_repairs=0 合法。JSON/YAML 中禁止可执行标签与任意对象构造。全部插件参数经 config_schema／后端 options schema 校验；未知键 fail fast，扩展字段放入明示命名空间而不是随意透传。

## 9. RunBundle 布局目标

```text
run-id/
  public-problem.json
  public-config.json
  environment-lock.json
  dataset-manifest.json
  budget-ledger.json
  events.jsonl
  candidates/<candidate-id>/
    artifact.json
    representation.json|model.py
    build.json
    execution.json
    solve-result.json
  evaluation.json
  reports/report.md
```

失败时缺少的阶段文件不伪造，bundle manifest 明确当前终态和可用产物。内部私有 oracle、未脱敏 raw response 与凭据不在公开 bundle；raw LLM trace 可含敏感业务数据，按可配置的本地访问与导出策略保存，默认导出仅提供脱敏摘要。导出 oracle 或 raw trace 不是普通报告器的隐式行为。
