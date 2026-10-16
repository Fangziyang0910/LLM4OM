# 固定评测数据来源

本页保留官方数据的固定身份、内容观察和许可。平台题库来自 OPT-Agent 的整理版本，与以下原始评测快照区分。接入步骤见[Benchmark 指南](../development/benchmarks.md)。

## 固定版本

| 数据 | 固定来源 | 读取范围 |
|---|---|---|
| NL4Opt | [49f1e0d](https://github.com/nl4opt/nl4opt-competition/tree/49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea) | generation_data 与原始标注 schema |
| NLP4LP | [f0f2abb](https://huggingface.co/datasets/udell-lab/NLP4LP/tree/f0f2abb5d4fa01812ab2c818dd350f6c34041d15) | 2127 个文件，全部参数/参考 JSON；参考代码仅计算哈希，未执行 |
| MAMO | [2c91069](https://github.com/FreedomIntelligence/Mamo/tree/2c91069dee5c1e4db4b899eb176ec987d0251bb3) | EasyLP、ComplexLP、ODE 三个原始文件 |

固定哈希用于核对来源字节。NLP4LP 完整清单另存于 [nlp4lp_source.json](../../src/llm4om/nlp4lp_source.json)。

| 固定文件 | SHA-256 |
|---|---|
| [NLP4LP train.jsonl](https://huggingface.co/datasets/udell-lab/NLP4LP/blob/f0f2abb5d4fa01812ab2c818dd350f6c34041d15/train.jsonl) | `84dbed2b8f27c10f94718c93bdc9608d606dffc56139021a859ee1e45bc0619f` |
| [NLP4LP README](https://huggingface.co/datasets/udell-lab/NLP4LP/blob/f0f2abb5d4fa01812ab2c818dd350f6c34041d15/README.md) | `ffcb833d8211bc2409246515fd7a0af81fa596b53ccdc510ae4cc4c2b7bb3938` |
| [MAMO EasyLP](https://github.com/FreedomIntelligence/Mamo/blob/2c91069dee5c1e4db4b899eb176ec987d0251bb3/data/optimization/Easy_LP/mamo_easy_lp.jsonl) | `b37ae7d9fc0b8c39e172d070aed84e600549407886ef970083c0f6cadc2e60a6` |
| [MAMO ComplexLP](https://github.com/FreedomIntelligence/Mamo/blob/2c91069dee5c1e4db4b899eb176ec987d0251bb3/data/optimization/Complex_LP/mamo_complex_lp.jsonl) | `07eb3db3d2af099871dfa4425b14887775179c158c38944fe4fe152b615bbfc3` |
| [MAMO ODE](https://github.com/FreedomIntelligence/Mamo/blob/2c91069dee5c1e4db4b899eb176ec987d0251bb3/data/ode/mamo_ode.jsonl) | `e877c8e12add7ec6b528e3cd64d83d48dac019f9d3f09327f803f802ef015dfa` |
| [MAMO LICENSE](https://github.com/FreedomIntelligence/Mamo/blob/2c91069dee5c1e4db4b899eb176ec987d0251bb3/LICENSE) | `187442db4df3afd21f2f0525739fd4beac28a62daaba3ee8d3533f60e7c33ec7` |
| [OptiMUS README](https://github.com/teshnizi/OptiMUS/blob/59e8d99653459b40361f618eafdc91eee3a85ebb/README.md) | `2b74b2975d1b516a47e498b72480d5e3e889a825dd68a25255c7d0dd64aafca3` |
| [OptiMUS LICENSE](https://github.com/teshnizi/OptiMUS/blob/59e8d99653459b40361f618eafdc91eee3a85ebb/LICENSE) | `17b0a6b26154e8c43a04fa87cb35888f25915ba4387cb17c5d8cdd95d92a97fa` |

## 许可

NL4Opt 固定树提供 MIT 许可。NLP4LP 数据卡声明 CC BY-NC 4.0 及研究用途限制，没有独立 LICENSE；OptiMUS 代码的 MIT 许可不覆盖该数据。MAMO 根许可为 CC BY-SA 4.0，保留归属及修改声明。

这些是固定来源中的许可观察。公开题库的再分发范围还需按其实际来源记录，不能推定缺失的授权。

## 数据结构与参考

NL4Opt 的 document 提供公开题面。结构标注缺少独立最优值、变量域和求解证明，不能直接构成数值参考。官方 split 哈希见[导入模板](../../examples/tasks/nl4opt-import.yaml)。

NLP4LP 的 train.jsonl 包含 361 条，并非完整 train/dev/test 三分。部分 parameters、problem_info 和 solution 是外层字符串内的 JSON。参数可以为标量、列表、字典和字符串，不能统一转成浮点数。

原数据中 37 条缺少 solution，ID 3 和 51 的 solution 无效，其余 322 条可解析但没有最优性证书。原描述和具体参数公开；参考代码、problem_info、参数化描述、keywords 和 solution 保留在评测侧。

MAMO 原始 EasyLP/ComplexLP/ODE 分别有 652/211/346 条。ID 在各子集中重启，需要连同子集使用。优化 Answer 可解析为有限数，但没有参考模型、向量、域或求解证书。ODE 即使答案为数值也不进入优化评测。

题面包含整数、连续与舍入要求，不能根据 EasyLP 名称或参考小数位推断变量域。公开数学评阅在运行前确定类型、舍入和资格。

原 MAMO 评分脚本通过 COPT 读取 LP 并比较目标，分母是已生成文件数。该口径不自动成为本项目协议。本项目冻结样本分母，并使用显式容差和舍入规则，见[评测协议](../evaluation.md)。
