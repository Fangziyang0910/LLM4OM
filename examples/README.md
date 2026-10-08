# 示例规格与手算参考

这些文件是人工编写的契约 fixture。S01 CLI／SDK 已能显式回放公开建模产物并保存记录；它们不代表真实 LLM 输出或 Solver 实验结果。

## 1. 文件角色

| 文件 | 用途 | 是否允许作为方法输入 |
|---|---|---|
| [problem.json](specs/problem.json) | 公开描述、需求条目与数据引用 | 是 |
| [products.csv](specs/data/products.csv)／[capacities.csv](specs/data/capacities.csv) | 公开业务数据 | 是 |
| [formulation.json](specs/formulation.json) | 五元素 Formulation，引用人工 LPIR | Mock 流程显式使用；非真实方法输出 |
| [model-artifact.json](specs/model-artifact.json) | 共同封装：表述可用、Code 尚待生成 | 工程 Mock 响应；后续编译才生成 CodeArtifact |
| [model-ir.json](specs/model-ir.json) | 人工构造的目标模型，仅用于工程 fixture | 真实基准建模时否；Mock 流程可显式使用 |
| [oracle.json](specs/oracle.json) | 自建参考目标与独立规则说明 | 否；Evaluator 读取 |
| [plugin-manifest.json](specs/plugin-manifest.json) | direct 插件 Manifest 草案 | 配置／发现元信息 |
| [experiment.yaml](specs/experiment.yaml) | 离线示例配置草案 | 公开部分可以；oracle 由 TaskAdapter 私有处理 |
| [run.yaml](specs/run.yaml) | S01 无 oracle 单问题配置 | 全部为公开配置；仍是工程 Mock |
| [expected-evaluation.json](specs/expected-evaluation.json) | 预期结果断言 | 否；不能冒充真实 run 输出 |

例子将 oracle 放在同一源码目录是为了文档可读；运行时只能挂载明确的公开数据文件，不能把整份 examples／源码目录挂进生成代码容器。

`run.yaml` 与 `experiment.yaml` 分别演示单问题和 benchmark 两种用法。前者使用单数 method，没有 task/oracle_path、experiment_id 和 repeats；后者由任务适配器导入公开问题与私有参考材料。两者配置草案为 0.2.0，显式选择 five_element。Mock 响应指向 model-artifact.json；Formulation 内的 structured_ir_ref 指向独立手写的 LPIR 0.1.0，不是已从文本编译出的结果。Code 引用当前为空，阶段为 pending；后续真实编译产生源表述可追踪的 CodeArtifact。S01 已使用单问题应用入口；benchmark 将在 S08 复用它。当前可运行：

```bash
uv run --locked llm4om run --offline --problem examples/specs/problem.json --config examples/specs/run.yaml
```

先按 [开发命令](../CONTRIBUTING.md#3-开发与校验)安装依赖。run 不读取 oracle.json／expected-evaluation.json，不执行代码或求解；编译器、后端、求解器和容器配置只记录为后续目标。Code 为 pending，Solve 和独立语义检查为 not_available。实际 RunBundle 在 runs 下，详情见 [S01](../docs/development/s01-offline-run.md)。benchmark 命令与独立检查待后续实现。

## 2. 数学问题

生产 A、B 两种产品，数量为非负整数。单位利润分别为 3、2；资源 cutting 单位消耗为 2、1，总量 8；资源 finishing 单位消耗为 1、2，总量 8。

```text
max 3A + 2B
s.t. 2A + B <= 8
     A + 2B <= 8
     A, B >= 0 and integer
```

枚举可行整数点得到最优 `(A,B)=(3,2)`，目标 13。LP 松弛的两个资源约束交于 `(8/3,8/3)`，目标为 `40/3`；要求整数的任务不能接受该连续解。

独立评估必须使用原问题的整数域、两条资源规则及原利润计算，而不是只检查候选自己的约束。只得到目标值 13 时仍不能证明模型在其他实例中等价。

文件中的数据 sha256 按原始 UTF-8 CSV 字节计算；更改数据必须同步文件引用、数据绑定和 reference revision。

当前可运行 `python3 scripts/check_repository.py` 校验这些设计文件，包括五元素字段与阶段引用的 hash／大小／revision。它从 CSV 独立枚举整数点并核对 IR 绑定、参考断言和 LP 松弛证据；它不调用 LLM、编译器或 Solver。维护工具的命令与测试入口见 [贡献流程](../CONTRIBUTING.md)。

## 3. 数据绑定错误的设计反例

若把产品利润绑定为 A=2、B=3，候选模型会选择 A=2、B=3，并报告目标 13。该解满足原资源约束，但按原问题利润计算为 12。候选自报目标与参考数值同为 13，独立原目标计算仍能发现错误。这是拟加入验收的绑定反例，不能当作已经运行的结果。
