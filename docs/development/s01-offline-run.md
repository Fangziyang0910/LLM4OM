# S01 离线单问题流程

状态：已实现；包版本 0.1.0；设计基线 0.4.0；日期 2026-10-09。范围来自 [S01](../implementation-plan.md#s01-统一问题契约与离线纵向流程)，字段来源为 [契约](../plugin-contracts.md)。完整 1.0 验收仍由 [AC 清单](../acceptance.md)管理。

## 运行

在仓库根目录执行：

```bash
uv sync --locked --extra dev
uv run --locked llm4om run --offline --problem examples/specs/problem.json --config examples/specs/run.yaml
```

没有 uv 时，Python 3.11／3.12 环境也可用 `python -m pip install -e '.[dev]'` 安装；依赖的完整锁定使用 uv.lock。CLI 从任意工作目录接受问题／配置路径；数据路径相对于问题文件，Mock 引用和 store.root 相对于配置文件。`--output` 显式覆盖 store.root。

CLI 返回 JSON `{run_id, bundle_path, status}`。退出码 0 表示 `artifact_ready`，1 表示已保存失败 RunBundle；参数错误或无法写入存储返回 2。存储失效时 stderr 给出 `store_unavailable`，无法保证在失效磁盘上保存 bundle。SDK 会将存储 OSError 交给调用者。

SDK 与 CLI 调用相同应用入口：

```python
from pathlib import Path
from llm4om import run_problem

result = run_problem(
    Path("examples/specs/problem.json"),
    Path("examples/specs/run.yaml"),
    offline=True,
    output_root=Path("runs"),
)
print(result.run_id, result.bundle_path, result.status)
```

## 实际能力

| 位置 | 当前行为 | 后续工作 |
|---|---|---|
| 输入 | ProblemSpec 0.2.0；自然语言 description；requirements 可空、类型可 unknown；CSV hash 可留空后计算 | 用户文本交互、任务适配 |
| 数据 | UTF-8 CSV；声明表头、string／number／integer、nullable、unique_by；保持原始字节 | 其他数据格式 |
| 方法／Provider | direct 的 `hand_authored_fixture_replay` 变体；Mock 一次读取明确输入绑定的人工输出 | 真实 direct、外部 LLM、论文方法 |
| Formulation | five_element，检查身份、revision、字段、引用、数据绑定；保存来源 | 语义检查与真实生成 |
| 严格 IR | 验证引用身份、hash、版本与数据绑定，保留人工来源 | S02-A 完整 IR 语义校验、编译 |
| Code／Solve | 不执行；记录 pending／not_available；配置中的 Compiler／Backend／Solver／Executor 只是请求目标 | S02-A 编译与 HiGHS，S04 隔离 |
| 记录 | 独立 run_id、原子文件替换、递增 JSONL 事件、候选、Mock 计数、公开配置、环境、报告 | 取消、崩溃恢复、外部调用结算 |

当前 profile 仅接受示例中的 direct＋Mock＋five_element／lp_ir 配置，以及 Pyomo／HiGHS／container 请求目标；其他组合在 Mock 前拒绝。插件发现和通用 capability admission 在 S03 实现。S01 没有建立空 Registry 或 Provider／Solver Adapter。

Mock 响应必须属于相同原始 ProblemSpec 字节、revision 和数据 hash。修改问题或数据后，要明确编写新的人工 fixture；回放不会推断新问题的模型。五元素文本不会被当作 Python 执行，也没有从五元素自动生成严格 IR。

RunBundle 以 `bundle.json` 为入口。引用均相对于该运行目录，包含 hash、大小、namespace 和 schema_version；manifest 自身不引用自身。每个运行只复制明确的公开数据和产物引用，不复制源码／示例目录。公开配置去除本地存储位置，Mock 响应路径投影到公开产物；原始凭据和 oracle 字段被拒绝。

Mock attempt 记为 1，外部 LLM 请求和 Solver 调用均为 0；缺失 token usage 为 null。预算在 S01 校验并计数；墙钟中断、并发预留、未知外部结果结算分别在 S03–S05 实现。

## 交付证据

- tests/test_cli_run.py 从 CLI 观察成功、失败和公开产物；逐个行为先 red 再 green。
- 正常流程、输入保持、无 oracle／requirements 拆分、独立运行、公开引用 hash 与报告一致性通过。
- 负例覆盖重复键、非有限数值、版本／配置／预算、CSV 类型／空值／重复键、路径与 symlink 越界、输入／产物绑定、缺失五元素、伪报 Code、凭据、递归 YAML 与存储不可写。
- 完整仓库校验、类型检查、Python 环境与包安装结果见 [校验记录](../spec-validation.md)。

Standards 对照开发规范与接口契约，Spec 对照开工前已确认的 S01。审阅基线为 `da3609131ede07d85d922d9a8d1dd224bcf934c3`。GitHub Issues 读取当前返回 HTTP 401；没有伪造 issue 编号，也没有关闭远程工作项。

下一步优先 S02-A：将伴随的严格 LPIR 编译为 CodeArtifact，经真实 HiGHS 求解，分别验证 MILP=13 与 LP=40/3。S03-A 的第三方方法发现也已解除 S01 阻塞。
