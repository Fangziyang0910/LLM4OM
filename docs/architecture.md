# 架构

LLM4OM 只做三件事：建模、求解、记录过程。LLM 调用、重试和回调交给 LangChain；图编排、运行、流式推送和持久化交给 LangGraph 及其服务器。平台只保留它们不提供的部分：代码目标、求解沙箱、步骤记录和工作台页面。

```text
浏览器（React + @langchain/langgraph-sdk）
   │  threads.create · runs.create（后台运行，可重放的流）· runs.joinStream · threads.get
   ▼
LangGraph 服务器（langgraph-api，内存运行时，数据在 <workspace>/.langgraph_api/）
   │  每个方法注册为一张平台图（server/graphs.py）；/api/* 由 server/app.py 提供
   ▼
平台图：prepare ──► model ──► solve
          │           │           └─ 方法没有求解最终代码时，在沙箱中求解一次
          │           └─ method.graph().astream(..., context=Context)
          │                 ├─ runtime.context.llm(role)    → LangChain 聊天模型（流式；回调记录每次调用）
          │                 ├─ runtime.context.solve(code)  → Docker Worker：构建 → 用该写法的求解器求解
          │                 └─ Method.titles 中节点的更新     → 中间产物步骤
          └─ 校验请求：问题非空、写法存在且方法支持、LLM 已配置
```

一次运行分两个阶段：数学建模和代码表达，都在方法图内完成；代码随后在沙箱中运行，得到结果。平台图把“方法”和“最终求解”分成两个节点，方法内部是否交错两个阶段、是否根据求解反馈回到建模，由方法自己决定。

## 模块

```text
src/llm4om/
├── __init__.py          公共入口：run、run_problem 及常用类型
├── cli.py               命令行：serve、run、build-worker
├── languages.py         代码写法与代码契约：LANGUAGES、CodeTarget、MILP_LANGUAGES
├── llm.py               服务商预设、LLMSettings、chat_model()、本机设置文件 SettingsStore
├── sandbox/             沙箱
│   ├── __init__.py      Sandbox（solve、run_script）与 SolveResult
│   ├── worker.py        沙箱内的独立脚本；不导入 llm4om
│   └── worker.Dockerfile
├── runtime.py           运行中的状态：Limits、Recorder（计数、上限、步骤、推送）、方法使用的 Context
├── methods/             建模方法：Method、methods()、各方法的图
├── graph.py             平台图 platform_graph(method)、RunState、RunContext、Resources、进程内运行 run()
└── server/              Web 工作台
    ├── graphs.py        每个方法的平台图，供 LangGraph 服务器注册
    ├── app.py           服务器挂载的路由：选项、LLM 设置、模型列表、题库、前端页面；拒绝非 JSON 的 POST
    ├── examples.py      内置题库的只读浏览（数据在 examples_data/）
    └── web_assets/      前端构建产物（源码在 frontend/）
```

依赖只朝一个方向：

```text
languages · llm · sandbox  →  runtime  →  methods  →  graph  →  server · cli
```

`languages`、`llm`、`sandbox` 互不依赖。方法只依赖 `runtime`、`languages`、`sandbox` 和 `methods` 本身，不依赖平台图或服务器。`sandbox/worker.py` 在沙箱中独立运行，因此不导入任何平台模块；它与 `languages.py` 各自列出四种写法，是隔离的代价。

## 平台图

| 键 | 内容 |
|---|---|
| 输入 | `description`（问题描述）、`data`（数据文件名到文本） |
| 运行上下文 `RunContext` | `language`、`provider`、`model`、`options`。只写服务商和模型名，不写密钥；服务器按服务商读取本机保存的设置 |
| 输出 | `formulation`、`code`、`solve`、`failure`、`steps`、`usage`（LLM 调用、求解、token） |

`prepare` 发现请求不可用时写入 `failure` 并结束运行，不调用 LLM；有效请求记录内部截止时间 `_deadline`。`model` 和 `solve` 共享剩余时间，超时、超限或出错时写入一个错误步骤和 `failure`。

方法图在 `model` 节点内运行，平台不为它保存检查点（`checkpointer = False`）：AutoFormulation 这类方法的内部状态很大，逐步保存的代价高于收益。平台图本身由服务器保存检查点。

进程内运行（命令行、测试、`run_problem`）通过 `config["configurable"]["llm4om_resources"]` 传入 `Resources`，替换设置文件、沙箱、上限或聊天模型工厂。服务器从环境变量 `LLM4OM_WORKSPACE`、`LLM4OM_SANDBOX` 读取默认资源。

运行用哪个 LLM 只由 `SettingsStore` 决定：已保存的服务商设置，加上 `LLM4OM_LLM_*` 环境变量给出的设置（该服务商没有保存设置时）；没有保存选择时选环境变量的服务商。`resolve(provider, model)` 取指定或已选服务商的设置，再用运行指定的模型名覆盖。设置页、模型列表和平台图都通过它读取。

## 方法接口

