# 内置 Benchmark 浏览与试用

2026-10-14，SDK／Worker 0.37.0 开发版本。Web 面向普通使用者：平台维护样例，使用者选择 Benchmark、查看每条题面，再复制或带入单问题建模。无需上传数据集、配置样本或组织实验。

## 数据来源与范围

直接复用 [OPT-Agent](https://github.com/Fangziyang0910/OPT-Agent/tree/ad1c15bed95af0efc7de7d28c38baf2ad2f12351/benchmark) 已整理的数据与 `experiments/manager/` 的 `get_id()`／`get_input()`。固定来源提交为 `ad1c15bed95af0efc7de7d28c38baf2ad2f12351`；保留原顺序、原 ID 和管理器输出的题面，不重新下载或再造适配器。

| 内置 Benchmark | 问题数 |
|---|---|
| NL4Opt | 205 |
| NL4LP | 178 |
| MAMO Easy | 642 |
| MAMO Complex | 210 |
| IndustryOR | 99 |
| ComplexOR | 18 |
| OptiBench | 403 |
| OptMATH | 128 |
| NL4COP | 150 |
| 合计 | 2033 |

这是用户整理版本的公开题面库，不与上游原始 split／样本数量混合。NL4LP 按来源项目名称保留，不冒充 SDK 的 NLP4LP 原始快照。所有源数据的业务信息已包含在管理器输出中，无需另接参数文件。原文件的答案、参考解和 solver_code 不进入题面包、浏览接口、复制文本或建模输入。

题面位于 `src/llm4om/benchmark_sources/`，随 wheel／sdist 分发。目录记录来源提交、原文件路径及 SHA-256、题面包哈希与数量。NL4Opt／MAMO 的原许可文本保留；其余数据在 OPT-Agent 快照中未逐项标注许可，不为它们推定许可。

平台维护者需要刷新题面时执行：

```bash
uv run --locked python scripts/prepare_benchmarks.py --source-root /path/to/OPT-Agent
```

脚本复用现有管理器，检查源文件与管理器相对 HEAD 无修改、题面非空及 ID 唯一，输出可重复生成的公开投影。此命令是维护入口，不是普通使用者的前置步骤。启动或浏览 Web 不访问 OPT-Agent 路径，不联网下载。

## 行为与接口

`GET /api/datasets` 只返回内置目录；工作区导入任务和内部测试 fixture 不混入页面。`GET /api/datasets/<task_id>?offset&limit` 校验题面包大小、SHA-256 和数量，分页返回公开问题与建模草稿，不读取私有评测资料。默认每页 100 条，HTTP 单次最多 200 条。

“复制问题”将完整公开题面写入剪贴板。“带入建模”填好描述与公开输入，保留当前方法、求解器和预算配置；使用者点击“开始建模”后才提交任务。公共问题与业务数据仍由共同输入契约校验，不引入额外插件或依赖。CLI Task／Evaluation 与批量评测接口独立保留。

## 验收

- 全部 2033 条输入逐条与 OPT-Agent 管理器核对，原 ID／顺序／题面一致；重新生成后文件哈希不变。
- 公共 HTTP 测试覆盖全部条目分页、隐藏工作区 fixture、未知目录拒绝、跨源拒绝及无参考答案输入；Web 相关 9 项 Python 测试通过，包含实际 HiGHS 求解与父记录保留。
- 本机 Chrome 检查九组数据浏览、分页、剪贴板写入参数、带入建模、业务数据携带、配置保留、提交输入隔离及窄屏。业务参数用独立 fixture 验证，不冒充真实数据；剪贴板检查调用浏览器原生写入，不依赖 headless 系统剪贴板回读。
- 前端类型／构建、Python 类型、仓库检查及 wheel／sdist 内容检查通过。本机服务更新后核对 5 个历史工作项、1262 个文件内容保持不变。

本轮验收为题面浏览与建模输入流程，不是全量建模准确率评测。部分 NL4COP 问题可能需要超出当前 LP/MILP 的求解能力；可浏览和试用不扩大已有求解器支持声明。
