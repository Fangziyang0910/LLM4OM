# LLM4OM

**用自然语言描述优化问题，查看数学模型、求解代码和决策结果。**

LLM4OM（Large Language Models for Optimization Modeling）是一个自动优化建模平台。你可以用中文或英文描述生产计划、资源分配、项目选择等问题，选择语言模型和求解器，然后开始建模。平台保存建模过程和产物，便于检查结果、补充信息和继续修改。

```text
问题描述 + 可选业务数据 → 数学表述（Formulation）→ 求解代码（Code）→ 求解结果
```

Web 工作台是主要使用入口。CLI 和 Python SDK 提供相同的建模流程，也支持批量实验和插件扩展。

## 能做什么

- **从描述开始建模**：直接输入目标、规则和已知数据。可以附加 CSV 或 JSON，无需预先编写数学公式。
- **选择模型和求解器**：独立选择 LLM、建模方法和求解器。更换求解器时，平台组合对应的代码要求。
- **查看建模过程**：查看方法实际执行的步骤、阶段产物、公开检查和修正理由。方法需要补充信息时，可以在页面回答。
- **阅读建模产物**：切换“结果”“数学模型”和“求解代码”，查看目标值、决策变量、约束、代码和求解状态。
- **修改并再次求解**：修改问题、数学模型或代码，创建派生版本。历史版本保留，可继续查看或导出。
- **浏览内置样例**：打开平台集成的 Benchmark，逐条阅读、复制问题，或带入输入区试用。
- **保存本机设置**：分别保存各供应商的模型和密钥。刷新页面或重启同一工作区后继续使用。

当前支持线性规划（LP）和混合整数线性规划（MILP）。平台处于开发阶段，当前版本为 `0.37.0`，尚未发布正式 1.0。

## 启动工作台

