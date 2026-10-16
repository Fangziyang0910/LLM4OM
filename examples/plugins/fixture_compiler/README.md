# 独立 Compiler 示例

本例演示可信编译器注册、配置和 Worker 安装。规范见 [插件契约](../../../docs/contracts/plugins.md)。该示例改变源码格式，复用现有LPIR数学转换；它是工程fixture。

在仓库根目录构建和安装：

```bash
uv build --wheel examples/plugins/fixture_compiler --out-dir /tmp/llm4om-compiler-wheel
uv pip install --python .venv/bin/python --no-deps /tmp/llm4om-compiler-wheel/llm4om_fixture_compiler-0.1.0-py3-none-any.whl
uv run --locked llm4om plugins list
```

复制examples/specs/solve.yaml，在相同公开输入目录中修改compiler选择：

```yaml
compiler:
  plugin_id: llm4om.examples.ast_compiler
  config:
    marker: selected_compiler
```

运行doctor和run即可使用该编译器。它接收grounded LPIR及明确的Pyomo目标，返回CompiledCode。源码通过ast.unparse重新排版并保存marker；变量、约束与内部变量映射随Code保存。配置和包身份进入admission及编译来源。

容器运行须将同一wheel安装在可信镜像中：

```bash
uv run --locked python scripts/build_worker_image.py --tag llm4om-worker:with-compiler --plugin-wheel /tmp/llm4om-compiler-wheel/llm4om_fixture_compiler-0.1.0-py3-none-any.whl
```

在executor.config.image中选择该镜像。doctor核对宿主与Worker的Manifest、配置、依赖及可执行包内容；缺少或不同的编译器在生成前拒绝。镜像不挂载宿主源码、不在运行时安装包。额外Python依赖须预先纳入锁定运行环境，构建工具不会隐式解析它们。

插件是可信代码。describe、create和compile不得调用LLM或读取隐藏评测材料。当前profile只支持grounded LP/MILP→Pyomo；工厂及原生Code继续保留方法生成来源。改变包或配置需要新运行，已有run不能静默迁移。
