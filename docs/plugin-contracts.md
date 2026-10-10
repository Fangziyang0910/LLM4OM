# 插件、接口与数据契约

核心对象／配置／Manifest 草案：0.2.0；GroundedLPIR：0.1.0；文档修订：0.4.0。本文定义当前开发契约；S01 已落实离线输入与公开产物，S02-A 已落实严格 IR 编译与真实 HiGHS；S03 落实单候选方法 profile 与当前路径预检；实际范围见 [S01](development/s01-offline-run.md)／[S02-A](development/s02-highs.md)／[S03](development/s03-plugins.md)。Protocol 是接口示意，数据对象在对应纵向切片落实并验证。领域含义见 [GLOSSARY](../GLOSSARY.md)，调用顺序见 [详细设计](detailed-design.md)。

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

source 对研究方法另记录研究路线（prompting-based／training-based／hybrid）、接入方式（原流程适配／流程变体）、原模型与实际外部 LLM 的差异，以及可获得的 `paper_url`、`citation_key`、`paper_version`、`upstream_commit`、`variant_id` 与适配差异引用。名称或题目不是唯一身份；论文、模型权重、推理流程与数据集分别关联。考察提交不自动作为已验证接入版本。

内部 registry 键为 `(kind, plugin_id)`，一次环境不允许相同键的多个活动版本。与内置键冲突必须报错，不能以安装顺序覆盖。已实现的method／llm_provider／task_adapter／evaluator／compiler／model_backend／solver_backend／data_loader使用entry point分组`llm4om.plugins`；加载第三方Python包会执行可信插件代码，因此安装／加载与生成代码隔离是两个问题。

### 能力声明与匹配规则

能力是显式枚举或带版本的描述，不使用未定义的 `supports_everything`。最少声明 `problem_types`、`input_artifact_kinds`、`output_artifact_kinds`；方法另声明 `formulation_representations`、`code_representations` 和阶段输出可用性，并按种类声明 `model_backends`、`solvers`、`llm_features`、`oracle_requirements`、`execution_modes`、`supports_checkpoint`、`supports_clarification`。

缺失能力等于未知，不等于支持。Planner 先验证静态组合，再以无付费默认的 dependency check 验证本机环境。`preflight_ok` 只表示准备条件通过，不能保证运行时服务或模型行为正常。

`problem_type_hint=unknown` 与“插件能力未知”不同：用户可以只提供自然语言。配置显式限定本次允许的目标类型（1.0 为 LP/MILP），Planner 验证方法能产出这些类型，运行后再次核对实际产物类型；无法落入范围时记录 unsupported／needs_input，不借猜测宣称支持新的问题类型。

插件实例由其安装包导出的 factory 接收已验证 config 和声明的资源依赖后创建。初始化不允许隐式发送付费请求；生命周期资源清理由运行层负责，构造失败转换为明确依赖或配置错误。

## 2. 插件接口目录

| 种类 | 最小业务接口 | 调用位置／关键约束 |
|---|---|---|
| `method` | `async run(problem, context, *, checkpoint=None) -> MethodOutcome` | 只访问公开问题和 Context；内部搜索策略不泄漏到核心；checkpoint 能力必须声明 |
| `llm_provider` | `async complete(request, context) -> LLMResponse` | Gateway 控制凭据、预算、重试和 trace |
| `task_adapter` | `iter_cases(config) -> Iterator[EvaluationCase]` | 导入／调度端；公开输入与 oracle 分开 |
| `data_loader` | `load(ref, schema, context) -> DataView` | 受控数据读取，有限视图和大小限制 |
| `compiler` | `compile(ir, target_backend) -> CompiledCode` | 支持 IR schema 与目标 Backend；Code／Build由编排层记录，不调用 LLM |
| `model_backend` | `load(build, data) -> ModelHandle` / `export(handle) -> dict` | Worker 内构建模型；native另提供受控read_transport；Handle不跨进程序列化 |
| `solver_backend` | `runtime() -> dict` / `solve(handle, options) -> dict` | Worker 内，仅接收声明的Handle；应用层归一化并绑定SolveResult |
| `evaluator` | `evaluate(case, outcome, context) -> EvaluationResult` | 隐藏评分进程；不能反向泄漏 oracle |
| `executor` | `async execute(request, context) -> ExecutionResult` | 执行安全模式、资源限制、清理与证据 |
| `artifact_store` | `put(value, metadata) -> ArtifactRef` / `get(ref, access) -> bytes` | 内容寻址与访问控制；引用不是任意宿主路径 |
| `reporter` | `render(experiment_result, destination, context) -> ReportRef` | 只读取已形成结果，不重新决定正确性 |

Registry、Planner、预算账本与状态机是 1.0 稳定核心，不为了未来假设把每个内部函数变成公开插件。Executor／Store／Reporter 允许替换，但初期只保证表中小接口。

### 方法接口与 Context

