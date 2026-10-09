# S04-B 取消与恢复

本页记录 Issue 16 的当前实现与本机验收范围。规范来源为 [DD-07](../design/experiments-and-interfaces.md#dd-07-持久化恢复与报告)、[接口契约](../plugin-contracts.md#12-s04-b-cancellation-and-resume-sdk-070) 和 [验收清单](../acceptance.md)。SDK／Worker 为 0.7.0，未发布；本机验收已通过，修复后的独立审查仍待完成。

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
Direct 的内部 checkpoint 仅保存版本与 request_id，恢复时重新解析已保存的响应，不声称保存了任意方法搜索状态。
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
同一 run 的文件锁只允许一个写者。控制文件绑定 run_id、UID 和随机 owner_id；cancel 不向持久化 PID 发信号。

Gateway 保存的成功响应只复用，不新增 HTTP attempt。未知结果保留 reservation，request_id 不重发。
私有 archive 仍位于 store/.private/run_id；不可变 journal 连接每次 admission／settlement，state.json 必须精确匹配链中版本。
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

2026-10-09 修复基线 f82b8e2 本机 Python 3.12.11 完整回归：200 tests，379.359 秒，全部通过。
strict mypy 检查 22 个源码文件；仓库／参考检查、wheel／sdist 构建通过。
Python 3.11.13 使用干净 wheel：11 个崩溃／派生用例、2 个监督用例、1 个 Provider 复用用例通过；没有重复完整矩阵。
新 Worker 实际求解目标 13，容器已删除；镜像 ID 为 `sha256:995a1957f3eb8817fc94c7178c30478bb03351665a2b0ea56206de85fd88d391`。
容器与本机 SDK 源码 hash 都为 `eff6ca3ac5731a30ce2155919ffc62689be956f0718c0e422582d506576febcf`。
证据位于 `/tmp/llm4om-s04b/fix-evidence/`。旧 SDK 的两个崩溃用例独立复现失败，新实现通过；
验收覆盖进程硬退出与 OS 文件发布失败，未验证物理断电。没有付费模型请求或云端 CI。
后续独立复审发现并修复完成状态提交、首次 genesis 恢复、转义凭据和私有日志耦合问题。
求解完成状态在 solver_finished 之前提交，已用耗尽 Solver 上限的硬退出／恢复用例验证复用目标 13。
最新修复的完整回归、镜像一致性及复审仍待验收，以上基线包／镜像证据不替代最新源码验收。
OptiMUS／CoE、Web、batch 与完整 1.0 尚未完成；本切片不更改这些已批准范围。

恢复要求原公开输入／配置仍在原路径且字节不变；本版不提供移动目录后的自动路径迁移。
已完成运行的身份校验不加载 Provider 凭据，也不新增模型／Solver API 调用。

S05-B 的 SDK0.8.0 将相同资源 journal 用于 OpenAI-compatible 与 Messages，解码由 Adapter 声明。
成功回复回放延迟凭据解析，API key 缺失不阻止复用；完整运行仍拒绝 SDK／源码身份不一致，
不会自动迁移本页0.7.0记录。新增证据见 [S05-B](s05b-messages.md)。
