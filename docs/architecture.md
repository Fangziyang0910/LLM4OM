# 架构

LLM4OM 围绕问题建模、求解和过程记录工作。原工作台和优化对话是并列入口，独立需求对话继续可用。LLM 调用、重试和回调交给 LangChain；图编排、运行、流式推送和持久化交给 LangGraph 及其服务器。平台只保留业务提示、代码目标、求解沙箱、步骤记录和工作台页面。

```text
浏览器（React + @langchain/langgraph-sdk）
   │  threads.create · runs.create（后台运行，可重放的流）· runs.joinStream · threads.get
   ▼
LangGraph 服务器（langgraph-api，内存运行时，数据在 <workspace>/.langgraph_api/）
   │  每个方法注册为一张平台图（server/graphs.py）；/api/* 由 server/app.py 提供
   ▼
平台图：prepare ──► [revise] ──► model ──► solve ──► [explain] ──► finish

prepare：校验问题、写法、方法支持和 LLM 配置
model：method.graph().astream(..., context=Context)
        ├─ runtime.context.llm(role)   → LangChain 聊天模型（流式；回调记录调用）
        ├─ runtime.context.solve(code) → Docker Worker：构建 → 求解
        └─ Method.titles 中节点结束时的更新 → 中间产物步骤
solve：方法没有求解最终代码时，在沙箱中求解一次
```

一次运行分两个阶段：数学建模和代码表达，都在方法图内完成；代码随后在沙箱中运行，得到结果。平台图把“方法”和“最终求解”分成两个节点，方法内部是否交错两个阶段、是否根据求解反馈回到建模，由方法自己决定。

条件调整的 `revise` 和结果解读的 `explain` 位于方法图外。它们复用本次运行的 LLM、预算、步骤和持久化，不改变方法内部编排或提示。

优化对话注册为 `optimization` 图，与 `solution_chat` 共用 `agent.py` 的 LangChain Agent 编排。它允许无原方案启动，使用 `model_and_solve` 把完整题面和当前附件交给任意已注册方法的平台图。`modeling_capabilities` 从既有方法注册表、九个建模库及沙箱原生后端目录读取能力；固定配置优先于工具参数。未指定时为 Direct、Pyomo 和自动后端。后续通过既有查询和场景工具继续讨论。首次建模与条件调整均独立保存结果并在原生会话状态中记录引用；`pending_model` 固定重试请求，已保存方案在最终回复失败后继续可读。

LangChain 工具中间件在每轮允许一次方案变更调用（建模、场景计算或选择已存方案），避免并行调用重复求解或冲突写入当前方案。多个业务场景仍在一次 `solve_scenarios` 调用内计算；选择并修改条件时直接传 `base_plan_id`。查询和表达式计算不受这项限制，其输入错误作为原生错误工具消息返回，供模型在本轮修正。

`chat_prompts.py` 共享自然对话准则，并分别定义建模委托和实际结果使用规则。知识问答、写作、代码解释、资料整理和闲聊不要求进入建模，不改写已有需求或当前方案。`calculate` 用 simpleeval 计算单个数值表达式，不执行 Python 脚本或开放属性访问。普通算术不依赖方案；引用 `v`、`values` 或 `objective` 时读取指定检查点的实际数值，聚合不受提示中前 100 项的限制。表达式、结果及读取的决策值数量保存为工具产物。`lookup_variables` 通过 `next_offset` 分页读取完整变量。

运行时提示词、工具说明和内部代码文本使用英文。回复语言由 `locale` 独立指定为 `Simplified Chinese` 或 `English`；题面、附件、历史消息和生成产物保留各自原语言。用于界面的方法介绍、阶段名称及其他展示文案继续走中英文翻译，双语文档保留。

优化对话的实际步骤通过 `modeling_step` custom 事件推送，包含工具调用 ID、方法、建模库和公开步骤。LLM 步骤仅发送状态，产物携带实际模型与代码；它们在任务卡片与建模工作区显示，不混入 Agent 的回复消息。首个运行在导航前由原生 SDK 创建，新页面及刷新时查询活动 Run 并用 `useStream.joinStream` 连接。入口与产物呈现见 [ADR 0016](adr/0016-optimization-agent.md)。

需求对话独立注册为 `requirements` 图（`START → discuss → END`），不计入建模方法。每轮通过 LangChain `create_agent` 运行原生模型／工具循环，复用预设、`Resources`、`Recorder` 和 token 预算。回复直接流式输出自然文本，`update_draft` 通过 `Command` 更新完整需求稿；原生模型中间件每次读取最新稿件，本轮更新完成后移除工具并转入回复，可选 `web_search` 调用 DeepSeek 独立 Search API。搜索结果和来源放在原生 `ToolMessage.artifact`，凭据仅在工具闭包中。独立搜索密钥绑定独立地址，否则仅 DeepSeek 预设在自身地址使用自身密钥。调用失败保留上一份需求稿、用户消息和已计量用量，重试复用原消息 ID。状态由原生线程和检查点保存。前端用 SDK `useStream` 的原生消息流继续对话（含子图 token）、`threads.updateState` 保存人工改稿；新建空对话用 `threads.create` 的 `graphId` 与 `supersteps` 保存初稿，不调用 LLM。