```python
class ModelingMethod(Plugin, Protocol):
    async def run(
        self, problem: PublicProblem, context: MethodContext,
        *, checkpoint: MethodCheckpoint | None = None
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

Context 中不存在 Evaluator、EvaluationOracle 或原始完整 EvaluationCase；内部方法不能自行构造 Provider 绕过 Gateway。角色模型选择经 `llm.complete(request, role="critic")` 等请求，由实验配置控制，记录具体角色和模型。当前主要调用通用外部 LLM；专用训练模型未来通过同一 Provider／model 配置接入。

MethodOutcome 的 `status` 为 `candidate_selected | needs_input | failed | exhausted`。包含最终 candidate_id（可空）、公开 candidates 引用、诊断、ClarificationRequest（可空）及 opaque checkpoint（可空）。checkpoint 必须可序列化、版本化；不能 pickle 任意运行对象以假装可移植。

`supports_checkpoint=false` 的方法必须拒绝非空 checkpoint。checkpoint 引用其方法版本、公开输入 hash、配置 hash 与预算／事件位置。恢复经过应用层兼容校验后传入，不要求核心解释方法内部状态。

MethodEvent 记录 `stage=formulation|code|selection`、candidate_id、阶段输入／输出引用和 call_ids。一次调用联合产生两阶段输出时，两份阶段记录可引用同一 call_id；账本按真实 attempt_id 计费，不重复计量。方法可在 Code／Solve 的公开反馈后返回 Formulation；不强制两个独立方法入口或固定两次调用。

ExecutionGateway 最小方法为 `async execute_candidate(candidate_ref) -> ExecutionResult`，使用 run 已锁定的表示转换、后端、求解参数与执行配置，负责预算和结果记录。它提供公开编译／执行／求解反馈，不调用隐藏 benchmark 评分。方法可以按需要执行中间候选；最终阶段复用配置一致的已有记录或补齐执行，见 DD-01/02。

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

自然语言用户输入可以没有人工需求拆分，requirements 为空合法。方法推断出的规则或新增假设属于候选说明，不静默改写为原始已确认需求。数据路径先相对于其 ProblemSpec 来源目录解析，再投影为受控公开引用。

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

reference_objective 可记录 `quality_label=optimal|best_known|feasible_reference|unknown` 及其求解／验证证据。TaskAdapter 依据实际参考记录确定标签，不从文件名或字段名推断最优性。缺乏最优性证据的参考保留其质量语义，见评测协议。

### 3.4 Candidate / ModelArtifact / 阶段输出

Candidate 必需：`candidate_id`、`run_id`、`parent_ids`、`sequence_no`、`artifact_ref`、`created_by`、`status`。`created_by` 包含方法／版本／variant_id、call_ids、提示 hash 与角色；候选状态为 proposed／invalid／executed／rejected／selected，求解终止状态另存。

ModelArtifact 是整个候选建模输出的共同封装：

| 字段 | 含义 |
|---|---|
| `schema_version`、`artifact_id` | 核心对象版本与输出身份 |
| `problem_ref`、`data_bindings` | 公开问题 revision 与数据 hash |
| `formulation_ref` | FormulationArtifact 引用，可 null |
| `code_ref` | CodeArtifact 引用，可 null |
| `stage_status` | formulation／code 分别为 available、pending 或 not_available；非 available 必须说明原因 |
| `assumptions`、`requirement_traces` | 声明假设与需求映射，可空，保留来源 |
| `diagnostics`、`warnings`、`provenance` | 方法、调用、上游版本、模型选择与用户编辑来源 |
| `optional_views` | 其他数学视图、图形或提取视图，标明来源与证据 |

available 必须有对应阶段引用；pending 表示后续阶段尚未完成；not_available 表示方法没有提供或无法忠实提取。最终可执行候选必须有 CodeArtifact，原生方法只有代码时 Formulation 可以 not_available。需要 LLM 补写五元素时形成带 inferred 来源的派生视图或新变体，不冒充原始输出。

#### FormulationArtifact 与默认五元素

必需字段：schema_version、formulation_id、problem_id、problem_revision、representation_kind、representation、data_bindings、provenance。`representation_kind=five_element` 的 representation 有五个字段：

| 字段 | 内容 |
|---|---|
| `sets` | 集合 ID、索引及说明；显式元素或受控数据引用 |
| `parameters` | 参数 ID、索引集合、数值／数据绑定与单位说明 |
| `variables` | 决策变量 ID、索引、域和边界 |
| `objective` | 目标方向、数学表达与解释 |
| `constraints` | 约束 ID、数学表达、解释与需求映射 |

表达可以使用 `expression_text`／LaTeX；集合、参数、变量和约束的稳定 ID 便于引用，字段齐全不证明数学正确。自由文本五元素是可读表述，不按任意 Python／LaTeX 表达式执行。

direct 的 formulation_mode=five_element 选择默认表述；output_mode=lp_ir 选择伴随严格 IR，随后由 Compiler 完成 Code，output_mode=python_factory 则由方法提供对应 CodeArtifact。两种模式的最终输出都使用 ModelArtifact，共同封装不是 LPIR 本体。

需要确定性编译时，额外提供 `structured_ir_ref`，指向经过校验的 GroundedLPIR，并记录它与五元素的来源关系；没有严格 IR 时，由方法的 Code 步骤生成代码。其他 representation_kind 如 grounded_lp_ir／native_formulation／domain_dsl 必须声明 schema 和能力范围；native_formulation 保留上游数学表述的原文／结构和明确 schema；默认五元素不要求改写历史方法。领域 DSL 是特定问题族的可选表示，1.0 暂不承诺 DSL 求解路径。

#### CodeArtifact 与实现来源

必需字段：schema_version、code_id、representation_kind、representation_ref、model_backend、source_formulation_ref（可 null）、data_bindings、provenance。1.0 representation_kind 为 python_factory／native_code；构建指令或其他求解输入在扩展时声明。

provenance 记录实现由方法生成、确定性编译或原生适配得到；编译来源另保存 compiler_id、compiler_version、源 IR hash 和 symbol_map 引用。代码阶段是模型的计算实现，随后才执行 Solve。工厂入口为 `build_model(data)`，原生脚本按锁定入口运行。

data_bindings 至少包含 data_id 和 hash；可获得时增加参数／集合 ID、来源列、键／索引、单位和变换产物引用。派生数据保留父数据 hash。详细绑定缺失时注明不可用。Formulation 与 Code 使用同一份明确数据 revision；换数据或修改数学含义形成新候选／revision。

optional_views 使用 origin=generated／extracted／inferred／hand_authored，数学层次为 parameterized／instantiated／unknown。来源标签与语义验证结论分别记录。

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

BuildArtifact 是确定性 Code 路径的构建记录，并关联其 CodeArtifact；包含编译器／版本、源产物 hash、目标 Backend、代码／模型文件引用、数据绑定、symbol_map、诊断与编译配置 hash。编译不改变方法或候选 ID，但生成派生产物 ID。

ModelHandle 仅在 Worker 内持有后端对象、模型类型、变量／约束映射和可导出能力。跨 Worker 传输使用 BuildArtifact／序列化模型及解向量，不能将后端 Python 对象传给核心调度器。

### 3.7 SolveResult / ExecutionResult

SolveResult 必需：`solver_id`、`solver_version`、`model_backend`、`raw_status`、`termination`、`has_primal_solution`、`solution_ref`、`objective_value`、`objective_sense`、`best_bound`、`reported_gap`、`solve_time_s`、`options`、`diagnostics`、`evidence_origin`。

`termination`：`optimal | feasible | infeasible | unbounded | infeasible_or_unbounded | time_limit | interrupted | error | unknown`。objective 和 solution 无解时为 null；time_limit 是否有解由 `has_primal_solution` 决定。gap 优先保留求解器定义；自行计算时记录公式版本和零分母处理。

ExecutionResult 必需：execution_id、mode、status、start/end、exit_code、资源统计、输出截断标记、solve_result_ref（可空）、stdout/stderr 引用、diagnostics。执行成功不推导 termination=optimal；脚本输出的自报数字不能自动视为 trusted extraction。

### 3.8 EvaluationResult

结果包括协议 ID／版本、最终候选 ID、formulation_validation／code_validation 及各 CheckOutcome、证据引用、primary outcome、分母归类、错误标签、warnings。每个 CheckOutcome 包含 `status=pass|fail|unknown|not_available|error`、检查器／版本、容差与解释。

主指标必须显式命名，如 `objective_match_rate`；禁止把 objective match 改名为“语义正确率”。完整字段和指标算法见 [评测协议](evaluation.md)。

## 4. LLM 请求、重试与用量

LLMRequest 包含 request_id、role、model_ref、messages、可选 tools、可选 response_schema、generation_options、timeout、metadata。Message 支持 text 与受控数据引用，1.0 不强制多模态。Provider 不支持 tools／JSON schema 时 fail fast；prompt fallback 必须是显式变体配置。

LLMResponse 包含 provider request ID、模型实际标识（可未知）、原始响应引用、标准化消息／工具调用、finish_reason、usage、timing、diagnostics。usage 的 input／output／cached／reasoning token 分别可 null；是否被包含在 total 的语义由 Provider 声明，不能重复计数。成本由版本化定价配置计算，不在源码永久硬编码在线价格。

429、5xx、连接问题可有限退避重试；认证、无效 schema、明确不支持请求不重试。所有真实尝试有独立 attempt_id，是否收费未知时记录 unknown。供应方处理后的超时不能宣称未产生调用成本。

## 5. 预算与候选选择契约

预算字段至少包括 max_llm_attempts、max_total_tokens、max_candidates、max_repairs、max_solver_calls、wall_time_s、max_concurrency。调用／候选／并发 admission 由核心原子计数；多 Agent 共享 run 预算，不能各自重复分配全额。

Token 阈值采用发送前估算＋最大输出预留和响应后结算；估算、未知供应方用量、最后一次调用越界分别报告。调用次数可严格限制，token／费用不能在供应方信息不足时伪称绝对硬上限。新调用必须在剩余预算不足时拒绝；未知结果保守占用预留，不直接当零。

方法的 Formulation 与 Code 调用共享 run 预算。阶段资源统计按 call_ids 关联，联合调用不能重复计费；分步调试实验的阶段输入固定并记录来源，使用隐藏参考表述辅助 Code 的实验单独标为 assisted。

方法可以用候选自身的约束检查、公开 solver 信息或自评来选择候选，不能借隐藏 benchmark 答案选择。选择策略写入 manifest/config；所有候选按记录保留，最终选定后不因评分失败偷偷换另一个。

## 6. 错误、取消与版本校验

统一 PluginError 包含 `code`、`stage`、`message`、`retryable`、`plugin_id`、`run_id`、`candidate_id`、`details_ref`。标准 code：CONFIG_INVALID、CAPABILITY_MISMATCH、DEPENDENCY_MISSING、AUTH_ERROR、RATE_LIMIT、PROVIDER_TIMEOUT、BUDGET_EXHAUSTED、DATA_INVALID、ARTIFACT_INVALID、COMPILATION_ERROR、EXECUTION_TIMEOUT、EXECUTION_OOM、SOLVER_ERROR、ORACLE_UNAVAILABLE、EVALUATION_ERROR、CHECKPOINT_INCOMPATIBLE、CANCELLED。

业务模型 infeasible 是 SolveResult；不自动包装成 SolverError。缺少参考答案是证据 not_available；评估器程序抛异常才是 EVALUATION_ERROR。未知插件异常保留脱敏 traceback 并转为稳定错误，不能使其他 run 退出。

Schema／plugin／IR／protocol 均记录完整版本。读入时校验声明版本；不支持的版本拒绝并报告原因，原事件和已保存输出保持不可变。新增问题类型或指标定义变化必须提升相关 schema／protocol 版本；报告禁止不说明地跨协议合并。

## 7. 接入完成的定义

每个插件交付 Manifest、配置说明、能力矩阵、至少一个成功 fixture、一个不支持或失败 fixture、取消／预算适用性与契约测试。原生方法另外交付上游提交锁、适配差异和复现实验；后端另外交付真实求解记录。此时才能在插件列表中标记 `verified`，而不是仅凭 import 成功。

## 8. ExperimentSpec 与单问题 RunConfig

已实现的 ExperimentSpec 0.1.0 使用 `schema_version`、`experiment_id`、`tasks`、`configurations`、`repeats`、`budget`、`exclusions`。`tasks` 中每项为 `{id, manifest}`，指向已冻结任务清单；`configurations` 中每项为 `{id, run_config}`，指向完整 RunConfig。相对路径基于 ExperimentSpec 目录，RunConfig 内相对路径仍基于其自身目录。任务 × 配置 × 重复次数展开矩阵，首个模型请求前完成全部未排除组合的公共输入、能力与依赖预检。`exclusions` 每项为 `{task_id, configuration_id, reason}`，不支持组合必须明确排除。

实验 `budget` 声明 `max_concurrency`、`wall_time_s`、`max_llm_attempts`、`max_total_tokens`、`max_solver_calls`。调度前预留完整单 run 的硬计数上限，已开始工作的预留在恢复时保留；当前不会回收未用上限。实验使用持久化绝对截止时间。每个并发样本通过已有 CLI 在独立进程运行，调用同一应用与评估接口；插件输出捕获不会跨样本共享。该配置不把 oracle 路径传给 RunConfig 或方法。

单问题 RunConfig 必需字段为 schema_version、method、llm、model_backend、solver、executor、budget、store；compiler 随 IR 路径需要，reporters、roles、evaluation 和 allowed_problem_types 可以按已声明默认值提供。公开问题由 SDK 参数或 CLI `--problem` 传入。它不要求 task、experiment_id、methods 列表、repeats 或 oracle_path；无 evaluation/oracle 时仍记录公开合法性与执行检查，独立检查为 not_available。示例见 [run.yaml](../examples/specs/run.yaml)。

单问题省略 evaluation 的明确默认值为 `llm4om.eval.public-v0.1` 与 `llm4om.evaluators.structural`，不隐式获取参考答案。省略 reporters 仍保存机器可读 RunBundle；是否额外呈现 Markdown 等格式由明确配置决定。

普通插件选择对象为 `{plugin_id, config}`，config 可为空对象；LLM 选择为 `{provider_plugin_id, model, config}`，solver 为 `{plugin_id, options}`。缺省 config 与 options 仅能使用 Manifest 中明确默认值，不能由插件静默选择模型或求解器。

每份 RunConfig 明确选择方法、默认 LLM、可选 `llm.role_models`、编译器、后端、求解器与执行方式。实验不隐式修改方法或模型来填补不支持组合。`experiment_id`、`case_id`、配置与 repeat 关联保存在实验记录，私有任务材料仅由 Task/Evaluator 读取。

实验目录保存公开 `experiment.json`、每个样本的原应用运行目录与公共评估，私有 `.private/experiment-state.json` 保存调度检查点与输入路径/hash。公开报告只导出选中样本 ID、资格、结果和来源，不导出冻结清单中的私有引用。继续执行要求输入 bytes、配置、SDK/source、Python 和插件执行身份一致；完成样本复用已保存结果，不重新调用模型。CSV 未知数值为空，JSONL/summary 未知量为 null；Markdown/HTML 明示 unknown。每个数据来源／协议／配置／repeat 独立统计，不将重复实验当成独立问题。

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
    formulation.json
    structured-ir.json       # when available
    code-artifact.json
    model.py                # when Code produced it
    build.json
    execution.json
    solve-result.json
  evaluation.json
  reports/report.md
```

失败时缺少的阶段文件不伪造，bundle manifest 明确当前终态和可用产物。内部私有 oracle、未脱敏 raw response 与凭据不在公开 bundle；raw LLM trace 可含敏感业务数据，按可配置的本地访问与导出策略保存，默认导出仅提供脱敏摘要。导出 oracle 或 raw trace 不是普通报告器的隐式行为。

### S01 已落实的离线子集

应用入口为 `run_problem(problem: Path, config: Path, *, offline=False, output_root=None) -> RunResult`；RunResult 包含 run_id、bundle_path 和 status。CLI 要求显式 `--offline`。此入口读取文件型 ProblemSpec／RunConfig；对象型 SDK、完整 MethodContext、Registry 和真实资源接口按后续切片落实。

`bundle.json` 使用 0.2.0，包含 run_id、mode=`offline_mock`、status=`artifact_ready|failed`、stages、error、model_artifact_ref、execution_plan 和 artifacts。artifact_ready 表示工程产物已保存，不是 MethodOutcome 的 candidate_selected，更不是求解完成；Candidate 仍为 proposed。error 为 null 或 `{code, stage, message}`；执行计划分别保存请求插件与实际 not_available 状态。所有 ArtifactRef 均以运行目录为 namespace 根，manifest 不包含自引用。

离线结构评估使用公开默认协议：Formulation 的字段和绑定检查通过时为 structural pass；Code 与语义检查为 not_available。严格 IR 此时只验证引用和数据绑定，完整编译语义归 S02-A。预算账本记录 Mock attempt／candidate 数量、external_llm_requests=0、solver_calls=0、total_tokens=null 和 cost=0；它不声称已实现外部预算预留或墙钟中断。

失败输入在存储可写时留下 bundle；存储错误由 SDK 抛出 OSError，CLI 返回退出码 2 和不含输入值的 store_unavailable。公开输入保留边界错误码，详细命令与 profile 见 [S01 实现记录](development/s01-offline-run.md)。

### S02-A 已落实的编译／求解子集

当前只执行 Mock 表述中明确提供的 grounded_lp 0.1.0，编译输出 python_factory 并关联源 Formulation、IR、symbol map 与数据 hash。工厂固定当前 revision，data 参数尚不重新绑定；参数化输入归 S02-B。自由文本、原生代码和真实 LLM 输出不进入当前编译入口。实际命令、版本与数值边界见 [S02-A 实现记录](development/s02-highs.md)。

RunConfig 可以显式选择 trusted_local，config 为空对象；container 由 S04-A 实际执行，也可离线回放，不会自动降级。solve extra 提供 Pyomo／HiGHS，缺失依赖或零 Solver 预算在 Mock 前拒绝。当前 Solver options 只支持 time_limit_s，实际容差和原生数值阈值随结果保存。

真实 bundle mode 为 trusted_local，执行完成为 completed；termination 与 primal 可用性由 SolveResult 分别表达。增加 solve_result_ref、execution_result_ref 和 final_candidate_id；执行错误仍保存已完成阶段。编译前快照与最终候选分别保存，旧事件引用不可失效。Code 的编译检查通过不推导 semantic_validation 通过；infeasible／unbounded 是实际结果。ExecutionResult 的 exit_code、CPU 与内存未测量时为 null。solver_calls 计 Solver 适配器尝试，外部 LLM 请求仍为零；容器资源限制由 S04-A 实施；当前取消／恢复与固定预算见 S04-B；完整多方法／batch 预算仍按后续切片落实。

### S03 已落实的方法 profile 与预检子集

SDK 的 entry point 分组 llm4om.plugins 导出 describe／create(config) 对象，S03-A／B初始版本只装载method；SDK0.18.0的Provider扩展见第23节。Manifest 的 capabilities.method_profile 为 grounded_single_candidate/0.1.0；plugin_version 当前为稳定 major.minor.patch，contract_range 为 `>=X.Y.Z,<A.B.C` 并包含核心契约 0.2.0。config_schema 自包含，允许本地片段引用，暂不接受 $id 或远程 $ref／$dynamicRef；dependencies.python 为分发包名称列表，记录已安装版本。source 暂不接受额外 ArtifactRef，研究 URL／固定版本／变体等文字元数据可保存。

当前 async run 返回内存 MethodOutcome：status=candidate_selected、final_candidate_id=001、proposal=ModelProposal(artifact, formulation, structured_ir)。核心验证原问题 hash／revision、声明的 Formulation 和数据绑定，生成实际引用与候选记录；多 revision／原生脚本资源见第 14 节，内部 checkpoint 扩展见第 12 节。MethodContext 提供 llm、只读公开 data／预算上限和 problem_sha256，以及可选运行资源。LLMResponse 提供 text、call_id、evidence_origin、source_sha256，以及可选 finish_reason；真实 Provider 完整 usage 与身份保存在 Gateway trace。

