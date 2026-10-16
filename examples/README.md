# 示例与手算参考

本目录提供人工工程 fixture、真实 LLM 配置模板和独立插件示例。人工模型用于验证流程，不属于真实方法的准确率成绩。运行结果在每次运行目录中产生。

## 文件与用途

| 文件 | 用途 |
|---|---|
| [problem.json](specs/problem.json) | 公开问题、需求和数据引用 |
| [products.csv](specs/data/products.csv)、[capacities.csv](specs/data/capacities.csv) | 原始公开业务数据 |
| [formulation.json](specs/formulation.json)、[model-ir.json](specs/model-ir.json) | 人工五元素与严格 LPIR |
| [model-artifact.json](specs/model-artifact.json) | Mock 响应，引用表述并等待编译 |
| [run.yaml](specs/run.yaml) | Mock + 容器 HiGHS；也可离线回放 |
| [solve.yaml](specs/solve.yaml) | Mock + 显式 trusted_local HiGHS |
| [gurobi.yaml](specs/gurobi.yaml) | Mock + 容器 Gurobi |
| [feedback-repair.yaml](specs/feedback-repair.yaml)、[messages.yaml](specs/messages.yaml) | 外部 LLM 配置模板 |
| [oracle.json](specs/oracle.json)、[expected-evaluation.json](specs/expected-evaluation.json) | 私有评测 policy 与手算断言，不是方法输入 |
| [import-checker.json](specs/import-checker.json) | 冻结公开问题和私有 policy |
| [experiment.yaml](specs/experiment.yaml)、[benchmark-run.yaml](specs/benchmark-run.yaml) | 使用外部 LLM 的批量实验模板 |

源码中相邻的公开/私有示例仅便于维护。运行时只传入明确公开文件，不能将整个 examples 目录挂载到生成代码容器。

## 运行示例

先按[贡献指南](../CONTRIBUTING.md#开发环境)安装依赖和构建 Worker，再执行：

```bash
uv run --locked llm4om run --problem examples/specs/problem.json --config examples/specs/run.yaml
uv run --locked llm4om run --offline --problem examples/specs/problem.json --config examples/specs/run.yaml
uv run --locked --extra solve llm4om run --problem examples/specs/problem.json --config examples/specs/solve.yaml
```

正常容器与本机路径均真实求解。离线只保存产物。Mock 绑定准确的问题字节和数据哈希；修改输入后需准备匹配的新 fixture。

外部 LLM 模板包含占位地址和模型配置。复制到本地后设置实际服务、API ID 和凭据；配置字符串不进行 shell 展开。真实运行会消耗模型额度。

[OptiMUS 示例](optimus/README.md)展示可选公开参数，[CoE 示例](coe/README.md)展示可选公开接口信息。当前两种方法都可以直接接受自然语言，无需这些附加文件。

批量实验命令与来源导入见[Benchmark 指南](../docs/development/benchmarks.md)。恢复和派生编辑见[运行指南](../docs/development/runs.md)。

## 数学问题

生产 A、B，数量为非负整数。利润分别为 3、2，两种资源上限均为 8。

```text
max 3A + 2B
s.t. 2A + B <= 8
     A + 2B <= 8
     A, B >= 0 and integer
```

枚举可行整数点得到 A=3、B=2，目标 13。LP 松弛为 A=B=8/3，目标 40/3。要求整数时不能接受该连续解。

若交换利润，模型可选 A=2、B=3 并自报 13；按原问题利润重算为 12。这个反例用于区分目标匹配和原问题正确性。

仓库检查从 CSV 独立枚举整数点，核对绑定、参考和松弛界。该检查不调用 LLM 或求解器。实际求解证据由运行测试另行产生。

## 插件示例

| 示例 | 验证的接口 |
|---|---|
| [fixture_method](plugins/fixture_method/README.md) | 独立方法与目标常数变体 |
| [fixture_provider](plugins/fixture_provider/README.md) | 独立文本协议 |
| [fixture_task](plugins/fixture_task/README.md) | 冻结任务与独立评估器 |
| [fixture_compiler](plugins/fixture_compiler/README.md) | 编译器选择和 Worker 身份 |
| [fixture_execution](plugins/fixture_execution/README.md) | 后端组件与真实求解器 |
| [fixture_data_loader](plugins/fixture_data_loader/README.md) | 有限数据视图 |
| [fixture_executor](plugins/fixture_executor/README.md) | 容器与拥有进程执行器 |
| [fixture_store](plugins/fixture_store/README.md) | 运行存储打开器 |
| [fixture_reporter](plugins/fixture_reporter/src/llm4om_fixture_reporter/__init__.py) | 公开报告渲染、结果副本隔离和失败处理 |

示例属于可信平台插件，公共接口见[插件契约](../docs/contracts/plugins.md)。插件安装本身不证明已执行或具有数学正确性。
