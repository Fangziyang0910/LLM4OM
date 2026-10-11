# S04-B 取消与恢复

本页记录 Issue 16 的当前实现与本机验收范围。规范来源为 [DD-07](../design/experiments-and-interfaces.md#dd-07-持久化恢复与报告)、[接口契约](../plugin-contracts.md#12-s04-b-cancellation-and-resume-sdk-070) 和 [验收清单](../acceptance.md)。首次实现于 SDK／Worker 0.7.0，当前已在未发布的 0.8.0 完成集成验收。

## 当前入口

```bash
llm4om cancel --run-id RUN_ID --output runs
llm4om resume --run-id RUN_ID --output runs
llm4om resume --run-id RUN_ID --output runs --strategy rerun
```

SDK 导出 `CancellationToken`、`cancel_run(run: Path)`、`resume_run(run: Path, *, cancellation=None, strategy="continue")`。
`run_problem` 新增可选 cancellation 参数，旧调用保持有效。Token 只绑定一次；需要恢复时使用新 Token。
CLI 的 SIGINT 设置相同的协作取消信号，返回可检查的 cancelled RunBundle。

## 实际恢复行为

核心保存 admitted、method_done、code_done、execute_pending、execute_done 的阶段位置；方法内部 JSON checkpoint 独立保存。
MethodPlugin 传入深拷贝；未显式保存的嵌套修改不会随 Gateway 资源回调提交。
Direct 的内部 checkpoint 仅保存版本与 request_id，恢复时重新解析已保存的响应，不声称保存了任意方法搜索状态。
Formulation 的核心引用、阶段和候选计数随 formulation_saved 一起提交；Code 的 build 先保存，阶段随 code_saved 一起提交。
完整 ModelArtifact 先于核心阶段发布时，恢复使用已验证的中断收据与实际不可变引用，在内部 checkpoint 拒绝前接纳完成阶段。
共用既有引用图校验；核对原公开问题、方法身份、Formulation／数据绑定和方法提供的 Code 来源，不拼造 ModelArtifact。
已完成 Formulation／Code 不再运行方法。匹配的 completed Execution／SolveResult 直接复用。
已经 completed／artifact_ready 的运行保持同一 run_id，事件和输入不变。

默认 continue 对不支持内部 checkpoint 且尚无完整阶段的插件返回 checkpoint_unsupported。
尚未调用方法的 admitted 阶段可以开始执行；核心在调用前保存 method_started，避免把已开始但无 checkpoint 的方法当作首次调用。
显式 rerun 创建新的运行并重新执行方法，保存 lineage_ref、父输入 hash、checkpoint／公开历史副本、累计费用与未知预留。
它可以产生新付费请求；不把父成功响应或 Solve 当作新方法输出。已有成功响应在 continue 中仍复用。
新运行使用新的 deadline；已有 paid／unknown 尝试、token／reservation 和 Solver 次数继续计入配置上限。
上限耗尽时派生运行明确失败；同一运行的 budget／deadline 从不重置。阶段已完成时，核心继续不要求方法内部 checkpoint。

恢复校验公开输入与配置字节、所有保存的引用和当前公开视图、方法 profile／Manifest／安装包、SDK 源码与版本、
Python／依赖版本、Worker 镜像与资源配置。校验失败先于 Provider HTTP 和候选求解。
公开路径保留原始输入身份；内容版本存于 history，原事件引用不会因新摘要而失效。
checkpoint.json 的 bytes 另存不可变 checkpoints/hash.json。视图替换前持久化以旧 checkpoint／owner 为基线的写入意图。
验证中断 owner 和不可变记录后，恢复只重建未提交视图；真正损坏的已提交公开 bytes 仍拒绝。
重建前把已验证的中断引用写入不可变核心 checkpoint；后续身份校验失败仍保留该收据。
应用核对已完成 Execution 的 run／attempt、输入与执行后候选、Code／数据绑定、Solver／Worker 身份和所有实际引用，
在核心仍为 execute_pending 时复用真实结果。即使 max_solver_calls=1 已耗尽，也不重新求解或转为 budget_exhausted。
新建 run／history／checkpoint／archive／journal 的全部目录祖先项在记录发布前持久化；文件权限与独占创建保持。
同一 run 的文件锁只允许一个写者。控制文件绑定 run_id、UID 和随机 owner_id；cancel 不向持久化 PID 发信号。

Gateway 保存的成功响应只复用，不新增 HTTP attempt。未知结果保留 reservation，request_id 不重发。
私有 archive 仍位于 store/.private/run_id；不可变 journal 连接每次 admission／settlement，state.json 必须精确匹配链中版本。
state.json 所处版本不得早于核心已提交 hash；有效旧 genesis 覆盖已提交 settlement 同样拒绝。
恢复从核心已知 hash 验证整条资源链，保留先于核心回调落盘的成功回复或未知预留；不声称跨文件系统事务。
首次 head 尚未创建时，仅恢复有效的空 genesis；已提交 head 的丢失或损坏仍拒绝。
Gateway.recover 负责完整校验，向应用返回 ledger 和明确字段列表投影的公开 trace，应用不解析私有日志。
目录 0700、文件 0600。checkpoint 只保存 hash／公开资源位置，不导出 raw reply 或凭据。
同一运行的总预算和绝对 deadline 不重置；过期恢复拒绝。已开始的 Solver 尝试仍计数，取消后再执行需要原预算中剩余的 slot。

## 取消与清理

Provider HTTP、Docker 控制／attach 与 trusted_local 的平台子进程均可被取消。
实际生成的参数化 Pyomo 和 native gurobipy 仍只在隔离 Worker 内构建。
trusted_local 子进程仅接收严格 IR，通过平台 API 求解，不执行模型源文件。
取消保留真实 stdout／stderr、已完成阶段与终态；没有实际 Solver API 结果时不生成 SolveResult。
Docker 清理继续使用既有有界 kill／inspect／remove；daemon 故障时保留实际诊断，不声称删除已成功。

安装的可信方法声明 `cancellation: cooperative/0.1.0`，须让出 async 执行并检查 Context cancellation，
不能吞掉任务取消或使用无界阻塞调用。缺少声明仍兼容旧 profile，但 admission 标记 unknown，不能声称方法内部执行有界。
这不是任意第三方 Python 插件的强制隔离。

## 本机证据与范围

`tests/test_resume_crash.py` 用实际 CLI 子进程在 OS rename 边界硬退出，覆盖公开视图、Solver 计数、
成功／未知资源提交、journal 与 mutable head 间隙、真实损坏拒绝、派生累计费用。
`tests/test_async_control.py` 验证公共 Method 取消等待清理及 SystemExit 诊断。
`tests/test_resume_run.py` 覆盖 CLI／SDK 取消、SIGINT、HTTP 子进程回收、无关宿主进程存活、
真实 Docker 删除、响应成功与未知结果复用、Code／Solve 完成边界、预算／deadline、损坏输入与并发写锁。
`tests/test_plugins.py` 覆盖独立安装方法的默认拒绝与显式派生重跑；原 Provider／Executor／Solver 测试保留。
手工候选验证目标 13、40/3 和 3；参数化 Pyomo 与 native Gurobi 的恢复不再发 HTTP 或最终重复求解。
合成 HTTP fixture 不证明某个付费模型的质量；Gurobi 仍只声明既有 size-limited 微型环境。

2026-10-09，集成版本 `ecefddd` 的本机 Python 3.12.11 完整回归：**241 tests，522.681 秒，全部通过**。
它包含全部最新修复：Formulation／Code／Execution 的完成发布恢复、方法 checkpoint 所有权、目录持久化、
资源 head 回退拒绝、取消清理、未知请求预留和显式派生重跑。原始独立方法、参数化 Pyomo／native Gurobi、
Task 导入与评测回归保留，真实 Docker／Solver 未跳过。

独立 Standards／Spec 审阅对照原始 S04-B／S05-B 范围，未发现新的 P1／P2；2026-10-11对resume／派生路径的复审同样通过（见/tmp/llm4om-reviews/s08-s09-group.md）。
strict mypy 检查22个源码文件，仓库128文件与参考检查、wheel／sdist 构建通过。
干净 Python 3.11.13 wheel 的7项重点场景通过（44.426秒），另经合成 Messages 与真实 Worker
求得 A=3、B=2、目标13；completed 恢复不需凭据，容器已删除。没有重复第二套完整版本矩阵。

源码／安装 wheel／Worker 的 SDK hash 为 `4913ca520852db5587fe79195992ce99f303480c7cc7f54f8ac796992fbdb063`；
镜像为 `sha256:edd9be002d1c96f8656cbf00f793d8e775182bc221c29308df0de4525a85a87f`。
公开产物与包的项目密钥扫描通过。完整日志、wheel／Worker 证明和审阅记录位于
`/tmp/llm4om-s05b/integrated-full-python312.log`、`/tmp/llm4om-s05b/integrated-evidence/` 和
`/tmp/llm4om-s05b/integrated-review-{standards,spec}.md`。

此前修复的逐步 red／green 保存在 `/tmp/llm4om-s04b/fix-evidence/`、
`/tmp/llm4om-s04b/final-fix-evidence/` 和 `/tmp/llm4om-s04b/formulation-fix-evidence/`。
这些工程 fixture 不证明付费模型质量；实际 Messages 模型任务另见 [S05-B](s05b-messages.md#实际服务与模型)。
验收覆盖进程硬退出与 OS 文件发布失败，未验证物理断电。未触发云端 CI。
OptiMUS／CoE、Web、batch 与完整 1.0 尚未完成；本切片不更改这些已批准范围。

Formulation／Code 后续修复的独立方法、工厂／native 与阶段复用 red／green 另存于
`/tmp/llm4om-s04b/formulation-fix-evidence/`；它们已纳入上述241项完整回归。

恢复要求原公开输入／配置仍在原路径且字节不变；本版不提供移动目录后的自动路径迁移。
已完成运行的身份校验不加载 Provider 凭据，也不新增模型／Solver API 调用。

S05-B 的 SDK0.8.0 将相同资源 journal 用于 OpenAI-compatible 与 Messages，解码由 Adapter 声明。
成功回复回放延迟凭据解析，API key 缺失不阻止复用；完整运行仍拒绝 SDK／源码身份不一致，
不会自动迁移本页0.7.0记录。新增证据见 [S05-B](s05b-messages.md)。
2026-10-11 P3 处置：澄清派生重试的快速路径窥读子 checkpoint 失败时回退到全量验证 resume（原先未验证窥读可抛裸 KeyError）。备注：deadline 检查在两层冗余出现，诊断来源可能不稳定，按备注保留。
