# S04-B 取消与恢复

本页记录 Issue 16 的当前实现与本机验收范围。规范来源为 [DD-07](../design/experiments-and-interfaces.md#dd-07-持久化恢复与报告)、[接口契约](../plugin-contracts.md#12-s04-b-cancellation-and-resume-sdk-070) 和 [验收清单](../acceptance.md)。SDK／Worker 为 0.7.0，未发布；独立审查与发布由父任务处理。

## 当前入口

```bash
llm4om cancel --run-id RUN_ID --output runs
llm4om resume --run-id RUN_ID --output runs
```

SDK 导出 `CancellationToken`、`cancel_run(run: Path)`、`resume_run(run: Path, *, cancellation=None)`。
`run_problem` 新增可选 cancellation 参数，旧调用保持有效。Token 只绑定一次；需要恢复时使用新 Token。
CLI 的 SIGINT 设置相同的协作取消信号，返回可检查的 cancelled RunBundle。

## 实际恢复行为

核心保存 admitted、method_done、code_done、execute_pending、execute_done 的阶段位置；方法内部 JSON checkpoint 独立保存。
Direct 的内部 checkpoint 仅保存版本与 request_id，恢复时重新解析已保存的响应，不声称保存了任意方法搜索状态。
已完成 Formulation／Code 不再运行方法。匹配的 completed Execution／SolveResult 直接复用。
已经 completed／artifact_ready 的运行保持同一 run_id，事件和输入不变。

不支持内部 checkpoint 且尚无完整阶段的插件返回 checkpoint_unsupported，不创建新运行、不重发模型请求。
本切片选择明确拒绝，不提供派生重跑策略。阶段已经完成时，核心恢复不要求插件支持内部 checkpoint。

恢复校验公开输入与配置字节、所有保存的引用和当前公开视图、方法 profile／Manifest／安装包、SDK 源码与版本、
Python／依赖版本、Worker 镜像与资源配置。校验失败先于 Provider HTTP 和候选求解。
公开路径保留原始输入身份；内容版本存于 history，原事件引用不会因新摘要而失效。
同一 run 的文件锁只允许一个写者。控制文件绑定 run_id、UID 和随机 owner_id；cancel 不向持久化 PID 发信号。

Gateway 保存的成功响应只复用，不新增 HTTP attempt。未知结果保留 reservation，request_id 不重发。
私有 archive 仍位于 store/.private/run_id，checkpoint 只保存其 hash／公开资源位置，不导出 raw reply 或凭据。
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

`tests/test_resume_run.py` 覆盖 CLI／SDK 取消、SIGINT、HTTP 子进程回收、无关宿主进程存活、
真实 Docker 删除、响应成功与未知结果复用、Code／Solve 完成边界、预算／deadline、损坏输入与并发写锁。
`tests/test_plugins.py` 覆盖独立安装方法的诚实拒绝；原 Provider／Executor／Solver 测试保留。
手工候选验证目标 13、40/3 和 3；参数化 Pyomo 与 native Gurobi 的恢复不再发 HTTP 或最终重复求解。
合成 HTTP fixture 不证明某个付费模型的质量；Gurobi 仍只声明既有 size-limited 微型环境。

交付执行一次 Python 3.12 主回归、strict mypy、仓库／参考检查、包构建及匹配的新 Worker 镜像验收。
Python 3.11 使用干净 wheel 做聚焦兼容检查。具体命令与结果保存于任务证据目录，由父任务独立复核。
OptiMUS／CoE、Web、batch 与完整 1.0 尚未完成；本切片不更改这些已批准范围。

恢复要求原公开输入／配置仍在原路径且字节不变；本版不提供移动目录后的自动路径迁移。
已完成运行的身份校验不加载 Provider 凭据，也不新增模型／Solver API 调用。
