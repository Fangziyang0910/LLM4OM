# LLM4OM

**用自然语言描述优化问题，查看数学模型、求解代码和求解结果。**

LLM4OM（Large Language Models for Optimization Modeling）是一个自动优化建模平台。你描述问题，选择建模方法和代码写法；平台调用 LLM 先建立数学模型，再写成代码，在隔离的容器中求解，并展示每一步的中间产物。

```text
问题描述 + 可选数据文件 → 建模方法（LLM） → 数学模型 + 求解代码 → 沙箱求解 → 结果
```

平台本身很薄：LLM 调用由 LangChain 完成，每个方法是一张 LangGraph 图，运行、流式推送和历史由 LangGraph 服务器（内存运行时，无需许可证）承担。平台只提供代码契约、求解沙箱和工作台页面。当前支持线性规划（LP）、混合整数线性规划（MILP）和约束规划（CP）。版本 `0.40.0`。

## 启动工作台

需要 Python 3.11–3.13、[uv](https://docs.astral.sh/uv/) 和 Docker。在仓库根目录执行：

```bash
uv sync --all-extras
uv run llm4om build-worker      # 构建求解沙箱镜像 llm4om-worker:4；镜像版本变化后需重新构建
uv run llm4om serve --workspace runs/web --port 8767
```

打开 <http://127.0.0.1:8767>。服务默认监听 `0.0.0.0`，同一网络中的其他机器用本机地址访问；只给自己用时加 `--host 127.0.0.1`。仓库已包含前端构建文件，无需 Node.js。

1. 点击左下角“预设模型”，添加一个预设：选择服务商，填写密钥和模型 ID。已设置 `LLM4OM_LLM_*` 环境变量时，这一步可以跳过。
2. 写出问题的决策、目标和约束；需要时拖入或添加 CSV、JSON 文件。也可以从首页的例子或“示例题库”开始。
3. 在右侧“运行设置”中选择建模方法、代码写法（写法决定求解器）和预设模型，点击“开始建模”或按 Ctrl+Enter。
4. 运行页顶部先给出结论：目标值与求解状态，或失败原因；“核对数学模型”和“查看解”直接跳到对应页签。下方左栏是“建模过程”，把 LLM 调用归入它们产出的阶段，正在进行的调用实时显示文字。右栏的“解”“数学模型”“求解代码”“问题与数据”四个页签给出产物：
   - 解可以按变量分组或列表查看，二维变量显示为矩阵，并可导出 CSV。
   - 方法改写过的数学模型和代码可以逐版查看，并与上一版对比。

运行在服务器上进行。关闭页面不会中断运行；重新打开时，页面从第一步重放到当前进度。

可以先试这个问题：

> 工厂生产 A、B 两种产品，数量必须是非负整数。每件 A 利润为 3，每件 B 利润为 2。A 消耗 2 单位切割资源和 1 单位加工资源，B 消耗 1 单位切割资源和 2 单位加工资源。两种资源各有 8 单位。请确定生产数量，使总利润最大。

最优解是 A=3、B=2，总利润 13。

左侧“运行记录”按日期列出同一工作区中的全部运行和各自的结果。运行页可以“再运行一次”（同样的问题和设置），或“修改后运行”（带回编辑页）。使用同一个 `--workspace` 即可保留设置和历史。左下角可切换浅色、深色或跟随系统。

## 建模方法

| 方法 | 流程 |
|---|---|
| Direct | 一次调用，同时给出数学模型和代码 |
| Feedback Repair | Direct，然后根据求解反馈修正 |
| TriVAL | 语义、数学模型、代码三阶段验证；每阶段构建、验证、修订 |
| OptiMUS | 提取参数、目标和约束，逐条建模和写代码，组装后调试 |
| Chain-of-Experts | 协调者逐个选择专家，汇总器写代码；可选反向反思 |
| OptiTree | 在固定问题类型树中匹配建模思路，再生成模型和代码 |
| OR-LLM-Agent | 先数学建模，再生成代码，根据执行错误调试，最后检查不可行或复查模型 |
| AutoFormulation | 运行上游搜索代码：逐层采样并剪枝建树，再用 MCTS 和两两比较排名（调用量很大） |

OptiMUS、CoE、OptiTree、OR-LLM-Agent 和 AutoFormulation 使用原工作的提示和流程。原提示针对 gurobipy 时，平台按所选写法改写其中与库相关的部分。这五个方法的原提示要求 LP/MILP，因此不提供 CPMpy 写法。

研究方法的固定来源和适配差异见[建模方法](docs/methods.md)。

## 代码写法与求解器

用户选择代码写法，写法决定求解器：

| 代码写法 | 求解器 | 适用 |
|---|---|---|
| Pyomo | HiGHS | LP、MILP |
| gurobipy | Gurobi（需要许可证；无许可证时只能求解小规模模型） | LP、MILP |
| OR-Tools `pywraplp` | SCIP | LP、MILP |
| CPMpy | OR-Tools CP-SAT | 约束规划：整数与布尔变量、全局约束、可满足性问题 |

生成的代码定义 `build_model(data)` 并返回模型，不调用求解。沙箱用该写法自己的接口求解并读出结果。

沙箱容器无网络、根文件系统只读、以非 root 用户运行。设置环境变量 `GRB_LICENSE_FILE` 后，许可证以只读方式挂载进容器。

## 模型与密钥

预设服务商：OpenAI、Google Gemini、Kimi、GLM、OpenRouter、阿里云百炼、DeepSeek、Anthropic。其他服务选择“OpenAI 兼容”并填写地址。

运行只能选择**预设模型**。每个预设固定服务商、接口地址、密钥、模型 ID 和请求参数：

- 预设只能添加和删除，不能修改。要换参数，删掉后重新添加。
- 密钥只保存在服务器上（`<workspace>/.private/llm-presets.json`，文件权限 `600`），任何接口和运行记录都不返回密钥，也不显示掩码。密钥只发给与它一起保存的接口地址。
- 服务器 `.env` 中的 `LLM4OM_LLM_*` 变量给出一个预设（id 为 `env`），排在第一位，是默认预设。页面上不能删除它，只能在服务器上修改。变量见 [.env.example](.env.example)。
- v0.38 保存的 `llm-settings.json` 在首次读取时转换为预设。

**DeepSeek 与 TriVAL**：DeepSeek 的思考模式不支持强制 `tool_choice`，TriVAL 的结构化输出需要它。在“高级参数 → 额外请求参数”中填写 `{"thinking": {"type": "disabled"}}`，或设置 `LLM4OM_LLM_EXTRA_BODY`。

Anthropic 的额外参数支持 `thinking`。OpenRouter 使用专用集成保留工具对话中的推理信息，推理强度可设置为 `{"reasoning": {"effort": "high"}}`；当前集成不支持的推理字段会报错。

## 内置题库

“示例题库”包含 9 组、2033 条公开题面，可以逐条阅读并带入输入区：

| Benchmark | 题数 | Benchmark | 题数 |
|---|---:|---|---:|
| NL4Opt | 205 | IndustryOR | 99 |
| NL4LP | 178 | ComplexOR | 18 |
| MAMO Easy | 642 | OptiBench | 403 |
| MAMO Complex | 210 | OptMATH | 128 |
| NL4COP | 150 | | |

题面来自 [OPT-Agent](https://github.com/Fangziyang0910/OPT-Agent) 的整理版本，不含答案。部分题目超出 LP/MILP 范围。平台不做批量评测。

## 命令行与 Python

```bash
uv run llm4om run --problem "……" --method trival --language pyomo
uv run llm4om run --file problem.txt --data demand.csv --method coe
```

命令在本进程中运行同一张图，逐步打印过程，最后输出数学模型、代码和求解结果。`--output state.json` 保存最终状态（含全部步骤）。`--preset` 按 id 选择工作区中的预设模型，默认使用第一个预设。

```python
from llm4om import run_problem

state = run_problem("……", method="optimus", language="gurobipy")
print(state["failure"] or state["solve"]["objective"])
```

Python 接口用 `preset=` 选择预设，或用 `llm=LLMSettings(...)` 直接传入设置。`--sandbox local` 在本机子进程中执行生成代码，不做隔离，只用于开发。

## 部署给课题组使用

在一台有公网 IP 的服务器上按“启动工作台”的步骤运行，在防火墙或云服务器安全组中放行端口（默认 8767），其他人用 `http://<公网 IP>:8767` 访问。服务器 `.env` 中的模型就是大家共用的默认预设。

工作台没有登录和权限控制，适合信任范围内的小组使用。能访问端口的人可以：

- 用任一预设发起运行，消耗该预设的额度；
- 添加和删除页面上添加的预设（服务器 `.env` 的预设不能删除）；
- 查看和删除全部运行记录。

访客读不到任何密钥。需要限制访问时，只放行课题组的 IP，或在前面加带登录的反向代理。Gurobi 学术许可证一般只限本人使用，供他人使用前请确认许可范围。

## 运行记录

每次运行是 LangGraph 服务器上的一个线程（thread）。线程状态保存问题、数据文件、数学模型、代码、求解结果、全部步骤和调用统计；线程元数据保存标题、方法、代码写法和模型名（无密钥）。服务器把它们保存在 `<workspace>/.langgraph_api/`，重启后仍在。

v0.38 使用新的运行格式。v0.37 的记录不会自动导入；旧工作区文件保留在原位置。

“最优”只说明求解器找到了当前模型的最优解。请对照问题检查数学模型是否完整。

## 接入新方法

方法是一张 LangGraph 图。状态继承 `ModelingState`：读 `problem`，写 `formulation` 和 `code`。节点通过 `runtime.context` 调用 LLM（`llm(role)`）和求解器（`solve(code)`）。代码提示中拼接 `context.target.prompt` 即可适配所选代码写法。只支持部分写法时，在 `Method` 中设置 `languages`。

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

`titles` 中的节点在运行过程中显示为步骤。把方法加入 `llm4om.methods.methods()`，或在你的包中注册 `llm4om.methods` 入口点。详见[架构](docs/architecture.md#方法接口)。

## 更多文档

- [文档导航](docs/README.md)
- [架构](docs/architecture.md)：模块、平台图、方法接口、沙箱和运行记录。
- [建模方法](docs/methods.md)：各方法流程、固定来源、适配差异和验证。
- [贡献指南](CONTRIBUTING.md)：开发环境和测试。

代码采用 [Apache-2.0](LICENSE)。第三方代码与数据的来源见 [NOTICE](NOTICE)。
