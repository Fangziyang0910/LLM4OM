# 建模方法契约

方法负责推理策略，核心负责资源和记录。所有方法只获得公开问题和已授权资源。编排与来源见[建模方法说明](../development/methods.md)。

## 方法入口与 Context

```python
async def run(problem, context, *, checkpoint=None) -> MethodOutcome: ...
```

实际公共类型在 [methods.py](../../src/llm4om/methods.py)。MethodContext 包含以下资源：

| 字段 | 语义 |
|---|---|
| `llm` | 受预算控制的异步 LLM Gateway |
| `data` | `data_id` 到公开原始字节的映射 |
| `budget/problem_sha256` | 本次预算与输入身份 |
| `cancellation/deadline` | 取消信号和原绝对截止时间 |
| `save_checkpoint` | 可选的版本化方法状态保存回调 |
| `resources` | 已准入的检查、选择、记录与脚本资源 |
| `clarifications` | 已接受的公开回答 |
| `data_views` | 声明暴露范围的数据视图 |
| `code_target` | 已预检后端、求解器与代码要求 |

Context 不包含评估器、隐藏参考材料或密钥。角色通过 LLM request 的 `role` 指定。各角色共享同一次运行的资源。

MethodOutcome 包含 `status/selected_check_id/proposal/clarification`。状态为 `selected/needs_input/failed/exhausted`。单次输出返回 ModelProposal；使用公开检查的方法返回真实检查 ID，并令 proposal 为空。

ModelProposal 包含 ModelArtifact、可空 Formulation、可选严格 IR、代码 proposal 和可选脚本执行 ID。方法不生成平台文件引用或假造求解证据。

## 方法 profile

| profile | 输出与执行要求 |
|---|---|
| `grounded_single/0.2.0` | 五元素及严格 IR，确定性编译后执行 |
| `factory_single/0.2.0` | 五元素及模型工厂，容器构建 |
| `native_single/0.2.0` | 五元素及 gurobipy 工厂，Gurobi/容器 |
| `grounded_checked/0.2.0` | 严格 IR 的公开检查与选择 |
| `factory_checked/0.2.0` | 声明的表述与工厂，可修正和选择 |
| `native_checked/0.2.0` | gurobipy 工厂的公开检查 |
| `native_script/0.1.0` | 原生表述和声明的原生脚本 |
| `native_script/0.2.0` | 允许缺少表述的原生脚本 |

具体后端、求解器和表示由解析后的 Manifest 能力决定。profile 不是对任意组合的支持声明。离线回放仅适用于声明的 Mock 单次路径；需要真实公开检查的 profile 拒绝离线。

`resolve_capabilities(config)` 返回该配置的完整能力对象。未实现此可选接口时使用静态 Manifest。核心按声明匹配，不读取插件私有配置来猜测策略。

## 可组合代码目标

Backend 可声明 `capabilities.code_generation={representation_kind, instruction}`。表示必须属于 Backend 接受类型。Context 提供该要求以及 `model_backend/solver/solver_name`。

共享提示将目标与方法各阶段提示组合，要求生成 `build_model(data)`。方法不按求解器 ID 分支。生成代码只构建模型，平台在隔离校验后执行所选求解器。

## 公开检查与最终选择

```python
async def check(check_id, proposal, *, parent_id=None, change_reason=None): ...
def select(check_id, *, rule, reason) -> MethodOutcome: ...
def remaining_budget() -> dict: ...
```

每个检查先占用一次 `max_checks`，再解析、编译和执行。修正还占用 `max_repairs`，需要同一运行中已检查的父记录及非空原因。实际求解占用 `max_solver_calls`，全部步骤共享原 deadline。

检查记录位于 `checks/<check_id>/record.json`，保存运行、父 ID、顺序、原因、产物引用、方法身份和状态。检查结果位于 `check.json`，保存 proposal 哈希、公开声明引用、阶段状态、执行/求解引用和诊断。

检查 ID 绑定完整 proposal、父关系和原因，不能改绑。无效输出保留诊断。预算在检查准入前拒绝时，不创建检查或额外求解。