LangGraph 就是平台的方法抽象。每个方法是一张编译好的 LangGraph 图，即使只有一个节点（Direct）。平台不另设阶段、产物或插件接口。

| 约定 | 内容 |
|---|---|
| 状态 | 继承 `ModelingState`。输入 `problem`（问题描述加数据文件）；输出 `formulation`、`code`，可选 `solve`（方法自己已求解时）和 `failure`（没有代码时的原因） |
| 运行时 | 图以 `context_schema=Context` 编译；节点签名为 `node(state, runtime: Runtime[Context])` |
| 步骤 | `Method.titles` 把节点名映射为步骤标题。只有列出的节点显示为步骤；每次更新渲染为 Markdown（文本原样、`code` 和 `*_code` 为代码块、其他为 JSON） |
| 隐藏 | 以 `_` 开头的状态键、`problem`、`solve`、`messages`、`failure`，以及 `Method.hidden` 中的键，不显示 |
| 上限 | `Method.limits` 覆盖默认上限（AutoFormulation 的搜索需要数千次调用） |
| 写法 | `Method.languages` 声明支持的代码写法；不声明表示全部支持 |

```python
@dataclass(frozen=True)
class Method:
    id: str
    name: str
    description: str
    graph: Callable[[], Any]        # 返回编译好的图
    source: str | None = None       # 固定的上游提交
    titles: Mapping[str, str] = {}  # 节点名 → 步骤标题
    hidden: frozenset[str] = frozenset()
    languages: frozenset[str] | None = None  # 支持的代码写法；None 表示全部
    limits: Limits | None = None
```

| `Context` 成员 | 用途 |
|---|---|
| `data` | 数据文件名到文本内容；问题全文在状态的 `problem` 中 |
| `target.language` | 所选代码写法：`pyomo`、`gurobipy`、`pywraplp` 或 `cpmpy` |
| `target.prompt` | 所选写法的代码契约，直接拼接到生成代码的提示中 |
| `target.library` | 代码所用的库名（`Pyomo`、`Gurobi`、`OR-Tools`、`CPMpy`），用于替换原提示中写死的库名 |
| `target.starter` | 所选写法的空 `build_model` 模板，供需要代码示例的提示使用 |
| `llm(role)` | 配置好的 LangChain 聊天模型。`role` 写入调用元数据，用于在过程列表中命名调用 |
| `solve(code, title)` | 在沙箱中构建并求解，返回 `SolveResult`；`feedback()` 给出可交给 LLM 的文本 |
| `run_script(script)` | 在沙箱中把脚本作为 `__main__` 运行，返回标准输出和异常栈。不计入求解次数。供原方法自己的检查脚本使用 |
| `solves` | 本次运行到目前为止的求解次数 |
| `options` | 方法自定义参数 |

方法图结束后，平台图取最终状态的代码。方法已求解过的代码复用结果；否则 `solve` 节点求解一次。

新方法放在 `methods/` 并加入 `methods()`，或在其他包中注册 `llm4om.methods` 入口点。

## 可插拔的代码提示

生成代码的提示按所选代码写法动态组装：

- 使用平台契约的方法（Direct、Feedback Repair、TriVAL、OptiTree、OR-LLM-Agent、CoE）把 `target.prompt` 拼进提示；原提示中写死的 “Gurobi” 换成 `target.library`。
- 原提示逐句针对某个库的方法（OptiMUS、AutoFormulation）为每种写法准备一个方言：gurobipy 方言就是上游原文，Pyomo 和 `pywraplp` 方言只替换与库相关的句子、示例和变量代码。
- 方法的建模范围只覆盖部分写法时，用 `Method.languages` 声明。服务端拒绝不支持的组合，前端只列出支持的写法。

## 代码契约

一次运行分两个阶段：数学建模（方法产出数学模型）和代码表达（方法把模型写成代码）。代码在沙箱中求解。用户选择代码写法，写法决定求解器。所有写法的代码结构相同：定义 `build_model(data)` 并返回模型对象，不调用求解。Worker 用该写法自己的接口求解，统一设置时限，读出状态、目标值和变量取值：

| 代码写法 | 代码返回 | 求解器 | Worker 求解 |
|---|---|---|---|
| Pyomo | `pyo.ConcreteModel` | HiGHS | Pyomo 的 HiGHS 接口（`pyomo.contrib.solver` 的 `highs`） |
| gurobipy | `gp.Model` | Gurobi | `model.optimize()` |
| OR-Tools `pywraplp` | `pywraplp.Solver` | SCIP | `solver.Solve()` |
| CPMpy | `cp.Model` | OR-Tools CP-SAT | `SolverLookup.get("ortools", model).solve()` |

CPMpy 模型可以没有目标，此时是可满足性问题：找到解时状态为 `feasible`，没有目标值，但有变量取值。代码返回的对象与所选写法不符时，Worker 报告错误，错误信息交给方法作为反馈。

## 沙箱

`Sandbox` 有两个动作：`solve(code, data, language, time_limit)` 构建并求解模型；`run_script(script, time_limit)` 运行检查脚本。外层超时比求解时限多 60 秒，用于启动沙箱、导入库和构建模型。请求格式和结果标记只在 `sandbox/` 内部使用。

