# 核心对象与配置

本页定义跨模块的数据约定。方法调用见[方法契约](methods.md)，构建和求解见[执行契约](execution.md)。

## ArtifactRef

必需字段为 `artifact_id`、`media_type`、`sha256`、`size_bytes`、`namespace`、`relative_path` 和 `schema_version`。非结构化文件的版本可以为 `null`。

路径限定在授权根目录。拒绝目录穿越、符号链接越界和未经声明的远程下载。哈希按原始字节计算；规范化 JSON 的哈希另记规范化版本。自然语言和浮点表示不被隐式改写以合并样本。

## ProblemSpec 与 PublicProblem

| 字段 | 约束 |
|---|---|
| `schema_version` | 已支持的公开问题版本 |
| `problem_id/revision` | 稳定问题 ID 与输入修订 |
| `description/language` | 原始描述和语言标识 |
| `problem_type_hint` | `lp/milp/unknown` |
| `requirements` | 可空；条目含 `id/text/category/source_span` |
| `data_refs` | 可空；条目含 `data_id/path/format/schema/sha256` |
| `assumptions` | 可空；条目含 `id/text/origin/status` |
| `source` | 用户输入或数据集身份与来源 |
| `metadata` | 声明的公开元数据，排除秘密和参考答案 |

需求类别为 `objective/domain/constraint/data/other`。`source_span` 指向原文字符范围或表格定位。假设状态为 `explicit/proposed/confirmed`。

PublicProblem 是路径、哈希和权限校验后的公开投影，不增加参考目标或参考代码。自然语言输入无需人工拆分需求。方法推断的规则保留方法来源，不能变成原始确认事实。

CSV 数据声明表头、类型、空值和唯一键。JSON 数据使用公开对象及 `schema.type=object`。单文件最多 8 MiB。拒绝重复键、非有限值和隐藏参考字段。保留原始字节，格式不被自动互换。

## 阶段产物与 ModelArtifact

ModelArtifact 封装一组数学表述和求解代码。最终选择确定建模输出；中间阶段产物保留各自来源。

| 字段 | 含义 |
|---|---|
| `schema_version/artifact_id` | 结构版本与产物身份 |
| `problem_ref/data_bindings` | 公开问题修订与数据哈希 |
| `formulation_ref/code_ref` | 阶段引用，可为 `null` |
| `stage_status` | 每阶段为 `available/pending/not_available`，不可用时说明原因 |
| `assumptions/requirement_traces` | 声明假设和需求映射 |
| `diagnostics/warnings/provenance` | 诊断、警告和实际生成来源 |
| `optional_views` | 带来源标记的其他视图 |

`available` 必须有对应引用。原生代码方法缺少数学表述时，如实记录 `not_available`。补写或提取的表述保留 `inferred/extracted` 来源。

### FormulationArtifact

必需字段为 `schema_version/formulation_id/problem_id/problem_revision/representation_kind/representation/data_bindings/provenance`。

默认 `five_element` 表述包含 `sets/parameters/variables/objective/constraints`。集合记录索引和元素或公开数据来源；参数记录值或来源映射；变量记录域和界；目标与约束记录表达和需求映射。

`expression_text` 和 LaTeX 用于阅读，不作为任意可执行表达式。需要确定性编译时，`structured_ir_ref` 指向已校验的严格 LPIR。没有严格 IR 时，由代码阶段生成实现。

`native_formulation` 保留声明的来源 schema 和原始状态。其他表示需要显式能力声明。当前没有通用 DSL 求解承诺。

### CodeArtifact

必需字段为 `schema_version/code_id/representation_kind/representation_ref/model_backend/source_formulation_ref/data_bindings/provenance`。来源表述可以为 `null`，但需要相应方法能力。

代码来源区分方法生成、确定性编译和人工修改。编译产物记录编译器、源 IR、配置和 symbol map。工厂入口为 `build_model(data)`；声明的原生脚本按锁定入口运行。

数据绑定至少包含 `data_id` 和原始哈希。可用时另记录参数、列、键、单位和变换来源。换数据或改变数学含义需要新的修订或阶段产物。导出视图不能替代原表述。

## GroundedLPIR

`grounded_lp/0.1.0` 表达具体数据实例的单目标线性 LP/MILP。

```text
ModelIR = {
  schema_version, ir_kind, problem_type, model_id,
  problem_id, problem_revision, data_bindings,
  variables: [{id, name, domain, lower_bound, upper_bound, requirement_ids}],
  objective: {sense, expression, requirement_ids},
  constraints: [{id, expression, sense, rhs, requirement_ids}],
  assumptions, provenance
}
LinearExpression = {
  constant: finite-number,
  terms: [{variable_id, coefficient: finite-number}]
}
```