doctor 与 run 共用 prepare_run；先验证参数，再匹配当前表示、目标类型、Backend／Solver、Provider 功能和 Executor，再检查分发包与真实求解依赖。缺失能力为未知；请求的资源须被方法声明，当前表示 profile 固定，不能靠枚举并集暗示 native_code 可用。allowed_problem_types 缺省 lp／milp，实际 IR 类型在产出后再次核对。真实运行保存 admission_plan_ref；离线计划只准备回放，不标记 Code／Solve 已执行。未知方法异常与 SystemExit 转为稳定错误和脱敏 frame，原错误参数／源码行与插件 Python 输出不进入公开结果。

示例、字段级诊断、实际版本和未实现项见 [S03](development/s03-plugins.md)。S03 不执行真实连通性检查，不加载 .env；后续 Provider 工作树实现见 S05-A 子集。SDK 包、核心对象 0.2.0、IR 0.1.0 和 profile 0.1.0 分别管理。

### S04-A 已落实的容器子集

container 配置必须包含 network=false、正 cpu_limit、整数 memory_limit_mb 和正 wall_time_s，可选 image、整数 pids_limit 和整数 output_limit_bytes。省略 image 使用 SDK 对应 Worker tag；admission 将它解析为本地不可变 image_id，检查真实 Worker 运行时，候选执行使用同一 ID。没有自动 pull 或本地降级。

公开 Executor 为 run_container(command: list[str], inputs: Mapping[str, bytes], limits, *, image) → ContainerExecution。输入只能是安全相对路径与公开 bytes；方法 Context 不获得此低层接口。实际求解由核心选择可信 Worker 入口，仅发送严格 IR、实际编译代码、Solver options 和公开 CSV。Worker 验证 IR／实际 CodeArtifact 的 hash，并经平台 Solver API 产生结果。

ExecutionResult 增加可选 worker_status、image_id、container_id、container_name、oom_killed、oom_evidence、restrictions 和 executor_diagnostics；stdout／stderr 为有界文件引用。oom_evidence 为 docker_state／docker_event 或 null；只使用实际标记或同容器的 daemon 事件，不从 137 推断原因。资源超限为 execution_timeout／execution_oom／execution_output_limit，SolveResult 缺失；已生成 Formulation／Code 保留。Docker 控制失败为 executor_error，缺环境为 executor_unavailable，非法直接 Executor 输入为 invalid_execution_request。控制与清理有界，失败保留实际退出／输出／容器身份和诊断，不用默认值伪造缺失测量。

固定策略、真实测试与当前限制见 [S04-A](development/s04-container.md)。它只交付 grounded LPIR 的容器路径和可复用 Executor；参数化工厂、原生代码、完整预算、取消／恢复均仍按开发计划实现。

### S05-A 文本 Provider 子集

公共接口保持 LLMGateway.complete(request) 与 MethodOutcome／ModelProposal。Provider factory 由 provider_plugin_id 选择并独立校验 config、text 能力和凭据，不依赖方法 ID。S05-A初始factory内置Mock与openai_compatible；后续Messages见S05-B，SDK0.18.0独立Provider见第23节。Provider 的 stdlib HTTP adapter 是窄 TextProvider，同步 complete(messages, timeout) 返回规范化文本和 usage；Gateway 提供方法使用的 async 接口并拥有资源控制。

openai_compatible 配置为 base_url、credential_env，另有 max_output_tokens（默认 1024）、max_retries（默认 2，范围 0～5）、timeout_s（默认 30）。只接受非流式 text；请求字段仅 messages、可选 request_id／role。doctor 优先读取配置目录 literal .env，不存在时读取当前工作目录 .env；进程环境优先，但不发请求。Credential、header 与 URL 凭据在公开投影边界拒绝，凭据值不进入配置快照、Context 数据或 Worker。

Direct 使用完整公开问题及 CSV 值，外部回复只能是 representation 和 structured_ir 两字段的紧凑数学对象。平台生成 artifact／formulation／IR ID、revision、数据 hash、引用与 provenance。representation 的五元素语义与 GroundedLPIR 数学字段复用本契约；紧凑 IR 只含 problem_type、variables、objective、constraints、assumptions。五元素与 IR 是联合生成，Code 是确定性编译；未取得语义证据时仍为 not_available。finish_reason=length 时 Direct 返回 llm_output_truncated，保留 trace 和用量，不形成 Formulation。旧 Mock packet 与独立方法 fixture 保持有效。

Gateway archive 是共享 run 资源身份。文件锁原子 admission，OS slot 锁限制并发；每次 attempt 使用独立 UUID。省略 request_id 时每次调用使用独立 UUID，相同消息可独立采样。显式 request_id 用于恢复；内容 hash 同时绑定端点／模型／输出上限／消息。预算与 deadline 恢复不重置；不同预算拒绝恢复。已保存成功直接复用，未知身份拒绝重新发送并保留预留。S05-A 单独不提供 CLI resume；S04-B 的公开恢复与内部 checkpoint 见第 12 节。

发送前按规范化输入 UTF-8 字节数估算 token，加最大输出预留；实际 total 可用才结算预留。input／output／total／cached／reasoning 缺失均为 null，cached 与 reasoning 不重复计费。无定价时 cost=null。结算后计入未知 attempt 的预留；最后调用实测占用越界返回 token_budget_overrun，并保留成功回复。429／5xx／连接故障有限重试，认证／无效请求／非法响应／超时不重试；失败 charge／usage 未知时保守保留预留。共享绝对 deadline 约束请求 timeout、重试、Docker 检查／create、Worker 启动、容器墙钟和 Solver time_limit（清理允许有界额外时间）；HTTP 在可终止子进程中执行，完整 deadline 覆盖 DNS、TLS 和持续滴流；取消回收进程并保留未知结果的预留。

公开 llm-trace.json 只包含身份／hash、模型／role、start／end、finish_reason、usage、reservation 和稳定诊断。原始回复与恢复状态存于公开运行目录之外的 .private/run_id，目录 0700、文件 0600，不列入 bundle。详细字段、配置、限制与验收命令见 [S05-A 实现记录](development/s05-provider.md)。已有本地 HTTP 接缝与两个真实外部模型／容器案例；具体证据见实现记录。完整 1.0 仍按开发计划验收。

## 7. S07-A local Task / Evaluation interface (implemented)

S07-A was delivered in unreleased0.4.0; its existing snapshot protocol remains unchanged in SDK0.10.0. `TaskAdapter.iter_cases(config: Path)` yields frozen
`EvaluationCase` values. For `NL4OptAdapter`, config is the imported `manifest.json`.
The case carries `case_id`, public ProblemSpec path, privileged `oracle_ref`, frozen manifest
bytes and frozen entry bytes. Pass only `case.public_problem` to `run_problem`; never pass
an EvaluationCase or its manifest to a method, Gateway or Worker.

`import_dataset(config: Path, output: Path) -> Path` returns a frozen manifest path.
The import config is schema 0.1.0 with exactly `dataset_id`, `source_kind`
(official/fixture/fork), `source_version`, `split` (train/dev/test), `path`, and `sha256`.
Paths are relative to the config directory and must remain within it. Official identity is
`nl4opt` at competition commit `49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea`, with the fixed
split hashes in [source research](development/s07-nl4opt.md). Fixtures/forks must use a
separate dataset ID and version. No fetch, source-directory mounting or registry is added.

Import validates the whole split before acceptance: exact byte hash, UTF-8 LF JSONL,
unique JSON keys, finite values, one signed decimal original ID per record, unique IDs,
upstream ID consistency and the known record field/type schema. Unknown record fields
are rejected. Annotations are preserved, not translated into mathematics. The original
`document` alone supplies the description; domains are unspecified and type hint is unknown.
Public ProblemSpec 0.2.0 contains source identity but no case/oracle references or source paths.

Snapshot layout: `public/<sample-id>.json`, `private/<sample-id>.json`, `manifest.json`.
Official snapshots also retain the fixed MIT `LICENSE`; redistribute it with public projections.
Public/private references have `task_public` / `task_private` namespaces and schema versions.
The private directory has mode 0700, annotations 0600. The manifest is privileged because
it contains oracle references. Public export means the public directory and public run
bundle, never the whole snapshot. Manifest schema 0.1.0 locks projection, protocol, source,
line/record hashes, public/private artifact hashes, reference quality, eligibility and reasons.
Import cannot overwrite an existing snapshot. Iteration checks content hashes.
`NL4OptAdapter.load_case(manifest, case_id)` loads validated frozen metadata for evaluation;
material checks run inside the Evaluator so changed or missing files produce saved error results.

`Evaluator.evaluate(case: EvaluationCase, outcome: Path) -> dict` consumes a persisted
run directory after modeling. `NL4OptEvaluator` implements raw-declaration protocol
`llm4om.eval.nl4opt-raw-v0.1`. `evaluate_case(manifest, case_id, outcome, output)` and CLI
`evaluate` save one public result to a new file; existing output is not overwritten.
Failures remain results; malformed or changed evidence produces `checker_error` and error
states, never a pass. All declared run artifacts are hash/size checked before using stage
validation flags. Unknown case/invalid manifest metadata is an admission error; changed or
missing case material is a persisted evaluation error. A failed run
before public-input persistence has `case_binding=not_available`; it is an attempted case
association, not verified input identity. Otherwise the exact public revision must match.

Result retains protocol, source, manifest/record hashes, projection/domain/normalization
policies, exclusion reason, reference quality, selected/eligible counts, run error and separate
structural, execution and solver-reported candidate primal evidence. It contains no oracle
paths or annotations. Structural evidence is not semantic verification. S07-A itself introduced no new method
or execution contract; S02-B originally used Worker image 0.5.0; the current image is 0.6.0.

## 10. S02-B parameterized factory interface (SDK 0.5.0)

`DirectFactory` accepts `output_mode=lp_ir|python_factory`. Its optional public declaration
`resolve_capabilities(config) -> dict` receives schema-validated method config and returns
**the full capabilities object** for that configuration. Discovery still uses `describe()`;
preflight validates and records the resolved declaration. Other installed factories may use
this same seam, or a static factory profile. Old factories without it retain their existing
Manifest behavior. Core does not inspect method IDs or plugin-specific config keys.

`factory_single_candidate/0.1.0` requires five-element Formulation, python_factory, Pyomo,
HiGHS, public data only, and container execution. Both `doctor` and `run` reject offline or
trusted_local before generation. Grounded profile stays `grounded_single_candidate/0.1.0`.
The compiler selection is required only for grounded LPIR. It is unused for supplied Code;
admission records `compiler_id=null`, `code_origin=method_generated` for factories.
S02-B introduced SDK/Worker 0.5.0; current tag is 0.6.0; core objects remain 0.2.0 and grounded LPIR 0.1.0.

An independently installed method returns:

```python
from hashlib import sha256
from llm4om import FactoryCodeProposal, ModelProposal, MethodOutcome

code = FactoryCodeProposal(
    source=source,  # exact UTF-8 Python source, not an IR fixture
    source_sha256=sha256(source.encode("utf-8")).hexdigest(),
    data_bindings=bindings,  # current public data IDs and raw byte hashes
    schema_version="0.1.0",
)
proposal = ModelProposal(artifact, formulation, code=code)
return MethodOutcome("candidate_selected", "001", proposal)
```

Artifact input uses existing pending-Code envelope. Source Formulation has
`structured_ir_ref=null`, the current problem ID/revision, and validated public bindings.
Factory profile requires Code alone, not a jointly supplied original IR. Source/hash, version,
Formulation and data bindings are validated without running source on the host. Supplied
source, Formulation and proposal metadata are saved before binding/contract rejection.
Persisted CodeArtifact has `factory_contract=python_factory/0.1.0`, `entry_point=build_model`,
exact `representation_ref`, `source_formulation_ref`, backend, bindings and method-generated
provenance, including the actual method declaration and generation provenance. Generation
can be hand-authored fixture or external Provider; method-generated does not imply an LLM
was called. No supplied Python is relabelled deterministic compilation.

