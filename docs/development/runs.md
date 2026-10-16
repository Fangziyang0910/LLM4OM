# CLI 与 SDK 运行指南

本文说明单问题运行、恢复和人工修改。安装与 Web 使用见 [README](../../README.md)，字段见[核心契约](../contracts/core.md)。所有命令从仓库根目录执行。

## 运行一个问题

```bash
uv run --locked llm4om plugins list
uv run --locked llm4om doctor --config examples/specs/run.yaml
uv run --locked llm4om run --problem examples/specs/problem.json --config examples/specs/run.yaml
uv run --locked llm4om run --offline --problem examples/specs/problem.json --config examples/specs/run.yaml
```

`run.yaml` 使用人工 Mock 产物，正常运行在容器内真实求解。`--offline` 保存阶段产物，不编译或求解。`solve.yaml` 显式使用 `trusted_local`，只执行平台的严格 IR 求解路径。

问题数据路径相对于问题文件。配置中的本地路径相对于配置文件。`--output PATH` 可以覆盖存储根目录。CLI 返回 `run_id`、`bundle_path` 和 `status`；SDK 的 `run_problem` 返回相同信息。

退出码 `0` 表示该命令的正常结果，仍需读取状态。`artifact_ready` 表示离线产物已保存；`needs_input` 表示等待回答。失败运行通常返回 `1` 并保存记录。参数错误或存储不可用返回 `2`。

## 使用真实 LLM

复制一个[示例配置](../../examples/README.md)，设置实际供应商地址和模型 API ID。密钥通过配置中的 `credential_env` 从本机 `.env` 或进程环境读取。

```bash
uv run --locked llm4om doctor --config /path/to/local-run.yaml
uv run --locked llm4om run --problem examples/specs/problem.json --config /path/to/local-run.yaml --output runs
```

`doctor` 默认不请求模型服务。`run` 会调用所选模型并消耗相应额度。供应商协议、角色模型和目录查询见 [LLM 配置](llm.md)。

## 读取运行记录

以 `bundle.json` 为入口读取公开引用。引用保存相对路径、大小、SHA-256 和命名空间。常见记录包括公开问题、公开配置、事件、资源账本、阶段产物、公开检查、最终选择和求解结果。

`completed` 表示运行流程完成。`SolveResult.termination` 单独记录最优、不可行、无界、时间限制等状态。没有可行解时，目标和解引用为 `null`。无参考评测材料的用户问题仍可完成建模和求解。

## 取消与恢复

```bash
llm4om cancel --run-id RUN_ID --output runs
llm4om resume --run-id RUN_ID --output runs
llm4om resume --run-id RUN_ID --output runs --strategy rerun
```

Ctrl-C 使用同一协作取消机制。SDK 对应 `CancellationToken`、`cancel_run` 和 `resume_run`。

默认 `continue` 使用原运行、预算和绝对截止时间。平台复用已保存且身份一致的响应与求解记录。未知外部结果保留预算预留，不自动重发。未完成的方法需要声明内部检查点能力；缺少检查点时返回 `checkpoint_unsupported`。

显式 `rerun` 创建派生运行，重新执行方法，可能产生新请求。父运行的已知消耗和未知预留继续计入总上限。原问题、配置、插件、SDK 或 Worker 身份变化会阻止严格恢复；旧记录仍可读取。

## 回答澄清

```bash
llm4om run --interactive --problem problem.json --config run.yaml --output runs
llm4om resume --run-id RUN_ID --output runs --answers answers.json
llm4om resume --run-id RUN_ID --output runs --answers revision-answers.json --revised-problem problem-v2.json
```

确认已有规则时，回答引用保存的请求，并将对应值设为 `true`。新增规则或数据使用 `action=revise`，提供同一 `problem_id` 的新 `revision`。新事实创建派生运行，原输入保持不变。非交互批次将未回答的澄清记为 `unresolved`，保留评测分母。

请求和回答字段见[方法契约](../contracts/methods.md)。

## 人工修改与报告

```bash
llm4om edit --help
llm4om report --run runs/RUN_ID
llm4om report --experiment runs/EXPERIMENT_ID
```

通过 CLI 的 `edit` 子命令导出编辑模板，再提交修改。SDK 使用 `export_edit(run, operation)` 和 `edit_run(run, edits)`。修改问题、表述或代码会创建标为人工辅助的派生运行，保存原因、父记录和累计预算。报告重建只读取已保存结果，不再次调用 LLM 或求解器。

批量实验见 [Benchmark 与评测数据](benchmarks.md)。
