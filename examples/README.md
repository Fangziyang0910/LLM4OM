# 示例规格与手算参考

这些文件是契约设计 fixture，当前没有可执行的 LLM4OM SDK。它们用于后续实现的结构校验、编译和独立评测，不是已经运行得到的实验结果。

## 1. 文件角色

| 文件 | 用途 | 是否允许作为方法输入 |
|---|---|---|
| [problem.json](specs/problem.json) | 公开描述、需求条目与数据引用 | 是 |
| [products.csv](specs/data/products.csv)／[capacities.csv](specs/data/capacities.csv) | 公开业务数据 | 是 |
| [model-ir.json](specs/model-ir.json) | 人工构造的目标模型，仅用于工程 fixture | 真实基准建模时否；Mock 流程可显式使用 |
| [oracle.json](specs/oracle.json) | 自建参考目标与独立规则说明 | 否；Evaluator 读取 |
| [plugin-manifest.json](specs/plugin-manifest.json) | direct 插件 Manifest 草案 | 配置／发现元信息 |
| [experiment.yaml](specs/experiment.yaml) | 离线示例配置草案 | 公开部分可以；oracle 由 TaskAdapter 私有处理 |
| [expected-evaluation.json](specs/expected-evaluation.json) | 预期结果断言 | 否；不能冒充真实 run 输出 |

例子将 oracle 放在同一源码目录是为了文档可读；运行时只能挂载明确的公开数据文件，不能把整份 examples／源码目录挂进生成代码容器。

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
