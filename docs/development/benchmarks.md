# Benchmark 与评测数据

平台题库用于浏览和试用。评测快照用于批量实验。两者使用不同入口，分别保留来源和资格信息。

## 内置题面

当前目录与数量见 [README](../../README.md#内置-benchmark)。题面直接复用 [OPT-Agent 固定提交](https://github.com/Fangziyang0910/OPT-Agent/tree/ad1c15bed95af0efc7de7d28c38baf2ad2f12351/benchmark)的 `get_id()/get_input()` 输出，保留原 ID、顺序和描述。

题面包位于 `src/llm4om/benchmark_sources/`，随安装包分发。`catalog.json` 保存源提交、路径、SHA-256、题面包哈希与数量。启动和浏览不访问外部数据目录，也不联网下载。

这是 OPT-Agent 整理版本。`NL4LP` 保留来源名称，与 SDK 的 `NLP4LP` 原始快照区分。题面不包含答案、参考解或求解器代码。部分 NL4COP 题目超出当前 LP/MILP 范围，可浏览不等于已支持其求解。

维护者在更新源数据后执行：

```bash
uv run --locked python scripts/prepare_benchmarks.py --source-root /path/to/OPT-Agent
```

工具检查源文件与管理器相对 HEAD 无修改、ID 唯一和题面非空，再生成公开投影。NL4Opt/MAMO 的许可原文保留；其他数据在该源快照中未逐项标明许可，平台不推定授权。

HTTP 的 `GET /api/datasets` 只列内置题库。单组接口默认每页 100 条，最多 200 条。复制和带入建模使用同一公开输入；带入只填表，不提交任务。接口字段见 [Web 契约](../contracts/web.md)。

## 冻结评测快照

CLI Task/Evaluation 接口支持 NL4Opt、NLP4LP、MAMO 和检查器 fixture。导入固定本地来源，不自动下载。

| 来源 | 公开输入 | 私有参考与资格 |
|---|---|---|
| NL4Opt | 原始 `document` | 原始标注不是数值最优解，不能直接用于目标匹配 |
| NLP4LP | 描述和具体 JSON 参数 | 固定发布保留 361 条；参考可用性为 322 可用但未验证、37 缺失、2 无效 |
| MAMO | EasyLP/ComplexLP 的原始问题 | 公开数学评阅确定 LP/MILP 与舍入规则；ODE 不进入优化评测 |
| Checker fixture | 公开问题和业务数据 | 明确的决策映射、独立检查器、参考质量和有限探测策略 |

官方来源身份、哈希和许可由相应适配器与来源清单校验。固定来源见[源码与数据考察](../references/source-inspection.md)。导入配置字段见[任务契约](../contracts/tasks.md)。

```bash
llm4om doctor --task-config /path/to/import-config.json
llm4om import --config /path/to/import-config.json --output runs/task-snapshot
llm4om run --problem runs/task-snapshot/public/CASE.json --config /path/to/run.yaml
llm4om evaluate --manifest runs/task-snapshot/manifest.json --case-id CASE_ID --run runs/RUN_ID --output evaluation.json
```

NL4Opt 配置模板见 [nl4opt-import.yaml](../../examples/tasks/nl4opt-import.yaml)。其他适配器配置按任务契约准备；路径相对于各自配置文件。

导入先验证整份来源，再发布只写一次的快照。`manifest.json` 和 `private/` 属于评测侧；方法只获得 `public/` 问题及公开数据。导出只包含许可允许的公开投影和公开运行记录。

## 批量实验

```bash
llm4om import --config examples/specs/import-checker.json --output runs/production-task
llm4om benchmark --config examples/specs/experiment.yaml --output runs/production-batch
llm4om benchmark --config examples/specs/experiment.yaml --output runs/production-batch --resume
llm4om report --experiment runs/production-batch
```

示例批次使用外部 LLM；运行前需配置实际服务和本机密钥。ExperimentSpec 按任务、配置和重复次数展开矩阵，所有未排除组合在首次生成前预检。不支持的组合要明确排除并给出原因。

样本按独立进程运行，共享实验并发与总预算。已开始样本预留完整单运行上限，当前不回收未用额度。恢复复用完成工作，不把它记为新的独立重复。

报告保存逐样本 JSONL/CSV、分组汇总及 Markdown/HTML。失败、取消、未解决澄清和未知费用保留。目标匹配、独立可行性和已验证解分别统计；规则见[评测协议](../evaluation.md)。