用户点击“用于建模”后，将 `description + data` 填入现有 Composer，再由用户选择方法并启动新运行。聊天记录、追问和助手判断不作为额外指令注入方法；需求稿没有强制“完整”门槛。边界见 [ADR 0014](adr/0014-requirements-conversation.md)。

方案对话独立注册为 `solution_chat` 图，通过原生检查点固定 `source`、`current` 和已生成方案引用。LangChain Agent 的模型中间件每次加载当前方案的实际题面、模型、代码及结果；`lookup_variables` 查询未完整放入提示的变量，也能读取指定已保存方案的题面、模型、代码、状态、目标和解读，供原方案比较使用。明确修改条件时，`solve_scenarios` 调用进程内 `graph.run(change=...)`，复用原方法、预设、建模库、后端和附件，完成后用原生 `threads.create(supersteps)` 将完整状态保存为独立方案。单个新方案成为当前方案，多个场景共享基准；工具本轮完成后移除，避免反复求解。`run(on_step=...)` 只将实际阶段变化通过工具的原生 `stream_writer` 转成进度，携带工具调用 ID 和场景序号，不推送代码或模型推理。

`select_plan` 只接受当前会话已知的方案 ID，校验后通过 `Command` 更新 `current`，保存实际来源、名称、状态和目标值回执；不改变 `source`，也不重新求解。最终回复失败时仍保留已完成的选择。可用方案按来源去重并标出原方案和当前方案；前端浏览历史仅改变展示，不调用该工具。

进程内平台图不继承对话检查点、进度键或消息流，建模代码不会作为聊天回复推送。计算属于父对话的原生 Run，不在同一任务队列中创建并等待子 Run；仅有一个执行槽时也能完成。派生方案没有单独的 Run 行，页面从已保存的完成时间识别结果。最终回复失败时保存已完成方案引用；重试按原消息 ID 读取本轮已算好的结果。取舍见 [ADR 0015](adr/0015-plan-conversation.md)。

批量计算失败时，`pending` 在原生状态中保留本轮消息 ID、固定基准和完整场景请求；部分完成不改变当前方案。重试使用原请求生成相同方案 ID，复用已保存结果并补完剩余场景。新消息不会被旧请求劫持。两类 Agent 均使用 `ContextEditingMiddleware(ClearToolUsesEdit)`：工具历史超过约 16,000 token 时清理旧工具输入和结果，保留最近三次工具结果；只改写模型请求，线程中的原始消息、来源和稿件不变。当前业务稿或实际方案每次单独注入。

## 模块

`agent.py` 只负责会话图、模型与预算、执行期限，以及将本轮结果写回原生状态。`capabilities.assemble_capabilities()` 按既有对话模式组合原生 LangChain 工具和中间件：方案、计算、建模能力各自维护工具、对应指令和工具可用条件。扩展能力可直接提供 `BaseTool` 或 `AgentMiddleware`，不需要修改会话图。搜索继续使用 `web_search.search_tool()`。

`capabilities.session.Conversation` 只保存本轮共享的方案缓存、已完成操作和待恢复请求。方案操作与首次建模共用每轮一次修改的限制。跨轮数据仍使用原有 LangGraph 状态与检查点；历史状态字段、运行引用和图名称不变。

```text
src/llm4om/
├── __init__.py          公共入口：run、run_problem 及常用类型
├── cli.py               命令行：host、solve、methods、target、backends；可选 serve、run 与 build-worker
├── host/                宿主模型适配、本地方法会话与执行记录，不连接平台 LLM 或 Web 服务
├── method_steps.py      平台与宿主模式共用的方法产物记录
├── languages.py         九个建模库、原生代码契约和 CodeTarget
├── code_prompts.py      官方建模接口的代码参考
├── model_code.py        原生变量、约束、目标和函数组装，供组件式方法复用
├── llm.py               服务商列表、LLMSettings、chat_model()
├── llm_presets.py       预设读写、迁移和环境预设；同一事务内读取并原子替换
├── storage.py           私有 JSON 文件的原子写入，供预设和 token 预算共用
├── budget.py            每个预设的每日 token 预算
├── progress.py          可展示进度的保存、取消时刷新和执行计时
├── sandbox/             沙箱
│   ├── __init__.py      Sandbox（solve、run_script）与 SolveResult
│   ├── worker.py        沙箱内的独立脚本；不导入 llm4om
│   └── worker.Dockerfile
├── runtime.py           运行中的状态：Limits、Recorder（计数、上限、步骤、推送）、方法使用的 Context
├── methods/             建模方法：Method、methods()、各方法的图
│   ├── presets.py       全部方法的参数，每次运行都用这一套
│   ├── direct/          Direct 与 Feedback Repair 共用生成节点和提示，分别编译为图
│   └── <method>/        复杂方法：__init__.py 导出入口，graph.py 编排，提示/解析/搜索各归其位
├── graph.py             平台图 platform_graph(method)、RunState、RunContext、Resources、进程内运行 run()
├── followups.py         完整题面整理、方案与无解解释、实际变量及冲突证据引用校验
├── requirements.py      需求对话图、业务需求稿与 LangChain Agent
├── agent.py             优化与方案对话图、模型和预算、本轮状态提交
├── capabilities/        原生 LangChain 能力装配
│   ├── __init__.py      按对话模式组合工具和中间件
│   ├── session.py       原有会话状态、方案引用、本轮缓存与恢复请求
│   ├── plans.py         方案读取、选择、场景求解及其指令
│   ├── calculation.py   数值计算与可恢复输入错误
│   └── modeling.py      首次建模、能力查询及其指令
├── chat_prompts.py      三类对话共享的表达准则
├── web_search.py        DeepSeek 搜索工具、来源与端点凭据绑定
└── server/              Web 工作台
    ├── graphs.py        各方法的平台图及两种独立对话图，供 LangGraph 服务器注册
    ├── app.py           服务器挂载的路由：选项、预设模型、模型列表、题库、前端页面
    ├── middleware.py    请求格式、运行频率、线程删除及进度清理
    ├── examples.py      内置题库的只读浏览（数据在 examples_data/）
    └── web_assets/      前端构建产物（源码在 frontend/）
```