最终选择要求检查无错误并具有可信的已完成求解证据。合法不可行或无界结果可以被选择。方法提供规则和原因，核心保存 `selection.json`，并核对运行归属。不同模型的自报目标不能直接用于默认排序。

选择后复用该检查结果，不再次求解。单次输出由平台形成检查 `001`。同身份完成检查的回放不增加检查、修正或求解次数。未知的已准入执行返回 `execution_outcome_unknown`，不自动重做。

## 修正与解码失败

代码修正复用父检查的确切 `formulation_ref`。新代码记录新的实际调用来源。数学表述变化需要新的 Formulation。严格 IR 的修改属于数学表述修改。

变更记录保存五元素和 IR 变化、约束增删、丢失需求关联及父引用。丢失原有公开需求关联返回 `requirement_coverage_lost`。声明比较不等于语义等价检查。

GenerationFailure 绑定真实 `call_id/response_sha256`，并记录有限的错误码、阶段和安全消息。支持 `invalid_json/invalid_object/invalid_method_outcome/llm_output_truncated`。资源核对响应真实存在，按一次检查/修正入账；原始回复不进入公开诊断或修正提示。

传输、认证和未知请求失败不被伪造成模型解码错误。Feedback Repair 按公开合法性、可信 primal、阶段完整性和顺序选择，不使用隐藏目标。

## 方法状态与恢复

内部检查点必须是显式保存的版本化 JSON。`supports_checkpoint=false` 拒绝非空检查点。MethodPlugin 传入深复制，原地修改只有调用 `save_checkpoint` 才持久化。

核心阶段恢复与内部推理恢复分别判断。完整阶段和可信执行结果可由核心复用；未完成推理需要方法检查点。成功选择的发布收据在方法再次进入前冻结，避免重复选择。完整身份规则见[执行与恢复](execution.md)。

## 澄清

`needs_input` 需要声明澄清能力、有效方法检查点和结构化问题，不能同时返回选中输出。问题最多 8 个，每题文本最多 4096 字符，总声明元数据最多 65536 字节。

问题字段为 `question_id/kind/question/statement_ref`。`confirm_existing` 锚定原 requirement 或 assumption 的准确 ID，核心加入原文；`new_information` 的锚点为 `null`。

ClarificationRequest `0.1.0` 保存平台请求 ID、运行、顺序、问题身份/修订/哈希、规范化问题和来源。请求 ID 绑定这些输入。交互运行停在 `needs_input`；非交互运行记录 `unresolved`，保留原尝试和分母。

回答包含 `schema_version/request_id/action/answers`。每题必须有唯一答案。确认要求全部问题为已有声明且值为 `true`。否定或新增事实使用 `revise` 和显式新 ProblemSpec。

修订保持 problem_id，改变 revision，创建派生运行。父问题和历史不改写，已有消耗和未知预留继承。相同请求/回答/修订的重试复用同一派生运行，不能改绑不同输入。

## 公开步骤事件

`resources.emit` 可发布 `type=modeling_step` 事件。字段为 `schema_version=0.1.0`、运行内稳定 `step_id`、`phase/label/actor/status`。字符串身份与标题非空，最多 512 字符。

phase 为 `formulation/code/solve/coordination`，status 为 `running/completed/failed`。协调是跨阶段操作，不增加第三个建模阶段。主机加入 UTC 时间戳；同一 step_id 合并展示生命周期。

完成公开检查发出 `check_finished(check_id, check_ref)`。首次保存选择发出 `selection_saved(check_id, rule, reason)`。同一选择恢复不再发一次事件。步骤完成不推导出业务正确。

## 旧记录

旧 `candidates/` 布局通过 Web 只读适配，文件保持不变。旧 `assess/max_candidates/final_candidate_id` 已改为 `check/max_checks/selected_check_id`。它们不作为新运行的别名；旧检查点不自动迁移。

评测字段 `candidate_primal/candidate_objective` 仍表示被评测模型，按原协议保留。Pass@k 仅统计独立运行，不将同一次运行的修正作为样本。
