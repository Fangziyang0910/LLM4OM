# Host-model skills / 宿主模型建模

The current Codex or Claude Code model performs conversation, modeling, code generation, review, and explanation. General Intelligent Optimization Solver (`llm4om`) runs the original methods and solvers locally as a general solver for complex optimization problems. No platform model preset, LLM API key, Web deployment, or listening port is needed.

宿主当前模型承担对话、理解、建模、代码生成、核对和结果解释。通用智能优化求解器（`llm4om`）在本地复用方法图、检查脚本和求解器，求解各类复杂优化问题。不需要配置平台预设模型、LLM API Key，也不需要部署 Web。

## Install / 安装

Install one skill and choose your host in the installer. Git and Node.js 22.20+ run the installer. Your agent needs workspace and shell access, [uv](https://docs.astral.sh/uv/getting-started/installation/), and Docker.

准备 Git 和 Node.js 22.20+，执行下列命令并选择宿主。运行时需要 Agent 能执行命令、读写工作区，并能调用 uv 和已启动的 Docker。

```bash
npx skills add Fangziyang0910/LLM4OM --skill llm4om -g
```

The first invocation downloads an isolated, pinned Python runtime. The first solve builds the corresponding Docker image if missing. Later sessions reuse both. Open a new agent session after installation. Use `-a codex` to select just Codex, or omit `-g` to install for the current project.

只需安装这个 Skill。首次调用自动下载隔离的运行库，首次求解按需准备镜像，之后复用缓存。安装后开启新会话。只装到 Codex 时可加 `-a codex`，只装到当前项目时去掉 `-g`。

## Use / 使用

Mention `$llm4om` in Codex or invoke `/llm4om` in Claude Code. Describe your problem, attach data, and optionally specify a method and library. The skill guides the host through the internal protocol; users do not need to write JSON themselves.

在 Codex 中使用 `$llm4om`，在 Claude Code 中使用 `/llm4om`。用户正常描述问题、提供数据或指定方法即可。Skill 引导宿主处理方法任务与 JSON 交接，不要求用户手动操作这些步骤。

For a first run, invoke the skill, then send / 首次可发送：

> Use Direct and Pyomo with HiGHS. A factory produces nonnegative integer quantities A and B, with profits 3 and 2. Cutting capacity: 2A + B <= 8. Assembly capacity: A + 2B <= 8. Maximize profit. Show the formulation, actual solution, and saved artifacts.

> 使用 Direct、Pyomo 和 HiGHS。工厂生产 A、B，两者均为非负整数，单件利润分别为 3、2。切割约束为 2A+B≤8，装配约束为 A+2B≤8。请最大化利润，给出数学模型、实际求解结果和保存的文件。

The expected optimum is A=3, B=2, profit=13. The host performs the reasoning and responds in your language. To use data, give it a local CSV / JSON file and explain the columns and units. To change requirements, ask it to save a new run for comparison.

该例的最优解为 A=3、B=2、利润=13。宿主使用当前模型建模并解释实际结果。使用附件时提供本地 CSV / JSON 路径及列名、单位；调整条件时，新建运行并保留原方案作对比。

You can also ask the agent to list methods, inspect available backends or execute an existing model. For direct terminal use, set `RUNNER` to the absolute path of `scripts/run.py` inside the installed skill. Run the commands in your workspace.

也可以让 Agent 查询方法、检查求解器或运行已有模型。手动调用时，将 `RUNNER` 设为已安装 Skill 内 `scripts/run.py` 的绝对路径，在项目工作区执行命令。

```bash
uv run --script "$RUNNER" methods
uv run --script "$RUNNER" target --language ortools --solver CP_SAT
uv run --script "$RUNNER" backends
uv run --script "$RUNNER" solve --code model.py --language pyomo --data orders.csv --output solve.json
```

The standalone CLI remains available for existing integrations. API model clients and the Web workbench are optional extras.

## Update and uninstall / 升级与卸载

To update only LLM4OM, finish active sessions and repeat the install command for the same agents. The updated skill selects its own runtime. To remove it, run the command below and select the same agents. Saved sessions stay in your workspace.

升级前先完成正在进行的会话。重新执行安装命令并选择原宿主，即可更新 Skill 及其指定的运行库。卸载时选择对应宿主，工作区中已保存的方案可继续查阅。

```bash
npx skills remove llm4om -g
```

## Setup problems / 安装问题

| Symptom / 现象 | Action / 处理 |
|---|---|
| Skill missing / 找不到技能 | Open a new session in the selected host / 在安装时选择的宿主中新开会话 |
| Runner fails to start / 无法启动脚本 | Check `uv --version` and access to GitHub and Python package indexes / 检查 uv、GitHub 和 Python 包源连通性 |
| Docker unavailable / 无法访问 Docker | Start Docker and run `docker info` in the agent’s terminal, then retry / 在 Agent 所用终端中确认 Docker 可用后重试 |
| Worker build fails / 镜像构建失败 | Check the build output and retry the original command after resolving the reported error / 按构建日志处理具体错误后重试原命令 |
| Missing solver license / 缺少商业许可证 | Configure the license or choose a compatible open-source backend / 配置许可证或选择兼容的开源求解器 |

On Linux, Codex discovered the project-installed skill. Claude Code used the skill to read a CSV, generate a Pyomo model and solve the production example above with HiGHS. Full macOS and Windows runs are unverified.

Linux 上已验证 Codex 能发现项目内安装的技能。Claude Code 使用技能读取 CSV、生成 Pyomo 模型，经 HiGHS 得到上例最优利润 13。macOS 和 Windows 的完整流程尚未验证。

## Local sessions / 本地会话

```bash
uv run --script "$RUNNER" start --file problem.md --method or_llm_agent --language pyomo --session runs/host/example
uv run --script "$RUNNER" resume --session runs/host/example --responses answers.json
uv run --script "$RUNNER" status --session runs/host/example
```

Each command returns JSON. `pending` contains the original method's tasks, native tool schemas, and requested sampling settings. The current agent answers each task and submits a JSON object mapping every pending ID to an answer. The graph then parses, routes, executes tools, solves, and decides what comes next. See the [response protocol](../skills/llm4om/references/protocol.md).

每次命令返回后进程可以退出。原生 LangGraph SQLite 检查点保存方法状态，本地执行记录保存已完成回答、求解和检查结果。恢复会复用已完成操作；执行中的操作被强制中断后可能需要重跑。`status` 只读取，不推进方法。不同会话彼此独立，同一会话不能同时执行两条命令。

The private session directory contains checkpoints, execution records, `result.json`, and available `formulation.md` / `model.py` files. Full attachments remain in local storage; BIND's prompts still expose schemas rather than full numeric arrays. Host commands do not read model presets or `.env`.

`--max-calls` caps host requests, including parallel candidates. `--max-solves` caps solves. `--time-limit` bounds each solve or helper script. Waiting for host answers does not consume the active execution budget. Token counts are unknown to the CLI and reported as `null`.

## Method fidelity / 方法保留范围

All registered method graphs and all five modeling libraries are available. Prompts, stages, repair loops, backtracking, and stopping rules are retained. OptiMUS parsing retries propagate native graph pauses rather than treating them as malformed model output. Sessions record the method source and fixed parameters.

保留原有方法的搜索、投票、工具、局部修复与回溯。LP/MILP 方法的问题范围不因所选建模库改变。宿主模型的温度和上下文隔离不能由通用 Skill 强制控制；因此保留的是方法流程，而不是原 API 采样分布或论文实验结果。

Scripted host answers with real solvers validate execution and control flow. Real host smoke runs validate integration separately. Neither proves modeling accuracy on arbitrary problems.
