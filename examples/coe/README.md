# CoE 公开生产问题

SDK／Worker0.13.0 开发示例；不是论文 benchmark 分数。流程与差异见 [实现记录](../../docs/development/s06-coe.md)；规范由 [插件契约](../../docs/plugin-contracts.md)维护。

公开问题和 CSV 来自项目原始生产 fixture。`public-interface.json` 只给函数 stub、参数和变量名称，不给最优解或参考模型。方法默认执行3次动态专家协作，再由 reducer 生成原生函数。此例关闭反思；启用时生成的公开测试与原任务求解分别执行，参数和预算分别记录。

```bash
uv sync --locked --extra dev --extra solve --extra gurobi
uv run --locked python scripts/build_worker_image.py
uv run --locked llm4om run --problem examples/coe/problem.json --config examples/coe/run.yaml
```

上面 run 配置的 endpoint 是占位符。使用本地忽略的配置替换 endpoint，通过 `.env`／环境提供凭据。密钥和运行数据不提交。原生输出只声明 gurobipy／Gurobi 容器路径；Formulation 为 not_available。流程实现使用原创提示词、固定 seed 和一次原生导入，明确记录与上游源码的差异。

没有额外公开接口文件时，`public_contract_data_id: null` 使用原创默认 stub `prob_problem()`，可以直接处理自然语言和可选公开数据。该默认接口不读取 benchmark 私有参考代码。
