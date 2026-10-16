# 测试指南

按修改范围选择检查。文档、界面、方法流程和真实外部接入分别验证，避免把一种证据当成另一种。验收场景见[验收清单](../acceptance.md)。

## 文档与维护工具

```bash
uv run --locked python scripts/render_references.py --check
uv run --locked python scripts/check_repository.py
uv run --locked python -m unittest discover -s tests -p test_repository_checks.py -v
```

仓库检查自动发现受 Git 管理及未忽略的新文件，验证文本、本地链接、示例配置、引用、数据哈希和数学 fixture。固定上游字节另由清单核对，无需手工维护逐文件目录。

## Python 与容器

```bash
uv sync --locked --all-extras
uv run --locked --all-extras mypy
uv run --locked --all-extras python scripts/build_worker_image.py
uv run --locked --all-extras python -m unittest discover -s tests -v
uv build
```

完整测试要求可访问的 Docker daemon、Worker 镜像和相关可选依赖。真实容器测试不自动跳过。Gurobi 验收以当前可用许可证为准。

独立执行插件的测试还需要含插件镜像：

```bash
uv build examples/plugins/fixture_execution --wheel --out-dir dist/fixtures
EXECUTION_TEST_IMAGE="$(uv run --locked python -c 'from llm4om.executors import DEFAULT_IMAGE; print(DEFAULT_IMAGE + "-with-execution")')"
uv run --locked python scripts/build_worker_image.py --tag "$EXECUTION_TEST_IMAGE" --plugin-wheel dist/fixtures/llm4om_fixture_execution-0.1.0-py3-none-any.whl
```

其他插件用例自行构建并安装到临时目录，复用已锁定的构建依赖。`--offline` 仅约束 uv 缓存访问；Docker 基础镜像和运行依赖仍需已存在或可下载。

## 方法与求解器矩阵

```bash
PYTHONPATH=tests uv run --locked --all-extras python -m unittest test_research_method_runs.ResearchMethodRunTests.test_all_seven_methods_with_all_three_real_solvers -v
```

该测试使用确定性 HTTP 回复和真实容器求解，覆盖七种方法与三个求解器的 21 个组合。它验证流程与兼容性，不测量真实 LLM 建模准确率。

## 浏览器流程

```bash
npm --prefix frontend install
npm --prefix frontend run build
```

每个测试族使用全新的一次性工作区。不要用真实历史运行目录；重启 fixture 时也换一个空目录。

终端 1：

```bash
uv run --locked --extra solve python tests/helpers/web_guidance_server.py --workspace /tmp/llm4om-web-fixture
```

终端 2：

```bash
LLM4OM_WEB_TEST_URL=http://127.0.0.1:8774 \
LLM4OM_WEB_TEST_PROVIDER_URL=http://127.0.0.1:8775 \
LLM4OM_WEB_TEST_WORKSPACE=/tmp/llm4om-web-fixture/jobs \
LLM4OM_BROWSER_MODULE="$PWD/frontend/node_modules/playwright" \
LLM4OM_BROWSER_EXECUTABLE=/absolute/path/to/chrome \
node tests/web_story_flow.cjs
```

浏览器路径使用本机 Chrome。核心测试位于 `tests/web_*flow.cjs`，通过公共 HTTP 接口建立独立场景。`LLM4OM_WEB_TEST_WORKSPACE` 指向 `<workspace>/jobs`。`web_methods_flow.cjs` 验证页面生成的 21 个方法/求解器配置均通过真实预检。

连通性测试使用 `tests/helpers/connectivity_server.py` 的独立工作区，Web/Provider 端口为 `8796/8797`。延迟步骤观察可为 guidance fixture 设置 `--response-delay 4`，并为澄清测试设置 `LLM4OM_WEB_TEST_LIVE_PROGRESS=1`。

`tests/replays/` 是特定历史记录的手工复查脚本，需要匹配样本和调用记录。它们不替代可独立运行的核心流程测试。

## 交付证据

报告实际执行的检查、结果和未覆盖条件。来源、配置、模型、求解器和执行身份需要与证据对应。确定性 fixture、真实求解、真实 LLM 和冻结实验分别命名。已有接入范围见[支持验证](validation.md)。
