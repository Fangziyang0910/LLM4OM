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
          │                 └─ Method.titles 中节点结束时的更新 → 中间产物步骤
          └─ 校验请求：问题非空、写法存在且方法支持、LLM 已配置
```

一次运行分两个阶段：数学建模和代码表达，都在方法图内完成；代码随后在沙箱中运行，得到结果。平台图把“方法”和“最终求解”分成两个节点，方法内部是否交错两个阶段、是否根据求解反馈回到建模，由方法自己决定。

## 模块

```text
src/llm4om/
├── __init__.py          公共入口：run、run_problem 及常用类型
├── cli.py               命令行：serve、run、build-worker
├── languages.py         代码写法与代码契约：LANGUAGES、CodeTarget、MILP_LANGUAGES
├── llm.py               服务商列表、LLMSettings、chat_model()、预设模型 LLMPresetStore
├── sandbox/             沙箱
│   ├── __init__.py      Sandbox（solve、run_script）与 SolveResult
│   ├── worker.py        沙箱内的独立脚本；不导入 llm4om
│   └── worker.Dockerfile
├── runtime.py           运行中的状态：Limits、Recorder（计数、上限、步骤、推送）、方法使用的 Context
├── methods/             建模方法：Method、methods()、各方法的图
│   └── presets.py       全部方法的参数，每次运行都用这一套
├── graph.py             平台图 platform_graph(method)、RunState、RunContext、Resources、进程内运行 run()
└── server/              Web 工作台
    ├── graphs.py        每个方法的平台图，供 LangGraph 服务器注册
    ├── app.py           服务器挂载的路由：选项、预设模型、模型列表、题库、前端页面；拒绝非 JSON 的 POST
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
| 运行上下文 `RunContext` | `language`、`preset`。只写预设模型的 id，不写密钥，也不能改模型；服务器按 id 读取预设。方法参数不随运行传入，固定在 `methods/presets.py` |
| 输出 | `formulation`、`code`、`solve`、`failure`、`steps`、`usage`（LLM 调用、求解、token） |

`prepare` 发现请求不可用时写入 `failure` 并结束运行，不调用 LLM；有效请求记录内部截止时间 `_deadline`。`model` 和 `solve` 共享剩余时间，超时、超限或出错时写入一个错误步骤和 `failure`。

方法图在 `model` 节点内运行，平台不为它保存检查点（`checkpointer = False`）：AutoFormulation 这类方法的内部状态很大，逐步保存的代价高于收益。平台图本身由服务器保存检查点。

进程内运行（命令行、测试、`run_problem`）通过 `config["configurable"]["llm4om_resources"]` 传入 `Resources`，替换预设模型、沙箱、上限或聊天模型工厂。服务器从环境变量 `LLM4OM_WORKSPACE`、`LLM4OM_SANDBOX` 读取默认资源。

运行用哪个 LLM 只由 `LLMPresetStore` 决定（`Resources.llm` 给出时除外）。预设列表是 `LLM4OM_LLM_*` 环境变量给出的预设（id 为 `env`），加上 `<workspace>/.private/llm-presets.json` 中按添加顺序保存的预设；第一个是默认预设。`get(preset)` 按 id 取设置，id 不存在时报错并列出可选 id。

预设只能添加（`add`）和删除（`delete`），没有修改操作；`env` 预设不能删除。`public()` 返回的预设不含密钥。模型列表接口 `/api/models` 只使用请求中填写的密钥，从不补入已保存的密钥，因此密钥只会发往与它一起保存的接口地址。

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

方法图结束后，平台图取最终状态的代码。方法已求解过的代码复用结果；否则 `solve` 节点求解一次。

新方法放在 `methods/` 并加入 `methods()`，或在其他包中注册 `llm4om.methods` 入口点。

## 可插拔的代码提示

生成代码的提示按所选代码写法动态组装：

- 使用平台契约的方法（Direct、Feedback Repair、TriVAL、OptiTree、OR-LLM-Agent、CoE、ORThought、LLMOPT）把 `target.prompt` 拼进提示；原提示中写死的库名（“Gurobi”“Gurobipy”“Pyomo”）换成 `target.library`。
- 原提示逐句针对某个库的方法（OptiMUS、AutoFormulation）为每种写法准备一个方言：gurobipy 方言就是上游原文，Pyomo、`pywraplp` 和 PuLP 方言只替换与库相关的句子、示例和变量代码。
- 方法的建模范围只覆盖部分写法时，用 `Method.languages` 声明。服务端拒绝不支持的组合，前端只列出支持的写法。