Direct's compact external reply is exactly `{representation, python_factory}`;
`python_factory` is a source string. In grounded mode it remains `{representation, structured_ir}`.
A factory defines `build_model(data)` with `data: Mapping[str, bytes]`, keyed by public
`data_id`; no credential, oracle, host path or backend object is sent through that mapping.
It returns `llm4om.backends.ModelHandle(model, decision_map)` in the factory child.
The handle contains a constructed Pyomo ConcreteModel and a one-to-one mapping from
explicit stable decision IDs to **every** active scalar variable. Only closed real/integer
intervals and binary domains, finite supported numbers, linear expressions, bounded
constraint rows and exactly one active objective are accepted. Fixed variables, open or
noninterval domains, nonlinear expressions and unknown active components are rejected.
Ranged constraints become two rows; objective and constraint constants are preserved.

`PyomoFactoryBackend.load(source, data)` and `export(handle)` are Worker-local construction
interfaces. Host application never invokes them. The child exports only a versioned-request
instance view and decision component names; no Python model or handle is serialized back.
The trusted collector validates exported LPIR, checks problem/revision/data/source identity
and allowed LP/MILP type, then builds a fresh deterministic model and obtains evidence from
the existing native HiGHS interface. Child stdout is never a SolveResult channel. Child
prints go to bounded diagnostics; malformed or forged exports fail validation. The read-only
container prevents installed Solver code modification; parent dumpability is disabled to
prevent same-UID child access to collector memory and `/proc` parent fds. See [ADR-0005](adr/0005-factory-collector-isolation.md).

The bundle retains original Formulation/Code, plus an `optional_views` reference to
`factory-instance.json` and `decision-map.json`. Their origin is `factory_exported_instance`,
with source hash, current bindings and problem revision. This is an extracted candidate
instance, not original Formulation, deterministic compilation of supplied Python, or semantic
proof. Code validation level is `factory_contract`; successful solver evidence remains
`trusted_container_worker`. Structural checks and independently checked business semantics
remain separate. The NL4Opt evaluator derives Code level from its actual provenance.

Construction and solving share container wall time, memory, CPU, PID and total output limits.
Child capture is additionally bounded, with timeout and process-group cleanup. No failure
creates a SolveResult. Exceptions, invalid handles/maps, nonlinear/domain errors, stale
bindings and unsupported versions preserve supplied artifacts and diagnostics; preflight
failures happen before a method can produce new artifacts. Missing Docker never falls back
to local Python. See [S02-B evidence and limits](development/s02b-factory.md).


## 11. S06-A Gurobi and native Code (SDK 0.6.0)

Current support and actual local evidence: [S06-A](development/s06-gurobi.md).
Core objects remain 0.2.0; LPIR and proposal schema remain 0.1.0. SDK/Worker are 0.6.0.
RunConfig Solver IDs accept `llm4om.solvers.highs|llm4om.solvers.gurobi`; Backend IDs accept
`llm4om.model_backends.pyomo_factory|llm4om.model_backends.gurobipy`.
`time_limit_s` is finite and nonnegative (zero requests an immediate limit). No arbitrary SDK options
or license parameters are admitted. Effective options and native numerical limits accompany results.

The resolved grounded and Pyomo factory profiles may declare Gurobi; installed methods must declare
it explicitly. `native_single_candidate/0.1.0` requires five_element Formulation, `native_code`,
gurobipy Backend, Gurobi Solver, public data only and container execution. Direct resolves this profile
only for its declared `output_mode=native_gurobipy`. Core never infers plugin config or branches on
method IDs. Both doctor and run use this compatibility/dependency seam before generation.

`FactoryCodeProposal` adds `representation_kind` with default `python_factory`; native methods set
`representation_kind="native_code"`. Source/hash/bindings/version remain required. The representation
must match the resolved capabilities. Native persisted CodeArtifact retains `representation_kind=native_code`,
`factory_contract=native_gurobipy/0.1.0`, `entry_point=build_model`, native Backend and original source
Formulation. Direct's native compact response is exactly `{representation, native_gurobipy}`.
Neither original source nor Formulation is replaced by an LLM-written universal IR.

`GurobiFactoryBackend.load(source, data)` uses the same isolated Worker-only build_model(data) entry;
`export(handle)` writes SDK MPS and maps explicit decision IDs to every unique scalar variable name.
The child protocol contains base64 MPS bytes and mapping, never a solution. Names with whitespace
are rejected for MPS transport. The trusted collector uses a fresh SDK environment/model to read,
validate and optimize the native model; it does not call candidate optimize or read candidate X/ObjVal.
`ModelHandle` stays Worker-local. Supported native structure is single-objective linear LP/MILP;
quadratic/general/nonlinear/multiobjective/scenario/SOS/PWL and semi-domains fail before optimization.
Range slack variables must be explicitly mapped. SDK model constants, sense, bounds, types and linear rows are preserved in MPS transport. MPS cannot confer semantic equivalence to source or business requirements.

Optional views retain `factory-instance.json`, `decision-map.json` and native `native-model.mps` with
origin `native_exported_instance`, source hash, bindings/revision and relationship
`extracted_instance_not_source_formulation_or_semantic_proof`. Pyomo view origin remains
`factory_exported_instance`. Code validation level remains `factory_contract`, distinct from deterministic
compilation or semantic correctness. The Evaluator recognizes both actual Code contracts.

Gurobi API results use `trusted_gurobi_api` internally and `trusted_container_worker` in persisted
container results. The Worker protocol validates selected Solver, package version, Backend, runtime,
primal consistency and fields. Raw status is the SDK integer rendered as a string. Statuses 2/3/4/5/9/11
map to optimal/infeasible/infeasible_or_unbounded/unbounded/time_limit/interrupted; others remain unknown.
SolCount gates primal/vector/objective. Unavailable or nonfinite bound/gap is null. Runtime is actual SDK
Runtime. Options come from the platform, not candidate state or a model-file settings file.

Selected Gurobi runtime packages are Pyomo/gurobipy; optional SDK discovery and bounded doctor probes
record `solver_environment={availability,micro_model_verified,size_boundary_error}`. Availability is
`size_limited` on actual SDK error10010, otherwise `micro_model_available_size_limit_not_observed`.
No full-license conclusion follows. Public output excludes license identities/details/logs.
Base-only SDK installation can use container solving; host Gurobi absence does not break HiGHS/offline.

Finite Pyomo bounds and normalized row RHS must have magnitude below 1e20. This is the SDK
semantic infinity threshold, distinct from `GRB.INFINITY=1e100`. Result numerical limits record both.
Native row RHS is checked at the same threshold; the native view describes the already-built SDK model.
A `ModelHandle.decision_map` accepts any Mapping, including a read-only Mapping, under both Backends.

## 12. S04-B cancellation and resume (SDK 0.7.0)

`run_problem(..., cancellation: CancellationToken | None = None)` 保持旧调用兼容。
`cancel_run(run: Path) -> str` 返回 cancellation_requested／inactive；只写绑定 run_id／owner_uid／owner_id 的控制请求。
`resume_run(run: Path, *, cancellation=None, strategy="continue") -> RunResult` 默认使用同一运行、预算、私有 Gateway archive 和绝对 deadline。
`strategy="rerun"` 显式创建派生运行，重新执行方法；它不是方法内部 checkpoint 恢复。
CLI 为 `cancel|resume --run-id RUN_ID --output STORE_ROOT`；resume 可加 `--strategy continue|rerun`，默认 continue。run／resume 的 SIGINT 走相同协作路径。

核心 checkpoint.json 为 0.1.0 envelope，含 payload 和规范化 JSON 的 SHA-256。
payload 保存 run_id、不可变 ArtifactRefs、递增事件、当前公开视图的引用、核心阶段状态、原公开输入／配置 hash、
admission／SDK／Python／包身份、方法内部 checkpoint 和预算／资源位置。
文件经 fsync／原子 replace 发布；owner.lock 防止并发写者，control.lock 串行化控制身份更新。
新建 run、history、checkpoint、私有 archive／journal 的每层目录项先在其父目录 fsync，再发布引用其文件的记录。
原文件权限与新 run 的独占创建保持不变；OS fd／rename 验证不等于物理断电验收。
内容文件保存在 history/hash/path，原引用不改写；固定路径为当前公开视图。
checkpoint 的原始 bytes 另存于 checkpoints/hash.json；checkpoint.json 原子提交选择当前一致版本。
公开视图替换前，publication.json 保存基于该 checkpoint hash 的写入意图与 owner_id、目标不可变引用。
只有 owner 锁已释放、control 仍 active、owner_id 与基线 hash 均匹配的中断，才允许协调未提交视图。
恢复先校验全部不可变 bytes，再确认视图只含已提交或已记录的未提交 bytes，然后重建 checkpoint 视图。
修复视图前，核心 checkpoint 的 interrupted_publications 保存已验证的中断引用；对应不可变 bytes 纳入 refs。
未提交的新视图删除，但该收据与不可变历史保留，身份校验失败或再次中断不会丢失唯一恢复证据。
存储只提供已验证的中断引用及重新发布操作；应用决定哪些记录代表完成的 Formulation／Code 或 Execution／Solve。
已提交视图或不可变引用的真实损坏仍返回 checkpoint_incompatible。
OS atomic rename／fsync 是存储故障注入边界；协作取消测试使用公开 Method／资源和 SDK Token／事件记录。
不序列化 ModelHandle、Solver SDK 对象、credential、oracle 或 pickle。

MethodContext 兼容增加 cancellation 和可选 save_checkpoint(versioned_json) 回调。
只有 supports_checkpoint=true 的方法可保存／接收内部 checkpoint；核心阶段恢复与该能力独立。
MethodPlugin 向方法传入 checkpoint 的深拷贝。插件的原地修改只有经 save_checkpoint 才提交；Gateway 的资源回调不能隐式提交未保存的方法步骤。
Direct 声明 supports_checkpoint=true，仅保存 0.1.0 的 request_id；稳定请求内容仍由 Gateway hash 核对。
插件可声明 cancellation=cooperative/0.1.0，须让出 async 执行并检查 Token，遵守任务取消；
未声明时 admission 的 method_cancellation=unknown，不能据资源可取消就宣称插件内部有界。
独立 fixture 仍 supports_checkpoint=false，声明 cooperative，拒绝非空内部 checkpoint。

核心在调用方法前提交 method_started 标记。已开始的方法既无完整阶段也无内部 checkpoint 时，continue 返回 checkpoint_unsupported；
尚未调用方法的 admitted 阶段可以从头进入方法。显式 rerun 可重新执行不支持内部恢复的方法。
派生运行的 RunBundle.lineage_ref 指向 immutable lineage.json，记录 operation=derived_rerun、parent_run_id、
input_hashes、父 checkpoint 引用、父公开历史副本、parent_budget_ledger、parent_resource_records 和 reused_records。
语义重跑不复用父模型回复／Solve，reused_records 为空；已有证据副本不冒充新方法输出。
新 run 使用新的 deadline，但父 paid／unknown 尝试、已知 token、未知 reservation 和 Solver 次数仍计入原配置上限。
不足时派生 run 明确 budget_exhausted，不能通过重复派生忘记费用或未知预留。rerun 可产生新的付费请求，须由用户显式选择。
完整 Formulation／Code 阶段直接继续；匹配的 execute_done 复用保存的真实 Execution／SolveResult。
Formulation 的 artifact_ref、stages、候选计数与 method_done 随 formulation_saved 一起提交。
Code 的 build 记录先保存，artifact_ref、stages 与 code_done 随 code_saved 一起提交；方法直接提供 Code 时也使用同一顺序。
完整 ModelArtifact 已发布但核心尚未提交时，先协调已验证的 interrupted_publications，再判断 checkpoint_unsupported。
协调只读取收据中的不可变 ModelArtifact，验证完整引用图、公开问题、Formulation／数据绑定与准入方法身份；
方法提供的 Code 保留原 source_formulation_ref、源码引用、后端与来源，不从公开投影拼造 ModelArtifact。
成功后复用原 artifact_ref，补齐候选及核心状态并提交一次完成事件；不调用方法或 LLM，不消耗新 attempt。
真正尚未完成的方法仍遵循上述默认拒绝／显式派生重跑规则。SDK 源码身份严格匹配，不承诺旧源码 checkpoint 迁移。
Execution／SolveResult 引用和 execute_done 在 solver_finished 事件之前一起提交；发布完成事件后的崩溃不再重复求解。
公开 completed Execution 先于 execute_done 落盘时同样复用。Execution 记录 run_id、execution_id、solver_call、
input_artifact_ref 与执行后的 artifact_ref，分别绑定核心已准入的尝试、原候选与含提取视图的候选。
恢复先验证中断引用及实际不可变依赖，再核对原候选、Code／Formulation／数据绑定、Solver 结果结构／版本／来源和 Worker 身份。
通过后重新发布记录并提交 execute_done；不新增 Solver admission，也不从任意公开文件或 stdout 取结果。
匹配由已验证的公开 bytes、数据绑定、固定配置／Manifest／包及 Worker 身份共同确定。
completed／artifact_ready 恢复幂等；其他过期恢复返回 deadline_exhausted。
solver_calls 在尝试前持久化，取消不退还已开始的 slot；下一尝试需要原预算中剩余 slot。