变量域为连续、整数或二元。无界界限使用 `null`。变量和约束 ID 唯一，重复线性项按数学语义合并。二元域与显式界取交集；矛盾界拒绝，不自动交换。

表达式为常数加线性项之和。目标常数、约束常数和目标方向必须保留。`lp` 不能包含整数或二元变量。未支持的非线性、indicator、SOS 和逻辑结构不能放进文本字段后称为可编译。

## BuildArtifact 与 ModelHandle

BuildArtifact 关联 Code，保存编译器身份、源哈希、目标后端、模型文件、数据绑定、symbol map 和诊断。编译生成派生产物，不改变方法身份。

ModelHandle 仅在 Worker 内持有实际后端对象和决策映射。跨进程传输使用受控实例或 MPS，不传输 Python 模型对象。

## 求解与执行记录

SolveResult 包含求解器身份、后端、原始状态、`termination`、`has_primal_solution`、解引用、目标、方向、bound、gap、耗时、选项、诊断和证据来源。

`termination` 为 `optimal/feasible/infeasible/unbounded/infeasible_or_unbounded/time_limit/interrupted/error/unknown`。没有 primal 时，解和目标为 `null`。gap 保留求解器报告值；其他计算需要注明公式。

ExecutionResult 保存执行身份、模式、状态、时间、退出码、资源测量、输出截断、日志引用、诊断和可空的求解引用。执行成功不推导出模型最优。未采集资源为 `null`。

## 评测对象

EvaluationCase 将公开问题与私有参考评测材料关联。EvaluationOracle 可包含参考目标、参考解、独立检查器、参考模型、性质或人工评阅。缺失项表示证据不可用。

EvaluationResult 保留协议、最终检查、各层状态、证据、分母和错误。检查状态为 `pass/fail/unknown/not_available/error`。目标匹配不改名为语义正确率。详细规则见[评测协议](../evaluation.md)。

## RunConfig

必需字段为 `schema_version/method/llm/model_backend/solver/executor/budget/store`。严格 IR 路径需要 `compiler`。`reporters/roles/evaluation/allowed_problem_types` 等选项使用声明的默认值。

普通插件选择为 `{plugin_id, config}`，LLM 为 `{provider_plugin_id, model, config}`，求解器为 `{plugin_id, options}`。配置字段经 schema 校验。未知键拒绝，模型和求解器不能隐式替换。

问题通过应用参数或 `--problem` 传入，不在单问题配置中要求任务清单、实验 ID 或 oracle 路径。缺省公开评测使用 `llm4om.eval.public-v0.1` 和 structural 评估器。无参考材料仍可运行。

预算计数为非负整数，总时间为正数，并发至少为 1。允许 `max_repairs=0`。预算使用 `max_checks`，不再接受旧 `max_candidates`。

## ExperimentSpec

`0.1.0` 包含 `schema_version/experiment_id/tasks/configurations/repeats/budget/exclusions`，并可选择报告器。任务为 `{id, manifest}`，可选 `case_ids` 限定原选中案例；配置为 `{id, run_config}`。

任务、配置和重复次数展开矩阵。首个模型请求前预检全部未排除组合。排除项包含 `task_id/configuration_id/reason`。资格不随方法结果变化。

实验预算声明并发、总时间、LLM 尝试、token 和求解次数。调度预留完整单运行计数上限，已开始预留在恢复后保留，当前不回收未用额度。

公开实验记录保留配置、案例、结果和来源；私有调度状态保存输入路径与哈希。来源、协议、配置和 repeat 分组统计。未知数值在 JSON 为 `null`、CSV 为空。

## 公开运行布局

以 `bundle.json` 中的实际引用为准。常见文件如下，尚未产生的阶段不补造。

```text
RUN_ID/
  bundle.json
  public-problem.json
  public-config.json
  environment-lock.json
  budget-ledger.json
  events.jsonl
  checks/CHECK_ID/
    record.json
    check.json
  selection.json
  evaluation.json
  reports/
```

公开引用保留大小、哈希和命名空间。原始响应和资源日志位于存储根目录的 `.private/`，不进入公开 bundle。存储可写时，失败也保存可用产物；存储不可用时，CLI 返回 `store_unavailable` 和退出码 2。

## 错误与版本

实际异常使用 `RunError(code, stage, message, details=...)`。公开 bundle 的错误保留 `code/stage/message`；各接口可以投影经校验的公开详情。错误码采用源码中的小写形式，如 `invalid_config`、`capability_mismatch`、`budget_exhausted` 和 `checkpoint_incompatible`。

不可行模型属于求解结果。缺参考属于证据不可用。评估器异常才属于评测错误。版本不支持时在执行前拒绝，旧输出保持不变。新增问题类型或指标语义时更新对应 schema 或协议。
