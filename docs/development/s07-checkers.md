# S07-D 原问题独立检查

SDK／Worker 0.12.0 开发实现；工作项 [#26](https://github.com/Fangziyang0910/LLM4OM/issues/26)。规则由 [评测协议](../evaluation.md)维护，接口由 [插件契约](../plugin-contracts.md)维护。此切片实现原问题解检查和有限实例探测，完整1.0仍包含 CoE、批量实验、Web 和发布验收。

原问题检查器接收公开问题、原始公开数据和显式映射的业务决策。它独立检查变量域／业务约束并重算目标，不使用候选约束或自报目标决定原问题是否正确。候选模型的 reported objective、原问题目标、参考质量和 verified solution 分别保存。

## 当前支持

- `ProductionChecker`：原始 products／capacities CSV 中的两个产品、非负整数数量、全部声明资源容量和原始利润。
- `UnitCapChecker`：明确声明的非负整数 Q∈[0,1]、恒零目标微型问题。Q=0 和 Q=1 均接受，不按单个参考向量评分。
- `CheckerFixtureAdapter`：冻结原始公开问题／数据、私有 policy、版本、hash 和两种事前 eligibility；SDK 与 CLI 共用 import／evaluate。
- `IndependentCheckerEvaluator`：真实 persisted outcome 的绑定验证、原问题检查、原目标质量及失败分母。
- 安装于 `llm4om.checkers` 的受信任检查器；固定入口、声明版本、来源文件 hash、SDK checker hash 和包版本。此插件运行在受信任评测进程中，不能用于执行数据集附带的任意源码。

有限探测目前支持与确定性 Code 来源关联的 grounded LPIR，且业务映射覆盖全部候选变量。辅助变量不猜值，原生／opaque Code 没有相应视图时为 not_available。点集和数据替换在建模前冻结；总点数≤5000、替换组≤50。数据替换遵循原文件 schema，候选保持固定。报告不声称已验证数据重绑定、完整表述等价或 semantic_verified。

参考目标区分 proven_optimum、best_known 和 feasible。已证明最优按 abs＋relative tolerance 匹配；其他两者按方向比较质量阈值，独立可行的改进可以通过。没有参考目标时只报告独立可行性。单位转换仅应用事先声明的正比例／偏移。

## 本机运行

从仓库根目录运行。示例使用人工 Mock 表述和真实 HiGHS，不能称真实 LLM 方法质量实验。

```bash
uv sync --locked --extra dev --extra solve --extra gurobi
uv run --locked llm4om import --config examples/specs/import-checker.json --output /tmp/llm4om-production-task
uv run --locked llm4om run --problem examples/specs/problem.json --config examples/specs/solve.yaml --output /tmp/llm4om-production-runs
```

记录 run 命令返回的 `bundle_path`，再执行以下命令；RUN_DIRECTORY 替换为该实际路径。

```bash
uv run --locked llm4om evaluate --manifest /tmp/llm4om-production-task/manifest.json --case-id fixture-production-milp-001 --run RUN_DIRECTORY --output /tmp/llm4om-production-score.json
```

snapshot 和 score 不覆盖已有文件。私有目录为0700、policy 为0600。Method、Provider 和 Worker 只消费明确公开的问题／数据；评测不参与候选选择或方法反馈。score 公开检查结果、来源和反例索引，排除私有 policy、probe 坐标及替换内容。

此 Mock 响应按源 ProblemSpec 的精确字节绑定，所以示例 run 使用原始公开问题。Evaluator 核对冻结问题身份与原始公开数据，允许路径变化而不允许字节／schema 变化。真实 Provider 的任务运行可以直接使用导入后的 public 问题；本机 HTTP／真实 Solver 测试已覆盖该路径。

## 验收证据

本机公共 Task／Evaluation／CLI／SDK／SolutionChecker 和实际 HiGHS／Gurobi 测试覆盖：正确模型、整数域遗漏、资源约束遗漏、交换利润导致自报13但原目标12、未声明缩放、恒零目标偶合、多最优解、无 primal、缺 oracle／checker／mapping／reference、插件异常及非法输出。检查器异常不导出其私有异常文本。

测试使用预定 HTTP fixture 验证 Provider 工程通路；本切片没有新增付费模型调用，也不将 fixture 结果当作模型准确率。本机 Python3.12.11 完整回归290项／666.828秒通过；干净 Python3.11 wheel 的15项聚焦任务／评测测试通过。mypy31个模块、仓库169文件、参考资料／diff 和 wheel／sdist 检查通过。独立 Standards／Spec 审阅受本机 Codex CLI 配额限制，当前未完成；自查不能替代独立审阅。GitHub CI 未触发，包和 Worker 未公开发布。

实际 CLI HiGHS run `2766a72c24914649a2eb62d44c2f8c77` 与容器 Gurobi run `e3982c820de143228bd56b0e194e0024` 均通过原问题可行性、目标13和有限点检查。第一次将 byte-bound Mock 用于路径规范化后任务的 run `8e8345df305744589f0ccc578dd01af7` 被正确拒绝；失败评测保留分母1／率0，独立重复成功不改写它。

最终源码／wheel／Worker 代码 hash 为 `ed102dd514d443867bd4d1f53e4dfaccca2b9c5dd63b65e933d70372239cbd63`。Worker0.12.0 镜像为 `sha256:00bae627774a1e8850c9c67368a2cf98d622af3c32ec21eb34150702eda073ea`；0.11.0 标签仍保留。169个源文件、197个公开运行／评分文件与52个 wheel 条目通过实际密钥扫描；运行与包均不含 oracle 文件。完整本机材料保存在 `/tmp/llm4om-s07d/verification.json` 及其相邻日志，不纳入版本控制。