依赖只朝一个方向：

```text
languages · llm · sandbox  →  runtime  →  methods  →  graph  →  capabilities · requirements  →  agent · server · cli
storage → llm_presets · budget ──────────────────────┘
runtime → progress ─────────────────────────────────┘
```

`languages`、`llm`、`sandbox` 互不依赖。方法只依赖 `runtime`、`languages`、`sandbox` 和 `methods` 本身，不依赖平台图或服务器。`sandbox/worker.py` 在沙箱中独立运行，因此不导入任何平台模块；它按库调用原生接口与插件注册表。`languages.py` 只描述九个库和生成代码的契约，不复制后端插件名单。

## 平台图

| 键 | 内容 |
|---|---|
| 输入 | `description`（问题描述）、`data`（数据文件名到文本）、可选 `change`（条件调整要求） |
| 运行上下文 `RunContext` | `language`、`solver`、`preset`、`explain`、`locale`。只写预设模型的 id，不写密钥，也不能改模型；服务器按 id 读取预设。方法参数固定在 `methods/presets.py` |
| 输出 | `formulation`、`code`、`solve`、`failure`、`steps`、`usage`、`spec`、`timing`；条件调整保存 `revision`，方案解读保存 `explanation`，无解解释保存 `infeasibility`；解释失败保存 `explanation_error` |

图的输入类型 `RunInput` 只开放问题、数据和调整要求，内部结果不能通过输入注入。每次 `prepare` 都清空旧产物、解读、步骤、计数和配置，再建立本次运行状态；同一线程再次运行也遵守这一规则。

有 `change` 时先运行 `revise`，把原题和调整要求保存为 `revision`，整理新题面并交给原方法。调整要求只消费一次，再次运行同一线程不会重复应用。工作台创建独立新线程，元数据 `parent` 记录原线程和检查点 ID；读取基准通过 SDK 原生 `threads.getState(thread, checkpoint)`，不自建版本存储，也不把不同条件混入方法对比组。

工作台设置 `explain=true`，有可用解且建模未失败时执行 `explain`。LLM 返回直接回答原题的摘要、业务标签、单位、补充说明及对实际变量的引用；摘要可以引用实际求解数值，表格和数值字段读取 `solve`，平台校验变量引用。提示要求根据执行代码和数据核对实体映射，无法确认时保留原变量名，不将程序下标直接视为业务编号；这不构成对业务标签或摘要语义的确定性校验。没有统一计算依据的资源剩余量和敏感性指标不补造。解读失败写入独立错误，保留原求解状态。进程内 `run()` / `run_problem()` 可传 `explain=True` 和 `change=...`；默认保留只建模与求解的调用行为。

同一个 `explain` 节点也处理有实际诊断的 `infeasible` 结果。LLM 解释冲突并引用证据 ID；平台校验 ID，再绑定到原始约束字符串。没有冲突证据或只报告局部不可行时不调用。候选调整作为未验证的要求变更展示，点击后填入现有条件调整窗口，不执行代码或修改原状态；用户提交后沿原生检查点关系建立新线程求解。

Excel 导出由 `frontend/src/features/runs/workbook.ts` 完成。工作簿从实际 `solve` 读取完整数值，按精确变量名关联业务标签；使用 `write-excel-file` 按需生成，复用已有下载入口。问题工作表保存完整题面和运行背景，不添加服务器导出端点、额外 LLM 调用或业务模板框架。

`prepare` 发现请求不可用时写入 `failure` 并结束运行，不调用 LLM；有效请求记录内部截止时间 `_deadline` 和不含密钥的 `spec`，包括平台版本、方法来源与参数、限制、LLM 设置、代码写法、求解器和沙箱镜像。`model` 和 `solve` 共享剩余时间，超时、超限或出错时写入一个错误步骤和 `failure`，保留已完成的数学模型和代码。失败后不再补跑最终求解。`finish` 固定 `timing`：从开始校验到结束，不含服务器排队时间，不随备注和标签变化。没有完成计时的记录在对比表中显示未知；中断运行的详情可读取进度快照中的时间。

Web/API 模式的方法图在 `model` 节点内运行，平台不为它保存检查点（`checkpointer = False`）：AutoFormulation 这类方法的内部状态很大，逐步保存的代价高于收益。平台图本身由服务器保存检查点。`progress.save_progress` 在方法执行期间合并公开步骤和产物，每秒至多一次写入原生 Store，取消时立即刷新；不保存内部搜索树或密钥。正常完成后删除临时进度，最终状态成为唯一结果。

