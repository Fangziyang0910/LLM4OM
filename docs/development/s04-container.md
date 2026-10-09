# S04-A 容器执行

本页记录已批准 S04-A 的实现与真实验证，关联 [Issue #6](https://github.com/Fangziyang0910/LLM4OM/issues/6)。规范来源为 [执行设计 DD-05](../design/execution.md)、[契约](../plugin-contracts.md)及 [AC-05/14](../acceptance.md)。当前路径为公开 grounded LPIR → 确定性 CodeArtifact → Pyomo／HiGHS；取消与恢复由 S04-B 继续实现。

## 使用

在 Linux 主机上安装 Docker Engine，确保当前用户可以访问 daemon，再从仓库根目录执行：

```bash
uv sync --locked --extra dev --extra solve
uv run --locked python scripts/build_worker_image.py
uv run --locked llm4om doctor --config examples/specs/run.yaml
uv run --locked llm4om run --problem examples/specs/problem.json --config examples/specs/run.yaml
```

构建器只向 Docker 提供 SDK wheel、带 hash 的锁定依赖和 Dockerfile。它不使用仓库根目录作为构建上下文。`--offline` 仅让 uv 使用本地解析／构建缓存；Docker 的基础镜像与 pip 依赖仍须已经可用或可下载。执行阶段使用本地镜像，不自动 pull。

`run.yaml` 默认选择 container，`--offline` 仍可回放同一配置。`solve.yaml` 显式选择 trusted_local。缺少 Docker、镜像或 Worker 依赖会在方法运行前拒绝；不会改成 trusted_local。容器路径只需宿主的基础 SDK，Pyomo／HiGHS 来自 Worker 镜像；完整开发测试同时验证本地路径，因此仍安装 solve extra。

## 输入、执行与证据

doctor 和 run 共用 admission。Worker 的真实运行检查返回 Python、SDK、Pyomo 和 highspy 版本；检查完整元数据和与宿主相同的 SDK 版本，非法证据明确拒绝。运行计划保存镜像 ID；候选执行使用该不可变 ID，避免预检后同名 tag 被替换。核心仅挂载请求 JSON、实际 CodeArtifact 和明确公开 CSV，不挂载问题目录、源码、`.env`、oracle 或 Docker socket，也不转发宿主环境变量。

可信 Worker 同时检查 IR 编译代码与实际挂载代码的 SHA-256。两者必须对应同一个 CodeArtifact。Worker 通过平台构建／Solver API 抽取结果，不从候选打印的数字生成 SolveResult。任意脚本的 Executor 测试只验证隔离行为，其 stdout 不被解释为求解证据。

ExecutionResult 保存实际 exit code、镜像与容器 ID、资源限制、Worker 状态、输出截断和控制／清理诊断。stdout／stderr 合计受到上限约束。正常 Worker 的 CPU 时间与峰值 RSS 来自 Linux getrusage，覆盖该 Worker 进程；它们不等同于整个容器的 cgroup 采样。资源故障未得到这些测量时为 null。超时、OOM 和输出超限不制造 Solver 状态或解。

## 限制

| 配置／固定策略 | 实际行为 |
|---|---|
| network=false | Docker network=none |
| cpu_limit | cgroup CPU 配额；保存 NanoCpus |
| memory_limit_mb | 内存上限；memory-swap 与 memory 相同 |
| wall_time_s | 从创建准备开始计时；超时终止 Worker |
| pids_limit，缺省 64 | 限制容器进程／线程数 |
| output_limit_bytes，缺省 1 MiB | stdout／stderr 合计上限；超过后停止 Worker 并继续排空管道 |
| 固定权限 | UID/GID 65532、只读根目录、cap-drop ALL、no-new-privileges |
| 固定挂载 | 公开输入只读；64 MiB 的 /tmp 为 tmpfs、noexec、nosuid、nodev |

Docker 控制命令各有 2 秒上限，控制输出上限为 1 MiB；本地 CLI 进程组终止后最多等待 0.5 秒回收。超限后 attach／kill 也有明确期限，持续排空输出避免管道背压阻止终止。容器退出后执行 remove；清理失败保留容器身份和诊断，不把失败覆盖成成功。daemon 完全失联时无法保证远端容器已经删除，恢复后的自动协调仍属后续恢复工作。

若正常收集到 exit=137 且 OOMKilled=false，执行器最多等待 2 秒复查该标记。仍缺少标记时，再有界查询该容器在本次运行时段的 Docker oom 事件；实际标记或匹配容器 ID 的事件才构成 OOM 证据。ExecutionResult 的 oom_evidence 说明来源为 docker_state／docker_event。没有相应证据的 SIGKILL 仍为 failed；事件历史可能不完整，缺少事件不证明没有 OOM。已经确定的 timeout／output_limit 保留原终态。

策略依据 Docker 官方 [运行参数](https://docs.docker.com/engine/containers/run/)、[资源约束](https://docs.docker.com/engine/containers/resource_constraints/)和 [无网络模式](https://docs.docker.com/engine/network/drivers/none/)。本页支持声明以真实 fixture 为准。

## 实际验证范围

环境：Linux、宿主 Python 3.12.3／3.11.13、Docker 29.6.2；Worker Python 3.12.15、SDK 0.3.0、Pyomo 6.10.1、highspy 1.15.1。基础镜像固定为 python:3.12-slim 的 sha256:05cda9777409a9c3ffddd94a4c476b79f0769a0b4857f0c7ed9226b6800b0d6f。

公共 CLI 已实际得到 A=3、B=2、目标 13。代码替换测试先在旧镜像上失败，增加实际 CodeArtifact 核对后通过。真实输出超限测试先缺失 Worker 状态／stdout 证据，补齐应用记录后通过；SolveResult 为 null。真实 Executor 测试覆盖非 root、只读挂载／根目录、宿主环境与 socket 隔离、网络、越界读写、无限循环、OOM、进程限制、stdout／stderr 上限、容器删除及下一任务成功。

Docker daemon／控制命令卡住使用外部 CLI fixture，覆盖 create、attach、kill、inspect 和 remove，以及后代保留管道、已关闭管道和不完整退出证据。它们验证有限时间返回和失败证据，不替代真实 Docker 资源测试。执行测试均通过公共 CLI／Executor；真实硬件测试不跳过。完整检查、包安装与独立审阅结果见 [校验记录](../spec-validation.md)。

当前没有接入真实 LLM、参数化工厂／原生代码、取消／resume 或 benchmark 调度。Linux 已运行上述真实 fixture；macOS 客户端尚未验收，Windows 不标为已验收。完整 1.0 的完成条件仍由需求规格和验收清单维护。