## 代码契约

一次运行分两个阶段：数学建模（方法产出数学模型）和代码表达（方法把模型写成代码）。代码在沙箱中求解。用户选择代码写法，写法决定求解器。所有写法的代码结构相同：定义 `build_model(data)` 并返回模型对象，不调用求解。Worker 用该写法自己的接口求解，统一设置时限，读出状态、目标值和变量取值：

| 代码写法 | 代码返回 | 求解器 | Worker 求解 |
|---|---|---|---|
| Pyomo | `pyo.ConcreteModel` | HiGHS | Pyomo 的 HiGHS 接口（`pyomo.contrib.solver` 的 `highs`） |
| gurobipy | `gp.Model` | Gurobi | `model.optimize()` |
| OR-Tools `pywraplp` | `pywraplp.Solver` | SCIP | `solver.Solve()` |
| CPMpy | `cp.Model` | OR-Tools CP-SAT | `SolverLookup.get("ortools", model).solve()` |
| PuLP | `pulp.LpProblem` | CBC（PuLP 自带） | `problem.solve(PULP_CBC_CMD(...))` |
| CVXPY | `cp.Problem` | Clarabel | `problem.solve(solver=CLARABEL)`；只接受连续凸模型，含整数变量时报错 |

MILP 写法是 Pyomo、gurobipy、`pywraplp` 和 PuLP（`languages.MILP_LANGUAGES`）。CPMpy 模型可以没有目标，此时是可满足性问题：找到解时状态为 `feasible`，没有目标值，但有变量取值。代码返回的对象与所选写法不符时，Worker 报告错误，错误信息交给方法作为反馈。

## 沙箱

`Sandbox` 有两个动作：`solve(code, data, language, time_limit)` 构建并求解模型；`run_script(script, time_limit)` 运行检查脚本。外层超时比求解时限多 60 秒，用于启动沙箱、导入库和构建模型。请求格式和结果标记只在 `sandbox/` 内部使用。

`Sandbox("docker")` 在镜像 `llm4om-worker:7` 中运行 Worker：无网络、只读根文件系统、`tmpfs` 工作目录、去除全部 capability、非 root 用户。`worker.py` 构建进镜像，不在运行时挂载，因此平台本身在容器中运行时也能使用；修改 `worker.py` 或 `worker.Dockerfile` 时要同时更新镜像标签（`WORKER_IMAGE` 与 `compose.yaml`）。`docker run` 只使用本地镜像（`--pull never`）。设置了 `GRB_LICENSE_FILE` 时以只读方式挂载许可证。超时或取消时删除容器。

求解状态为 `infeasible` 时，Worker 在同一次运行中找出一组互相冲突的约束，写入 `SolveResult.diagnosis`（`tool`、`items`、`total`、`error`）：线性模型写成 LP 文件后由 Gurobi 计算 IIS（无许可证时只适用于小模型），CPMpy 模型用 CPMpy 的 MUS，CVXPY 模型不诊断。诊断限时 20 秒，最多列出 60 条。诊断只给人看：`feedback()` 不包含它，方法拿到的反馈与原方法相同。Gurobi 预求解把模型判为“不可行或无界”时，Worker 关闭对偶约简（`DualReductions=0`）再求解一次，得到确定的状态。

`Sandbox("local")` 用本机子进程运行同一脚本，只用于开发和测试。子进程只继承路径、语言、临时目录和 Gurobi 许可证位置等必要环境变量，不继承 API 密钥。超时或取消后等待子进程退出。

## 步骤记录与推送

`Recorder` 是一次运行在一个节点内的记账：LLM 调用数、求解次数、token、上限和步骤。平台图的每个节点从状态的 `usage` 创建它，因此计数跨节点连续；节点结束时用 `recorder.update()` 写回本节点的步骤和最新计数。

`Recorder.step()` 记录一步（`llm`、`artifact`、`solve` 或 `error`），并立即作为 LangGraph 的 custom 流事件推送 `{"step": ...}`。同一步开始时推送一次（`running: true`），结束时按 `id` 再推送一次。方法不直接记录步骤，也看不到 `Recorder`。

方法图中 `Method.titles` 列出的节点结束时，回调（`graph._NodeSteps`）立即把该节点的更新记为一个 `artifact` 步骤。回调在下一个节点开始前触发，所以步骤顺序与执行顺序一致：一次代码生成的产物总在它的求解之前。

