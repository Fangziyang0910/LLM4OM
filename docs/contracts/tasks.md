# 任务与评测契约

TaskAdapter 在导入/评测端使用。方法只获得公开问题。指标定义见[评测协议](../evaluation.md)，使用步骤见[Benchmark 与评测数据](../development/benchmarks.md)。

## 共同接口

```text
import_source(config: Path, output: Path, settings: dict) -> Path
iter_cases(manifest: Path) -> Iterator[EvaluationCase]
load_case(manifest: Path, case_id: str) -> EvaluationCase
evaluate(case: EvaluationCase, outcome: Path) -> EvaluationResult
```

`import_dataset` 返回冻结 manifest 路径。`evaluate_case` 和 CLI evaluate 保存新的公开结果文件，不覆盖已有输出。

Task 声明 `frozen_task/0.1.0`、`separate_public_private/0.1.0`、协议和默认评估器。Evaluator 声明 `frozen_evaluation/0.1.0`、协议和 evidence_levels。二者不进入 MethodContext。

导入配置可选 `adapter_config` 和 `evaluation={evaluator_plugin_id, config}`。核心先解析选择字段，再把来源字段交给适配器。doctor --task-config 只预检，不读取隐藏来源或发布快照。

## 冻结与公开边界

导入先验证来源，在独立 staging 生成并核对 public/private 引用，再发布只写一次的快照。公开目录只包含问题及允许数据；privileged manifest 关联私有参考。

Manifest 保留来源、原始 ID、split、行/记录哈希、公开/私有引用、参考质量、选择和资格。`plugin_bindings/0.1.0` 绑定 SDK、Task/Evaluator、配置、依赖和来源，私有 import-seal 绑定最终 manifest 字节。

数据、配置或执行身份变化需要新导入。旧内置未绑定快照只读评测并标为 `legacy_unbound`，不冒充新绑定；已安装未绑定适配器拒绝。

方法、LLM、Worker 和公开导出不获得 manifest 私有引用或参考材料。许可与归属声明按原来源单独保留，不改标为 SDK 许可。

## NL4Opt

导入配置 `0.1.0` 含 `dataset_id/source_kind/source_version/split/path/sha256`。source_kind 为 official/fixture/fork，路径相对于配置且不能越界。固定官方提交为 `49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea`。

完整 split 在接纳前检查哈希、UTF-8 LF JSONL、唯一 JSON 键、有限数、合法唯一原始 ID 和已知记录 schema。未知记录字段拒绝。fixture/fork 使用独立数据集 ID 和版本。

公开描述只来自 `document`。原标注留在私有侧，不转成参考最优值。快照为 public、private 和 manifest；官方 MIT 许可随允许的公开投影保留。

协议为 `llm4om.eval.nl4opt-raw-v0.1`。结构、执行、求解器自报证据分别保存。原标注不提供数值目标，目标匹配资格不能据此建立。

## MAMO

导入配置 `0.2.0` 的 `adapter_id` 为 `llm4om.tasks.mamo`，包含 `dataset_id/source_kind/source_version/files/license_file/reviews/selected/tolerance`。files 明确列出 easy_lp、complex_lp、ode 的本地路径及哈希。

官方身份匹配固定来源、数量和 CC BY-SA 4.0 许可。快照保留全部优化案例及原始记录；公开只投影 Question，Answer 和原数据材料私有保存。ODE 不进入优化范围。

selected=null 选择全部优化题，显式选择使用 `easy_lp:<id>/complex_lp:<id>`。评阅绑定准确 Question 哈希，声明 LP/MILP/unsupported/unresolved、变量域、舍入策略、理由和公开证据位置。

缺评阅保留在 selected，原数据集名称或 Answer 不赋予数值资格。协议 `llm4om.eval.mamo-numeric-v0.1` 使用绝对加相对容差。只按预声明规则舍入被评测目标，原始参考值保持不变。

舍入为 none 或 `decimal_half_away_from_zero`，小数位 0–12。公开结果不泄漏私有目标值、差值或 Answer。

## NLP4LP

导入配置 `0.2.0` 的 `adapter_id` 为 `llm4om.tasks.nlp4lp`，包含 `dataset_id/source_kind/source_version/release_root/sha256/reviews/selected/tolerance`。固定来源清单见 [nlp4lp_source.json](../../src/llm4om/nlp4lp_source.json)。

本地发布包含 train.jsonl、来源 README 和逐实例数据。官方身份锁定提交、聚合哈希及全部 2127 个文件。保留全部 361 个原始案例，参考可用性 322/37/2 分别记录，坏参考不删除公开问题。

公开投影包含描述与原始具体参数 JSON。data_id 为 parameters，类型为 object，原始标量、列表和映射保持。参考代码、problem_info、keywords、参数化描述和解留在私有材料中。

评阅同时绑定描述与数据哈希，说明变量域、舍入、数据绑定和公开证据。数值资格还要求实际可用参考。参考向量存在不证明最优或可行。

协议 `llm4om.eval.nlp4lp-supplied-v0.1` 核对完整公开输入和原数据。复制路径可以不同，但字节、哈希、schema 和问题身份需一致。数值比较在最终选择之后进行。

## 独立解检查器

检查器使用 `llm4om.checkers` entry point，属于可信 Python 扩展。`describe` 声明版本、所需决策/公开数据、目标方向、范围和覆盖；`check` 接收原问题、原始业务数据和显式映射的业务决策。

结果含有限的原目标、方向和独立可行性状态、违反规则及覆盖。通过要求无违反项。输入不包含模型自报目标、候选约束或私有参考目标。检查器包/源码身份在冻结时绑定。

checker_fixture 配置 `0.2.0` 的 `adapter_id` 为 `llm4om.tasks.checker_fixture`，其余字段为 `dataset_id/source_version/cases/selected`。每例绑定公开问题/数据及私有 evaluation policy。缺 policy 如实保存。

私有 policy 包含 checker、decision_mapping、reported_objective_mapping、reference_objective、probe_points 和 data_perturbations。目标映射只接受预声明正比例和偏移。参考声明值、方向、质量、来源和容差。

有限探测最多 5000 个点和 50 次数据扰动。点完整覆盖原决策，替换数据满足原 schema。公开只显示数量、覆盖和反例索引，不导出私有点或替换内容。

探测仅检查与确定性 Code 关联的严格 IR，标为 `finite_predeclared_grounded_instance_probes`。它不证明完整语义、重新绑定或不透明代码等价。

## 评测输出与失败

所有公开引用先核对字节、大小和身份，再使用校验标记。原始运行的公开输入与 case 绑定；尚未保存输入的失败记录只能标为绑定不可用。

结果中的 case、协议、manifest、资格、run 和计数需与冻结记录一致。资格确定后，生成、执行或检查器失败保留分母，分子为零。零分母的率为 `null`。

检查器分别冻结 `N_independent_eligible/N_verified_eligible`；后者还需质量阈值。公开结果区分自报匹配、原目标质量、独立可行性、verified solution 和性质探测。

未知案例或无效 manifest 为准入错误。材料改变、丢失或检查器异常保存安全评测错误。公开结果不能超过声明证据层次，也不能包含 oracle 字段、私有引用或受限配置。
