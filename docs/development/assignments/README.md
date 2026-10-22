# 30 天轮换开发任务

任务基线为 v0.40：LangChain 调用模型，LangGraph 编排和保存运行，独立 Worker 执行代码。三位同学依次从已验收的 `main` 开发，每阶段按课余开发安排 10 天。

| 阶段 | 负责人 | 主任务 | 接手条件 |
|---|---|---|---|
| [A：基线与首个求解器](01-baseline-and-method-audit.md) | @chuleipangtong，GitHub #107 | 八种方法复核、必要修正、首个新增求解器 | 记录实际 `main` 提交 |
| [B：前端与 LLMOPT](02-workbench-and-first-extension.md) | @ShengZhihong0311，GitHub #108 | 完善现有界面、接入 LLMOPT | A 的交付已验收并合入 |
| [C：第二组扩展与回归](03-platform-and-second-extension.md) | 同学 C | 新方法、新求解器、整体回归 | B 的交付已验收并合入 |

本轮基础维护已修复解析、异步取消、总时限、供应商参数、断流和 Worker 环境变量问题，并整理了测试与前端。接手后先运行现有检查，再处理剩余任务；具体证据见 [方法验证](../../methods.md#验证)，不能将确定性测试当成真实 LLM 的语义正确性证明。

## 当前接口

先读 [README](../../../README.md)、[架构](../../architecture.md)、[方法](../../methods.md)和 [CONTRIBUTING](../../../CONTRIBUTING.md)。

- 八种方法为 Direct、Feedback Repair、OptiMUS、CoE、OptiTree、OR-LLM-Agent、AutoFormulation 和 TriVAL。新增方法实现 `Method` 和 LangGraph 图，使用 `Context.llm()`、`Context.solve()`，不重建 Gateway 或插件框架。
- 四种语言和求解器绑定为 Pyomo/HiGHS、gurobipy/Gurobi、pywraplp/SCIP、CPMpy/CP-SAT。`Method.languages` 限定支持范围；MILP 方法不能因界面新增选项就声称支持 CP。
- 生成代码实现 `build_model(data)`。数据为文件名到文本的映射；Worker 求解，不把密钥传入生成代码。
- 运行只选择预设模型（`LLMPresetStore`）：预设只能添加和删除，密钥不出现在任何接口响应中。新功能不能重新开放读取或修改密钥的路径，见 [ADR 0010](../../adr/0010-llm-presets.md)。
- CLI 与 Web 共用 `platform_graph()`。Web 的 threads、runs、取消和 SSE 来自 LangGraph Server；前端通过官方 SDK 访问。步骤和最终结果来自同次运行。
- 旧版 SolverBackend、严格 IR、独立产物目录、通用澄清、人工派生编辑和批量评测不属于当前接口。任务不要求恢复这些已移除功能。下载当前数学模型、代码及结果属于现有界面功能。

## 依赖与交接

谁改接口，谁在同次修改中同步全部调用方、配置、测试、文档和前端构建文件。保持方法的核心提示和策略，记录来源及适配差异。

复用 `docs/methods.md` 的方法说明与验证表，以及 `tests/` 中的问题和脚本化模型，不另建报告系统。记录实际支持的“方法—语言—求解器”组合；新增项补相应组合，受影响的已有项回归。不能再沿用旧版 28/32/45 个 Pyomo 全排列指标：当前每种语言绑定一个求解器，CP 也有独立能力边界。

确定性检查包括正常求解、不可行、无界、执行失败、修正、取消、超时和断流，按实际支持范围选择。数学检查使用有独立预期的不同问题，不能只核对目标值 13。真实 LLM、真实求解器与脚本化回复分别记录。

后续同学先复跑 CLI、Web、配置与历史、取消和结果对应关系，再接手。无法启动、工程计算错误、结果错配、关键步骤丢失或入口断开，必须由当期负责人修复。交付可运行的 `main` 提交、共同测试入口、新增项配置及来源，以及一页以内的接口变化和已知问题。密钥、运行数据及许可证不进入 Git。

完整检查命令见 CONTRIBUTING；至少运行 Ruff、Python 测试、前端 lint、前端测试和构建。真实运行默认使用 Docker，`local` 仅用于开发与确定性测试。
