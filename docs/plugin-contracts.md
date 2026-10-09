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

内部 registry 键为 `(kind, plugin_id)`，一次环境不允许相同键的多个活动版本。与内置键冲突必须报错，不能以安装顺序覆盖。entry point 名称规划为 `llm4om.plugins`；加载第三方 Python 包会执行可信插件代码，因此安装／加载与生成代码隔离是两个问题。

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

实验配置必需字段为 schema_version、experiment_id、task、methods、llm、model_backend、solver、executor、evaluation、budget、repeats、store、reporters。compiler 仅在相应 IR 转换路径必需；roles、sample_selection、cache_policy、allowed_problem_types 为可选配置。默认 allowed_problem_types 为 [lp,milp]。

单问题 RunConfig 必需字段为 schema_version、method、llm、model_backend、solver、executor、budget、store；compiler 随 IR 路径需要，reporters、roles、evaluation 和 allowed_problem_types 可以按已声明默认值提供。公开问题由 SDK 参数或 CLI `--problem` 传入。它不要求 task、experiment_id、methods 列表、repeats 或 oracle_path；无 evaluation/oracle 时仍记录公开合法性与执行检查，独立检查为 not_available。示例见 [run.yaml](../examples/specs/run.yaml)。

单问题省略 evaluation 的明确默认值为 `llm4om.eval.public-v0.1` 与 `llm4om.evaluators.structural`，不隐式获取参考答案。省略 reporters 仍保存机器可读 RunBundle；是否额外呈现 Markdown 等格式由明确配置决定。

普通插件选择对象为 `{plugin_id, config}`，config 可为空对象；LLM 选择为 `{provider_plugin_id, model, config}`，solver 为 `{plugin_id, options}`。缺省 config 与 options 仅能使用 Manifest 中明确默认值，不能由插件静默选择模型或求解器。

methods 是方法选择列表；角色 LLM 配置可在 roles 中覆盖默认 llm。1.0 实验可以按显式变体配置展开方法／模型／后端组合，展开后的每个 RunConfig 固定一个实例、方法、资源配置及评测协议，不共享可变插件状态。

task.config 的 oracle_path／私有数据只在 TaskAdapter 与评估端存在。PublicRunConfig 投影去除这些字段、凭据和敏感路径后才传给方法／导出；不是把原始 YAML 直接塞进 Context。配置相对路径以该配置文件所在目录为基准，最终访问仍受对应工作根目录和公开／私有权限控制；示例中 store.root 可解析至仓库 runs，方法的数据引用不允许因此访问该整棵目录。

ExperimentSpec 展开后每个 RunConfig 使用单数 method，并关联所属 experiment_id 与 case_id 等运行元数据。该关联不向方法暴露私有 oracle。单问题与实验共用 DD-01，用例差别在任务展开、参考材料与汇总。

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

SDK 的 entry point 分组 llm4om.plugins 导出 describe／create(config) 对象，当前只装载 method。Manifest 的 capabilities.method_profile 为 grounded_single_candidate/0.1.0；plugin_version 当前为稳定 major.minor.patch，contract_range 为 `>=X.Y.Z,<A.B.C` 并包含核心契约 0.2.0。config_schema 自包含，允许本地片段引用，暂不接受 $id 或远程 $ref／$dynamicRef；dependencies.python 为分发包名称列表，记录已安装版本。source 暂不接受额外 ArtifactRef，研究 URL／固定版本／变体等文字元数据可保存。

当前 async run 返回内存 MethodOutcome：status=candidate_selected、final_candidate_id=001、proposal=ModelProposal(artifact, formulation, structured_ir)。核心验证原问题 hash／revision、五元素和数据绑定，生成实际引用与候选记录；这不是完整的多候选 Protocol；当前内部 checkpoint 扩展见第 12 节。MethodContext 当前提供 llm、只读公开 data／预算上限和 problem_sha256；MethodContext 的 LLMResponse 提供 text、call_id、evidence_origin、source_sha256，以及可选 finish_reason；真实 Provider 完整 usage 与身份保存在 Gateway trace。窄 profile 明确版本化，后续增加资源和状态时同步声明。

doctor 与 run 共用 prepare_run；先验证参数，再匹配当前表示、目标类型、Backend／Solver、Provider 功能和 Executor，再检查分发包与真实求解依赖。缺失能力为未知；请求的资源须被方法声明，当前表示 profile 固定，不能靠枚举并集暗示 native_code 可用。allowed_problem_types 缺省 lp／milp，实际 IR 类型在产出后再次核对。真实运行保存 admission_plan_ref；离线计划只准备回放，不标记 Code／Solve 已执行。未知方法异常与 SystemExit 转为稳定错误和脱敏 frame，原错误参数／源码行与插件 Python 输出不进入公开结果。

示例、字段级诊断、实际版本和未实现项见 [S03](development/s03-plugins.md)。S03 不执行真实连通性检查，不加载 .env；后续 Provider 工作树实现见 S05-A 子集。SDK 包、核心对象 0.2.0、IR 0.1.0 和 profile 0.1.0 分别管理。