LLM 调用由聊天模型上的回调记录，包括子图和 `create_agent` 智能体中的调用。回调在调用开始时检查上限；模型流式输出时，每 0.25 秒推送一次新写出的文本 `{"delta": {"id", "text", "reasoning"}}`；调用结束时写入输出文本、工具调用、token 数和耗时。方法无需自己记录。

前端用 `runs.create` 创建后台运行，并设置 `streamResumable`。页面无论是刚创建运行还是稍后打开，都用 `runs.joinStream(..., lastEventId: "-1")` 从第一个事件重放，再接上实时事件。运行结束后，页面读取线程状态。

流连接重试失败后，页面重新读取运行状态。运行已结束时展示最终结果；仍在运行或服务器不可达时显示连接错误，并提供“重新连接”。

## 运行记录

运行是 LangGraph 服务器上的一个线程：

| 位置 | 内容 |
|---|---|
| 线程元数据 | 标题、方法、代码写法、服务商与模型名（无密钥）；对比运行的 `group`；用户写的 `note` 和 `tags` |
| 线程状态 | 问题、数据文件、数学模型、代码、求解结果、失败原因、全部步骤、调用统计 |
| 运行（run） | 状态：`pending`、`running`、`success`、`error`、`timeout`、`interrupted`（已停止） |

服务器把线程、运行和检查点保存在 `<workspace>/.langgraph_api/`。内存运行时每 10 秒、以及正常退出时，把内存中的数据写入这些文件（先写临时文件再改名，不会写出半个文件）；进程被强制结束时，最多丢失最近约 10 秒的变化。备份就是复制整个工作区。停止运行时，方法节点被取消，线程状态只保留输入。页面打开已停止的运行时，从服务器保留的流中重放停止前的步骤；服务器重启后，这些步骤不再可得。

## 前端

`frontend/` 是独立的 React 单页应用，只通过 HTTP 与服务器交互：运行、线程和流走 LangGraph 接口（`@langchain/langgraph-sdk`），设置、选项和题库走 `/api/*`。它不导入任何 Python 代码；构建产物输出到 `src/llm4om/server/web_assets/`，随 Python 包发布。

```text
frontend/src/
├── main.tsx        挂载：主题、QueryClient、Tooltip、Toaster、字体与全局样式
├── App.tsx         布局、路由（/、/run/{thread_id} 与 /compare/{group}）、对话框；运行页和对比页按需加载
├── index.css       Tailwind 入口、颜色变量（浅色与深色）、Markdown 与代码高亮样式
├── api.ts          运行、对比、备注与标签、历史，/api 请求
├── sdk.ts          LangGraph 客户端；体积大，首屏之后再加载
├── i18n.ts         t()：中文原文为键，按语言取译文；locales/en.ts 是英文
├── report.ts       一次运行的 Markdown 报告
├── spreadsheet.ts  Excel 工作簿 → 每个工作表一个 CSV
├── format.ts       状态文案、数字、token 与耗时的格式化
├── useRun.ts       一次运行的实时数据：读取线程，并重放与接续流
├── steps.ts        步骤 → 阶段、版本、摘要（纯函数）
├── tables.ts       解的变量分组与矩阵视图、数据文件的 CSV/TSV 解析（纯函数）
├── types.ts        与服务器对应的类型
├── lib/utils.ts    cn()：合并 Tailwind 类名
└── components/
    ├── ui/         shadcn/ui 组件（生成后按需修改）
    ├── Composer    编辑页：问题与数据、运行设置
    ├── RunView     运行页：结论卡、建模过程、产物
    ├── Timeline    建模过程：阶段、LLM 调用、求解输出
    ├── Outputs     产物标签页：解、数学模型、求解代码、问题与数据；版本切换与对比
    ├── Solution    解：分组或列表、二维变量的矩阵视图、CSV 导出
    ├── Content     Markdown、代码、纯文本、差异视图
    ├── Compare     对比页：同一问题的各方法与预设并排
    ├── Sidebar     历史运行（文字与 #标签 筛选）、示例题库与预设模型入口、外观与语言切换
    ├── Examples / PresetsDialog    题库与预设模型对话框
    └── status / theme              状态颜色与图标、主题菜单与 Toaster
```

