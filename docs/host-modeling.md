# Host-model skills / 宿主模型建模

The current Codex or Claude Code model performs conversation, modeling, code generation, review, and explanation. LLM4OM runs the original methods and solvers locally. No platform model preset, LLM API key, Web deployment, or listening port is needed.

宿主当前模型承担对话、理解、建模、代码生成、核对和结果解释。本地程序复用方法图、检查脚本和求解器。不需要配置平台预设模型、LLM API Key，也不需要部署 Web。

## Install / 安装

Prepare [uv](https://docs.astral.sh/uv/getting-started/installation/), Git, Node.js 22.20 or newer, a running Docker installation, and an authenticated Codex or Claude Code session that can execute commands. The CLI supports Python 3.11–3.13; the command below selects Python 3.12. No repository checkout is needed.

准备 uv、Git、Node.js 22.20 或更新版本、已启动的 Docker，以及已登录且能执行命令的 Codex 或 Claude Code。以下命令将 CLI 与 Skill 固定到同一个发布版本。

```bash
uv tool install --python 3.12 git+https://github.com/Fangziyang0910/LLM4OM@v0.43.0
llm4om build-worker
npx skills add https://github.com/Fangziyang0910/LLM4OM/tree/v0.43.0/skills/llm4om --skill llm4om -g -a codex -a claude-code
```

The three commands install the isolated CLI, build the existing solver image, and install the English skill for both hosts. The base package excludes Web and model-provider dependencies. `llm4om[llm]` adds API-model clients; `llm4om[web]` adds the existing workbench and those clients.

三条命令分别安装 CLI、准备求解镜像和安装技能文件。安装技能不会自动安装 Python 或 Docker。基础包用于宿主建模和纯求解；`llm` 与 `web` 是原有 API 模型运行和工作台的可选依赖。

`-g` installs the skill across projects. Keep only `-a codex` or `-a claude-code` if you use one host. The first worker build downloads modeling libraries and solver backends and can take several minutes. Open a new host session after installation.

`-g` 表示全局安装；只使用一个宿主时保留对应的 `-a` 参数。首次构建求解镜像需要下载依赖，可能花费较长时间。完成后开启新的宿主会话。

Confirm installation / 核对安装：

```bash
llm4om --version
llm4om methods
llm4om backends
```

The version should be `LLM4OM 0.43.0`. `methods` lists 13 methods; `backends` queries the actual Docker worker. A listed backend may still need its own commercial license. Start with Pyomo / HiGHS or CPMpy / OR-Tools when no commercial solver is required.

版本应为 `LLM4OM 0.43.0`。`methods` 列出 13 种方法；`backends` 查询实际求解镜像。商业后端仍需要其自身许可证，首次可使用 Pyomo / HiGHS 或 CPMpy / OR-Tools。

Release [v0.43.0](https://github.com/Fangziyang0910/LLM4OM/releases/tag/v0.43.0) also contains a wheel and a separate skill ZIP. If Git cloning is unavailable, replace the first and third commands with these direct downloads, keeping `llm4om build-worker` between them:

```bash
uv tool install --python 3.12 https://github.com/Fangziyang0910/LLM4OM/releases/download/v0.43.0/llm4om-0.43.0-py3-none-any.whl
npx skills add https://github.com/Fangziyang0910/LLM4OM/releases/download/v0.43.0/llm4om-skill-0.43.0.zip --skill llm4om -g -a codex -a claude-code
```

无法克隆 Git 仓库时，可用上述 Release 附件替换 CLI 和 Skill 的安装来源。仍需执行 `llm4om build-worker`。

## Use / 使用

Mention `$llm4om` in Codex or invoke `/llm4om` in Claude Code. Describe your problem, attach data, and optionally specify a method and library. The skill guides the host through the internal protocol; users do not need to write JSON themselves.

在 Codex 中使用 `$llm4om`，在 Claude Code 中使用 `/llm4om`。用户正常描述问题、提供数据或指定方法即可。Skill 引导宿主处理方法任务与 JSON 交接，不要求用户手动操作这些步骤。

For a first run, invoke the skill, then send / 首次可发送：

> Use Feedback Repair and Pyomo with HiGHS. A factory produces nonnegative integer quantities A and B, with profits 3 and 2. Cutting capacity: 2A + B <= 8. Assembly capacity: A + 2B <= 8. Maximize profit. Show the formulation, actual solution, and saved artifacts.

> 使用 Feedback Repair、Pyomo 和 HiGHS。工厂生产 A、B，两者均为非负整数，单件利润分别为 3、2。切割约束为 2A+B≤8，装配约束为 A+2B≤8。请最大化利润，给出数学模型、实际求解结果和保存的文件。

The expected optimum is A=3, B=2, profit=13. The host performs the reasoning and responds in your language. To use data, give it a local CSV / JSON file and explain the columns and units. To change requirements, ask it to save a new run for comparison.

该例的最优解为 A=3、B=2、利润=13。宿主使用当前模型建模并解释实际结果。使用附件时提供本地 CSV / JSON 路径及列名、单位；调整条件时，新建运行并保留原方案作对比。

The CLI also exposes standalone tools:

```bash
llm4om methods
llm4om target --language ortools --solver CP_SAT
llm4om backends
llm4om solve --code model.py --language pyomo --data orders.csv --output solve.json
```

`methods` reports installed methods and fixed parameters. `target` prints the maintained library contract. `backends` queries the actual execution environment. `solve` executes `build_model(data)` code and returns the native status, objective, variables, output, and errors. None calls an LLM.

原有 `llm4om run` 使用平台预设模型，与宿主模式分开。Skill 使用 `host` 或 `solve`，不调用 `run`。

## Update and uninstall / 升级与卸载

To upgrade, select one release and reinstall both components from that release. For v0.43.0:

```bash
uv tool install --force --python 3.12 git+https://github.com/Fangziyang0910/LLM4OM@v0.43.0
llm4om build-worker
npx skills add https://github.com/Fangziyang0910/LLM4OM/tree/v0.43.0/skills/llm4om --skill llm4om -g -a codex -a claude-code
```

Keep the CLI and skill on the same release. Start a new modeling session after changing the package version or method parameters; keep old session directories as records. The solver image stays `llm4om-worker:12` in this release.

CLI 和 Skill 使用同一版本。升级后创建新的建模会话，保留旧目录中的记录。当前版本的求解镜像仍为 `llm4om-worker:12`。

```bash
npx skills remove llm4om -g -a codex -a claude-code
uv tool uninstall llm4om
```

Uninstalling leaves saved sessions and the Docker worker image intact. Remove those separately only when no longer needed.

卸载保留已有会话文件和 Docker 求解镜像，不影响已保存方案。

## Setup problems / 安装问题

| Symptom / 现象 | Action / 处理 |
|---|---|
| `llm4om` is not found / 找不到命令 | Run `uv tool update-shell`, then open a new terminal / 更新 PATH 后开启新终端 |
| Docker cannot connect / 无法连接 Docker | Start Docker and confirm `docker info` works in this terminal / 启动 Docker，确认当前终端可访问 |
| Worker image is missing / 缺少求解镜像 | Run `llm4om build-worker`; keep its build log if it fails / 构建镜像，失败时检查日志 |
| Skill is not visible / 宿主看不到技能 | Open a new session and confirm the installation targets your host / 新开会话并检查对应宿主是否安装 |
| A backend reports a missing license / 后端缺少许可证 | Choose an available open-source backend or configure that solver's license / 选择可用开源后端或配置许可证 |

Linux installation and Docker execution are verified. Full macOS and Windows installation has not been verified. For trusted development without Docker, install `solve` and `autoformulation` extras into the CLI environment and pass `--sandbox local`; generated code then runs in that Python environment without container isolation.

已验证 Linux 安装与 Docker 执行；macOS、Windows 尚未完成整套验证。本机直接执行模式用于可信开发环境，需另装对应求解依赖。

## Local sessions / 本地会话

```bash
llm4om host start --file problem.md --method feedback_repair --language pyomo --session runs/host/example
llm4om host resume --session runs/host/example --responses answers.json
llm4om host status --session runs/host/example
```

Each command returns JSON. `pending` contains the original method's tasks, native tool schemas, and requested sampling settings. The current agent answers each task and submits a JSON object mapping every pending ID to an answer. The graph then parses, routes, executes tools, solves, and decides what comes next. See the [response protocol](../skills/llm4om/references/protocol.md).

每次命令返回后进程可以退出。原生 LangGraph SQLite 检查点保存方法状态，本地执行记录保存已完成回答、求解和检查结果。恢复会复用已完成操作；执行中的操作被强制中断后可能需要重跑。`status` 只读取，不推进方法。不同会话彼此独立，同一会话不能同时执行两条命令。

The private session directory contains checkpoints, execution records, `result.json`, and available `formulation.md` / `model.py` files. Full attachments remain in local storage; BIND's prompts still expose schemas rather than full numeric arrays. Host commands do not read model presets or `.env`.

`--max-calls` caps host requests, including parallel candidates. `--max-solves` caps solves. `--time-limit` bounds each solve or helper script. Waiting for host answers does not consume the active execution budget. Token counts are unknown to the CLI and reported as `null`.

## Method fidelity / 方法保留范围

All 13 existing method graphs and all nine modeling libraries are available. Prompts, stages, candidate counts, ranking, voting, selective repair, backtracking, and stopping rules are retained. OptiMUS parsing retries propagate native graph pauses rather than treating them as malformed model output. Sessions record the method source and fixed parameters.

保留原有方法的搜索、投票、工具、局部修复与回溯。LP/MILP 方法的问题范围不因所选建模库改变。宿主模型的温度和上下文隔离不能由通用 Skill 强制控制；因此保留的是方法流程，而不是原 API 采样分布或论文实验结果。

Scripted host answers with real solvers validate execution and control flow. Real host smoke runs validate integration separately. Neither proves modeling accuracy on arbitrary problems.
