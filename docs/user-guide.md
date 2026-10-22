# 使用指南

本文说明怎样用工作台、命令行和 Python 接口求解优化问题。安装和启动见 [README](../README.md#快速开始)，部署给多人使用见[部署指南](deployment.md)。

## 一次运行的流程

```text
问题描述 + 可选数据文件
   → 建模方法调用 LLM，写出数学模型和求解代码
   → 沙箱执行代码，用所选写法的求解器求解
   → 结果：目标值、变量取值、数学模型、代码和全部过程
```

运行在服务器上进行。关闭页面不会中断运行。重新打开时，页面从第一步重放到当前进度。

## 工作台

![新建页面](assets/home.png)

### 1. 添加预设模型

点击左下角“预设模型”，选择服务商，填写密钥和模型 ID，再保存。服务器设置了 `LLM4OM_LLM_*` 环境变量时，已经有一个默认预设，可以跳过这一步。

预设固定服务商、接口地址、密钥、模型 ID 和请求参数：

- 预设只能添加和删除，不能修改。要换参数，就删掉后重新添加。
- 密钥只保存在服务器上（`<workspace>/.private/llm-presets.json`，权限 `600`）。所有接口和运行记录都不返回密钥，也不显示掩码。密钥只发给与它一起保存的接口地址。
- 服务器 `.env` 中的 `LLM4OM_LLM_*` 变量给出 id 为 `env` 的预设。它排在第一位，是默认预设。页面上不能删除它，只能在服务器上修改。

支持的服务商：OpenAI、Google Gemini、Kimi、GLM、OpenRouter、阿里云百炼、DeepSeek 和 Anthropic。其他服务选“OpenAI 兼容”，再填写接口地址。

### 2. 写问题

写清决策、目标和约束。需要数据时，拖入或添加 CSV、JSON 文件，每个文件最大 2 MB。Excel 工作簿（`.xlsx`）的每个工作表会转换为一个 CSV 文件。

也可以从首页的三个例子开始，或在“示例题库”中选择公开题目。

### 3. 选择方法、写法和模型

右侧“运行设置”有三项：

| 设置 | 说明 |
|---|---|
| 建模方法 | 10 种方法，见 [README](../README.md#建模方法)和[建模方法](methods.md) |
| 代码写法 | 写法决定求解器，例如 Pyomo 用 HiGHS。原提示只覆盖 LP/MILP 的方法只能选四种 MILP 写法 |
| 预设模型 | 本次运行使用的 LLM |

点击“开始建模”，或按 Ctrl+Enter。

### 4. 看结果

![运行结果](assets/run.png)

运行页顶部先给结论：目标值和求解状态，或失败原因。“核对数学模型”和“查看解”直接跳到对应页签。

- **建模过程**（左栏）：LLM 调用按它们产出的阶段分组。正在进行的调用实时显示文字。
- **解**：按变量分组或列表查看。二维变量显示为矩阵，可以导出 CSV。
- **数学模型**和**求解代码**：方法改写过的版本都可以查看，并和上一版对比。

  ![数学模型](assets/formulation.png)

- **问题与数据**：本次运行的问题描述和数据文件。

“最优”只说明求解器找到了当前模型的最优解。请对照问题检查数学模型是否完整。

### 不可行模型

模型不可行时，“解”页签列出一组不能同时满足的约束。线性模型用 Gurobi IIS 求出，CPMpy 模型用 MUS 求出。这些信息只给人看，不交给建模方法。CVXPY 写法没有这项诊断。

![不可行诊断](assets/conflict.png)

线性模型的诊断通过 Gurobi 完成。没有完整许可证时，Gurobi 只能处理小规模模型，大模型会提示诊断失败。

### 对比多个方法

打开“运行设置”中的“对比”开关，勾选多个方法或预设模型，一次最多发起 12 个运行。对比页并排列出每个运行的结果、目标值、用时、LLM 调用数和 token，并提示目标值是否一致。

![方法对比](assets/compare.png)

目标值相同不代表模型都对。几个方法可能犯同样的错。点击一行，可以查看该运行的数学模型、代码和过程。

服务器设置了每小时运行上限时，对比可能只启动一部分运行。这时页面仍打开对比页，并提示有几个运行没有启动。

### 备注、标签和报告

- **备注与标签**：在运行页选择“更多操作 → 备注与标签”，记录结论。在左侧搜索框输入 `#标签`，可以筛选运行。能打开工作台的人都能看到和修改备注。
- **导出报告**：选择“更多操作 → 导出报告（Markdown）”，下载问题、设置、结果、数学模型、代码和备注。
- **再运行一次**：用同样的问题和设置重新运行。**修改后运行**：把问题和设置带回编辑页。
- **复制链接**：运行页和对比页都有固定地址，可以发给同事。

### 界面

左下角可以切换浅色、深色或跟随系统，也可以切换中文或英文。浏览器语言不是中文时，界面默认是英文。

![深色英文界面](assets/dark-en.png)

## 服务商说明

**DeepSeek 与 TriVAL**：DeepSeek 的思考模式不支持强制 `tool_choice`，而 TriVAL 的结构化输出需要它。在“高级参数 → 额外请求参数”中填写 `{"thinking": {"type": "disabled"}}`，或在服务器上设置 `LLM4OM_LLM_EXTRA_BODY`。

**Anthropic**：额外参数支持 `thinking`。

**OpenRouter**：平台使用专用集成，保留工具对话中的推理信息。推理强度可以设为 `{"reasoning": {"effort": "high"}}`。当前集成不支持的推理字段会报错。

## 内置题库

“示例题库”包含 9 组、2033 条公开题面。可以逐条阅读，再带入输入区。

| Benchmark | 题数 | Benchmark | 题数 |
|---|---:|---|---:|
| NL4Opt | 205 | IndustryOR | 99 |
| NL4LP | 178 | ComplexOR | 18 |
| MAMO Easy | 642 | OptiBench | 403 |
| MAMO Complex | 210 | OptMATH | 128 |
| NL4COP | 150 | | |

题面来自 [OPT-Agent](https://github.com/Fangziyang0910/OPT-Agent) 的整理版本，不含答案。部分题目超出 LP/MILP 范围。来源和许可见 [Benchmark 来源](references/benchmark-sources.md)。

## 命令行

```bash
uv run llm4om run --problem "……" --method trival --language pyomo
uv run llm4om run --file problem.txt --data demand.csv --method coe
```

命令在本进程中运行和服务器相同的图。它逐步打印过程，最后输出数学模型、代码和求解结果。

| 参数 | 说明 |
|---|---|
| `--problem` / `--file` | 问题描述文本，或 UTF-8 文本文件 |
| `--data` | 数据文件（CSV 或 JSON），可以重复 |
| `--method` | 方法 id，例如 `direct`、`orthought`、`llmopt` |
| `--language` | `pyomo`、`gurobipy`、`pywraplp`、`pulp`、`cpmpy` 或 `cvxpy` |
| `--preset` | 预设模型 id；默认用第一个预设 |
| `--workspace` | 保存预设的工作区 |
| `--output` | 把最终状态（含全部步骤）写入 JSON 文件 |
| `--sandbox local` | 在本机子进程中执行生成代码，不隔离，只用于开发 |

## Python 接口

```python
from llm4om import run_problem

state = run_problem("……", method="optimus", language="gurobipy")
print(state["failure"] or state["solve"]["objective"])
```

用 `preset=` 选择预设，或用 `llm=LLMSettings(...)` 直接传入模型设置。

## 运行记录

每次运行是 LangGraph 服务器上的一个线程（thread）：

- **线程状态**保存问题、数据文件、数学模型、代码、求解结果、全部步骤和调用统计。
- **线程元数据**保存标题、方法、代码写法、模型名、备注和标签，不含密钥。

服务器把它们保存在 `<workspace>/.langgraph_api/`，重启后仍在。使用同一个 `--workspace`，就能保留预设和历史。

## 常见问题

**页面一直显示“无法连接服务器”。** 检查 `llm4om serve` 或 `app` 容器是否在运行（`docker compose ps`），以及防火墙是否放行端口。

**运行失败，提示 Docker 或镜像不存在。** 先运行 `uv run llm4om build-worker` 构建沙箱镜像。Docker 部署会自动构建。

**gurobipy 写法提示许可证或规模限制。** 没有完整许可证时，Gurobi 只能求解小规模模型。换用 Pyomo、`pywraplp` 或 PuLP，或按[部署指南](deployment.md#gurobi-许可证)挂载许可证。

**提示预设的每日 token 已用完。** 服务器设置了 `LLM4OM_DAILY_TOKENS`。换一个预设，或等到第二天。