方法返回的 `failure` 即使已有代码也会保留，例如 Feedback Repair 达到修正上限但仍有建模问题。后续节点抛出异常时，平台保留已完成的数学模型、代码和对应求解结果。

进程内运行（命令行、测试、`run_problem`）通过 `config["configurable"]["llm4om_resources"]` 传入 `Resources`，替换预设模型、沙箱、上限或聊天模型工厂。服务器从环境变量 `LLM4OM_WORKSPACE`、`LLM4OM_SANDBOX` 读取默认资源。

运行用哪个 LLM 只由 `LLMPresetStore` 决定（`Resources.llm` 给出时除外）。预设列表是 `LLM4OM_LLM_*` 环境变量给出的预设（id 为 `env`），加上 `<workspace>/.private/llm-presets.json` 中按添加顺序保存的预设；第一个是默认预设。预设 `name` 是显示名称，API 始终使用 `settings.model`；旧预设未命名时显示模型 ID。环境预设通过 `LLM4OM_LLM_NAME` 命名，运行快照保存 `preset_name`。`get(preset)` 按 id 取设置，id 不存在时报错并列出可选 id。`prepare` 记录配置，`model` 开始前校验配置仍一致，随后所有角色共享同一份已解析设置。建模过程中删除或替换同名预设不会切换该运行的 LLM。求解和预算扣费不再重新查询预设。

预设只能添加（`add`）和删除（`delete`），没有修改操作；`env` 预设不能删除。新增预设用随机 UUID，不按模型名复用 ID；已有预设保留原 ID。`public()` 返回的预设不含密钥。额外请求参数不能覆盖显式配置字段或调用记录回调。预设读改写由服务内共享锁串行化；先写权限为 600 的临时文件，再原子替换，写入失败保留旧文件。预算文件损坏时报告错误，不把已有用量当成零；后台落盘失败记录错误日志，`flush()` 也会抛出写入异常。一个工作区只供一个服务进程使用，与内存运行时一致。模型列表接口 `/api/models` 只使用请求中填写的密钥，从不补入已保存的密钥，因此密钥只会发往与它一起保存的接口地址。

## 方法接口

宿主模型模式由 `host/` 提供独立执行入口，不经过平台预设解析。`HostChatModel` 通过原生 `interrupt` 把任务交给当前 Agent；回答后原方法图继续解析、路由和执行工具。模型任务、求解与检查脚本以原生 `task` 保存已完成结果。本地 SQLite 检查点保存方法内部状态，执行记录恢复计数、步骤及精确代码对应的求解结果。与 Web 模式相比，逐次交接需要额外保存方法内部状态，取舍见 [0017](adr/0017-host-model-skills.md)。CLI 用法见[宿主建模](host-modeling.md)。

LangGraph 就是平台的方法抽象。每个方法是一张编译好的 LangGraph 图，即使只有一个节点（Direct）。平台不另设阶段、产物或插件接口。

| 约定 | 内容 |
|---|---|
| 状态 | 继承 `ModelingState`。输入 `problem`（问题描述加附件预览）与 `description`（仅题面）；输出 `formulation`、`code`，可选 `solve`（方法自己已求解时）和 `failure`（失败原因） |
| 运行时 | 图以 `context_schema=Context` 编译；节点签名为 `node(state, runtime: Runtime[Context])` |
| 步骤 | `Method.titles` 把节点名映射为步骤标题。只有列出的节点显示为步骤；每次更新渲染为 Markdown（文本原样、`code` 和 `*_code` 为代码块、其他为 JSON） |
| 隐藏 | 以 `_` 开头的状态键、`problem`、`solve`、`messages`、`failure`，以及 `Method.hidden` 中的键，不显示 |
| 上限 | `Method.limits` 覆盖默认上限（AutoFormulation 的搜索需要数千次调用） |
| 写法 | `Method.languages` 声明建模库；原生 API 的选择在代码中表达 |

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
    linear_only: bool = False       # 数学问题范围，与库选择独立
    limits: Limits | None = None
    parameters: Callable[[], dict[str, Any]] = dict  # 返回可 JSON 序列化的固定参数快照
