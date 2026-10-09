# 独立安装的工程方法示例

这是 S03 的可运行接入示例，由本项目编写，不是论文方法。接口来源为 [当前方法契约](../../../docs/development/s03-plugins.md)。插件从 Mock 文本响应取得人工五元素／IR，将目标常数加上配置的 objective_offset，再交给核心验证、编译与求解；它用于证明不同方法可以独立安装和运行，不能作为原问题的语义正确结果。

在仓库根目录执行，先安装 SDK 0.2.0：

```bash
uv sync --locked --extra dev --extra solve
uv build --wheel examples/plugins/fixture_method --out-dir /tmp/llm4om-fixture-wheel
uv pip install --python .venv/bin/python --no-deps /tmp/llm4om-fixture-wheel/llm4om_fixture_method-0.1.0-py3-none-any.whl
.venv/bin/llm4om plugins list
.venv/bin/llm4om doctor --config examples/specs/plugin-run.yaml
.venv/bin/llm4om run --problem examples/specs/problem.json --config examples/specs/plugin-run.yaml
```

预期目标值为 20，A=3／B=2，semantic_validation 仍为 not_available。清单和环境记录分发包 llm4om-fixture-method 0.1.0、Manifest、entry point 与方法变体。卸载示例使用 `uv pip uninstall --python .venv/bin/python llm4om-fixture-method`，不修改核心或源 fixture。

entry point 导出具有 describe／create 的对象；配置在 create 前按 Manifest 校验。run 为 async，接收公开问题和 MethodContext，返回 MethodOutcome；实例只持有自己的方法配置。当前 profile 是单候选严格 LPIR，完整 Prompt／修正、native_code、checkpoint 和其他资源插件按后续切片接入。

SDK 0.7.0 增加 Context cancellation／save_checkpoint。fixture 声明 cooperative/0.1.0，仍不支持内部 checkpoint；完整阶段可由核心恢复，未完成内部方法则明确拒绝。该版本依赖 SDK >=0.7.0,<0.9.0。