`Sandbox("docker")` 在镜像 `llm4om-worker:3` 中运行 Worker：无网络、只读根文件系统、`tmpfs` 工作目录、去除全部 capability、非 root 用户。设置了 `GRB_LICENSE_FILE` 时以只读方式挂载许可证。超时或取消时删除容器。

`Sandbox("local")` 用本机子进程运行同一脚本，只用于开发和测试。子进程只继承路径、语言、临时目录和 Gurobi 许可证位置等必要环境变量，不继承 API 密钥。超时或取消后等待子进程退出。

## 步骤记录与推送

`Recorder` 是一次运行在一个节点内的记账：LLM 调用数、求解次数、token、上限和步骤。平台图的每个节点从状态的 `usage` 创建它，因此计数跨节点连续；节点结束时用 `recorder.update()` 写回本节点的步骤和最新计数。

`Recorder.step()` 记录一步（`llm`、`artifact`、`solve` 或 `error`），并立即作为 LangGraph 的 custom 流事件推送 `{"step": ...}`。同一步开始时推送一次（`running: true`），结束时按 `id` 再推送一次。方法不直接记录步骤，也看不到 `Recorder`。

LLM 调用由聊天模型上的回调记录，包括子图和 `create_agent` 智能体中的调用。回调在调用开始时检查上限；模型流式输出时，每 0.25 秒推送一次新写出的文本 `{"delta": {"id", "text", "reasoning"}}`；调用结束时写入输出文本、工具调用、token 数和耗时。方法无需自己记录。

前端用 `runs.create` 创建后台运行，并设置 `streamResumable`。页面无论是刚创建运行还是稍后打开，都用 `runs.joinStream(..., lastEventId: "-1")` 从第一个事件重放，再接上实时事件。运行结束后，页面读取线程状态。

流连接重试失败后，页面重新读取运行状态。运行已结束时展示最终结果；仍在运行或服务器不可达时显示连接错误，并提供“重新连接”。

## 运行记录

运行是 LangGraph 服务器上的一个线程：

| 位置 | 内容 |
|---|---|
| 线程元数据 | 标题、方法、代码写法、服务商与模型名（无密钥） |
| 线程状态 | 问题、数据文件、数学模型、代码、求解结果、失败原因、全部步骤、调用统计 |
| 运行（run） | 状态：`pending`、`running`、`success`、`error`、`timeout`、`interrupted`（已停止） |

服务器把线程、运行和检查点保存在 `<workspace>/.langgraph_api/`。停止运行时，方法节点被取消，线程状态只保留输入。页面打开已停止的运行时，从服务器保留的流中重放停止前的步骤；服务器重启后，这些步骤不再可得。

## 前端

`frontend/` 是独立的 React 单页应用，只通过 HTTP 与服务器交互：运行、线程和流走 LangGraph 接口（`@langchain/langgraph-sdk`），设置、选项和题库走 `/api/*`。它不导入任何 Python 代码；构建产物输出到 `src/llm4om/server/web_assets/`，随 Python 包发布。

```text
frontend/src/
├── main.tsx        挂载：QueryClient、图标默认值、Toaster
├── App.tsx         布局、路由（/ 与 /run/{thread_id}）、对话框
├── api.ts          LangGraph 客户端、/api 请求、状态文案、格式化
├── useRun.ts       一次运行的实时数据：读取线程，并重放与接续流
├── steps.ts        步骤 → 阶段、版本、摘要（纯函数）
├── types.ts        与服务器对应的类型
└── components/     页面与控件
```

| 需要 | 使用 |
|---|---|
| 服务器数据（选项、设置、运行列表、题库分页） | TanStack Query：缓存、运行中轮询、失效后重取 |
| 运行的实时流 | LangGraph SDK 的 `runs.joinStream` |
| 弹出选择器 | Radix Popover：焦点、Escape、点外关闭、避让定位 |
| 对话框 | 原生 `<dialog>`（`showModal`） |
| 提示消息 | sonner |
| 图标 | lucide-react |
| Markdown 与公式 | react-markdown、remark-gfm、remark-math、rehype-katex；代码高亮用 highlight.js |

样式是一份 `style.css`，颜色与尺寸都来自 `:root` 上的变量，暗色模式跟随系统。

## 服务器与安全

`llm4om serve` 以内存运行时启动 `langgraph-api`（与 `langgraph dev` 相同），不需要 LangSmith 许可证。它注册每个方法的平台图，挂载 `server/app.py`，默认只监听 `127.0.0.1`，CORS 不允许任何跨源请求。`server/app.py` 的中间件对所有路由（包括 LangGraph 接口）拒绝非 JSON 的 POST，因此其他网站无法借浏览器发起运行或修改设置。

## 上限

`Limits` 给出每次运行的 LLM 调用数、求解次数、单次求解时限和总时长。超过时方法抛出 `LimitExceeded`，运行记为失败。