Gateway admission／settlement 先写 journal/hash.json 不可变版本（0.1.0、previous_sha256、state），
再原子更新私有 state.json，最后回调保存核心资源 hash／账本。两处存储不声称跨文件系统事务。
恢复验证完整单链、核心已知 hash 位于链上、当前 state.json 精确匹配链中版本、固定 archive／Provider／
预算／deadline／请求身份、只追加 attempt 与一次结算、usage／reservation 和 raw response hash。
按链顺序检查 mutable head 必须等于或晚于核心已提交 hash；有效的旧 genesis 也不能覆盖已提交 settlement。
已验证的新 journal head 可前进于核心引用或 mutable head；其预留和成功回复仍保留。破坏链或实际 bytes 仍拒绝。
archive／journal 目录为 0700，私有文件为 0600，不保存 API credential；只公开脱敏 trace 与累计资源账本。
成功回复复用既有 attempt_id；未知结果保留预留并返回 provider_outcome_unknown，不重新提交相同 request_id。
私有 raw reply 不进入公开 checkpoint。Mock 的同请求工程回复可持久化复用，仍 external_llm_requests=0。
首次 journal 已提交而 state.json 尚不存在时，只恢复经过验证、没有请求的单个 genesis 版本；已提交资源的 head 缺失仍拒绝。
Gateway.recover(archive, expected_sha256, budget, deadline, inherited_ledger) 在资源锁内校验日志与预算，
返回 RecoveredResources(ledger, trace)，不要求 API key。公开 trace 使用明确字段列表，应用层不读取私有响应／日志字段。
HTTP 响应的解码 JSON 键和所有字符串值也检查凭据回显，包括转义后的内容；检测到回显先于归档失败。
容器和 HTTP 子进程使用已有有界清理；trusted_local 的严格 IR／运行时检查也在拥有的子进程执行。
生成的工厂或 native 源码始终只在隔离 Worker 内执行。

S04-B RunBundle 兼容增加 public_problem_ref 和 public_projections（固定路径 → 不可变 ArtifactRef，排除 bundle 自引用）。评估器同时校验版本引用与当前公开视图，接受 cancelled 并保留评测分母；旧 bundle 的固定路径仍可读取。TaskAdapter 的 write-once snapshot 保持原 public/ 与 private/ 布局，资源控制／history 只属于运行。

## 13. S05-B Messages Adapter (SDK 0.8.0)

`llm4om.providers.anthropic` 是独立的非流式文本 Messages Adapter，与 OpenAI-compatible 共用
HTTP 子进程和 Gateway。`provider_factory(id)` 返回声明 `provider_type` 的 HTTPTextFactory；
该 Adapter 的 `decode_reply(value)` 同时用于实际响应与 journal 校验。核心恢复不按 Provider ID
切换解码规则，也不读取凭据来校验已保存的响应。原 OpenAI 解码和 journal 布局保持兼容；
完整 run 仍要求原 SDK 版本、源码 hash、Python／依赖及 Worker 身份一致，不自动迁移旧运行。

配置字段与 OpenAI 文本路径相同：base_url、credential_env、max_output_tokens、max_retries、timeout_s。
Messages 发送 POST `base_url/messages`，带 `anthropic-version: 2023-06-01` 和 `x-api-key`。
system 消息按出现顺序移到顶层 system 文本块；user／assistant 的顺序与文本块边界保留。
共同 Gateway 的 messages.content 接受字符串或非空 `{type: text, text: string}` 数组。
不支持工具、response_schema、图片或流式请求；Messages 的 doctor 配置和 Gateway 请求均以
capability_mismatch 提前拒绝这些能力。其他未知配置仍为 invalid_config，不做自动 fallback。

响应必须是 assistant message，包含合法 content 数组。text 块按顺序拼接；thinking 和
redacted_thinking 仅保留在私有原始响应，不冒充公开文本或 reasoning token 测量。
未知／畸形块、缺失 content 和非法 usage 以 invalid_provider_response 失败，不重试。
仅有 thinking 的 max_tokens 响应可保存为空文本，并让 Direct 返回 llm_output_truncated。
stop_reason 原样记录；end_turn／stop_sequence 映射 finish_reason=stop，max_tokens 映射 length，
其余字符串原样保留，缺失为 null。实际 message id、model 和 request-id header 可未知；不补写请求模型。
原始响应 SHA-256 按 HTTP body bytes 计算。响应 body、解码后的键／值和 request-id 中含凭据则失败，
不写入响应 archive 或公开 trace。错误 body 不存储、不回显。

Messages usage 归一化为：input_tokens = input_tokens + cache_creation_input_tokens + cache_read_input_tokens；
cached_tokens = cache_creation_input_tokens + cache_read_input_tokens，是输入子集；
output_tokens 使用实际 output_tokens；total_tokens = 归一化 input_tokens + output_tokens。
任一加数缺失／null，则对应和为 null；0 是真实已知值。非法类型、负值、非有限值拒绝。
reasoning_tokens 与无定价来源的 cost 恒为 null；不能由 thinking 文本或模型名字推测。
原始各分量留在私有响应，可由响应 hash 核对。

Gateway 保留既有 attempt／并发／token 预留／绝对 deadline／取消所有权。429、5xx（包括529）和
连接错误按 max_retries 有界退避；400 等请求错误、401／403（共同 auth_error）、超时和非法响应不重试。
成功缺少 total 仍保留预留，失败／取消保留未知结果。已持久化成功在 core 回调之前或 mutable head
之前崩溃，仍经不可变链校验后复用；未知 request_id 不重发；真实损坏拒绝。
已完成身份校验不构造凭据 Provider；未完成恢复通过 factory.restore 延迟凭据解析，仅真正新增
HTTP attempt 时读取。成功回复回放与未知 request_id 检查不要求 API key，也不读取凭据文件。
TextProvider.prepare() 是本地、幂等的准备接口；HTTP Adapter 复用 factory 的凭据校验，
成功后在该 Provider 实例内固定凭据。Gateway 在资源锁内先检查保存记录、deadline 和预算，
再调用 prepare()，复查取消与 deadline 后才持久化 attempt／预留；准备失败不增加请求或预留。
补回有效凭据后，同一 run／request_id 可继续。同步 complete 与异步 acomplete 的直接调用也先准备；
已准备的 transport 与重试不重新读取环境，避免 admission 后再发生本地凭据错误。
真正发送后的 HTTP 认证失败仍保留实际 attempt 和未知费用。显式 rerun 的既有累计资源语义不变。

## 14. S06-B native script resources (SDK 0.9.0)

Status: implemented development interface; remaining acceptance is recorded in
[S06-B](development/s06b-optimus.md). Existing0.2.0 CSV/five-element profiles
remain valid. ProblemSpec0.3.0 also accepts JSON object data with
`format=json`, `schema={type: object}`, a public relative path and SHA-256.
Duplicate keys, nonfinite values, reserved oracle material and non-object JSON
are rejected before generation. Every file has an8MiB bound; original bytes
are retained. JSON is not silently converted to CSV or given invented columns.

Native Formulation0.3.0 has `representation_kind=native_formulation`,
`representation={schema: <declared source-state schema>, state: <original JSON object>}`,
problem identity/revision, data_bindings, provenance and structured_ir_ref=null.
Bindings cover the admitted public files and hashes. This stores original
source states without fabricating five-element content or semantic evidence.

The `native_script/0.1.0` method profile requires native_formulation,
native_script, gurobipy, Gurobi and container execution. Offline/HiGHS/local
execution and undeclared combinations reject admission before paid calls.
`MethodContext.resources` is an optional mediated `MethodResources` interface:

```python
class MethodResources(Protocol):
    async def execute(self, execution_id: str, code: ScriptCodeProposal) -> dict[str, Any]: ...
    def record(self, name: str, value: bytes) -> ArtifactRef: ...
    def emit(self, event: dict[str, Any]) -> None: ...
```

SDK0.15.0 supplies public record/emit resources to admitted methods. Script
execution remains restricted to the native-script profiles; candidate assessment
uses the explicitly admitted profile in section 20. Context also carries the original absolute
`deadline`; existing cancellation and save_checkpoint contracts remain.
No hidden evaluator, credential or unrestricted host execution is supplied.
Artifact names are bounded basenames under `method/`; JSON artifacts are
validated. ScriptCodeProposal0.1.0 contains original source, source_sha256,
exact public-derived data_json bytes and data_bindings. A selected ModelProposal
contains the matching execution_id. CodeArtifact0.2.0 retains source_formulation,
source bytes, `factory_contract=native_script/0.1.0`, `entry_point=code.py`,
data_json_ref and execution_id; it does not claim a build_model factory.

Execution feedback contains source exit/status/stdout/stderr, original source
and data refs, untrusted capture refs, optional trusted solve_result_ref and
collector_error. Source exit and collector status remain distinct. The raw
script runs in a protected child inside the read-only, network-disabled Worker;
its capture is a candidate transport. The fresh collector validates MPS,
variable map and supported structure before solving through actual SDK APIs.
Source text/stdout/capture attributes cannot assert trusted result fields.

Each script attempt consumes one Solver slot; a supported capture's collector
consumes another. Two available slots are required before script admission.
Ledger counters retain script_executions, collector_calls, capture_attempts,
hook_optimize_observations and separate admission_solver_probe_calls.
source_optimize_calls=null and source_optimize_measurement identifies untrusted
hook observations: arbitrary Python can bypass the hook, so the platform cannot
assert an exact in-script optimize count. Existing wall/CPU/memory/output bounds
still constrain the execution. Failed calls stay in the denominator.

Execution IDs bind exact source/data hashes, data bindings and frozen admission.
A complete verified result is reused; unknown admitted execution is not retried.
Interrupted complete publication can be reconciled from verified receipts.
Cancelling stops the owned script container and the fixed-source driver; a
killed driver's pipes are drained before its event loop closes. Completed
resume needs no new credential, model request or Solver call.

OptiMUS uses the fixed default main (EC=true, RAG=None). All source calls use
Gateway and deterministic replay IDs. The original three-execution repair loop
and last-successful-executed selection remain; an unexecuted final repair cannot
be selected as solved. Requested RAG modes fail before paid calls until actual
compatible rights-cleared corpus/index/embedding resources are admitted.

## 15. S07-C MAMO Task interface (SDK 0.10.0)

Status: development implementation; actual evidence and remaining acceptance
are recorded in [S07-C](development/s07-mamo.md). Existing NL4Opt0.1 snapshots
and import configs remain valid. A `.json` configuration is parsed as strict
JSON, preserving scientific-notation numbers; other config files use the
existing duplicate-key/finite-value-safe YAML loader.

MAMO import config0.2.0 explicitly selects `adapter_id=llm4om.tasks.mamo` and
contains dataset_id, source_kind (official/fixture/fork), source_version, files,
license_file, reviews, selected and tolerance. files contains exactly easy_lp,
complex_lp and ode, each with a bounded local path and SHA-256. Official source
must equal the fixed commit/hashes/counts and original CC BY-SA4.0 license.
Fixtures/forks use distinct IDs/versions. No fetch or solver support is implied.

Snapshot0.2.0 preserves all optimization cases in manifest.cases, public
ProblemSpec0.2.0 under `public/`, and original records/files under0700 `private/`.
Each entry retains subset/sample ID, original line/raw-record/Question hashes,
public/private refs, selected/eligible, review, reference_quality and exclusion
reason. Original data bytes and Answer remain private; public source metadata
contains no answer or hidden-code/model/vector reference. Official LICENSE and
ATTRIBUTION remain separate from the SDK license. Full snapshot/manifest is
privileged; export only the declared public problems/license/attribution and
public run results.

