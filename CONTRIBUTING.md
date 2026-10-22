# 开发指南

本文面向修改 LLM4OM 代码的人：搭建环境、本地开发、测试、接入新方法、增加代码写法和发布版本。先读 [GLOSSARY](GLOSSARY.md)、[CODING_STANDARDS](CODING_STANDARDS.md) 和[架构](docs/architecture.md)。工作项使用 [GitHub Issues](docs/agents/issue-tracker.md)。

## 环境

| 工具 | 版本 | 用途 |
|---|---|---|
| Python | 3.11–3.13 | 服务端、方法和测试 |
| [uv](https://docs.astral.sh/uv/) | 最新版 | 依赖管理 |
| Docker | 任意较新版本 | 求解沙箱 |
| Node.js | 22.13 或更新 | 只在修改前端时需要 |

```bash
git clone https://github.com/Fangziyang0910/LLM4OM.git && cd LLM4OM
uv sync --all-extras
uv run llm4om build-worker          # 构建沙箱镜像 llm4om-worker:7
cp .env.example .env                # 填写默认预设，供真实运行使用
```

## 项目结构

```text
LLM4OM/
├── src/llm4om/
│   ├── cli.py               命令行：serve、run、build-worker
│   ├── languages.py         代码写法与代码契约
│   ├── llm.py               服务商、LLM 设置和预设模型
│   ├── runtime.py           运行上下文、步骤记录、上限和每日 token 预算
│   ├── graph.py             平台图：prepare → model → solve
│   ├── methods/             10 种建模方法，每种是一张 LangGraph 图
│   │   └── presets.py       全部方法的固定参数
│   ├── sandbox/             沙箱：worker.py 在容器中构建并求解模型
│   └── server/              LangGraph 服务器的图注册、/api 路由、题库和前端构建产物
├── frontend/                React 工作台（Vite、Tailwind v4、shadcn/ui）
│   ├── src/                 页面、组件和 locales/en.ts 英文译文
│   └── e2e/                 Playwright 测试和脚本化 LLM
├── tests/                   pytest：方法、沙箱、平台图、服务器和命令行
├── docs/                    使用、部署、架构、方法、ADR 和参考资料
├── compose.yaml · Dockerfile · docker-entrypoint.sh
└── langgraph.json           LangGraph Studio 读取的图列表
```

模块依赖只朝一个方向：`languages · llm · sandbox → runtime → methods → graph → server · cli`。详见[架构](docs/architecture.md)。

## 本地开发

后端：

```bash
uv run llm4om serve --workspace runs/dev --port 8767
```

修改服务端代码后，重启服务。开发时可以加 `--sandbox local`，在本机子进程中执行生成代码，不需要 Docker。

前端：

```bash
npm --prefix frontend ci
npm --prefix frontend run dev       # 开发服务器；/api、/threads、/assistants 代理到 8767
npm --prefix frontend run build     # 输出到 src/llm4om/server/web_assets/，随 Python 包发布
```

仓库包含前端构建产物，所以只改后端的人不需要 Node.js。修改前端后，提交前要重新构建。

调试方法图时，可以用 LangGraph Studio：在仓库根目录运行 `uv run langgraph dev`。它读取 `langgraph.json`，注册与 `llm4om serve` 相同的图。

### 前端约定

- 界面文字写成 `t("中文原文")`，并在 `frontend/src/locales/en.ts` 中加英文。`i18n.test.ts` 会检查遗漏。服务器给出的方法说明和步骤标题也要加英文。
- 组件优先用 `frontend/src/components/ui/` 中的 shadcn/ui 组件。需要新组件时，在 `frontend/` 下运行 `npx shadcn@latest add <组件>`，再检查导入路径是否为 `@/lib/utils`。
- 颜色使用 `index.css` 中的变量，例如 `bg-muted`、`text-destructive`。不要写死色值。
- 工作台常通过 `http://<IP>` 打开。不要使用只在 HTTPS 下可用的浏览器接口，例如 `crypto.randomUUID`；必须用时，提供退路。

## 测试

| 检查 | 命令 | 内容 |
|---|---|---|
| Python 规范 | `uv run ruff check` | |
| Python 测试 | `uv run pytest` | 方法主要路径、沙箱、平台图、服务器、命令行 |
| 前端规范 | `npm --prefix frontend run lint` | ESLint，含 React Hooks 规则 |
| 前端单元测试 | `npm --prefix frontend test` | 步骤分组、断流恢复、公式渲染、解的表格、报告、Excel、译文完整、发起运行 |
| 浏览器测试 | `npm --prefix frontend run e2e` | 真实页面上的运行、对比、不可行诊断、备注、报告、Excel 和英文界面 |

Python 测试不调用真实 LLM，也不需要 Docker。方法使用脚本化聊天模型，求解使用本机 Worker（需要 `solve` 可选依赖）。AutoFormulation 的等价判断测试需要 `autoformulation` 可选依赖。

浏览器测试使用构建好的页面，并需要 `solve` 和 `gurobi` 可选依赖（`uv sync --all-extras` 已包含）。第一次运行前安装浏览器：

```bash
npm --prefix frontend run build
(cd frontend && npx playwright install chromium)
npm --prefix frontend run e2e       # 启动脚本化 LLM（8796）和本机沙箱的服务（8797）
```

真实运行使用 `.env` 中的模型：

```bash
uv run llm4om run --problem "……" --method trival
```

确定性测试和真实运行的结果要分别报告。CI（`.github/workflows/checks.yml`）在 Python 3.11–3.13 上运行全部检查，并构建 Docker 镜像。

## 接入研究方法

方法是一张 LangGraph 图。状态继承 `ModelingState`：读 `problem`，写 `formulation` 和 `code`。节点通过 `runtime.context` 调用 LLM（`llm(role)`）和求解器（`solve(code)`）。代码提示中拼接 `context.target.prompt`，就能适配所选代码写法。

```python
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.methods import Method
from llm4om.methods.common import TWO_PARTS, ask, split_formulation_and_code
from llm4om.runtime import Context, ModelingState


async def generate(state: ModelingState, runtime: Runtime[Context]) -> dict:
    context = runtime.context
    reply = await ask(context, "model", "Model the problem. " + TWO_PARTS + "\n\n" + context.target.prompt, state["problem"])
    formulation, code = split_formulation_and_code(reply)
    return {"formulation": formulation, "code": code}  # 平台会求解未求解过的最终代码


def my_graph():
    graph = StateGraph(ModelingState, context_schema=Context)
    graph.add_node("generate", generate)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", END)
    return graph.compile()


MY_METHOD = Method("my_method", "我的方法", "一句话说明。", my_graph, titles={"generate": "数学模型与代码"})
```

`titles` 中的节点在运行过程中显示为步骤。把方法加入 `llm4om.methods.methods()`，或在你的包中注册 `llm4om.methods` 入口点。

移植已发表的方法时：

1. 在 `src/llm4om/methods/` 中写成 LangGraph 图，定义 `Method`，加入 `methods()` 和 `langgraph.json`。
2. 记录固定的上游提交，填入 `Method.source`。
3. 忠实移植核心建模逻辑：编排、提示、解析和停止条件。只做适配、避错和必要的修正，在[建模方法](docs/methods.md)和源码的 `llm4om:` 注释中逐条记录。论文与代码冲突时，以代码为准。
4. 原提示写死某个库时，为每种代码写法准备方言，gurobipy 方言保留原文。方法只覆盖部分写法时（例如原提示要求 MILP），设置 `Method.languages`。
5. 方法参数写入 `methods/presets.py`。
6. 在 `tests/test_methods.py` 中用脚本化模型跑通主要路径。
7. 在 `frontend/src/locales/en.ts` 中加方法说明和步骤标题的英文。
8. 用真实 LLM 至少跑通一个问题，把结果写入[建模方法](docs/methods.md#验证)。

第三方代码和数据保留来源与许可，并更新 [NOTICE](NOTICE)。

## 增加代码写法

一种写法对应一个建模库和一个求解器（[ADR 0008](docs/adr/0008-code-language.md)）。需要改这些地方：

1. `languages.py`：在 `LANGUAGES` 中加入 `Language`（库名、求解器、代码契约和起始代码）。MILP 写法加入 `MILP_LANGUAGES`。
2. `sandbox/worker.py`：在 `SOLVERS` 中加入求解函数。能找出冲突约束时，加入 `CONFLICTS`。
3. `sandbox/worker.Dockerfile` 和 `pyproject.toml` 的 `solve` 可选依赖：加入库和求解器。
4. 更换沙箱镜像标签：`WORKER_IMAGE`、`compose.yaml`，以及文档和 CI 中的标签。
5. `tests/test_sandbox.py`：求解、错误和不可行三种情况。
6. README、[GLOSSARY](GLOSSARY.md) 和[架构](docs/architecture.md)中的写法表。

## 文档

- 用户能看到的变化，同时更新 [README](README.md)、[README.en.md](README.en.md)、[使用指南](docs/user-guide.md)或[部署指南](docs/deployment.md)。
- 每个版本在 [CHANGELOG](CHANGELOG.md) 中记录。
- 架构取舍写成 ADR（[索引](docs/adr/README.md)），术语写入 [GLOSSARY](GLOSSARY.md)。
- 修改 `docs/references/catalog.json` 后，运行 `python3 scripts/render_references.py`。
- 界面有明显变化时，更新 `docs/assets/` 中的截图和 `demo.gif`。截图使用 1440×900 视口、2 倍像素密度；`demo.gif` 是一次真实运行的录屏，宽 960 像素。

## 发布

1. 更新 `pyproject.toml` 和 `frontend/package.json` 的版本号，运行 `uv lock` 和 `npm --prefix frontend install`。
2. 重新构建前端。
3. 在 [CHANGELOG](CHANGELOG.md) 中写这个版本的变化。
4. 运行全部检查，并用真实 LLM 跑通几个问题。
5. 提交，推送到 `main`，确认 CI 通过。

## 交付

- 密钥、运行数据和商业许可证不提交。
- 报告改动、实际执行的检查和未验证的条件。
- 安全问题按 [SECURITY](SECURITY.md) 私下报告。