```

| `Context` 成员 | 用途 |
|---|---|
| `data` | 数据文件名到文本内容；问题全文在状态的 `problem` 中 |
| `target.language` | 所选九个建模库之一；OR-Tools 的规范 ID 为 `ortools` |
| `target.solver` | 原生后端标识，默认 AUTO |
| `target.prompt` | 所选写法的代码契约，直接拼接到生成代码的提示中 |
| `target.library` | 代码所用的库名（`Pyomo`、`Gurobi`、`OR-Tools` 等九个库），用于替换原提示中写死的库名 |
| `llm(role)` | 配置好的 LangChain 聊天模型。`role` 写入调用元数据，用于在过程列表中命名调用 |
| `solve(code, title)` | 在沙箱中构建并求解，返回 `SolveResult`；`feedback()` 给出可交给 LLM 的文本 |
| `run_script(script)` | 在沙箱中把脚本作为 `__main__` 运行，返回标准输出和异常栈。不计入求解次数，但共用沙箱并发额度。供原方法自己的检查脚本使用 |
| `solves` | 本次运行到目前为止的求解次数 |

方法图结束后，平台图取最终状态的代码，只从 `Context.solved` 读取这份代码实际执行过的结果。新版代码尚未执行就中断时，不关联上一版的解；旧结果仍在过程步骤中。没有失败且最终代码尚未执行时，`solve` 节点求解一次。

新方法放在 `methods/` 并加入 `methods()`，或在其他包中注册 `llm4om.methods` 入口点。简单方法保留单文件；复杂方法的包入口只导出方法对象与图工厂。AutoFormulation 的候选节点、UCT 和排名归入 `search.py`；CoE 的专家提示和输出解析分别放在 `prompts.py`、`parsing.py`。图节点只组织执行，上游提示与研究流程不变。平台在准备运行时调用 `Method.parameters()` 记录参数，不根据方法 ID 猜测 `presets.py` 中的变量名；无参数的方法默认返回空字典。

## 可插拔的代码提示

生成代码的提示在方法调用处组装，13 个内置方法均可选择九个库：

- `CodeTarget.prompt` 统一提供库的原生 API 参考、返回类型和可选后端要求。整段代码生成方法把它嵌入原提示，替换写死的库名，不改建模和修正流程。
- CoE 的代码示例直接使用同一份原生参考，不另建空模型模板；避免指定 CP-SAT 时，示例仍初始化 MPSolver。OptiMUS 的整段调试也嵌入完整契约。
- OptiMUS、SAC-Opt、AutoFormulation 生成组件或表达式。`ModelCode` 提供同一套原生变量声明、约束、目标和 `build_model(data)` 组装；对应组件提示也由这些代码片段生成。它没有引入模型中间表示，也不在库之间翻译模型。
- 索引变量使用标量或元组键的字典。变量类型、上下界保留数学含义；CPMpy/CP-SAT 的整数边界必须由问题推导，不补造大数，不把连续变量改成整数或把整数放松为连续变量。CasADi 整数域用 `set_domain` 和 Bonmin，最大化的符号在结果中恢复。
- `Method.linear_only` 描述 LP/MILP 问题范围。它不限制建模库。`Method.languages` 留给外部方法声明确有必要的库限制；内置方法不使用该白名单。

## 代码契约

数学建模与代码生成仍在方法图中完成。只选择建模库与可选后端。Worker 自动识别原生模型类型；同一模型的标量、矩阵等写法共用求解入口。原生 API 与返回类型见[接口清单](references/modeling-libraries.md)。

`build_model(data)` 只构建原生模型。需要端点、变量集合或底层符号/数值输入的接口返回规定的字典。Worker 调用所选原生后端，不跨库翻译数学模型。MPSolver 自身绑定后端，所以使用其原生 protobuf 在该接口内部转入指定引擎，并拒绝把整数模型交给 LP 引擎求连续松弛。

`CodeTarget` 负责库与原生 API 代码契约；后端名单由执行环境的原生注册表提供。组件组装复用 `ModelCode`，不再按方法维护四种方言表。

CPMpy 和原生 CP 接口允许无目标的可满足性模型，成功时保存变量但目标值为空。CVXPY AUTO 走原生 solver_path，并把真正使用的引擎写入 SolveResult.solver；显式后端不会自动替换。Routing 启发式结果是 feasible，非凸 NLP 的局部结果使用 locally_optimal/locally_infeasible。原生接口的安装、模型兼容性和商业许可分别对待。

## 沙箱

`Sandbox.solve(code, data, language, time_limit, solver=...)` 构建并求解模型；`run_script` 运行方法的检查脚本；`catalog` 在同一执行环境读取并缓存后端能力。外层超时比求解时限多 60 秒，用于启动沙箱、导入库和构建模型。请求格式和结果标记只在 `sandbox/` 内部使用。所有运行共享服务的 Sandbox，`solve` 和 `run_script` 共用并发额度，默认最多 4 个，由 `LLM4OM_SANDBOX_JOBS` 设置。排队仍计入运行总时限，单次沙箱超时从取得额度后开始。`--jobs` 单独控制并发运行数。

`Sandbox("docker")` 在镜像 `llm4om-worker:12` 中运行 Worker：无网络、只读根文件系统、`tmpfs` 工作目录、去除全部 capability、非 root 用户。`worker.py` 构建进镜像，不在运行时挂载，因此平台本身在容器中运行时也能使用；修改 `worker.py` 或 `worker.Dockerfile` 时要同时更新镜像标签（`WORKER_IMAGE` 与 `compose.yaml`）。`docker run` 只使用本地镜像（`--pull never`）。设置了 `GRB_LICENSE_FILE`、`MOSEKLM_LICENSE_FILE` 或 `COPT_LICENSE_DIR` 时只读挂载对应许可证文件；不挂载 COPT 整个目录。超时或取消时等待 `docker rm --force` 完成，确保容器已删除才释放并发额度。

求解状态为 `infeasible` 时，Worker 在同一次运行中找出一组互相冲突的约束，写入 `SolveResult.diagnosis`（`tool`、`items`、`total`、`error`）：线性模型写成 LP 文件后由 Gurobi 计算 IIS（无许可证时只适用于小模型），CPMpy 模型用 CPMpy 的 MUS，CVXPY 模型不诊断。诊断限时 20 秒，最多列出 60 条。`feedback()` 不包含诊断，已移植的研究方法继续使用原反馈；本项目的 Feedback Repair 单独读取诊断，用于对照题面复核。Gurobi 预求解把模型判为“不可行或无界”时，Worker 关闭对偶约简（`DualReductions=0`）再求解一次，得到确定的状态。

`Sandbox("local")` 用本机子进程运行同一脚本，只用于开发和测试。子进程只继承路径、语言、临时目录和 Gurobi 许可证位置等必要环境变量，不继承 API 密钥。超时或取消后等待子进程退出。

求解结果保留所有变量；前端按需显示更多、按完整数据筛选和导出 CSV。给 LLM 的反馈仍只展示有限的非零变量，保持原方法的反馈格式。

## 步骤记录与推送

`Recorder` 是一次运行在一个节点内的记账：LLM 调用数、求解次数、token、上限和步骤。平台图的每个节点从状态的 `usage` 创建它，因此计数跨节点连续；节点结束时用 `recorder.update()` 写回本节点的步骤和最新计数。

`Recorder.step()` 记录一步（`llm`、`artifact`、`solve` 或 `error`），并立即作为 LangGraph 的 custom 流事件推送 `{"step": ...}`。同一步开始时推送一次（`running: true`），结束时按 `id` 再推送一次。方法无需直接记录步骤。

方法图中 `Method.titles` 列出的节点结束时，回调（`graph._NodeSteps`）立即把该节点的更新记为一个 `artifact` 步骤。回调在下一个节点开始前触发，所以步骤顺序与执行顺序一致：一次代码生成的产物总在它的求解之前。

LLM 调用由聊天模型上的回调记录，包括子图和 `create_agent` 智能体中的调用。回调在调用开始时检查上限；模型流式输出时，最多每 0.05 秒推送一次新写出的文本 `{"delta": {"id", "text", "reasoning"}}`；调用结束时写入输出文本、工具调用、token 数和耗时。方法无需自己记录。

前端用 `runs.create` 创建后台运行，并设置 `streamResumable`。页面无论是刚创建运行还是稍后打开，都用 `runs.joinStream(..., lastEventId: "-1")` 从第一个事件重放，再接上实时事件。运行结束后，页面读取线程状态。

流连接重试失败后，页面重新读取运行状态。运行已结束时展示最终结果；仍在运行或服务器不可达时显示连接错误，并提供“重新连接”。

## 运行记录

运行是 LangGraph 服务器上的一个线程：

| 位置 | 内容 |
|---|---|
| 线程元数据 | 标题、方法、代码写法、服务商与模型名（无密钥）；对比运行的 `group`；用户写的 `note` 和 `tags` |
| 线程状态 | 问题、数据文件、数学模型、代码、求解结果、失败原因、全部步骤、调用统计、固定配置和执行时间 |
| Store 的 `("llm4om", "progress")` / thread id | 运行中和中断后的公开步骤、产物、配置与时间；服务端删除线程时一并清理 |
| 运行（run） | 状态：`pending`、`running`、`success`、`error`、`timeout`、`interrupted`（已停止） |

服务器把线程、运行、Store 和检查点保存在 `<workspace>/.langgraph_api/`。内存运行时每 10 秒、以及正常退出时，把内存中的数据写入这些文件（先写临时文件再改名，不会写出半个文件）；进程被强制结束时，可能丢失最近约 10 秒的已写入 Store 的变化，加上最多约 1 秒的进度合并间隔。备份就是复制整个工作区。停止运行时，方法节点被取消，公开进度刷新到 Store；页面将它合并到线程状态，重启后仍可查看已保存的步骤和产物。旧版本中断记录没有这份快照时，只能尝试重放尚未过期的流。保存进度不等于恢复方法内部执行。

`ThreadCleanup` 使用原生 SDK 处理线程删除生命周期：对 `DELETE /threads/{id}` 和删除策略的 `POST /threads/prune`，先取消并等待正在排队或执行的运行，再交给原生接口删除线程，成功响应前清理进度。清理失败时保留失败响应；单个线程已不存在的删除重试仍清理剩余进度。客户端只需删除线程。这使用服务器的[自定义中间件](https://docs.langchain.com/langsmith/custom-middleware)，没有替代原生线程存储。

## 前端

`frontend/` 是独立的 React 单页应用，只通过 HTTP 与服务器交互：运行、线程和流走 LangGraph 接口（`@langchain/langgraph-sdk`），设置、选项和题库走 `/api/*`。它不导入任何 Python 代码；构建产物输出到 `src/llm4om/server/web_assets/`，随 Python 包发布。

```text
frontend/src/
├── main.tsx / App.tsx   挂载、路由、布局和跨功能组合
├── api.ts / types.ts   普通 JSON HTTP 请求和共享选项/预设类型
├── i18n.ts / locales/  中英文文本
├── format.ts          状态、数字和用时的展示
├── features/
│   ├── composer/      Composer、ProblemEditor、DataEditor、Examples、Excel 导入、Draft 类型及测试
│   ├── chat/          三类对话共用的消息渲染、输入、模型选择、滚动跟随和标签页内的未发送草稿
│   ├── presets/       PresetsDialog
│   ├── requirements/  需求对话、可编辑需求稿、原生线程创建与交接
│   ├── solution_chat/ 方案对话、固定方案读取与独立方案导航
│   └── runs/          RunView、Compare、Outputs、Solution、Timeline、状态图标
│                      Explanation、Infeasibility、RevisionDialog、ScenarioComparison、ScenariosDialog、ScenarioResults
│                      api、sdk、useRun、history、types、steps、tables、report、workbook 及相邻测试
├── components/        Sidebar、Content、PageErrorBoundary、theme 等共享界面
│   └── ui/            shadcn/ui 组件
└── lib/                utils.ts 合并 Tailwind 类名；csv.ts 统一 CSV/TSV 无损文本解析与转义
```

测试文件 `*.test.ts(x)` 放在被测模块旁边，由 Vitest 运行（界面使用 jsdom，Excel 写入与回读使用 Node）。`frontend/e2e/` 是浏览器测试（Playwright）：它启动脚本化的 OpenAI 兼容服务（`e2e/mock_llm.py`）和使用本机沙箱的 `llm4om serve`，在真实页面上跑运行、对比、无解解释及调整、备注与标签、报告导出、Excel 导入导出和英文界面，不需要密钥和 Docker。`tests/test_server_restart.py` 另验证真实服务正常退出后，重启仍能读取中断前的步骤与产物。

聊天消息中的工具结果由 `features/chat/results.tsx` 按 `ToolMessage.artifact.type` 注册展示，支持 `draft`、`selected_plan`、`calculation`、`plans` 和 `search`。新工具返回已有产物类型即可复用相同展示。产物保留原字段，历史消息缺少类型时按原工具名匹配；未知类型不误用其他展示。错误仍由通用消息层呈现，方案数值与来源链接继续取自实际工具产物。

历史列表使用 TanStack `useInfiniteQuery` 和原生 `threads.search(offset, limit)`，每页 100 条，可加载更早的记录。文字搜索作用于已加载记录，尚有未加载记录时明确显示范围。对比最多 12 次运行；耗时来自 `values.timing.elapsed`，不用可修改的线程更新时间。历史和详情共用 `runMeta()`：实际执行配置取 `spec`，备注和标签取线程元数据；旧记录没有 `spec` 时继续使用元数据。

界面文字用中文原文作键（`t("开始建模")`），英文译文在 `locales/en.ts`；`i18n.test.ts` 检查每个键都有译文、占位符一致。服务器给出的方法说明和步骤标题也经过 `t()`。语言默认跟随浏览器，切换后保存在浏览器中。

页面按用户的任务顺序组织：

1. 编辑页用 `ProblemEditor` 管理编辑、Markdown 预览和附件展示，`Composer` 管理草稿、文件读取及运行设置。问题占据主区域，配置摘要打开原有完整设置；底部建模操作常驻。`Requirements` 通过编辑器和助手插槽复用同一个 `Composer`，提交建模前等待原生需求稿保存队列。
2. 运行页先用结论卡回答“得到了什么”（目标值、状态或失败原因），再提供“核对数学模型”和“查看解”。
3. 运行中展开建模过程与产物分栏；完成后默认收起过程，保留显式展开入口。`SolutionChat` 在结果旁显示对话，通过 `renderRun` 插槽复用完整 `RunView`；查看其他方案与对话的当前基准分开保存，不改写原生图状态。

电脑端以数学模型、代码和求解结果为主要内容。运行、Agent 与方案对话的分栏保存与恢复直接使用 `react-resizable-panels.useDefaultLayout`，只保存用户操作造成的变化；不另外维护布局格式。共享 `useDesktop` 读取同一桌面断点。运行头部收拢低频操作和技术信息，结果下方集中放置条件调整、业务场景和可选对话；业务解读下折叠完整变量，避免重复统计。三类对话通过 `use-stick-to-bottom` 处理内容重排与用户上翻；共享滚动钩子补充视口尺寸变化的观察，仅在仍跟随时滚到底部。问题编辑区在 Markdown 预览期间保留 textarea，保留选区和滚动位置；隐藏的预览不持续渲染。

历史的 `groupHistory()` 只根据原生元数据的 `parent`、`group` 和 `origin` 归并记录，不按题名猜测关联。`origin` 是需求稿交接、复制编辑或重复运行的来源线程 ID，仅用于追踪，不进入建模输入。原记录不迁移，各线程仍独立保存和删除；历史分页未加载来源时仍可展示关联子记录。

两类对话共用 `ChatInput` 和 `useChatDraft`：未发送文字只存入标签页的 `sessionStorage`，按线程区分。消息使用 LangChain 自带的 UUID v7，通过 `getRandomValues` 兼容 HTTP；浏览器暂存提交标记，收到根图的原生输入检查点后才清除对应文本，保留后来起草的文字。刷新时也可用原生线程快照确认保存，不能用乐观消息作为持久化依据。回复期间允许起草，但下一次发送仍受原生运行状态限制。导航搜索状态由 App 持有，抽屉关闭或布局变化不重置。懒加载页面失败由 React 错误边界保留导航并提供重载；服务数据失败就地重试，不创建额外运行。

`ChatMessages` 统一呈现工具执行、取消与失败重试。搜索来源与计算卡片仅读取实际 `ToolMessage.artifact`；来源按需展开，计算卡片跳转到已保存方案。停止通过 SDK `runs.cancel(wait=true)` 等待服务端中断，若尚未确认输入检查点，先通过 `threads.updateState` 按原消息 ID 保存已提交问题，再停止本地流；重试复用原用户消息，未发送草稿保持不变。刷新通过 SDK 的原生可恢复流重连，不创建另一个运行。

依赖锁文件合并同版本的 Radix 内部包，使抽屉、菜单和选择器共用焦点与弹层状态；不通过重置页面样式或取消焦点管理来绕过嵌套弹窗问题。

`Explanation` 将业务标签与实际求解数值组合。`RevisionDialog` 收集调整要求；`startRevision()` 从原生检查点读取题面、附件和固定配置，发起新线程。`ScenarioComparison` 读取该检查点，按实际数值比较目标和同名变量；变量缺失与零值保持区分。Markdown 报告同时包含解读、调整要求和原题。

`ScenariosDialog` 收集 2 至 6 项业务变化，`startScenarios()` 只读取一次基准检查点，创建独立原生运行并用 `group` 关联。`ScenarioResults` 读取实际状态，展示固定基准、目标与同名变量；不将业务条件差异解释为多方法不一致。部分启动失败时保留已启动记录。方案对话生成的多场景也使用同一元数据与展示。

`DataEditor` 在本地保留未保存文本，CSV/TSV 每页 50 行、超过 50 列用原文编辑；不把字符串转换为数值。保存校验文件大小、CSV 引号和 JSON 语法，成功后才更新附件；需求稿通过原生 `threads.updateState` 保存。需求稿自动保存只处理实际编辑区的失焦，忽略 React portal 弹窗的焦点事件。已经运行的附件快照不随草稿编辑变化。

各页共用最大 1600 像素的内容宽度。导航在 1280 像素以上常驻；编辑页在 1024 像素以上按需并排显示主要内容与助手，窄窗口使用页签。长题面、方法列表和短屏设置使用各自的滚动区域，不把开始按钮推到屏外。

问题预览和运行题面共用 `Content.Markdown`，只渲染原文，不改变提交内容。题面关闭单美元符号公式，避免价格被当成数学表达式；显式公式分隔符继续支持。生成的数学模型和建模步骤保留原有公式语法。

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
| Markdown 与公式 | react-markdown、remark-gfm、remark-math、rehype-katex；mdast-util-from-markdown 标识公式转换需跳过的代码；代码高亮用 highlight.js |

颜色只来自 `index.css` 中 `:root` 与 `.dark` 上的变量；组件不写死颜色值。

## 服务器与安全

`llm4om serve` 以内存运行时启动 `langgraph-api`（与 `langgraph dev` 相同），不需要 LangSmith 许可证。它注册每个方法的平台图，挂载 `server/app.py`，默认监听 `0.0.0.0`，CORS 不允许任何跨源请求。`server/middleware.py` 对所有路由（包括 LangGraph 接口）拒绝非 JSON 的 POST，因此其他网站无法借浏览器发起运行或修改预设。

Docker 部署（`Dockerfile`、`compose.yaml`）把服务器放进 `app` 容器，数据放在 `llm4om-data` 卷的 `/data` 中。`app` 通过挂载的宿主机 Docker socket 启动同级沙箱容器；启动脚本 `docker-entrypoint.sh` 采用 socket 的用户组后，以非 root 用户、无 capability 运行服务器，见 [ADR 0011](adr/0011-docker-compose-deployment.md)。

两个可选上限防止共享部署被滥用：`LLM4OM_RUNS_PER_HOUR` 限制每个客户端地址每小时发起的运行数（中间件按 `RUN_STARTS` 匹配发起运行的请求，批量请求按数组中的运行数计费，整批超限返回 429）；`LLM4OM_DAILY_TOKENS` 限制每个预设每天的 token（`budget.TokenBudget`，计数保存在 `.private/token-usage.json`，在每次 LLM 调用前检查）。服务在反向代理之后时设置 `LLM4OM_TRUST_PROXY=1`，按 `X-Forwarded-For` 的最后一项区分客户端。`compose.yaml` 的 `https` profile 用 Caddy 自动申请证书并反向代理到 `app`。

工作台面向信任范围内的小组，不做登录和权限控制：能访问端口的人可以运行、添加和删除页面上的预设、删除运行记录。密钥是唯一的保密边界：它只保存在服务器上，不出现在任何接口响应、线程元数据或运行状态中。见 [ADR 0010](adr/0010-llm-presets.md)。

## 上限

`Limits` 给出每次运行的 LLM 调用数、求解次数、单次求解时限和总时长。超过时方法抛出 `LimitExceeded`，运行记为失败。预设的每日 token 预算用同一个异常停止运行；最后一次调用可能略超预算。


## 新方法的数据边界

`ModelingState.description` 保留不含附件预览的题面；`problem` 保留现有题面加预览语义。BIND 只读取前者与完整附件的结构，避免先拼接长数据再从字符串剥离。其他方法继续使用 `problem`。完整附件始终从 `Context.data` 传入沙箱的 `build_model(data)`。

SAC-Opt 在图状态中保留原约束、组件、回译、逐项比较和已通过标志。回译不读取原约束；已通过组件不进入下一轮修正。最终语义未通过仍保留求解结果和失败标记。OptiMind 的发布提示在包内固定存储；分类只选择这些类型，执行反馈不含基准真值。
