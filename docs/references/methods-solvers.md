# 建模方法与求解器接入调查

核验日期：2026-10-23。范围为“输入问题与数据 → 建模 → 求解”。当前共 13 种方法、九个建模库，库内原生后端由运行环境发现。SAC-Opt、BIND、OptiMind 均可选择九个库。以下保留最初接入调查；当前接口清单见[建模库调查](modeling-libraries.md)，验证见[建模方法](../methods.md#验证)。

## 三种新方法实际提供了什么

| 方法 | 核心机制 | 本轮接入范围 |
|---|---|---|
| SAC-Opt | 参数、变量、目标、约束锚点；约束代码回译和语义比较；冻结已通过约束，只修正未通过约束 | 独立实现与自写提示；共享组件指引支持九个库；5 轮语义比较，最多执行 3 次。固定提交 `ec0ddb544ae6b70714181740ebbba16027df50e4`。[论文](https://proceedings.mlr.press/v306/zhang26cb.html) · [代码](https://github.com/Forrest-Stone/SAC-Opt/tree/ec0ddb544ae6b70714181740ebbba16027df50e4) |
| BIND | 大数据不直接进入提示，LLM 按结构生成绑定代码；根据执行反馈调试 | JSON/CSV 完整附件直接进入沙箱；不使用已知最优值或参考模型大小。固定提交 `1dac06be656c41d827ef20987cf8af0b48d382a2`，MIT。[论文](https://arxiv.org/abs/2605.21751) · [代码](https://github.com/SprocketLab/Text2Opt-Bench/tree/1dac06be656c41d827ef20987cf8af0b48d382a2) |
| OptiMind | 根据问题类别加入错误分析提示，生成代码并结合求解反馈反思 | 公开推理流程，一条轨迹最多 5 次生成；公开提示仅含 TravelingSalesman 六对提示。固定提交 `419cf7b9eee20b6af036abf15152fa775b20c951`，MIT。[论文](https://arxiv.org/abs/2509.22979) · [代码](https://github.com/microsoft/OptiGuide/tree/419cf7b9eee20b6af036abf15152fa775b20c951/optimind) |

阅读范围包括 SAC-Opt 的 `run.py`、四类提取器、`data2model.py`、`model2data.py`、`update_util.py`、组装/执行及 LLM 工具函数；BIND 的默认 agentic 路径、schema offload、repair 提示；OptiMind 的 `eval.py`、提示构建、提示 CSV 和执行反馈工具。三份源码已检出固定提交核对，未运行其整套基准。

SAC-Opt 上游没有许可证声明，因此不复制原代码和提示。平台保留锚点和选择性修正机制，但将组件生成、回译与比较按当前待处理约束批量执行；改动详见[实现说明](../../src/llm4om/methods/sac_opt/README.md)。

BIND 原基准能用参考最优值判断结果，部署平台没有这项信息。这里将可部署的结构绑定与执行调试保留下来，不能把原基准的答案判断包装成通用能力。无附件时沿用直接建模路径；纯文本附件不参与此结构化路径。

OptiMind 的“训练模型”和“推理流程”是不同部分。本轮没有下载 OptiMind-SFT 权重，也没有补造完整提示库。已有 LLM 预设可以连接另行部署的模型服务。

## 求解器与接口

| 新增路径 | 能力与选用理由 | 分发及边界 |
|---|---|---|
| `pyscipopt` / SCIP | 原生接口可表达非线性约束，补充已有 pywraplp/SCIP 的线性接口 | PySCIPOpt 6.3.0 wheel 自带 SCIP。[官方安装说明](https://pyscipopt.readthedocs.io/en/stable/install.html) |
| `casadi` / Ipopt | 连续光滑 NLP、自动微分；报告局部解 | CasADi 3.8.1 带 Ipopt，避免额外编译 ASL/PyNumero。`Opti` 接口只最小化，最大化需转为负目标。[CasADi 文档](https://web.casadi.org/docs/#opti-stack) · [Ipopt](https://github.com/coin-or/Ipopt) |
| `coptpy` / COPT | 原生 LP、MILP、凸二次/锥优化接口 | coptpy 8.0.7 自带运行库；无许可证仅小规模非商业模式。支持只读挂载许可证。[官方 Python 接口](https://guide.coap.online/copt/en-doc/pythoninterface.html) · [许可证配置](https://guide.coap.online/copt/en-doc/install.html#installing-license) |
| `cvxpy_mosek` / MOSEK | 凸锥、SDP、混合整数锥优化 | MOSEK 11.2.6；需要许可证，不支持混合整数 SDP。通过现有 CVXPY 接口接入。[官方文档](https://docs.mosek.com/latest/pythonfusion/intro_info.html) |
| `cvxpy_osqp` / OSQP | 连续凸二次规划与线性约束 | OSQP 1.1.3，开放已有依赖的执行路径。[官方设置](https://osqp.org/docs/interfaces/solver_settings.html) |
| `cvxpy_scs` / SCS | 连续凸锥优化，含 SDP、指数锥、幂锥 | SCS 3.3.1，开放已有依赖的执行路径。[CVXPY 求解器文档](https://www.cvxpy.org/tutorial/solvers/index.html) |

当前配置为九个建模库加可选原生后端；`AUTO` 交给原生库选择。历史 `pywraplp` 和 `cvxpy_*` 标识归一化为库与后端，已有记录仍可读取。当前镜像为 `llm4om-worker:12`。

当前机器没有 MOSEK 许可证，已验证其明确报告许可证错误；持证成功路径的自动测试需要 `LLM4OM_TEST_MOSEK=1` 和有效许可证。COPT 使用自带小规模模式验证。不能据此声称商业部署授权或大规模性能已验证。

## 其余候选及优先判断

- **DRoC**：面向车辆路径的约束分解与知识检索。它对物流场景有针对性，但需要专门知识库，不作为本轮通用接口扩张。[ICLR 2025 论文](https://proceedings.iclr.cc/paper_files/paper/2025/hash/73d6c3e4b214deebbbf8256e26d2cf45-Abstract-Conference.html)
- **IR2Solve**：结构化中间表示与确定性验证/编译，需要引入新的表达模式和编译器。本次未找到可核实的官方实现，不据此断言没有公开代码。[论文](https://arxiv.org/abs/2608.02641)
- **ORLM、SIRL、OptMATH**：重点是训练或数据生成，不能靠增加一个提示按钮复现。模型服务可经现有预设接入。[ORLM](https://github.com/Cardinal-Operations/ORLM) · [SIRL](https://github.com/Cardinal-Operations/SIRL) · [OptMATH](https://github.com/optsuite/OptMATH)
- **CPLEX、cuOpt**：CPLEX 已可作为原生后端，完整能力受许可证限制；cuOpt 涉及 GPU 部署，本机没有验证。

OptiMUS 原固定提交已经是 0.3，本轮修正显示名称与论文引用，未重复增加一个方法。[固定 README](https://github.com/teshnizi/OptiMUS/blob/e182e9ef5841605c2a7e87467021fd83522b6484/README.md) · [论文](https://arxiv.org/abs/2407.19633)

选择接入这些方法的工程理由是补充语义对齐、长数据绑定和具体求解能力。本轮运行验证证明流程可执行，不证明新方法整体优于现有方法，也不替代论文规模的效果评测。


## DeepSeek 原生客户端与提示组装（2026-10-23）

核对了 [LangChain 官方 DeepSeek 集成](https://docs.langchain.com/oss/python/integrations/chat/deepseek)及本机锁定的 `langchain-deepseek 1.1.1` 源码（`ChatDeepSeek` 的请求构造、结果和流式 reasoning_content 读取、结构化输出）。原生客户端支持工具调用和结构化输出，但具体网关未必支持 JSON Schema。本机接口真实接受工具调用，拒绝 JSON Schema；TriVAL 三个验证器因此统一显式使用 LangChain `ToolStrategy`，不增加协议包装器。

预设显示名称与 API 模型 ID 分开。本机模型目录返回的 ID 包含 `deepseek-flash`；`deepseek-v4.1 flash-1017` 用作用户指定的显示名称，不据此推断网关背后的模型权重版本。

组件式方法复用原生变量、约束、目标和返回值片段，完整代码方法复用库提示。该改动不新增抽象模型表示，不改变 MCTS、锚点修正或验证的核心流程。
