# S08 批量实验与报告

状态：已编写可运行功能代码，正在补齐本机聚焦验收。范围对应 FR-31～FR-34、DD-06／07 和 [Issue51](https://github.com/Fangziyang0910/LLM4OM/issues/51)。接口以 [插件契约](../plugin-contracts.md#8-experimentspec-与单问题-runconfig)为准，指标以 [评测协议](../evaluation.md)为准。首版不代表完整 S08／1.0 验收完成。

## 使用

从仓库根目录执行；实际模型配置使用已授权的外部 LLM，凭据仅在本地 `.env`。先构建当前 Worker 镜像。

```bash
uv run --locked python scripts/build_worker_image.py
uv run --locked llm4om import --config examples/specs/import-checker.json --output runs/production-task
uv run --locked llm4om benchmark --config examples/specs/experiment.yaml --output runs/production-batch
uv run --locked llm4om benchmark --config examples/specs/experiment.yaml --output runs/production-batch --resume
uv run --locked llm4om report --experiment runs/production-batch
```

SDK 使用 `run_experiment(config, output, offline=False, resume=False, cancellation=None)` 和 `report_experiment(output)`。相对路径基于配置所在目录；每个完整 RunConfig 可以选择不同方法、LLM、后端和求解器。冻结导入时确定资格，不使用模型结果改变分母。

## 行为

- 任务 × 配置 × repeat 展开矩阵。全部未排除组合在首次模型请求前预检；不支持组合报错并要求显式 exclusion。
- 每个样本调用已有单问题 CLI／应用和 Task/Evaluator。并发样本拥有独立进程、插件资源与运行目录，失败隔离。
- 有限并发、持久化总截止时间和实验硬计数预留。已开始样本保留完整 run 上限，恢复不重置已消耗或未知预算。当前预留不会回收未用额度；设置总预算时需按单 run 上限 × 计划样本数计算。
- Ctrl-C 停止新调度，并取消拥有的资源子进程。未运行、失败、超时和取消样本保留资格与分母。`--resume` 保留完成工作和运行 ID；仅继续未完成工作，不作为新的独立 repeat。
- 保存公开配置、源清单 hash、case ID、公共问题 hash、插件与执行身份。私有状态保存输入路径；oracle 原始内容和引用不会进入报告或方法 Context。
- `reports/results.jsonl` 保存逐样本完整公共证据；CSV 保存可分析列；`summary.json` 保存各阶段状态、失败、分母、未知资源数量和排除矩阵；Markdown/HTML 提供相同分组的结果入口。
- 数据来源／协议／配置／repeat 分开统计。独立可行性、数值匹配、verified solution 分开；结构和执行检查不能替代语义证据。Mock 明示为工程证据，不输出真实方法排名。费用／tokens 未知保持 null，不填写零。

## 验证与剩余范围

本机聚焦验收覆盖实际并发 HiGHS、原问题检查、已完成工作恢复、总预算、显式排除、输入漂移拒绝与取消分母。执行结果在交付时补充。没有触发 GitHub Actions，也没有重复完整回归。

仍需完成三种方法的真实公共样本比较、1000／100任务性能与故障验收、Web 批量展示和独立 Standards／Spec 审阅。Linux 为当前执行环境；平台锁与过程监督不声称已验证 Windows／macOS。