`selected=null` selects all optimization questions; an explicit list uses
`easy_lp:<id>` / `complex_lp:<id>`. `reviews` is a list bound to exact Question
hashes, with classification lp/milp/unsupported/unresolved, domain_policy,
rounding_policy, reviewer, reason and public evidence spans for problem_type,
variable_domains and rounding. Supported reviews require every aspect and
explicit domains/rounding; unsupported/unresolved cases retain a reason.
This is a declared public mathematical review, not keyword certification.
Missing reviews stay in selected counts with `public_math_review_required`;
they do not gain numeric evaluation eligibility from an EasyLP label or Answer.

`TaskAdapter.load_case(manifest, case_id)` loads frozen metadata for scoring;
`iter_cases` yields selected cases after public/private hashes and public review
checks. It keeps selected ineligible cases, since admission/generation failures
must remain observable. MAMOAdapter implements this interface alongside
NL4OptAdapter. Generic evaluate_case chooses the declared Task/Evaluator pair.
Run material is verified in a shared checker before privileged comparison;
missing/changed case files become persisted checker errors with frozen counts.

Protocol `llm4om.eval.mamo-numeric-v0.1` uses explicit abs_tol/rel_tol and
`abs(pred-ref)<=abs_tol+rel_tol*abs(ref)`. Rounding policy is `none` with
null decimal_places or `decimal_half_away_from_zero` with decimal_places0–12.
Only the candidate is rounded; the original numeric reference is preserved.
Reference digits do not determine the rounding rule. Output exposes the
candidate objective and supplied-reference match status, never the private
reference value/difference or Answer. Independent feasibility/semantic layers
remain unavailable without an independent checker/model/certificate.

Per-case evaluation0.2.0 records N_selected/N_eligible from the frozen manifest,
N_evaluated1, selected/eligible, objective_match_numerator and its case
objective_match_denominator (1 for an eligible case, otherwise0), and a case
objective_match_rate. Failed generation, execution and checker attempts keep
that denominator with numerator0. This is not the global experiment rate;
S08 aggregation must use the complete frozen selection and retain failures.

## 16. S07-B NLP4LP Task interface (SDK 0.11.0)

Status: development interface; evidence/pending acceptance is recorded in
[S07-B](development/s07-nlp4lp.md). NL4Opt0.1 and MAMO0.2 protocols stay valid.

NLP4LP import config0.2.0 contains adapter_id=llm4om.tasks.nlp4lp, dataset_id,
source_kind (official/fixture/fork), source_version, release_root, sha256,
reviews, selected and tolerance. The local release directory contains train.jsonl,
source README and per-instance data/<original-id> files. Official identity pins
the release commit, aggregate hash and all2,127-file hashes/sizes. No network
fetch/access acceptance occurs. Fixtures/forks use distinct IDs/versions.

Public projection: public/<id>.json ProblemSpec0.3.0 plus exact concrete
public/params-<id>.json bytes. data_id=parameters, format=json, schema.type=object,
SHA-256 and a problem-relative path bind them. Source scalar/list/dictionary/string
values retain types. Source reference definitions do not supply public metadata.
Private records and original aggregate/per-instance bytes preserve code,
problem_info, keywords, parametrized_description and nested solutions. The
source card/attribution is separate from SDK code licensing and must accompany
permitted public projections. The SDK ships only source hash metadata.

Manifest0.2.0 identifies original ID/difficulty/line/record/description/data hashes,
source consistency, private refs, reference_quality and reference_diagnostic.
reference_counts uses available_unverified/missing_solution/invalid_solution.
The fixed release is361records with322/37/2 in those categories. Malformed private
solutions remain diagnostics; no public question is removed for that reason.
A decoded objective/vector is not an optimum/feasibility certificate.

The shared public review schema supports subset=train and also requires
public data_sha256, data_binding_policy and a data_binding evidence aspect.
Review binds exact description/data and declares domains/rounding/reasons.
selected=null selects all original IDs; an explicit list uses the original ID
strings. N_imported/N_selected/N_eligible are frozen before modeling; numeric
eligibility additionally requires an available supplied reference. Unknown
classification/bindings and unsupported structure cannot acquire LP/MILP status
from difficulty labels. NLP4LPAdapter implements the same selected iteration/
load_case interface as the other tasks.

NLP4LPEvaluator uses llm4om.eval.nlp4lp-supplied-v0.1. Common case/run checks
verify all public artifacts and frozen source data; copied run data paths can
differ only with identical bytes/hash/schema and problem identity. Grading
occurs after model selection and verifies private source material separately.
Objective match uses the shared abs+relative tolerance and candidate-only
rounding rule. Public result records availability, binding policy, unknown
vector mapping/independent feasibility/semantic evidence, and case numerator/
denominator. It does not expose private values/vectors/code or collapse missing
reference, model failure and checker failure into one success flag. Complete
experiment aggregation remains S08; one case rate is not a full benchmark rate.

Direct prompts now describe provided CSV/JSON data and the public problem;
factory Code parses the declared raw-byte format. This does not introduce
JSON column metadata or prove per-parameter mathematical binding automatically.

## 17. S07-D SolutionChecker (SDK 0.12.0)

`SolutionChecker.describe() -> dict` declares schema0.1.0, checker_id/version,
required_decisions, public_data_ids, scope, objective_sense and coverage.
`check(public_problem, public_data_bytes, mapped_business_decisions) -> dict`
returns schema0.1.0, finite original_objective, objective_sense and
independent_feasibility={status:pass|fail,violations,coverage,level}.
The level is independent_original_business_rules. Violations belong to coverage;
a passing status requires no violations. Input is privileged evaluation-only;
it excludes candidate reported objective, reference target and candidate constraints.

Installed trusted entry points use group llm4om.checkers, name=checker_id,
and factory(config)->SolutionChecker. Source/version/entry-point/package identity
and the SDK checker source hash are frozen at admission and compared at evaluation.
Dataset paths cannot load a checker module. Invalid manifests/outputs and plugin
exceptions produce saved errors; output and exceptions cannot publish private diagnostics.
This is a trusted Python extension seam, not an untrusted-code sandbox.

The checker_fixture import config0.2.0 contains adapter_id,
dataset_id, source_version, cases and selected. Each case has problem_path,
problem_sha256, evaluation_path and evaluation_sha256; a null evaluation path
means no supplied checker policy. Public ProblemSpec/data refs retain original
identity/schema/hash; snapshot paths are normalized. Private policy0.1.0 has exactly
checker={plugin_id,version,config}|null, decision_mapping|null,
reported_objective_mapping={scale>0,offset}|null, reference_objective|null,
probe_points and data_perturbations, plus schema_version.
The reference has value,sense,quality=proven_optimum|best_known|feasible,
source,abs_tol,rel_tol. Decision mapping is an explicit one-to-one business ID
→candidate solution ID mapping. Missing or incomplete mapping is unknown.

Probe points map all original decisions to finite numbers. Data perturbations
have id, replacement_data={public_data_id:UTF-8-content}, and probe_points.
At most5000 total points and50 perturbations are accepted. The original public
schema also validates replacement bytes. These policies stay in task_private.
Public results show counts, coverage and counterexample indexes; point coordinates,
replacement contents and private references are not exported. Probe output is
finite_predeclared_grounded_instance_probes, complete_semantic_proof=false,
data_rebinding_tested=false. The inspectable IR must be the actual deterministic
Code source. Opaque or auxiliary-variable cases without complete mapping are
not_available; no arbitrary code, pickle or expression evaluation is used.

Protocol llm4om.eval.checker-v0.1 snapshots have N_selected,
N_independent_eligible and N_verified_eligible. The latter also requires a declared
reference threshold. Results separately record reported_objective_match,
original_objective, original_objective_quality, objective_consistency,
independent_feasibility, verified_solution and property_checks. Each solution
rate has its own numerator/denominator; unavailable admission evidence yields
null rates, while admitted failures retain their denominator. Original quality
and feasibility determine verified_solution. Reported units and finite model
probes do not redefine that solution metric. Missing primal/oracle and checker
errors cannot become semantic_verified; limited evidence never proves complete
Formulation or Code equivalence.

## 18. S06-C native Code without Formulation (SDK 0.13.0)

The native_script/0.2.0 method profile declares formulation_representations=[],
code_representations=[native_script] and gurobipy/Gurobi/container support.
ModelProposal.formulation is null only when the admitted profile permits this
and ModelArtifact.formulation_ref=null with an explicit not_available reason.
A supplied Formulation must match the admitted representation and available stage.
Code source_formulation_ref is null in this case; its generation provenance comes
from the real method output. Public evaluation does not label missing Formulation
structurally passed. Core completed-Code recovery verifies the nullable reference
and the actual Code/source/method/data identities. Earlier profiles retain their
required Formulation contract. No method-ID branch is added to orchestration.

CoE public_contract_data_id is optional/null. The default is an original public
prob_problem() stub. A selected public JSON contract has exactly code_example,
entry_point and input keyword arguments. Config defaults are collaboration3,
reflection=false, trials3 and seed0; actual routing seed/resolved behavior are
recorded. The interface file is public input, never benchmark reference code.
The method preserves all original native function bytes and appends a declared
isolated invocation driver. Public reflection uses first-alphabetical prob_*
discovery and generated public arguments, ignores returned values and may feed
bounded source errors back to experts. Its diagnostics are untrusted source
feedback, separate from trusted Solver evidence.

Final execution uses the original declared entry_point and input, not a generated
test's arguments. Reflection therefore has a separately counted final execution;
only the matching final receipt is reused as the Run's SolveResult. Original
source bytes, trial inputs/executions, reflections, last reducer selection and
fidelity differences remain inspectable. No opaque return value or public test
success creates independent original-problem correctness. Original prompts,
one-import adaptation, seeded fallback and configured Provider sampling/caps are
named changes; source-exact prompt/runtime and paper-score reproduction are not
claimed.

## 19. S05-D1 role model routing (SDK 0.14.0)

RunConfig.llm.role_models is an optional object keyed by exact logical role names.
Each value has exactly provider_plugin_id, model and config. Empty/omitted
mappings preserve the default. Supported overrides are online HTTP text Providers;
Mock/default-offline combinations fail admission. Each override is validated
with its own Provider schema and the method's requested features before calls.
Method requests use a role field in the common complete(request) interface.

Admission freezes default/role resources and distinguishes declared requested
model names from Provider/config resource differences. Same requested names do
not prove same weights or experiment conditions. Calls retain actual Provider,
requested/returned model, role, endpoint hash, usage and null unknown cost.

Gateway owns one archive/budget/concurrency/deadline for every role. The selected
Provider controls that request's output cap, transport, retry and timeout.
Private provider_identity.roles freezes each role's Provider/model/endpoint hash
and cap; immutable request hashes use the actual selected resource. Journal
validation checks each attempt against its declared role identity and decodes
successful raw replies with that Provider. Changed role identity or unknown
outcome cannot produce a silent replay/resubmit. Credentials are resolved using
the selected role's credential_env and literal .env fallback; completed replay
needs no new credential and keeps its original call_id and accounting.

## 20. S05-C1 public candidate assessment (SDK 0.15.0)

`grounded_candidates/0.1.0` admits five-element Formulation plus grounded LPIR,
with the same explicit compiler, Pyomo backend and declared LP/MILP Solver matrix
as the original grounded profile. The current real candidate assessment evidence
covers HiGHS in trusted_local and container modes. Generated factory/native Code
and native-script feedback retain their existing profiles; they do not yet imply
this multi-candidate assessment interface. Offline replay rejects this profile
during preflight because it has no actual Solver execution.

```python
class MethodResources(Protocol):
    async def assess(self, candidate_id: str, proposal: ModelProposal, *,
                     parent_id: str | None = None,
                     change_reason: str | None = None) -> dict[str, Any]: ...
    def select(self, candidate_id: str, *, rule: str, reason: str) -> MethodOutcome: ...
```

Assessment admits one bounded candidate ID and charges the shared candidate count
before parsing, compilation or execution. A repair requires an already assessed
parent in this run and a nonempty public change_reason; it also charges max_repairs.
`max_repairs=0` is valid. Root candidates and repairs share max_candidates; actual
Solver attempts share max_solver_calls and the original absolute deadline. Budget
refusal before candidate admission creates no candidate and no extra Solver call.
The existing LLM Gateway continues to own all actual LLM usage and reservations.

Assessment0.1.0 returns candidate_id, proposal_sha256, the supplied public proposal
text reference, status=`invalid|executed`, per-stage availability, actual artifact,
execution and Solve references, has_primal_solution, termination and public stage
diagnostics. Invalid output and its diagnostics remain in the candidate directory.
The proposal hash binds the full declared proposal, parent and change reason;
candidate IDs cannot be rebound. Candidate metadata records parent_ids, sequence,
actual method identity and change_reason. Supplied proposals are public modeling
outputs; full raw Provider responses retain their existing private archive boundary.

