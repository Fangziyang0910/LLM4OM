# CoE 公开接口示例

此例使用生产问题和公开 CSV。public-interface.json 只提供接口、参数和变量说明，不含答案或参考模型。该文件为可选输入；当前 CoE 可直接接受自然语言。

复制 run.yaml 到本地忽略文件，设置实际 LLM 地址、API ID 和 .env 密钥。先按[贡献指南](../../CONTRIBUTING.md)构建 Worker，再执行：

```bash
uv run --locked llm4om doctor --config /absolute/path/to/local-config.yaml
uv run --locked llm4om run --problem examples/coe/problem.json --config /absolute/path/to/local-config.yaml
```

此配置使用最多三次专家协作，关闭反思，再由 reducer 生成数学表述与 gurobipy 工厂。平台独立调用 Gurobi，保存阶段产物与检查结果。

启用反思后，公开执行诊断参与下一轮修订。当前流程不生成额外测试实例或执行 prob_* 函数。实现使用独立编写的提示，来源和差异见[方法说明](../../docs/development/methods.md)。
