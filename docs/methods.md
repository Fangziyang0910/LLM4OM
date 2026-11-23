# 建模方法

方法负责建模流程：调用 LLM、输出中间产物、请求求解、根据反馈修正。平台提供 LLM、代码契约和求解沙箱。接口见[架构](architecture.md#方法接口)。

每个方法都是一张 LangGraph 图，即使只有一个节点。前 8 个精确建模方法开放 Pyomo、OR-Tools、CVXPY、PySCIPOpt、CasADi 五个建模库；第 9 个方法 AutoCO 为内置求解器方法（`languages=frozenset()`），自带 12 类启发式与进化算法池并在隔离沙箱中完成代码体检、短时试跑与正式求解。代码提示和组件组装共享库指引，库内 API 由代码表达，平台识别原生模型。OptiMUS、CoE、OptiTree、OR-LLM-Agent 保留 LP/MILP 建模范围；它与库选择独立。所选库及后端仍须能够表达并求解该数学问题。

## 方法一览

| id | 名称 | 图 | 预设参数 |
|---|---|---|---|
| `direct` | Direct | `generate`；校验数学模型与代码均存在，平台求解最终代码 | — |
| `or_llm_agent` | OR-LLM-Agent | `math_model → write_code → execute →（fix → execute）* → end_round`，再按结果做一轮不可行检查或模型复查 | `temperature`=0.2；主轮 3 次、不可行检查 1 次、复查 2 次（`attempts`） |
| `llmopt` | LLMOPT | `define → write_code → execute →（self_correct →（define 或 write_code）→ execute）*`；五要素模型 → 代码 → 执行，LLM 分别判断模型和代码对错，回到错的一步重写 | `max_resolves`=12 |
| `trival` | TriVAL | 语义验证 → 数学模型验证 → 代码验证；每阶段构建、验证、修订；代码缺陷可回溯到数学模型 | 每阶段最多验证 5 轮（`max_validations`），代码最多执行 20 次（`max_code_executions`） |
| `bind` | BIND | schema → 生成 → 求解 → 错误反馈修正 | `temperature`=0、`top_p`=1、`max_rounds`=3 |
| `autoco` | AutoCO | `semantic_grounding → formulate ⇄ review_formulation → instantiate（沙箱体检）→ select_algorithm（知识图谱 + 沙箱试跑）→ solve_problem` | `max_modeling_revisions`=1、`max_instantiate_attempts`=3、`max_kg_steps`=6、`enable_pilot`=true、`seed`=42 |
| `optitree` | OptiTree | `classify*（逐层匹配问题类型）→ retrieve → reason → execute →（inspect → execute）*`，最多检查 4 次 | `temperature`=0、`max_inspections`=4 |
| `coe` | Chain-of-Experts | `start_trial → conductor ⇄ expert → reducer →（evaluate → backward）→ finish`；协调者逐个选专家，专家依次评论，汇总器写代码；开启反思时，代码出错则从最后一位专家向前询问责任 | `temperature`=0、`max_collaborate_nums`=3、`enable_reflection`=false、`max_trials`=3 |
| `optimus` | OptiMUS 0.3 | `parameters → objective → constraints → check_constraints → formulate_constraints → formulate_objective → write_code → assemble → execute →（debug → use_fix → execute）*`，最多 3 次执行 | `temperature`=1.0、`max_debug_tries`=3 |

参数全部集中在 [`src/llm4om/methods/presets.py`](../src/llm4om/methods/presets.py)，每个方法一个不可变的 dataclass。移植方法的取值依据上游固定提交，部署适配差异另行说明。运行时不能改参数：命令行、Python 接口和页面都不接受方法参数；要换参数，改这个文件。

各方法通过 `Method.parameters()` 声明运行记录中的参数快照。复杂方法的图在 `graph.py`，提示、解析和搜索按职责分开；包入口只导出方法对象与图工厂。CoE 的提示和解析分别位于 `coe/prompts.py` 与 `coe/parsing.py`，移动保留原文和逻辑。

共享代码契约要求保留题意中的变量域、决策单位和约束方向。后端不能表达或求解所需模型时，生成代码应明确报告不兼容，不得通过放松整数域、改动等式或事后取整来适配后端。Worker 也会拒绝将已声明整数变量的 OR-Tools 模型交给连续后端。生成提示不能证明原题已被正确建模，数量是否可分仍应在需求和数学模型中明确。

8 种精确建模方法的运行上下文接收 `locale`，与选择建模库的 `language` 分开。`zh` 要求说明正文使用简体中文，`en` 使用英文。语言要求追加在各方法原有的消息或代理系统提示中，不改变研究流程、温度、搜索参数或停止条件。BIND 和 OR-LLM-Agent 在初始系统消息中追加一次，使后续历史继续沿用；其余独立调用分别追加。TriVAL 的语义、数学模型及代码验证代理均传递该要求。

五要素固定标题、判断行、代码围栏标签、JSON 键及枚举值、分类名称、工具标识和数据仍按原协议保留，说明性字段可使用所选语言。数学模型页面、阅读对照和方法过程产物仅在显示时翻译已知标题、状态标签和专家名称；步骤关联仍使用原始角色标识，未知扩展名称保持原文。JSON、代码、原始运行记录、文本差异、复制和下载保留生成原文。已有记录的正文不会因切换界面语言而重新生成，语言要求也不能保证模型每次均遵守，需结合真实运行检查。

## Direct

该方法由本项目维护，位于 `methods/direct/`。Direct 保留一次 LLM 调用：明确变量域、目标方向、单位、索引、数据来源和每条约束，输出数学模型和完整代码。格式不完整时报告失败，不把空代码交给求解器。附件预览可能截断，代码通过 `build_model(data)` 读取完整数据。

## 固定来源与实现方式

既有研究方法的核心建模逻辑忠实移植：编排、提示、解析和停止条件来自上游。BIND 的部署适配另见文末，不将其描述为逐字移植。目标不是逐行复刻上游的工程代码（文件输出、日志、命令行），而是让建模过程与上游一致。改动只有三类：

- **适配**：接入平台所必需，例如由平台提供 LLM、在沙箱中执行、按代码写法替换库名。
- **避错**：避免明显的运行失败，不改变机制。
- **修正**：上游代码与自身逻辑明显矛盾时才做，并单独列出。

论文与代码冲突时，以代码为准。每条改动在下文和源码中（`llm4om:` 注释）记录。

| 方法 | 固定来源 | 实现方式 |
|---|---|---|
| TriVAL | [SCUT-EIPI/TriVAL@380a529](https://github.com/SCUT-EIPI/TriVAL/tree/380a529) | 移植原 LangGraph 图、节点、提示和循环上限 |
| OptiMUS 0.3 | [teshnizi/OptiMUS@e182e9e](https://github.com/teshnizi/OptiMUS/tree/e182e9ef5841605c2a7e87467021fd83522b6484) | 上游 README 标注为 v0.3；`main.py` 流程改写为图；提示逐字提取（`optimus/prompts.py`，MIT）；保留上游输出格式并强化解析/格式重试；代码示例按库组装（`optimus/graph.py`），共享原生代码生成（`model_code.py`） |
| CoE | [xzymustbexzy/Chain-of-Experts@afb89bf](https://github.com/xzymustbexzy/Chain-of-Experts/tree/afb89bf602690ea621f13a23c42722f20f653a43) | `main.py` 的 `chain_of_experts` 改写为图；七位专家、协调者和汇总器的提示逐字保留 |
| OptiTree | [MIRALab-USTC/OptiTree@2e70ecf](https://github.com/MIRALab-USTC/OptiTree/tree/2e70ecfd0a3c8e9c0c16d36d7d498a7344cfdec9) | `Reasoner.reason_run` 改写为图；分类、推理、检查三组提示逐字提取（`optitree/prompts.py`）；随包分发原问题类型树和思路模板（`optitree/source/`，MIT） |
| OR-LLM-Agent | [bwz96sco/or_llm_agent@5dccdaa](https://github.com/bwz96sco/or_llm_agent/tree/5dccdaab89ab91c3cb28066fe849423dc124d287) | `or_llm_eval.py` 的 `or_llm_agent` 改写为图；提示逐字保留，代码请求改为平台契约 |
| LLMOPT | [antgroup/LLMOPT@1492dd3](https://github.com/antgroup/LLMOPT/tree/1492dd33e39ea13f1afe32a0adc13d4217334195) | `inference/inference_q2f2c.py` 的 Q2F → F2C → 执行改写为图，加上论文的自我校正循环；`prompts/generate_prompt.py` 与 `prompts/self_correction_prompt.py` 逐字收录（`llmopt/prompts.py`）。论文见 [ICLR 2025](https://arxiv.org/abs/2410.13213) |

这些实现使用你配置的通用 LLM，没有复现论文的模型、数据或运行条件。采样温度沿用上游：OR-LLM-Agent 0.2；CoE 0（协调者 `max_tokens=10`）；OptiTree 0；OptiMUS 上游不设温度，这里用 OpenAI 默认值 1.0。

### TriVAL

详细说明见 [`methods/trival/README.md`](../src/llm4om/methods/trival/README.md)。

| 改动 | 类型 | 原因 |
|---|---|---|
| 各节点通过 `context.llm("trival.<节点>")` 取得模型 | 适配 | LLM 由平台配置 |
| `code_executor` 改为调用 `context.solve()` | 适配 | 代码在平台沙箱中构建和求解 |
| 代码智能体提示中的求解器选择和 OR-Tools/CP-SAT/CVXPY 语法段落，替换为平台代码契约 | 适配 | 代码写法由用户选择 |
| 代码验证提示删去“代码是否打印可解释的求解结果”一条 | 适配 | 平台契约要求代码只构建模型，结果由 Worker 输出 |
| `messages[-1].content` 改为 `.text` | 避错 | Anthropic 等模型返回分块内容 |
| agent 节点和多工具编辑中间件使用异步调用；工具声明 `ToolRuntime[ContextSchema]` | 避错 | 取消可沿调用链传播；工具上下文按实际类型序列化，无需全局屏蔽警告 |
| `code_agent` 生成代码后清除入口预设的“未生成代码”失败标记 | 避错 | 平台保留方法的显式失败，成功路径不能携带过期失败标记；不改变验证和路由 |
| 出口节点汇报仍未通过的语义、数学模型或代码验证，并保留实际产物与求解结果 | 适配 | 达到验证上限不等于验证通过；不改变上游的修复路线和阶段上限 |

TriVAL 的三阶段验证器通过普通结构化工具提交原有验证结果，不强制 `tool_choice`。模型、接口与思考参数沿用运行预设；使用支持工具调用的模型即可，不需要为 TriVAL 单独关闭思考。验证阶段、修订路由与循环上限保持不变。

### OptiMUS 0.3

当前固定提交已采用 [OptiMUS v0.3](https://arxiv.org/abs/2407.19633)，不是待新增方法。界面显示版本，方法 id 仍为 `optimus`。

上游 `main.py` 的流程（`ERROR_CORRECTION=True`，不启用 RAG）：目标 → 约束（冗余检查 k=5、每条约束置信度检查 k=5）→ 约束公式 → 目标公式 → 逐条代码 → 确定性组装 → 执行与调试（最多 3 次）。

| 改动 | 类型 | 原因 |
|---|---|---|
| 上游从 `params.json` 读取参数和取值。附带同格式 `params.json` 时照此使用；否则运行上游的参数提取提示，并在输出格式中加一个 `value` 字段 | 适配 | 平台输入是自然语言，参数取值必须来自题面 |
| 保留上游建模提示；代码提示嵌入共享库指引和原生示例。变量、约束、目标、返回对象通过 `ModelCode` 组装，支持五个库 | 适配 | 代码写法由用户选择 |
| 整段调试提示也嵌入所选库与后端的完整代码契约 | 适配 | 调试调用独立于组件生成，仍需知道 `build_model(data)` 的返回类型和只构建不求解的约定 |
| 组装结果包装为 `build_model(data)`，参数取值写入代码；删去 `model.optimize()` 和结果打印 | 适配 | 平台契约只构建模型 |
| 约束检查走上游的 `ask_LLM` 分支；参数的人工确认（`input()`）不执行 | 适配 | 平台运行没有人工交互；上游 `main.py` 本身也不运行参数提取 |
| 解析时把五个以上连续的 `=` 视为一个 `=====` 分隔符 | 避错 | 上游在 `=======` 内部找到“闭合”分隔符，取出空代码。DeepSeek 实测这样写，目标函数代码因此丢失，模型以目标值 0 “最优”结束 |
| 读取分隔符内的全文，不额外跳过首字符；只删除代码块开头的语言标签 | 避错 | 分隔符后没有换行时首字符丢失；全局删除 `python` 会破坏变量名和字符串 |
| 缺少完整分隔符或 Python 代码块时报解析错误 | 避错 | 不再用负索引截取无效代码 |
| 回复没有 `=====` 分隔符时，代码读取最后一个完整 Markdown 代码块；目标与目标公式支持 Markdown 围栏、`OBJECTIVE:` 行或闭合 LaTeX 分隔符回退 | 避错 | 模型常省略 `=====` 或先写片段再写完整语句 |
| JSON 对象和数组按顶层配对边界解析，清理字符串外行注释并在未转义 LaTeX/尾逗号等情况下调用 `json_repair`；约束公式支持键名大小写归一及可选字段（`NEW VARIABLES`、`AUXILIARY CONSTRAINTS`）缺省 | 避错 | 解决通用 LLM 在 JSON 中漏转义 LaTeX 反斜杠或省略空可选字段导致的解析崩断 |
| 变量元信息缺失 `shape` 默认标量 `[]`，缺失或非法 `type` 显式报错并触发节点级格式修复重试（最多 3 次），不静默放宽为连续变量；重复声明既有变量自动跳过 | 避错 | 避免缺字段崩溃同时坚守“不静默放松变量域”的平台契约 |
| 全部解析重试继续传递原生 `GraphBubbleUp` 与 `LimitExceeded` | 适配 | 宿主模型通过 LangGraph 暂停交接任务，暂停或预算超限不是解析失败 |

调试以“求解状态为最优”为成功条件；支持 CasADi 等原生后端报告的 `locally_optimal`，保留其局部含义。因此不可行或无界的模型也会进入调试。

### Chain-of-Experts

| 改动 | 类型 | 原因 |
|---|---|---|
| 专家提示中的 `code_example` 使用平台完整库契约及其原生参考，替代数据集的 `prob_*` 函数；汇总器和反思也嵌入库契约 | 适配 | 复用同一份参考，避免空模板初始化的模型与指定后端 API 冲突；参考说明原生整数域、目标和返回对象 |
| 程序员角色中的 “Gurobi” 换成所选写法的库名 | 适配 | 代码写法由用户选择 |
| 反思时在沙箱中构建并求解代码；不再让 LLM 生成测试输入 | 适配 | 平台直接执行模型 |

每轮试验开始时清空评论池，与上游一致：每轮试验是一次独立运行。反思只在代码执行失败时触发，`enable_reflection` 默认关闭，与上游命令行一致。

### OptiTree

上游 `Reasoner.reason_run`：解释器从根类型“Mixed Integer Programming”开始，在当前节点的子类型中逐层匹配（`TemplateMatcher.final_template`）；最深匹配节点的整条树条目（去掉 `id`）作为思路模板交给推理器写代码；代码运行失败时由检查员修改，最多 4 次。题面前加上 `test.py` 的 MILP 前缀。

| 改动 | 类型 | 原因 |
|---|---|---|
| 推理提示中的 “gurobi code” 换成所选写法的库名；推理和检查提示末尾拼接平台代码契约，替代模板中的求解与打印代码 | 适配 | 代码写法由用户选择 |
| 代码在沙箱中执行。上游在输出为错误、空或 “None” 时检查；这里在代码无法运行时检查，检查员读取沙箱反馈 | 适配 | 平台契约只构建模型，没有打印输出 |
| 上游 `Agent` 把自己的回复以 `system` 角色存入对话；这里改为 assistant 消息 | 适配 | 多家供应商拒绝首条之后的 system 消息 |
| 匹配到的类型不在树中、回复缺少判断字段，或匹配会回到路径上已有的节点时，停在当前节点 | 避错 | 上游在这些情况下抛出异常或循环 |

### OR-LLM-Agent

| 改动 | 类型 | 原因 |
|---|---|---|
| 代码请求中的“使用 Gurobi……以及求解和结果输出”改为平台代码契约 | 适配 | 代码写法由用户选择 |
| 两条恢复提示中的“Gurobi Python code”改为“Python code”；建模提示中的 “Gurobi” 换成所选写法的库名 | 适配 | 同上 |
| 代码在平台沙箱中执行 | 适配 | — |

修复对话只保留在副本中，只有最后一次代码进入主对话，与上游 `generate_or_code_solver` 一致。上游在最后一次修复后不再执行；平台把这段未执行代码作为中间产物输出，最终结果取最后一次实际执行的代码。

### LLMOPT

上游流程：`Q2F` 让 LLM 按模板写出五要素模型（Sets、Parameters、Variables、Objective、Constraints），`F2C` 只根据五要素模型写代码，然后执行。论文第 3.4 节在测试时加入自我校正：`self_correction` 提示把问题、五要素模型、代码和运行信息交给 LLM，分别判断五要素模型和代码是否正确；第 4.1 节规定最多重解 12 次。

LLMOPT 的主要贡献是微调模型（多指令 SFT 加 KTO 对齐），发布为 [LLMOPT-Qwen2.5-14B](https://huggingface.co/ant-opt/LLMOPT-Qwen2.5-14B)。平台使用所选预设运行经过修改的测试时流程。当前代码生成同时读取原题、完整附件和五要素模型，以免数学表述省略表格后代码补造数据；这改变了上游只读五要素的 F2C 输入机制，不是未修改的论文复现。运行参数记录 `code_context=problem_and_formulation`，旧记录保持原样。部署论文模型只能替换模型来源，不能消除这项流程差异。

| 改动 | 类型 | 原因 |
|---|---|---|
| 代码请求的结尾（“写 Pyomo 代码，以 `from pyomo.environ import *` 开头，打印最优解，写成类并加 main 函数”）改为平台代码契约；其余提示中的 “Pyomo”/“pyomo” 换成所选写法的库名 | 适配 | 代码写法由用户选择；平台读取模型而不是打印输出 |
| 自我校正提示的运行信息是沙箱反馈（状态、错误、目标值和非零变量），不是代码的打印输出 | 适配 | 生成代码不再打印结果 |
| 自我校正提示中“生成并执行 pyomo 代码”一句改为说明平台契约：代码定义 `build_model(data)` 并返回模型，由平台求解 | 适配 | 不说明时，判断者把“代码没有调用求解、没有打印”判为错误，每轮都要求重写正确的代码（DeepSeek 实测） |
| 五要素取第一个代码块；该块不含全部五个小节（Sets、Parameters、Variables、Objective、Constraints）时，改用整段回答去掉代码块标记的文本 | 避错 | 上游假设回答只有一个代码块。通用 LLM 常把每个小节分别放进代码块，或不用代码块，按原规则只取到 Sets，代码因缺少参数而建错；不用代码块时上游直接中断 |
| 五要素请求追加 Markdown 列表、LaTeX 数学分隔符和显式变量域的展示约定；保留五个小节标题和外层围栏 | 适配 | 原提示允许完整 LaTeX 文档语法，容易混入裸写公式环境与列表命令；不改自检判词、回退路线或重解上限 |
| 上游没有发布循环代码。五要素判为错时回到 `define`（随后重写代码），否则代码判为错时回到 `write_code`，两者都对时结束 | 适配 | 按论文的文字描述实现；论文未说明两个判断如何对应到返回哪一步 |
| 五要素、代码及自检都读取原题和完整附件；代码步骤同时读取五要素模型 | 机制变更（平台方案） | 五要素可能只写“见表1”或省略参数，F2C 会丢失具体数据；不再把该版本视为未修改的 F2C 复现 |
| 增加数据来源要求，保留原编号、数值、单位和对应关系；自检明确核对实现数据，禁止默认或示例数据补缺 | 平台方案 | 真实配送题多次把原题坐标替换成编造坐标；提示及 LLM 自检不能提供任意问题的数据正确性保证 |
| 必要输入缺失或矛盾时，代码步骤返回明确的 `MISSING_PROBLEM_DATA:` 原因，平台报告失败，不执行虚构模型 | 平台方案 | 无法确定输入时保留缺失信息，避免用默认数据制造可求解结果 |
| 被否定的步骤收到原反思内容及上一版产物；代码重写还收到执行反馈 | 避错 | 只跳回节点会重复原提示，丢失具体修正理由 |
| 反思必须包含五要素和代码各自明确且不冲突的 True/False 判断；缺失或冲突时报告失败，保留实际求解结果 | 避错 | 接受结果仍要求模板判断行；冲突检查也覆盖判词后带解释的情况，不能因行尾有解释而漏掉否定判断。兼容模板中的 Markdown 加粗、代码标记与布尔值方括号 |
| 原反思文本作为“自我校正”步骤产物保存；达到 12 次重解后明确报告末次产物尚未通过复核 | 适配 | 保留既有次数与回退路线，避免求解器最优状态掩盖反思未通过；末次实际求解结果仍保留 |
| 结果取最后一次执行 | 适配 | 论文未说明；与“判对即停”一致 |

`prompts.py` 保留上游原文，`graph.py` 组合原题与五要素并附加上述数据要求，仍作为单条用户消息发送，不加系统消息，不设温度。没有新增 LLM 调用、修改自检路由或重解上限。明确的数据缺失回答保留缺失原因；其他代码回答没有 ```` ```python ```` 块时同样失败。仓库没有声明许可证，上游提示仅用于研究用途（见 NOTICE）。

## 验证

> 注：下方按日期归档的验证记录保留当时版本的方法与建模库集合（后续精简已移除部分方法与库）。

### 宿主模型与本地 CLI（2026-10-24）

`tests/test_host.py` 用脚本化宿主回答和真实本机求解验证全部 13×9 组合；每次交接重新打开 SQLite 检查点。AutoFormulation 双分支用例保留 29 次宿主请求、10 次比较投票和两次求解，选出目标值 13；恢复不重复已完成求解。另验证 TriVAL 从代码验证回溯到数学模型，以及执行预算、数据卸载、错误回答和跨进程恢复。Direct、Feedback Repair 与 TriVAL 通过真实 Docker Worker 验证。

真实接入分别使用当前 Codex 会话和已登录的 Claude Code 当前模型，均只通过基础 CLI 和 Docker 求解，不配置平台 LLM，不启动 Web：

| 宿主 | 方法 / 建模库 | 实际结果 |
|---|---|---|
| 当前 Codex 会话 | Feedback Repair / OR-Tools CP-SAT，CSV 利润数据 | A=3、B=3，目标值 36；经一次公式排版修正，4 次宿主任务、2 次求解 |
| Claude Code | Feedback Repair / Pyomo | 面包 4 批、蛋糕 3 批，利润 44；2 次宿主任务、1 次求解 |
| Claude Code | TriVAL / CPMpy | x=3、y=2，目标值 18；13 次宿主任务、1 次求解，三阶段验证通过 |

基础包在新建隔离环境中验证：无 Web 服务端与模型供应商集成包，仍可发现方法、生成宿主任务并跨进程读取会话。技能经 `npx skills add` 分别安装到 Codex 与 Claude Code 目录，并核对全部文件。真实案例只证明这些具体接入路径；完整参数的复杂搜索仍由宿主模型及其上下文能力决定。

### 核心建模链路检查（2026-10-24）

逐一检查了 13 张方法图的生成、修复、停止条件和代码提示组装，并检查平台最终结果的关联。修复两处提示适配问题：OptiMUS 的调试缺少完整代码契约；CoE 另行拼接的空模板在指定 CP-SAT 时仍初始化 MPSolver。删除这套重复模板及其 imports/constructor 配置，统一读取 `CodeTarget.prompt`。各研究方法的判断策略、修复路由、循环上限和原始提示文件保持不变。

TriVAL 退出时新增结果报告：任何阶段仍未通过验证，就明确写入失败原因，并保留实际产物和求解结果。脚本化回归分别复现语义、数学模型、代码验证耗尽而求解器仍报告 `optimal` 的三条路径，确认求解状态不再掩盖验证失败；原来的阶段推进和回溯行为不变。

另修复平台结果关联：LLMOPT 等方法可能在状态里同时保留新版代码与上一版求解结果。新版执行前超限时，平台现在只关联 `Context.solve` 对这份代码实际取得的结果；上一版结果仍在过程步骤中。回归同时检查新版代码不继承旧解、相同代码仍保留已有解，以及九个建模库的调试。

真实运行使用原生 ChatDeepSeek、模型 ID `deepseek-flash`（关闭思考）和 Docker Worker 12，共 22 次平台运行，全部满足各自的数值或可行性检查。初始 16 次覆盖全部方法和九个建模库，另补充 5 次负边界／CoE 检查，并在 TriVAL 退出状态修复后复测四皇后：

| 方法 | 建模库／后端 | 问题与实际结果 |
|---|---|---|
| Direct | coptpy／COPT | 两个连续 LP，最优值分别为 1.5 和 0；后者的最优解需要负数和分数变量 |
| Feedback Repair | CVXPY／Clarabel；Pyomo／HiGHS | 凸二次规划最优值 0.5；真实矛盾约束保持 `infeasible`，未放宽 |
| TriVAL | CPMpy／OR-Tools | 四皇后无目标可满足性模型；四个列值互异、无对角冲突，目标值为空 |
| OptiMUS 0.3 | PuLP／CBC | 两个连续 LP，最优值 1.5 和 0；均实际遇到执行错误并通过调试完成 |
| Chain-of-Experts | OR-Tools／CP-SAT | 二元背包最优值 7；模板收拢后复测仍为 7 |
| OptiTree | gurobipy／Gurobi | 二元背包最优值 7 |
| OR-LLM-Agent | Pyomo／HiGHS | 两个连续 LP，最优值 1.5 和 0 |
| ORThought | PySCIPOpt／SCIP | 凸二次目标通过辅助变量表达，最优值约 0.5 |
| LLMOPT | CVXPY／Clarabel | 两个连续 LP，最优值 1.5 和约 0 |
| AutoFormulation | Pyomo／HiGHS | 带整数数量和双重索引的运输问题，最优值 10 |
| SAC-Opt | OR-Tools MathOpt／HiGHS | 二元背包最优值 7，实际经历锚点、回译和比较 |
| BIND | gurobipy／Gurobi | 执行时读取 21,001 项 JSON 完整附件，最优值 34；关键数据在末尾 |
| OptiMind | CasADi／Ipopt | 连续凸二次规划，`locally_optimal`，目标值约 0.5 |
| Direct | CasADi／Ipopt；OR-Tools 最大流 | 最大化目标恢复符号后为 4；原生最大流为 3 |

连续 LP 使用边界 $-2\le x\le4,\ 0\le y\le3,\ x+y\ge1.5$。最小化 $x+2y$ 的参考解是 $(1.5,0)$、目标值 1.5；最小化 $2x+y$ 的参考解是 $(-1.5,3)$、目标值 0。后者用于检查负边界、连续域和零目标值。凸二次规划为 $\min (x-1)^2+(y-2)^2$，满足 $x,y\ge0,\ x+y\le2$，参考解 $(0.5,1.5)$、目标值 0.5。

AutoFormulation 在真实检查进程中临时采用 `n_used_gpt=2, n_top=2, n_reward=1, total_rollouts=2, n_dv_unique_gpt=1, n_eval=1, num_warmup=1`，完整模型候选等价去重后实际进行一次有效 rollout。产品默认参数未改。这些案例验证具体路径，不作为通用准确率或论文效果评测。

完整 Python 回归 517 项通过、143 项跳过（含默认未开启的 Docker 路径及不可用插件等），其中继续覆盖 117 组方法与库组合。单独开启 Docker 的本机／容器原生接口与后端回归有 239 项通过、16 项因插件或许可不可用跳过。前端单测 90 项、浏览器回归 66 项，以及 Ruff、ESLint 和 TypeScript 检查通过。真实 LLM 证据与脚本化回归分别记录，不将单题成功扩展为所有数学问题均可表达。

### 九个建模库的通用组合（2026-10-23）

`tests/test_method_libraries.py` 用脚本化 LLM 与真实本机求解，覆盖 13 个方法 × 九个库的 117 组组合。每组检查原生求解值 13、整数取值、数学模型、代码以及调用/产物/求解步骤。共享片段另检查显式 OR-Tools 后端、连续域不支持时的报错、二维索引、负边界、固定二元值、按索引变化的参数边界和未知类型不被静默放松。

本轮 Python 回归共 435 项通过，12 项因环境或许可跳过；Docker 回归 126 项通过，5 项跳过。前端 40 项 Vitest、10 项 Playwright、类型检查、ESLint 和 Ruff 通过。镜像为 Worker 12。

真实验证使用原生 `ChatDeepSeek`、网关模型 ID `deepseek-flash`（关闭思考模式）与 Docker Worker 12，问题为 README 的整数生产计划。首次 117 次调用有 100 次得到正确解；17 次失败暴露了 TriVAL 的 JSON Schema 选择、AutoFormulation 组件格式与边界字段、CoE 缺少完整库契约、OptiMUS 无语言标签代码块的解析问题。修正后复测对应组合，并补测九个 CoE 组合，117 组均取得目标值 13 的真实解。

AutoFormulation 此处仅验证单候选流程，临时设置 `n_used_gpt=1, n_top=1, n_reward=1, total_rollouts=1, n_dv_unique_gpt=1, n_eval=1, num_warmup=1`，不改变产品默认搜索参数。其他方法使用产品预设。测试证明这些组合能够运行，不是通用建模正确率或论文效果评测。库本身的表达限制仍成立，例如 CPMpy 不能表达连续决策。

### SAC-Opt、BIND、OptiMind 与新增求解路径（2026-10-22）

确定性检查：Python 166 项通过（含本机 Gurobi）；默认跳过的 14 项 Docker 测试另行执行后全部通过，另 1 项持证 MOSEK 成功测试因无许可证跳过。前端 37 项 Vitest、8 项 Playwright 通过。新增浏览器用例检查 SAC-Opt/OptiMind/BIND 的求解器可选范围，并完成 BIND 建模。Ruff、ESLint、类型检查、前端构建与 wheel 构建通过；wheel 与当前源码/数据/前端产物一致，无旧构建缓存残留。Worker 10 与当前 `worker.py` 字节一致。

新回归覆盖：SAC-Opt 冻结已通过约束、仅修复失败组件、分项数量和格式重试、代码围栏解析、执行调试及未解决语义失败；BIND 超长完整数据绑定、JSON 非矩形结构、CSV 边界、修复历史和真实不可行；OptiMind 有/无专项提示、成功后的反思以及无代码/执行失败时的退出条件。求解器覆盖 SCIP 非线性约束、Ipopt 局部结果与超时、COPT 整数规划、OSQP 二次规划、SCS 半正定约束及许可证隔离。

真实 LLM 使用环境预设 `deepseek-flash`。下表使用 Docker Worker 10；最终 SAC-Opt 运行在提示区分固定参数/决策变量、补全附件契约并处理分项代码围栏后完成：

| 方法 | 代码写法 | 问题与结果 | LLM 调用 / 求解 |
|---|---|---|---|
| SAC-Opt | gurobipy | 生产计划，最优值 13；约束语义检查通过 | 21 / 1 |
| BIND | PySCIPOpt | 生产计划，JSON 只向 LLM 提供结构，完整数据在代码中读取，最优值 13 | 1 / 1 |
| OptiMind | Pyomo | 生产计划，通用提示，最优值 13，代码外最终答复结束反思 | 3 / 1 |

另一次 OptiMind 真实运行使用本地 PySCIPOpt，四城市有向旅行商矩阵为 `[[0,2,9,10],[1,0,6,4],[15,7,0,8],[6,3,12,0]]`。分类匹配 `TravelingSalesman` 并使用原提示，求得最优值 21，3 次 LLM 调用、1 次求解。

同一模型的 Direct 方法还在 Docker Worker 10 中验证了新增代码接口；每次均为 1 次真实 LLM 调用、1 次求解：COPT 整数生产计划为 13；OSQP 求解带线性约束的凸二次问题为 0.5；CasADi/Ipopt 求解有界 Rosenbrock 问题为 `locally_optimal`，目标约 `6.4e-18`；SCS 求解 `min trace(X), X-I ⪰ 0` 的 2×2 半正定问题为 `2.000011`（理论最优值 2）。

MOSEK 已验证缺失许可证时的明确失败，没有用其他求解器伪装成功。COPT 使用内置小规模非商业模式验证。这些验证说明接入流程和所列问题可以运行，没有测量大规模表现或整体建模准确率。

### Direct 与 Feedback Repair 更新（2026-10-22）

确定性检查：Python 138 项测试通过，默认跳过的 8 项 Docker 测试另行执行后全部通过；前端 36 项 Vitest、7 项 Playwright 浏览器测试通过。Ruff、ESLint、TypeScript 类型检查、前端构建和 Python wheel 构建通过；wheel 包含新的 `direct/` 包，不含旧 `direct.py`，页面引用的构建产物齐全。

新增回归覆盖：生成格式不完整及修正上限；代码求得最优但目标系数错误；真实不可行、无界、求解限时和无目标可满足性结果；复核响应无法解析；修正后仍有建模问题；后续生成或复核调用失败时保留已完成模型、代码和求解结果。TriVAL 成功路径不再携带过期失败标记。

真实运行使用环境预设 `deepseek-flash`，Docker 镜像 `llm4om-worker:9`，Pyomo/HiGHS：

| 输入与方式 | 方法 | 结果 |
|---|---|---|
| README 的生产计划，完整真实运行 | Direct | 最优值 13；1 次 LLM 调用、1 次求解 |
| 同上，完整真实运行 | Feedback Repair | 复核通过，最优值 13；2 次 LLM 调用、1 次求解 |
| 同一题增加 A 至少生产 5 件，完整真实运行 | Feedback Repair | `infeasible`；复核确认 A 的下限与切割容量冲突，未放宽约束；2 次 LLM 调用、1 次求解 |
| 首次生成注入错误：数学模型和代码都把 A 的利润系数从 3 改为 6；后续复核与修正使用真实 LLM | Feedback Repair | 第一次虽为 `optimal`、目标值 24，仍识别出系数错误；修正后最优值 13；1 次注入生成、3 次真实 LLM 调用、2 次求解 |

这些运行验证了流程与特定错误的恢复，没有测量整体建模准确率。

### 先前维护检查

本轮维护检查：Python 3.12 的 71 项测试通过（含本机 Gurobi）。前端 10 项 Vitest 测试、lint、类型检查和构建通过。依赖审计（前端 `npm audit`；Python 锁定依赖与 Worker 镜像内的包用 `pip-audit`）无已知漏洞。四种语言在 Docker 中求得生产计划预期最优值，另验证了容器取消。LangGraph Server 的后台运行、流重放、历史读取和 TriVAL 取消使用假 HTTP 模型及真实本机求解验证，取消后没有继续发起模型请求。

异常路径回归分布在对应模块的测试中（`tests/test_graph.py`、`test_llm.py`、`test_cli.py`、`test_methods.py`，前端 `src/features/runs/useRun.test.ts`）：JSON 中的 URL、转义和嵌套结构；TriVAL 超时与多工具顺序编辑；AutoFormulation 并发取消；建模与最终求解共享截止时间；求解超限记录；Anthropic 额外参数；OpenRouter 流式工具对话保留推理字段；断线后重新读取运行状态；节点产物步骤先于下一节点的调用记录。沙箱测试另检查环境变量隔离和取消后的子进程回收。这些测试使用脚本模型或本地假 HTTP 响应。

确定性测试（`tests/test_methods.py`、`tests/test_sandbox.py`、`tests/test_server.py`）用脚本化的聊天模型跑通全部 10 张图，覆盖：Pyomo、gurobipy、`pywraplp`、PuLP 和 CPMpy 各自由对应求解器求到最优，CVXPY 由 Clarabel 求解凸二次规划；不可行模型的冲突约束（Gurobi IIS、CPMpy MUS）；CPMpy 可满足性问题；代码与写法不符时的报错；Direct 生成 CPMpy 代码；OR-LLM-Agent 的修复与不可行复查；OptiMUS 在四种写法方言下的组装、调试、长分隔符与多代码块解析；CoE 的反向反思；OptiTree 沿类型树匹配并检查失败代码；AutoFormulation 的参数众数、变量分组、SymPy 等价剪枝、排名、双向比较和两模型排名；TriVAL 回溯到数学模型的路径；ORThought 的错误调试；LLMOPT 按自我校正结果回到五要素或代码步骤，以及 12 次重解上限；LLM 调用上限。

2026-10-21 用 DeepSeek（关闭思考模式）在 Docker 沙箱中做了真实运行：

| 问题 | 方法 | 代码写法（求解器） | 结果 |
|---|---|---|---|
| README 中的生产计划示例 | Direct、TriVAL、OptiMUS、CoE、OptiTree、OR-LLM-Agent、AutoFormulation（`n_used_gpt=3 n_top=2 n_reward=2 total_rollouts=4`） | Pyomo（HiGHS）、gurobipy（Gurobi）、`pywraplp`（SCIP） | 21 次运行全部最优，目标值 13 |
| 同上 | Feedback Repair | Pyomo（HiGHS） | 最优，目标值 13 |
| 同上 | Direct、TriVAL | CPMpy（CP-SAT） | 最优，目标值 13 |
| 单机 4 作业排程，最小化总拖期（参考最优值 0） | Direct | Pyomo（HiGHS） | 最优，目标值 0 |
| 同上 | Feedback Repair、TriVAL | CPMpy（CP-SAT） | 最优，目标值 0 |
| 8 皇后，第一行皇后在第 1 列（可满足性问题） | Direct | CPMpy（CP-SAT） | 找到解（`feasible`，无目标值），经检查合法；代码使用 `AllDifferent` |
| README 中的生产计划示例 | OptiMUS | gurobipy（Gurobi） | 首次组装的代码有语法错误，调试一轮后最优，目标值 13 |
| 3×4 带固定费用的运输问题 | AutoFormulation（`n_used_gpt=4 n_top=2 n_reward=2 total_rollouts=4`） | Pyomo（HiGHS） | 最优，目标值 1860；40 次 LLM 调用。两个完整模型进入 rollout，排名与两两比较都实际运行 |

平台改为 LangGraph 服务器后（[ADR 0009](adr/0009-langgraph-server.md)），同日经 `llm4om serve` 的线程、后台运行和可重放流再次真实运行，模型开启流式输出：

| 方法 | 代码写法 | 结果 |
|---|---|---|
| Direct | Pyomo、CPMpy | 最优，目标值 13 |
| Feedback Repair | gurobipy、CPMpy | 最优，目标值 13 |
| TriVAL | Pyomo、CPMpy | 最优，目标值 13 |
| OptiMUS | `pywraplp` | 最优，目标值 13 |
| Chain-of-Experts、OptiTree | Pyomo | 最优，目标值 13 |
| OR-LLM-Agent | gurobipy | 最优，目标值 13 |
| AutoFormulation（`n_used_gpt=2 n_top=2 n_reward=1 total_rollouts=2`） | Pyomo | 最优，目标值 13 |

8 个运行同时进行，全部成功；流式输出下 token 统计仍然完整。页面上的运行、停止和重新打开也做了浏览器检查。

生产计划示例上，OptiMUS 曾因长分隔符丢失目标函数代码，以目标值 0“最优”结束；修正解析后重跑为 13。这些运行只证明流程能端到端工作，不代表方法在 Benchmark 上的准确率。

### v0.41

确定性检查：Python 86 项测试、前端 16 项 Vitest 测试和 5 项 Playwright 浏览器测试通过，Ruff、ESLint、类型检查和构建通过。新增测试覆盖 PuLP 与 CVXPY 的求解、CVXPY 拒绝整数变量、各写法不可行模型的冲突约束（且不进入 `feedback()`）、OptiMUS 与 AutoFormulation 的 PuLP 方言、ORThought 的错误调试、LLMOPT 的回退路径与 12 次重解上限、每日 token 预算和运行频率上限。浏览器测试发现并修复了两个只在构建后的页面出现的错误：手动拆分的 SDK 代码块让发起运行报错 `r is not a function`；历史查询把 TanStack Query 的上下文当成元数据过滤条件，运行记录为空。

2026-10-22 用 DeepSeek（关闭思考模式）在 Docker 沙箱中真实运行。问题：README 中的生产计划（13）、3×4 运输问题（独立求得 1360）、凸二次规划 $\min (x-1)^2+(y-2)^2,\ x+y\le 2,\ x,y\ge 0$（0.5，解 $(0.5,1.5)$），以及合同下限与切割产能矛盾的生产问题（不可行）。

| 方法 | 代码写法（求解器） | 问题 | 结果 |
|---|---|---|---|
| Direct、OR-LLM-Agent | PuLP（CBC） | 生产计划 | 最优，13 |
| OptiMUS | PuLP（CBC） | 运输问题 | 最优，1360；19 次 LLM 调用 |
| Direct、Feedback Repair | CVXPY（Clarabel） | 凸二次规划 | 最优，0.5，解 (0.5, 1.5) |
| Direct | Pyomo、PuLP、CPMpy | 不可行生产问题 | `infeasible`；Pyomo 与 PuLP 由 Gurobi IIS 给出 3 条冲突约束，CPMpy 由 MUS 给出 2 条（$A\ge 5$ 与 $2A+B\le 8$） |
| ORThought | Pyomo、gurobipy、PuLP、CVXPY、CPMpy | 生产计划、运输问题、凸二次规划 | 5 次运行全部最优，目标值分别为 13、1360、1360、0.5、13；每次 1 次 LLM 调用 |
| LLMOPT | Pyomo、gurobipy、PuLP、CVXPY、CPMpy | 同上 | 5 次运行全部最优，目标值同上；每次 3 次 LLM 调用（五要素、代码、自我校正判对） |

LLMOPT 第一次真实运行暴露了两个适配问题（见上文 LLMOPT 改动表）：DeepSeek 把每个小节分别放进代码块，按上游规则只取到 Sets，运输问题得到目标值 0 和 4 的错误模型，并用满 12 次重解；判断者不知道平台契约，把“代码没有调用求解”判为错误。修正后 5 次运行都在第一轮判对。

同日在 Docker 部署上检查：经 Caddy 的 HTTPS 访问和流式输出正常；设置预算后，用完预算的预设在第一次 LLM 调用前停止；同一地址第 3 次发起运行得到 429；正常重启后运行记录数量不变（61 条）；`docker compose cp` 备份得到完整的 `.langgraph_api/` 与 `.private/`。恢复命令与迁移命令相同，本次没有在生产数据上执行。LangSmith 追踪没有实际接入验证。


## BIND

BIND 注册为独立 LangGraph 图，参数来自 `methods/presets.py`，在页面、CLI、Python 与 LangGraph 服务中可用。

| 方法 | 固定参考提交 | 图与公开范围 |
|---|---|---|
| BIND | [`1dac06b`](https://github.com/SprocketLab/Text2Opt-Bench/tree/1dac06be656c41d827ef20987cf8af0b48d382a2) | 数据结构 → 生成 → 求解 → 错误反馈 → 重新生成；最多 3 次，JSON/CSV 内容留在求解环境 |

BIND 默认温度 0、top_p 1。平台没有参考最优值或参考模型，删除了上游基准评分作为修复条件的依赖，只以真实执行状态决定是否调试。不可行是有效求解状态，不会据此改松约束。题面应说明数据字段语义；只有完整附件在代码执行时解析。细节见 [BIND 说明](../src/llm4om/methods/bind/README.md)。

该实现改变了执行环境和部分输出契约，不能直接宣称复现论文成绩。五个建模库通过共享指引接入；库的数学表达能力与方法的问题范围仍需满足。