The common application machinery validates input hashes/revision/data bindings,
Formulation and actual LPIR type, compiles Code and runs the admitted Solver.
No hidden oracle or independent benchmark result is passed to the method. A
trusted primal demonstrates candidate execution, not correctness for the original
natural-language problem. Assessment diagnostics are engine observations; a
method's change_reason and selection explanation are declared reasoning.

Selection requires an assessed candidate with trusted completed Solver evidence
and no assessment error. A legal infeasible/unbounded result can be selected; a
primal is not fabricated. The method declares rule and reason. The core preserves
these in immutable candidate-selection0.1.0 and validates run membership. It does
not infer mathematical optimality or compare objectives across candidate models.
The selected MethodOutcome has proposal=null and the real candidate ID. The
application reuses that candidate's verified execution without another Solver call.
Original single-candidate outcomes keep their existing proposal and ID001 behavior.

Same-identity completed assessment replay verifies all referenced bytes and consumes
no extra candidate/repair/Solver slot. Hard-exit recovery accepts a completed
assessment publication receipt with matching proposal hash and candidate ID.
An interrupted final-selection publication is verified against that assessment
and frozen before method reentry; recovery does not ask the method to choose again.
Methods need their declared versioned checkpoint to resume unfinished reasoning.
An admitted assessment with no completed receipt is execution_outcome_unknown;
it is never automatically executed again. SDK/source/Worker identity checks stay
strict across resume. SDK0.16.0 implements the feedback method and factory Code-only
reuse in section21; SDK0.15.0 evidence remains version-specific.

## 21. S05-C2 bounded feedback repair (SDK 0.16.0)

The project-authored `llm4om.methods.feedback_repair` baseline reuses Direct's
compact five-element output. Configuration keeps formulation_mode and output_mode;
lp_ir uses grounded_candidates/0.1.0, python_factory uses factory_candidates/0.1.0,
and native_gurobipy uses native_candidates/0.1.0. Factory profiles require container
execution. Native candidates require gurobipy/Gurobi; unsupported matrices reject
preflight before generation. Offline candidate profiles remain unsupported.

`MethodResources.remaining_budget()` returns remaining candidates, repairs,
solver_calls, llm_attempts, conservative total_tokens and wall_time_s. It reads the
shared ledger and original deadline. Gateway still owns atomic LLM admission and
unknown reservations; this view is not an independent allocation. The sequential
baseline checks it before new generation. A pending request resumes only through
Gateway's existing same-identity replay/unknown rules and assessment receipts.

`GenerationFailure(call_id, response_sha256, code, stage, message)` extends assess's
proposal input. Supported decoder failures are invalid_json, invalid_object,
invalid_method_outcome and llm_output_truncated; stage is formulation or code.
The resource verifies that the response actually exists in its Gateway responses,
and bounds the public diagnostic. It charges the candidate/repair just like a
ModelProposal, stores diagnostic origin=method_decoder and leaves Formulation,
Code and Solve unavailable. Raw reply text is not in the failure object, public
checkpoint or repair prompt. This records a method decoder observation, not an
independent semantic judgment. Transport/auth/unknown failures are not fabricated
as malformed mathematical candidates.

Repair requests use logical role=repair; the initial request uses formulation.
The original public problem/data remain the generation input. Feedback contains
the previous public assessment and declared output. A successful repair response
adds repair_stage=formulation|code and a bounded nonempty change_reason. LPIR
corrections declare formulation because LPIR is executable mathematical output.
Factory Code-only repair may omit representation and reuse the previous source
Formulation. A supplied changed mathematical representation cannot be hidden by
the code label.

The core checks Code-only Formulation/problem/revision/data identity against the
parent's actual source Formulation reference. It reuses that exact reference;
the new Code's generation provenance identifies the new actual call. Mathematical
repairs receive a new Formulation reference and matching Code. Old single-candidate
profiles do not activate the new Code-only parent semantics by a provenance label.

Each modeled child saves formulation-changes0.1.0: changed five-element chapters,
changed LPIR chapters, constraint IDs added/removed, existing public requirement
traces lost, parent proposal reference and source availability. Comparison is of
actual declarations, not mathematical equivalence. Loss of a previously covered
public requirement is requirement_coverage_lost and prevents execution/selection.
Changed domains/objectives/coefficients remain observable with a change reason;
preserved IDs do not certify correct natural-language modeling.

Selection rule legal-primal-completeness-latest/0.1.0 prefers legal trusted primals,
then available public stages and latest attempt. It does not compare candidate
objectives or use reference answers. A trusted legal infeasible/unbounded outcome
can remain selected. The method stops on its first legal primal or shared limits.
No legal candidate yields MethodOutcome exhausted and a saved method_exhausted
Run error/outcome; attempts remain public. Failed outcomes similarly retain
method_failed, rather than being mislabeled invalid_method_outcome.

The versioned method checkpoint stores a stable request_id, request_pending,
assessments and public feedback. It is saved before requesting and after accepting
an assessment. Replaying a completed but not yet accepted assessment consumes no
extra call or candidate; completed primals are selected before any new generation.
Core selection receipt recovery freezes a completed choice before method reentry.
No unknown admitted execution or LLM request is silently repeated. Existing
cancellation, private archive and strict SDK/source/Worker identity rules apply.

## 22. S05-D2 clarification (SDK 0.17.0)

MethodOutcome adds optional clarification. A needs_input outcome requires no
selected candidate/proposal, declared supports_clarification and a saved versioned
method checkpoint. FeedbackRepair implements this capability; legacy manifests
retain their own declarations. Direct's optional compact decoder accepts
`{clarification:{questions:[...]}}` only when its caller enables clarification.

Questions have question_id, kind=confirm_existing|new_information, question and
statement_ref. IDs are unique bounded identifiers; up to8 questions, each text
up to4096 characters, and total declared request metadata up to65536 bytes.
Confirmation anchors are exact public requirement/assumption kind+id; the core
adds the original statement text. New information uses a null statement_ref and
cannot be relabeled confirmation of an existing declaration.

ClarificationRequest0.1.0 stores platform request_id, run_id, sequence_no,
problem_id/revision/raw SHA, canonical questions and declared provenance. The ID
is deterministically bound to those request inputs, allowing completed-publication
recovery without another response or another ID. New rounds have a new sequence.
Full Provider replies remain private.

`run_problem(..., interactive=False)` is backward-compatible at the application
entry. True is explicit via SDK or CLI --interactive. A valid request produces
needs_input in interactive mode or unresolved in noninteractive mode, with no
fabricated Formulation/Code/Solve. RunBundle retains clarification_request_ref
and clarification_response_refs. CLI needs_input returns0; unresolved returns1.
Repeated resume without an answer returns the persisted status without new work.

`resume_run(..., answers:Path|None, revised_problem:Path|None)` reads a strict
ClarificationResponse0.1.0: schema_version, saved request_id, action=confirm|revise
and exactly one answer per question. Values are boolean or bounded public text;
question order is canonicalized. Confirmation requires every question to be
confirm_existing and every value exactly true. False or new facts require an
explicit revision. Accepted confirmations are immutable and versioned, enter only
public MethodContext.clarifications, and resume fresh generation from the method's
saved clarification state. The original same-run deadline stays fixed.

New business rules/data require action=revise and a supplied validated ProblemSpec
with the same problem_id and a changed revision. Revision data are validated/hash
checked before derived admission. The core uses its existing derived-run machinery:
new run/deadline, lineage.operation=clarification_revision, public parent history
copies, response reference and carried prior usage/unknown reservations. Parent
problem, candidates, responses and scoring are not rewritten; a private derivation
coordinator records the operation. Different content/answers cannot rebind the same
request+problem+revision operation. Identical retries resume the existing child.
Revised problems do not inherit stale confirmation records as fresh problem facts.

Core request/answer publications and method checkpoints remain separate. A completed
confirmation receipt is validated and accepted on resume; a persisted child
initialization identity permits recovery after derivation registration but before
model work. Unfinished/unknown external work still uses the existing Gateway and
execution rules. Revised input cannot be scored as the original frozen benchmark
case merely because it has the same problem_id. No hidden evaluator/oracle or
credential is added to MethodContext.

## 23. S03-C1 installed text Providers (SDK 0.18.0)

The common Manifest0.2.0 now applies to method and llm_provider factories in the installed llm4om.plugins group. Other kinds remain planned. discover_plugins()->dict[(kind,plugin_id),Plugin] is the SDK inventory; discover_methods() filters MethodPlugin instances. Every active manifest is validated before use; invalid installed plugins reject discovery instead of silently disappearing.

Provider factories declare capabilities.provider_profile=http_text/0.1.0 or the built-in mock_text/0.1.0; llm_features contains only actually supported text features. input_artifact_kinds=text_messages, output_artifact_kinds=text_response; problem_types=[] means the transport makes no optimization-family claim. Optional capabilities.usage_semantics explains token accounting. All common fields, stable SemVer, core contract interval, self-contained config_schema and dependencies.python follow section1. Field validation precedes credential lookup and external requests.

Installed HTTP factories implement the existing HTTPTextFactory contract: provider_type is a subclass of HTTPTextProvider with the same declared plugin_id, endpoint_path, request_id_header, _request(messages) and decode_reply(value). create(config,model,environment=...)/restore(config,model,environment=callable) retain the SDK credential, URL and request-limit semantics. Initialization and describe must not send paid requests. The owned transport forwards the validated public config, model and privately supplied credential, including protocol-specific config fields; it imports the installed factory; generated-code containers do not mount its package or credentials.

Decoded replies have exactly text:string, response_id/model/finish_reason:string|null, usage:{input_tokens,output_tokens,total_tokens,cached_tokens,reasoning_tokens}:nonnegative integer|null, and optional stop_reason:string|null. Booleans are not token counts. Raw HTTP and decoded responses are checked for credential content; invalid replies retain an unknown outcome and reservation. Import, Manifest and constructor diagnostics suppress plugin stdout/stderr and exception messages. This is failure hygiene for trusted code, not a sandbox for arbitrary installed Python.

Admission stores provider Manifest and provider_origin; each role_models entry stores its own provider/origin/model/config. Installed origin includes entry point/value, distribution/version and a hash of all distribution-registered files except .pyc caches. Declared dependency versions are saved. Recovery requires the same identities and decoder; no credentials or new requests are required for already-completed work. Source/Manifest/resource changes require a new environment/run rather than silent migration. The SDK/Worker snapshot rule remains in force.

Actual scope, independent example and local evidence: [S03-C1](development/s03-provider-registry.md).

## 24. S03-C2 installed Task and Evaluator (SDK 0.19.0)

The common llm4om.plugins Registry now supports task_adapter and evaluator. A Task factory creates import_source(config:Path,output:Path,settings:dict)->Path, iter_cases(manifest:Path)->Iterator[EvaluationCase] and load_case(manifest:Path,case_id:str)->EvaluationCase. A trusted Evaluator factory creates evaluate(case,outcome:Path)->EvaluationResult. FrozenTaskAdapter and evaluate_outcome expose the existing case/outcome verification behavior for independent adapters. They never enter MethodContext.

Task capabilities require task_profile=frozen_task/0.1.0, oracle_separation=separate_public_private/0.1.0, protocol_ids, default_evaluator_id, input_artifact_kinds=task_source and output_artifact_kinds=evaluation_manifest. Evaluators declare evaluator_profile=frozen_evaluation/0.1.0, protocol_ids, evidence_levels, evaluation_case/run_bundle inputs and evaluation_result output. Their config_schema and dependencies follow the common contract. Constructor/describe do not perform paid calls. doctor --task-config and SDK prepare_task validate selections without reading hidden source or publishing data.

Existing source import config retains its adapter-specific fields. Optional adapter_config defaults to{}; optional evaluation={evaluator_plugin_id,config} defaults to the Task's declared evaluator and{}. Core removes these selection fields before passing settings to import_source. The adapter writes only to assigned staging and returns its manifest.json path. Public problems/case references are validated under public/ and private/ before the directory is published.

Imported privileged manifest adds plugin_bindings0.1.0: runtime SDK version/code hash, Task/Evaluator manifests, installed origins, configs and dependency versions. private/import-seal.json anchors final manifest bytes. Altering the manifest, package or runtime rejects evaluation before construction; it never modifies prior evidence. New data/configs require a new import. Pre-registry built-in snapshots remain read-only and report binding_status=legacy_unbound with current actual identities; installed unbound snapshots reject.

