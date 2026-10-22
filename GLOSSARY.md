# LLM4OM 领域术语

以下定义用于代码、文档和工作项。模块与接口见[架构](docs/architecture.md)。

**自动优化建模（Automated Optimization Modeling）**：从自然语言问题和数据形成可求解的优化模型的任务。
_Avoid_: 与方法名 AutoFormulation 混用。

**问题（Problem）**：用户给出的自然语言描述，加上可选的数据文件。

**建模方法（Method）**：组织 LLM 调用、中间产物、求解和修正，最终给出数学模型和代码的策略。
_Avoid_: 用 LLM 或求解器的名称指代方法。

**预设参数（Preset）**：一个方法的全部参数，如迭代次数、采样数和温度。全部方法的预设集中在 `methods/presets.py`，每次运行都用同一套，运行时不能改。
_Avoid_: 方法选项（options）；运行不再传入方法参数。

**预设模型（LLM Preset）**：一组固定的 LLM 配置：服务商、接口地址、密钥、模型 ID 和请求参数。运行只能选择预设模型，不能临时改模型。预设模型只能添加和删除，不能修改；密钥只保存在服务器上，任何接口都不返回。服务器 `LLM4OM_LLM_*` 环境变量给出的预设（id 为 `env`）只能在服务器上修改。
_Avoid_: LLM 服务设置、profile；不要与方法的预设参数混用。

**适配（Adaptation）**：为接入平台而对研究方法做的必要改动，如由平台提供 LLM、代码改用平台契约。适配不改变方法机制。

**避错（Error Avoidance）**：为避免明显运行失败而做的小改动，如兼容分块回复。避错不改变方法机制。

**数学模型（Formulation）**：用集合、参数、变量及其域、目标和约束表达问题的数学表述。

**求解代码（Code）**：实现数学模型的 Python 代码，定义 `build_model(data)` 并返回模型对象。

**代码契约（Code Target）**：所选代码写法对应的代码要求，由平台拼接到方法的代码提示中。

**代码写法（Code Language）**：生成代码使用的建模库：Pyomo、gurobipy、OR-Tools `pywraplp`、PuLP、CPMpy 或 CVXPY。用户选择写法，写法决定求解器。方法可以只支持部分写法。
_Avoid_: 建模后端（Backend）；它已与求解器合并为代码写法。

**求解器（Solver）**：求解模型的程序，由代码写法决定：Pyomo → HiGHS，gurobipy → Gurobi，`pywraplp` → SCIP，PuLP → CBC，CPMpy → OR-Tools CP-SAT，CVXPY → Clarabel。

**方言（Dialect）**：原提示针对某个库的方法为每种代码写法准备的提示与代码片段。gurobipy 方言保留上游原文。

**沙箱（Sandbox）**：执行求解代码并用该写法的求解器求解的隔离环境。沙箱内运行的脚本叫 Worker。

**求解结果（Solve Result）**：一次求解的状态、目标值、变量取值、代码输出和错误。
_Avoid_: 把 `optimal` 当作建模正确；它只说明当前模型被求到最优。

**冲突约束（Infeasibility Diagnosis）**：模型不可行时，沙箱找出的一组不能同时满足的约束（Gurobi IIS 或 CPMpy MUS）。只展示给人，不进入方法的求解反馈。
_Avoid_: 把它当作修正建议；它只说明哪些约束合在一起无解。

**运行（Run）**：一次“问题 + 方法 + LLM + 代码写法”的执行。运行是 LangGraph 服务器上的一个线程，结果保存在线程状态中。

**对比（Comparison）**：同一问题用多个方法或预设模型各运行一次，并排查看。对比中的运行共享线程元数据 `group`。

**步骤（Step）**：运行中按顺序记录的一步：LLM 调用、中间产物、求解或错误。步骤开始时和结束时各推送一次，结束后写入线程状态。避免使用：事件。

**中间产物（Artifact）**：方法在过程中输出的内容，如语义事实、候选模型、专家意见。

**Benchmark**：带来源和许可的公开问题集合，可在“示例题库”中浏览和取用。
