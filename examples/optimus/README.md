# OptiMUS 公开参数示例

此例展示可选公开参数输入。当前 OptiMUS 也可直接从自然语言提取参数，无需提供 params/labels。编排和适配差异见[方法说明](../../docs/development/methods.md)。

problem.json、params.json 和 labels.json 是手写公开输入。问题为整数 `0 <= x <= 4`，最大化 `3x`，手算最优 x=4、目标 12。最优解不发送给方法。

先按[贡献指南](../../CONTRIBUTING.md)安装依赖并构建 Worker。复制 run.yaml 到本地忽略文件，设置实际端点和 API ID，通过 .env 或进程环境提供密钥。

```bash
uv run --locked llm4om doctor --config /absolute/path/to/local-config.yaml
uv run --locked llm4om run --problem examples/optimus/problem.json --config /absolute/path/to/local-config.yaml
```

复制配置后检查相对路径，必要时改用绝对路径。此例选择 gurobipy/Gurobi 容器工厂；其他兼容路径可按[求解指南](../../docs/development/solvers.md)配置。

运行会进行多次模型请求。阶段回复、生成代码、公开检查和选择保存在运行记录中。当前流程不启动固定上游 main，也不生成旧忠实度对照报告。
