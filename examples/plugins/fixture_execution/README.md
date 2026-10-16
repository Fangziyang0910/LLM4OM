# 独立 Backend／Solver 示例

本例演示共同注册接口和真实 Worker 执行。接口见[插件契约](../../../docs/contracts/plugins.md)。这是工程fixture，不是新的求解算法。

在仓库根目录构建和安装：

```bash
uv build --offline --wheel examples/plugins/fixture_execution --out-dir /tmp/llm4om-execution-wheel
uv pip install --no-deps /tmp/llm4om-execution-wheel/llm4om_fixture_execution-0.1.0-py3-none-any.whl
llm4om plugins list
```

在公开输入目录复制solve.yaml，再选择两个插件：

```yaml
model_backend:
  plugin_id: llm4om.examples.renaming_pyomo
  config:
    component: selected_decisions
solver:
  plugin_id: llm4om.examples.checking_highs
  config:
    component: selected_decisions
```

Backend实际重命名Pyomo变量组件，保持显式业务决策映射。Solver先检查所选组件存在，再调用原生HiGHS API，结果保存fixture_component。改变组件名后依然求得原MILP目标13；没有把插件列表当作执行证据。

容器运行需要安装同一wheel的可信镜像：

```bash
uv run --locked python scripts/build_worker_image.py --offline --tag llm4om-worker:with-execution --plugin-wheel /tmp/llm4om-execution-wheel/llm4om_fixture_execution-0.1.0-py3-none-any.whl
```

将executor.config.image设为该镜像。宿主只配置插件，实际模型构建与求解在Worker内进行。ModelHandle不跨进程传输；额外SDK依赖在Worker预检并冻结版本。插件是可信代码，不读取隐藏评分材料，不在构造期间调用付费服务。

该wheel还提供llm4om.examples.marking_gurobipy和llm4om.examples.checking_gurobi，使用相同component配置。native Backend在工厂构建及独立MPS读取时添加Worker-local标记，Solver验证标记后实际调用Gurobi。它不改模型系数，结果保存fixture_component。原生脚本的源码及首次执行保留，收集器使用这对插件独立读取并求解；当前Gurobi验收仍限真实微型环境。
