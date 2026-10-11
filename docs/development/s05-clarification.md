# S05-D2 澄清、确认与问题修订

SDK／Worker0.17.0 开发切片，工作项为 [#36](https://github.com/Fangziyang0910/LLM4OM/issues/36)。字段与状态语义见 [插件契约第22节](../plugin-contracts.md#22-s05-d2-clarification-sdk-0170)，原需求为FR-19/33、AC-09/23；完整平台与独立审阅仍待验收。2026-10-11独立Standards／Spec审阅通过：五个模块全部PASS-WITH-NOTES，无P1/P2，仅P3打磨项（报告/tmp/llm4om-reviews/s05-group.md）。

## 实际行为

支持澄清的方法返回 `needs_input` 与结构化 questions。核心校验原问题锚点并保存请求；CLI／SDK 的显式交互运行停在 `needs_input`，默认非交互运行以 `unresolved` 保留原始尝试与用量。没有回答的恢复不新增请求。

`confirm_existing` 只确认原问题中的 requirement 或 assumption。请求同时保存原文 statement，回答只能为true；否定、自由补充或数据／规则变化需要 `revise` 和显式新 ProblemSpec revision。确认记录通过公开 MethodContext 进入后续生成，原输入字节和已有候选不改写。

新修订保持problem_id、改变revision，在新run中建模。父公开问题、bundle、事件、用量与评分保持不变；子运行保存lineage、父历史副本、回答和已有用量。相同回答／修订重试复用同一子run，不能把已登记的revision重绑到不同输入。原run截止时间不延长；派生run有自己的截止时间，父用量和未知预留继续计入上限。

## CLI 与 SDK

```bash
uv run --locked llm4om run --interactive --problem problem.json --config run.yaml --output runs
uv run --locked llm4om resume --run-id RUN_ID --output runs --answers answers.json
uv run --locked llm4om resume --run-id RUN_ID --output runs --answers revision-answers.json --revised-problem problem-v2.json
```

第一条返回运行路径与needs_input；打开bundle的clarification_request_ref取得平台request_id。确认回答示例：

```json
{
  "schema_version": "0.1.0",
  "request_id": "COPY_THE_SAVED_REQUEST_ID",
  "action": "confirm",
  "answers": [{"question_id": "domain", "value": true}]
}
```

补充信息使用action=revise、value为公开文字，并提供明确的新问题修订；平台不从回答文本推测或自动改写业务规则。SDK用例为 `run_problem(..., interactive=True)` 和 `resume_run(..., answers=Path(...), revised_problem=Path(...)|None)`。交互状态的CLI退出码为0，unresolved退出码为1；0不代表已有模型或解。

## 恢复与当前证据

请求ID绑定run、原输入hash、问题与顺序，publication崩溃后保持同一ID。已发布的确认回答在恢复时重新验证并接纳，不要求再次提交文件。派生登记先保存可恢复的子初始化身份，再发布父关联；崩溃后完成同一子run，不重新分配付费工作。

Python3.12.11完整本机回归342项／814.375秒通过。8项澄清聚焦／32.201秒与干净Python3.11.13 wheel的8项／45.725秒通过：交互确认／真实HiGHS13、非交互unresolved、新增A≤2修订／真实HiGHS12、父历史不改写、同修订复用、无效回答、假锚点及请求／回答／派生登记的硬退出恢复。另修复等待状态下显式rerun被普通等待返回截断的问题，使用聚焦检查（本机1项／6.384秒；wheel1项／8.702秒），不重复完整回归。类型34模块、仓库191文件、资料导出、wheel／sdist及代码身份检查通过。GitHub Actions未触发。

实际外部运行 `0d65a4337d6349faab69f8079b5c3efd`：在原公开问题中声明待确认的非负整数假设，并要求先确认。DeepSeek-v4-pro-0813实际提出confirm_existing请求；提交绑定的true回答后，实际模型生成与容器HiGHS得到x_A=3、x_B=2、目标13。两次实际请求报告合计7470 tokens，cost未知；一候选／一Solver、零修正。选择后的原CSV业务检查通过，人工检查映射A→x_A、B→x_B明确保存；不作为冻结benchmark协议成绩。

真实pilot采用最终rerun小修复前的精确快照，源码hash `f21d7ffe3701ae076055c212f0c02969cadfaefbae9f1bee1750c6c6625df62f`／image `sha256:f17f98e8205173f28b03940b74921fd6ea3aa572be9666938ff35554e111b3e8`。该wheel及镜像单独保留，完成后用同一快照无凭据恢复，账本不变；没有新增付费重复。

最终源码／wheel／Worker hash为 `fa1ba6d20d6d2cd28c7d66026d6efbdf74acec82701b731f930d27d0cdb6435c`，image `sha256:ce6406fb7242e6bc01451be62d2b8b0ebc418b3fe7cb28a286f20bffb88c03a1`；两快照分别记录，不静默迁移旧运行。全部证据、私有Provider记录、原业务检查与恢复日志在 `/tmp/llm4om-s05d2-evidence/`。

反馈方法当前实现澄清；Direct／OptiMUS／CoE保持各自声明，不自动宣称具有交互流程。新增信息不会替换隐藏评测参考，也不把修订后的问题当作原题正确解。完整注册、批量实验、Web工作台与剩余发布验收仍在全目标内。
2026-10-11 P3 处置：65536 字节上限检查移出 jsonschema try 块——RunError 继承 ValueError，原先可被同一 except 吞掉；边界行为不变。