需要 Python 3.11 或 3.12、[uv](https://docs.astral.sh/uv/) 和可访问的 Docker Engine。当前完整验证环境是 Linux。生成代码在 Docker Worker 中执行。

在仓库根目录执行：

```bash
uv sync --locked --all-extras
uv run --locked --all-extras python scripts/build_worker_image.py
uv run --locked --all-extras llm4om serve --workspace runs/web --port 8767 --host 127.0.0.1
```

打开 [本地工作台](http://127.0.0.1:8767)。仓库已包含前端构建文件，使用工作台无需安装 Node.js。

使用同一个 `--workspace` 路径可以保留设置和历史记录。更新 Python 后端后，重启服务并刷新页面。

## 完成一次建模

1. 在“问题描述”中写出目标、约束和数据。需要时添加业务数据文件。
2. 点击输入区底部的模型按钮，选择供应商，填写密钥和模型名，再保存。
3. 需要更换方法时，先打开“建模选项”。再选择 HiGHS、Gurobi 或 OR-Tools。切换方法会应用该方法的默认配置，请重新确认求解器。
4. 点击“开始求解”。运行时可以查看建模步骤和执行诊断。
5. 完成后查看目标值和决策结果，再切换到数学模型或求解代码。

可以先试这个问题：

> 工厂生产 A、B 两种产品，数量必须是非负整数。每件 A 利润为 3，每件 B 利润为 2。A 消耗 2 单位切割资源和 1 单位加工资源，B 消耗 1 单位切割资源和 2 单位加工资源。两种资源各有 8 单位。请确定生产数量，使总利润最大。

此问题的最优解是 A=3、B=2，总利润为 13。你可以对照数学模型、代码和决策值检查建模结果。

运行后的工作区默认显示结果。建模过程中，过程面板自动展开；完成后收起，也可以手动打开。数学模型和代码页面保留各自的修正历史。顶部“历史记录”用于打开已有任务。

使用确定性编译的严格 IR，且已返回完整决策值时，页面还支持目标贡献、约束余量和决策试算。试算只更新页面中的代入计算；提交模型修改才会创建新版本并再次求解。

修改问题会再次调用 LLM。修改数学模型或代码则复用已有产物，再次求解。严格 IR 支持表单编辑；其他表述使用高级编辑。当前修改保留原始业务数据，更换数据时请新建问题。

## 建模方法

| 方法 | 核心流程 |
|---|---|
| Direct（单次生成） | 一次模型调用生成数学表述和模型表示，再编译或执行 |
| Feedback Repair（反馈修正） | 根据公开的解析、执行和求解诊断进行有界修正；支持澄清问题 |
| OptiMUS | 提取参数、目标和约束，逐条建模，再生成代码和调试 |
| CoE（Chain-of-Experts） | 协调者选择专家，汇总建模意见，失败后反思和修正 |
| OptiTree | 在固定问题类型树中查找建模思路，再生成模型和代码 |
| OR-LLM-Agent | 先完成数学建模，再生成代码，并根据执行错误调试 |
| AutoFormulation | 用蒙特卡洛树搜索组织参数、变量、目标和约束的生成，结合自评与公开检查选择输出 |

这些研究方法集成了原工作的核心编排和提示思路，使用你配置的通用 LLM。当前目标是方法可组合使用。具体适配差异和固定来源见[建模方法](docs/development/methods.md)。OptiMUS 可以直接读取自然语言描述，无需额外提供 `params/labels` 文件。

Web 预设中的 Direct、Feedback Repair 和 AutoFormulation 生成严格 IR，再由平台编译为 Pyomo 代码。OptiMUS、CoE、OptiTree 和 OR-LLM-Agent 直接生成模型工厂代码。两条路径都保留数学表述和代码产物。

## 求解器

七种方法都可以通过默认 Pyomo 路径选择以下求解器：

| 求解器 | 当前用途 | 使用条件 |
|---|---|---|
| HiGHS | LP/MILP | 开放求解器；随 Worker 依赖安装 |
| Gurobi | LP/MILP | 需要可用的 Gurobi 运行环境；已验证环境为有限规模许可证 |
| OR-Tools | 通过 MPSolver/SCIP 求解 LP/MILP | 随 Worker 依赖安装 |

除 AutoFormulation 外，其余六种方法还支持 gurobipy 原生工厂，此路径使用 Gurobi。Direct 和 Feedback Repair 需设置 `output_mode: native_gurobipy`；四种研究提示流程按建模后端选择代码目标。原生工厂均在容器中执行。当前没有接入 OR-Tools 的 CP-SAT、路径规划求解或非线性优化。配置组合和数值限制见[执行与求解](docs/development/solvers.md)。

## 模型与密钥

页面预设 OpenAI、Google Gemini、Kimi、GLM、OpenRouter、阿里云百炼、DeepSeek 和 Anthropic。预设地址固定；连接其他服务时，选择“OpenAI 兼容”并填写地址。

已有密钥时，编辑器会尝试读取模型列表。列表分别显示名称和 API ID，选择后使用 API ID 发起请求。也可以手动填写模型名。部分服务可能不提供模型目录，此时仍可手动配置。读取目录不会发起文本生成。

页面显示“是否配置密钥”和掩码预览。各供应商设置保存在 `<workspace>/.private/llm-settings.local.json`，文件权限为 `600`，已由 Git 忽略。完整密钥不通过查询接口返回，也不进入公开运行记录或导出。

也可以在本机 `.env` 中设置默认服务，变量见 [.env.example](.env.example)。模型名必须填写服务接受的实际 API ID。协议、目录支持范围和配置说明见[LLM 配置](docs/development/llm.md)。

## 内置 Benchmark

“示例题库”包含 9 组、2033 条公开题面：

| Benchmark | 题数 | Benchmark | 题数 |
|---|---:|---|---:|
| NL4Opt | 205 | IndustryOR | 99 |
| NL4LP | 178 | ComplexOR | 18 |
| MAMO Easy | 642 | OptiBench | 403 |
| MAMO Complex | 210 | OptMATH | 128 |
| NL4COP | 150 | | |

题面直接复用 OPT-Agent 已整理的版本。打开一组题目后，可以逐条阅读、复制，或点击“带入建模”。带入后仍由你主动开始求解，已选模型、方法和求解器会保留。

题库用于浏览和试用，部分题目超出当前 LP/MILP 范围。题库数量也不代表平台已通过这些问题的全量准确率评测。数据来源、许可和评测导入说明见[Benchmark 与评测数据](docs/development/benchmarks.md)。

## CLI 与 Python SDK

无需 LLM 密钥即可验证本机流程。以下示例回放人工编写的模型，并在容器内用 HiGHS 求解：

```bash
uv run --locked --all-extras llm4om doctor --config examples/specs/run.yaml
uv run --locked --all-extras llm4om run --problem examples/specs/problem.json --config examples/specs/run.yaml
```

命令返回 `run_id`、`bundle_path` 和 `status`。`bundle_path` 是运行目录，入口文件是该目录下的 `bundle.json`。目录还包含阶段产物、求解记录和已配置的报告。

Python 使用同一个应用入口：

```python
from pathlib import Path
from llm4om import run_problem

result = run_problem(
    Path("examples/specs/problem.json"),
    Path("examples/specs/run.yaml"),
    output_root=Path("runs"),
)
print(result.run_id, result.status, result.bundle_path)
```

`--offline` 只保存离线产物，返回 `artifact_ready`，不执行求解。真实 LLM、取消与恢复、批量实验的命令见[运行指南](docs/development/runs.md)和[示例说明](examples/README.md)。

## 常见问题

**配置正确，但任务在开始前失败。** 打开“建模选项”中的配置检查，确认 Worker 镜像、求解器和密钥可用。更新后端后，需要重启服务；旧进程可能仍使用旧配置模板。

**模型列表获取失败。** 核对供应商和密钥，或手动填写 API ID。目录可达只说明元数据接口可用，实际生成还取决于模型权限与服务状态。

**运行完成，是否表示建模正确？** `completed` 表示流程完成，`optimal` 表示求解器找到了当前模型的最优解。还需检查模型是否完整表达了原问题。无独立参考材料时，平台会如实显示对应检查不可用。

**在哪里找到设置和历史记录？** 保留启动时的工作区目录。换一个 `--workspace` 会打开另一组记录；删除工作区会删除其中的设置和运行数据。

## 更多文档

- [文档导航](docs/README.md)：按使用、开发和研究任务查阅。
- [贡献指南](CONTRIBUTING.md)：开发环境、修改流程和交付检查。
- [领域术语](GLOSSARY.md)：问题、方法、阶段产物、求解和评测的统一定义。
- [架构与接口](docs/architecture.md)：扩展方法、LLM 或求解器。
- [评测协议](docs/evaluation.md)：正确性层次、样本分母和资源统计。

代码采用 [Apache-2.0](LICENSE)。第三方代码与数据的来源见 [NOTICE](NOTICE)。