EvaluationResult keeps the existing0.1/0.2 public fields, including NLP4LP reference diagnostics/counts, data-binding policy and variable-mapping availability. Result case_id/protocol_id/manifest_sha256/source/eligibility/counts must match the frozen case. Imported selected/eligible counts must match actual unique case enumeration. Result run_id/run_status match the actual RunBundle; success counts require matching pass statuses. Counters preserve eligibility; zero-denominator rates are null. Values are finite JSON; private oracle fields/refs reject. Actual public run diagnostics may retain verified run_public references. Pass/fail evidence cannot exceed declared evidence_levels. Unknown Evaluator exceptions produce safe checker_error while preserving denominators. Public plugin_identity omits actual privileged config; exact config remains available in the privileged frozen manifest.

Actual support, example and local acceptance: [S03-C2](development/s03-task-registry.md).

## 25. S03-C3a installed Compilers (SDK 0.20.0)

The common Registry accepts kind=compiler through built-in factories and installed llm4om.plugins entry points. Factories expose describe() and create(config); a Compiler exposes compile(ir,target_backend)→CompiledCode with source and symbol_map. The SDK exports Compiler, CompiledCode, LPIRPyomoFactory, LPIRPyomoCompiler and resolve_compiler.

The current profile is grounded_lpir_pyomo/0.1.0, with deterministic=true, ir_schema_versions=[0.1.0], input_artifact_kinds=[grounded_lpir], output_artifact_kinds=[python_factory] and model_backends=[llm4om.model_backends.pyomo_factory]. problem_types must cover configured and actual LP/MILP types. RunConfig.compiler accepts plugin_id and optional config, defaulting to an empty object. Manifest/config/contract/dependency/capability failures reject before generation.

Compilation validates strict LPIR, bounded nonempty Python source (at most 8 MiB), syntax, variable/constraint IDs and integer index permutations, and the internal constant anchor. A Compiler receives a copy of public IR. Errors retain safe diagnostic types and frames, never exception text or compiler stdout. Code provenance contains actual compiler_id/version, source_ir_ref, symbol_map_ref and compiler_identity; Build records the selected Backend and compiler_config_sha256.

Admission freezes the full Manifest, config, dependency versions and installed origin. package_sha256 covers registered distribution files except bytecode. content_sha256 excludes bytecode and .dist-info installation metadata, so host and Worker can compare the same executable code/resources across installers. Portable compiler_identity includes Manifest/config/packages and origin kind/value/distribution/distribution_version/content_sha256. Resume compares the complete host binding and unchanged SDK/source/image identities.

The platform's grounded Worker request includes ir, source_sha256, symbol_map, solver_options, compiler, compiler_identity and target_backend. Worker resolves the same compiler, compares identity, recompiles and verifies source hash plus symbols before solve. The existing three-field built-in Worker request remains available for explicit low-level calls; platform requests always include the admitted selection. Container preflight checks installed compiler identity before generation. Trusted-local uses the owned process's same installation and validates identity at execution.

scripts/build_worker_image.py accepts repeatable --plugin-wheel for explicitly trusted prebuilt wheels. It prevents SDK replacement and filename collisions, installs those wheels without resolving dependencies, and uses only wheels/locked requirements as Docker context. Additional dependencies must already be in the locked runtime. It never mounts host source or installs plugins during a run. Actual supported paths and evidence: [S03-C3a](development/s03-compiler-registry.md).

The runtime probe uses a bounded output allowance of at least 64 KiB for admission metadata. Candidate execution retains the configured output limit. Malformed runtime envelopes remain executor_unavailable; absent/different compiler identities are compiler_unavailable.

## 26. S03-C3b registered ModelBackend and SolverBackend (SDK 0.21.0)

Both kinds use common describe()/create(config) factories and llm4om.plugins entry points. RunConfig.model_backend and solver accept plugin_id plus optional config; Solver options are checked against its self-contained options_schema. Current backend_profile and solver_profile are model_handle/0.1.0. Backends declare one handle_profile (pyomo_linear/0.1.0 or gurobipy_linear/0.1.0), and Solvers declare explicit handle_profiles and result_profile (highs_api/0.1.0 or gurobi_api/0.1.0). Problem types, configured artifacts, profile and actual dependency availability are checked before generation.

ModelBackend.load accepts parameterized source or CompiledCode with public data bytes and returns ModelHandle(model,decision_map,internal_variables=()). export validates the supported linear domain and explicit complete mapping. Compiled constant-only models may declare zero-bound internal variables; those variables do not become public decisions. NativeModelBackend also exposes read_transport(exported) as a context manager, using an independently read SDK model from bounded MPS transport. Handles stay inside Worker processes.

Generated factories execute only in the isolated construction child. That child selects the bound Backend and exports a model. The trusted collector validates the export and independently constructs a concrete instance or reads native MPS, then calls the selected Solver. Source scripts retain their original Code and execution; capture and independent collection are separate recorded operations. Unknown or incompatible profiles reject without replacing a method or rewriting Code. Existing method/compiler declarations can refer to registered adapters' compatible profiles; actual selected IDs/config/packages remain recorded.

Admission freezes full Backend/Solver Manifest, config, origin and applicable host package versions. Container hosts do not need unused numerical SDKs; the Worker checks declared dependencies, SDK availability and versions. Portable execution_identity excludes host numerical dependency packages while retaining executable package content, Manifest and config. Actual Worker package versions are bound by runtime/admission and immutable image ID. Grounded, factory and collector requests carry execution selections and execution_identity. Changed host bindings or Worker image identity cannot silently resume.

Solver runtime and results require finite JSON, explicit version strings, declared result profiles, exact requested options and complete public decision keys. Exception text, plugin stdout and private error details are suppressed at the selected Solver interface. Numerical SDK version/evidence interpretation follows result_profile rather than third-party ID. The platform binds actual Solver/Backend plugin IDs after the selected adapters execute. Solve success is evidence about the candidate model, not formulation correctness.

The SDK exports ModelBackend, NativeModelBackend, SolverBackend, their built-in factories, ExecutionResources and resolve_execution_resources. The public solvers.solve entry accepts optional config and backend_selection; solver_runtime/solver_packages can query an installed Solver with config. Trusted plugin wheels enter an immutable image at build time. Engineering examples and actual local support are recorded in [S03-C3b](development/s03-solver-registry.md); no general nonlinear support is claimed.

## 27. S03-C4 public DataLoader and DataView (SDK 0.22.0)

DataLoader is an installed `llm4om.plugins` factory with kind=data_loader,
data_loader_profile=public_bytes/0.1.0, explicit data_formats (csv/json) and
view_kinds (full/rows/summary). Core discovery checks its self-contained config
schema, contract and declared dependencies. RunConfig.data_loader selects
plugin_id/config; omitted selection uses llm4om.data_loaders.public. Admission
freezes full Manifest/config/package/executable identity and data_view limits.
Changed identity or exposure limits reject resume without changing saved evidence.

The core owns public_path, per-file 8 MiB bounded reading, original SHA-256, CSV
columns/types/nullability/unique keys and strict public JSON validation. The
DataLoader receives load(ref,schema,DataContext(raw,limits)) with admitted original
bytes, a copied schema and only data_id/format/sha256/size_bytes metadata. It
receives no filesystem path, gateway, budget, credentials or evaluation materials.
Loading trusted plugins remains distinct from executing generated code.

RunConfig.data_view sets mode=preview|full|summary, max_rows, max_columns,
max_bytes and an optional columns allow-list. Defaults are preview,100 rows,32
columns and65,536 bytes per input view. Bounds are enforced independently of the
Loader; full mode rejects an incomplete or excessive view. CSV previews select
original rows/columns without changing values or multiplicity. Object JSON
supports unchanged full bytes or a bounded top-level schema summary; nested
array row selection and numerical aggregation are not part of this profile.
Summaries contain declared structure/counts, not parameter values.

DataView has content bytes, format/kind, source_sha256, total_rows/rows, columns
and complete. The core verifies actual content, counts, original membership and
exposure bounds. Full views preserve exact original bytes and original format.
View SHA-256/size are computed separately from original data identity.
Unknown plugin errors expose safe types/frames, not private exception text or
details; original CSV diagnostics identify row/line/column and failure reason.

Original snapshots and Solver data binding remain unchanged. MethodContext.data
retains original public bytes; data_views supplies declared DataView objects. A
method without data_access=views conservatively requires a complete view before
generation. Direct/feedback_repair explicitly accept views and send their exact
content/metadata to the LLM; omitted values must not be invented. Third-party
methods must honor their declared access capability. A view is data exposure,
not proof of correct grounding or formulation.

The bundle projects data-views.json and individual content snapshots. Online
llm-trace.json references the immutable view record, alongside request hashes;
Direct's request includes the exact data/data_views content. Trusted Worker
construction receives original raw data, without the host Loader or hidden
materials. SDK exports DataLoader, DataContext, DataView, PublicDataFactory and
resolve_data_loader. The independent column-order wheel is an engineering
fixture, not a new research method. Local evidence is recorded in
[S03-C4](development/s03-data-loader.md).

## 网页实验控制

SDK／Worker0.25.0提供`cancel_experiment(output)`，绑定当前invocation的公开control identity。`run_experiment`在持有排他锁后接受新invocation，清除上一invocation的取消请求；完成样本复用和未完成继续分别记录。调度器优先合作取消拥有的RunStore，短暂等待后才终止仍未退出的资源进程。中断恢复保留先前结果历史和硬预算；已过期原deadline或缺少可用方法checkpoint时明确拒绝继续。

Web`/api/tasks`列已冻结任务的公开元数据；`/api/experiments`列出／提交变体矩阵，`/api/experiments/{id}`读取状态和公共结果，`/cancel`、`/resume`调用共同调度控制，`/export`只导出公开实验配置和报告。任务仅从项目runs或工作区tasks发现；没有公开任意服务器路径读取入口。

## 人工辅助编辑

SDK0.26.0的`export_edit(run, operation)`与`edit_run(run, edits)`使用公开EditSpec0.1.0。必需字段为schema_version、operation、reason、budget、problem、formulation、structured_ir、code、model_metadata。operation为problem/formulation/code；reason说明修改，budget明确包含父消耗的新总上限。Code对象为representation_kind/source/data_json；model_metadata保存assumptions/requirement_traces/warnings。原始数据不在此编辑入口替换。

人工修改建立新run和assisted_revision lineage，保存parent_run_id、父checkpoint/公开产物、parent_budget_ledger、parent_resource_records与编辑原因。问题编辑需新revision，Code-only不改来源数学表述。父候选和付费/未知预算继承，新增候选计数；新总上限显式变化记入lineage。RunBundle.assisted与budget-ledger.evidence_origin=assisted、方法human_assisted声明区分手工辅助和自动建模；分组报告N_assisted保留该区别。

公开源代码通过共同表示契约与容器执行。CompiledCode的原ConcreteModel工厂在编辑模板中公开加入保存symbol-map的ModelHandle适配，原bytes仍在父记录；人工编辑不伪称原确定性编译。CodeArtifact.provenance.generation记录user_edited，严格IR新编译仍记录真实Compiler来源。

## OptiMUS公开输入变体与实验case选择

SDK0.27.0提供`llm4om.methods.optimus_inline`，配置为`{rag_mode: null}`。固定main读取空params.json／labels.json，原始公开数据追加到描述；原参数声明接口仍由`llm4om.methods.optimus`提供，不默认替换。variant_id为optimus0.3-source_main-inline_public-ec_true-rag_none-external_chat，输入策略／有效描述hash／原数据hash保存在public-input-projection.json。主流程未增加LLM参数提取，也不注入参考材料。

ExperimentSpec.tasks的`{id, manifest}`可增加case_ids，表示原冻结selected案例的明确子集。资格、oracle、原manifest均不修改；具体共同case在实验快照冻结。N_selected为该实验子集，N_manifest_selected保留原总数；不同方法不按结果删样本。

## Web并发执行与取消

SDK0.28.0的Web提交／恢复／编辑通过独立CLI应用进程调用共同Python用例；plugin discovery和doctor不与运行共享解释器。公开HTTP字段不变。取消先向拥有的应用进程组发送SIGINT，最多十秒后清理；若未保存完整终态，job公开错误保留，不伪称完成。资源子进程默认即时取消保持不变。详见[S09](development/s09-process-isolation.md)。