测试文件 `*.test.ts(x)` 放在被测模块旁边，由 Vitest（jsdom）运行。`frontend/e2e/` 是浏览器测试（Playwright）：它启动脚本化的 OpenAI 兼容服务（`e2e/mock_llm.py`）和使用本机沙箱的 `llm4om serve`，在真实页面上跑运行、对比、不可行诊断、备注与标签、报告导出、Excel 导入和英文界面，不需要密钥和 Docker。

界面文字用中文原文作键（`t("开始建模")`），英文译文在 `locales/en.ts`；`i18n.test.ts` 检查每个键都有译文、占位符一致。服务器给出的方法说明和步骤标题也经过 `t()`。语言默认跟随浏览器，切换后保存在浏览器中。

页面按用户的任务顺序组织：

1. 编辑页左侧写问题、附数据；右侧固定显示建模方法、写法与求解器、LLM，选择直接可见。
2. 运行页先用结论卡回答“得到了什么”（目标值、状态或失败原因），再提供“核对数学模型”和“查看解”。
3. 下方左栏是建模过程，右栏是产物。宽屏下两栏可拖动调整宽度；窄屏下用“结果 / 过程”切换。

| 需要 | 使用 |
|---|---|
| 样式 | Tailwind CSS v4（`@tailwindcss/vite`）、tw-animate-css、`@tailwindcss/typography` |
| 组件 | shadcn/ui（基于 `radix-ui`）：对话框、抽屉、下拉菜单、选择框、单选、标签页、折叠、提示 |
| 主题 | next-themes：浅色、深色、跟随系统 |
| 可调宽度的分栏 | react-resizable-panels |
| 版本对比 | jsdiff（`diffLines`） |
| 字体 | Fontsource：Inter Variable、JetBrains Mono Variable（随构建打包，不访问外网） |
| 服务器数据（选项、设置、运行列表、题库分页） | TanStack Query：缓存、运行中轮询、失效后重取 |
| 运行的实时流 | LangGraph SDK 的 `runs.joinStream` |
| 提示消息 | sonner |
| 图标 | lucide-react |
| Markdown 与公式 | react-markdown、remark-gfm、remark-math、rehype-katex；代码高亮用 highlight.js |

颜色只来自 `index.css` 中 `:root` 与 `.dark` 上的变量；组件不写死颜色值。

## 服务器与安全

`llm4om serve` 以内存运行时启动 `langgraph-api`（与 `langgraph dev` 相同），不需要 LangSmith 许可证。它注册每个方法的平台图，挂载 `server/app.py`，默认监听 `0.0.0.0`，CORS 不允许任何跨源请求。`server/app.py` 的中间件对所有路由（包括 LangGraph 接口）拒绝非 JSON 的 POST，因此其他网站无法借浏览器发起运行或修改预设。

Docker 部署（`Dockerfile`、`compose.yaml`）把服务器放进 `app` 容器，数据放在 `llm4om-data` 卷的 `/data` 中。`app` 通过挂载的宿主机 Docker socket 启动同级沙箱容器；启动脚本 `docker-entrypoint.sh` 采用 socket 的用户组后，以非 root 用户、无 capability 运行服务器，见 [ADR 0011](adr/0011-docker-compose-deployment.md)。

两个可选上限防止共享部署被滥用：`LLM4OM_RUNS_PER_HOUR` 限制每个客户端地址每小时发起的运行数（中间件按 `RUN_STARTS` 匹配发起运行的请求，超过时返回 429）；`LLM4OM_DAILY_TOKENS` 限制每个预设每天的 token（`runtime.TokenBudget`，计数保存在 `.private/token-usage.json`，在每次 LLM 调用前检查）。服务在反向代理之后时设置 `LLM4OM_TRUST_PROXY=1`，按 `X-Forwarded-For` 的最后一项区分客户端。`compose.yaml` 的 `https` profile 用 Caddy 自动申请证书并反向代理到 `app`。

工作台面向信任范围内的小组，不做登录和权限控制：能访问端口的人可以运行、添加和删除页面上的预设、删除运行记录。密钥是唯一的保密边界：它只保存在服务器上，不出现在任何接口响应、线程元数据或运行状态中。见 [ADR 0010](adr/0010-llm-presets.md)。

## 上限

`Limits` 给出每次运行的 LLM 调用数、求解次数、单次求解时限和总时长。超过时方法抛出 `LimitExceeded`，运行记为失败。预设的每日 token 预算用同一个异常停止运行；最后一次调用可能略超预算。