### S04-A 已落实的容器子集

container 配置必须包含 network=false、正 cpu_limit、整数 memory_limit_mb 和正 wall_time_s，可选 image、整数 pids_limit 和整数 output_limit_bytes。省略 image 使用 SDK 对应 Worker tag；admission 将它解析为本地不可变 image_id，检查真实 Worker 运行时，候选执行使用同一 ID。没有自动 pull 或本地降级。

公开 Executor 为 run_container(command: list[str], inputs: Mapping[str, bytes], limits, *, image) → ContainerExecution。输入只能是安全相对路径与公开 bytes；方法 Context 不获得此低层接口。实际求解由核心选择可信 Worker 入口，仅发送严格 IR、实际编译代码、Solver options 和公开 CSV。Worker 验证 IR／实际 CodeArtifact 的 hash，并经平台 Solver API 产生结果。

ExecutionResult 增加可选 worker_status、image_id、container_id、container_name、oom_killed、oom_evidence、restrictions 和 executor_diagnostics；stdout／stderr 为有界文件引用。oom_evidence 为 docker_state／docker_event 或 null；只使用实际标记或同容器的 daemon 事件，不从 137 推断原因。资源超限为 execution_timeout／execution_oom／execution_output_limit，SolveResult 缺失；已生成 Formulation／Code 保留。Docker 控制失败为 executor_error，缺环境为 executor_unavailable，非法直接 Executor 输入为 invalid_execution_request。控制与清理有界，失败保留实际退出／输出／容器身份和诊断，不用默认值伪造缺失测量。

固定策略、真实测试与当前限制见 [S04-A](development/s04-container.md)。它只交付 grounded LPIR 的容器路径和可复用 Executor；参数化工厂、原生代码、完整预算、取消／恢复均仍按开发计划实现。

### S05-A 文本 Provider 子集

公共接口保持 LLMGateway.complete(request) 与 MethodOutcome／ModelProposal。Provider factory 由 provider_plugin_id 选择并独立校验 config、text 能力和凭据，不依赖方法 ID。当前 factory 仅内置 Mock 与 openai_compatible；第三方 entry point 仍只装载 method。Provider 的 stdlib HTTP adapter 是窄 TextProvider，同步 complete(messages, timeout) 返回规范化文本和 usage；Gateway 提供方法使用的 async 接口并拥有资源控制。

openai_compatible 配置为 base_url、credential_env，另有 max_output_tokens（默认 1024）、max_retries（默认 2，范围 0～5）、timeout_s（默认 30）。只接受非流式 text；请求字段仅 messages、可选 request_id／role。doctor 优先读取配置目录 literal .env，不存在时读取当前工作目录 .env；进程环境优先，但不发请求。Credential、header 与 URL 凭据在公开投影边界拒绝，凭据值不进入配置快照、Context 数据或 Worker。

Direct 使用完整公开问题及 CSV 值，外部回复只能是 representation 和 structured_ir 两字段的紧凑数学对象。平台生成 artifact／formulation／IR ID、revision、数据 hash、引用与 provenance。representation 的五元素语义与 GroundedLPIR 数学字段复用本契约；紧凑 IR 只含 problem_type、variables、objective、constraints、assumptions。五元素与 IR 是联合生成，Code 是确定性编译；未取得语义证据时仍为 not_available。finish_reason=length 时 Direct 返回 llm_output_truncated，保留 trace 和用量，不形成 Formulation。旧 Mock packet 与独立方法 fixture 保持有效。

Gateway archive 是共享 run 资源身份。文件锁原子 admission，OS slot 锁限制并发；每次 attempt 使用独立 UUID。省略 request_id 时每次调用使用独立 UUID，相同消息可独立采样。显式 request_id 用于恢复；内容 hash 同时绑定端点／模型／输出上限／消息。预算与 deadline 恢复不重置；不同预算拒绝恢复。已保存成功直接复用，未知身份拒绝重新发送并保留预留。S05-A 单独不提供 CLI resume；S04-B 的公开恢复与内部 checkpoint 见第 12 节。

发送前按规范化输入 UTF-8 字节数估算 token，加最大输出预留；实际 total 可用才结算预留。input／output／total／cached／reasoning 缺失均为 null，cached 与 reasoning 不重复计费。无定价时 cost=null。结算后计入未知 attempt 的预留；最后调用实测占用越界返回 token_budget_overrun，并保留成功回复。429／5xx／连接故障有限重试，认证／无效请求／非法响应／超时不重试；失败 charge／usage 未知时保守保留预留。共享绝对 deadline 约束请求 timeout、重试、Docker 检查／create、Worker 启动、容器墙钟和 Solver time_limit（清理允许有界额外时间）；HTTP 在可终止子进程中执行，完整 deadline 覆盖 DNS、TLS 和持续滴流；取消回收进程并保留未知结果的预留。

公开 llm-trace.json 只包含身份／hash、模型／role、start／end、finish_reason、usage、reservation 和稳定诊断。原始回复与恢复状态存于公开运行目录之外的 .private/run_id，目录 0700、文件 0600，不列入 bundle。详细字段、配置、限制与验收命令见 [S05-A 实现记录](development/s05-provider.md)。已有本地 HTTP 接缝与两个真实外部模型／容器案例；具体证据见实现记录。完整 1.0 仍按开发计划验收。

## 7. S07-A local Task / Evaluation interface (implemented)

S07-A was delivered in unreleased 0.4.0; current SDK is 0.6.0. `TaskAdapter.iter_cases(config: Path)` yields frozen
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
内容文件保存在 history/hash/path，原引用不改写；固定路径为当前公开视图。
checkpoint 的原始 bytes 另存于 checkpoints/hash.json；checkpoint.json 原子提交选择当前一致版本。
公开视图替换前，publication.json 保存基于该 checkpoint hash 的写入意图与 owner_id、目标不可变引用。
只有 owner 锁已释放、control 仍 active、owner_id 与基线 hash 均匹配的中断，才允许协调未提交视图。
恢复先校验全部不可变 bytes，再确认视图只含已提交或已记录的未提交 bytes，然后重建 checkpoint 视图。
未提交的新视图删除，但不可变历史保留。已提交视图或不可变引用的真实损坏仍返回 checkpoint_incompatible。
OS atomic rename／fsync 是存储故障注入边界；协作取消测试使用公开 Method／资源和 SDK Token／事件记录。
不序列化 ModelHandle、Solver SDK 对象、credential、oracle 或 pickle。

MethodContext 兼容增加 cancellation 和可选 save_checkpoint(versioned_json) 回调。
只有 supports_checkpoint=true 的方法可保存／接收内部 checkpoint；核心阶段恢复与该能力独立。
Direct 声明 supports_checkpoint=true，仅保存 0.1.0 的 request_id；稳定请求内容仍由 Gateway hash 核对。
插件可声明 cancellation=cooperative/0.1.0，须让出 async 执行并检查 Token，遵守任务取消；
未声明时 admission 的 method_cancellation=unknown，不能据资源可取消就宣称插件内部有界。
独立 fixture 仍 supports_checkpoint=false，声明 cooperative，拒绝非空内部 checkpoint。

未完成方法且没有内部 checkpoint 时，continue 返回 checkpoint_unsupported。显式 rerun 可执行此方法。
派生运行的 RunBundle.lineage_ref 指向 immutable lineage.json，记录 operation=derived_rerun、parent_run_id、
input_hashes、父 checkpoint 引用、父公开历史副本、parent_budget_ledger、parent_resource_records 和 reused_records。
语义重跑不复用父模型回复／Solve，reused_records 为空；已有证据副本不冒充新方法输出。
新 run 使用新的 deadline，但父 paid／unknown 尝试、已知 token、未知 reservation 和 Solver 次数仍计入原配置上限。
不足时派生 run 明确 budget_exhausted，不能通过重复派生忘记费用或未知预留。rerun 可产生新的付费请求，须由用户显式选择。
完整 Formulation／Code 阶段直接继续；匹配的 execute_done 复用保存的真实 Execution／SolveResult。
匹配由已验证的公开 bytes、数据绑定、固定配置／Manifest／包及 Worker 身份共同确定。
completed／artifact_ready 恢复幂等；其他过期恢复返回 deadline_exhausted。
solver_calls 在尝试前持久化，取消不退还已开始的 slot；下一尝试需要原预算中剩余 slot。

Gateway admission／settlement 先写 journal/hash.json 不可变版本（0.1.0、previous_sha256、state），
再原子更新私有 state.json，最后回调保存核心资源 hash／账本。两处存储不声称跨文件系统事务。
恢复验证完整单链、核心已知 hash 位于链上、当前 state.json 精确匹配链中版本、固定 archive／Provider／
预算／deadline／请求身份、只追加 attempt 与一次结算、usage／reservation 和 raw response hash。
已验证的新 journal head 可前进于核心引用或 mutable head；其预留和成功回复仍保留。破坏链或实际 bytes 仍拒绝。
archive／journal 目录为 0700，私有文件为 0600，不保存 API credential；只公开脱敏 trace 与累计资源账本。
成功回复复用既有 attempt_id；未知结果保留预留并返回 provider_outcome_unknown，不重新提交相同 request_id。
私有 raw reply 不进入公开 checkpoint。Mock 的同请求工程回复可持久化复用，仍 external_llm_requests=0。
容器和 HTTP 子进程使用已有有界清理；trusted_local 的严格 IR／运行时检查也在拥有的子进程执行。
生成的工厂或 native 源码始终只在隔离 Worker 内执行。

S04-B RunBundle 兼容增加 public_problem_ref 和 public_projections（固定路径 → 不可变 ArtifactRef，排除 bundle 自引用）。评估器同时校验版本引用与当前公开视图，接受 cancelled 并保留评测分母；旧 bundle 的固定路径仍可读取。TaskAdapter 的 write-once snapshot 保持原 public/ 与 private/ 布局，资源控制／history 只属于运行。
