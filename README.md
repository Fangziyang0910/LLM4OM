# LLM4OM

**自动优化建模集成平台 · A modular platform for automated optimization modeling**

LLM4OM 是让普通使用者通过自然语言解决优化问题的平台。输入问题与可选业务数据，选择建模方法和求解器，即可查看数学表述、代码与求解结果。Web 提供平台内置 Benchmark 的逐条浏览、复制和带入建模；数据由平台维护。开发者可通过 CLI、SDK 与插件继续接入方法、LLM、求解器和评测。

核心流程：**问题描述与数据 → Formulation（数学表述）→ Code（求解实现）→ Solve → 决策结果与运行记录**。不同方法可以联合生成或往返修正两阶段输出；Benchmark 在同一流程上组织批量实验与方法比较。

**LLM4OM = Large Language Models for Optimization Modeling**，其中 `4` 表示 `for`，`OM` 表示 `Optimization Modeling`，与 LLM4AD 的命名方式对应。仓库名为 `LLM4OM`，Python 包名、命令名与插件命名空间采用 `llm4om`。

完整项目标题：**LLM4OM: A Unified Platform for Automated Optimization Modeling with Large Language Models**。

## 当前状态

当前SDK／Worker为0.37.0开发版本，尚未发布完整1.0。CLI与Web已提供输入问题、选择方法、展示真实建模步骤、五元素表述、求解代码、决策结果和保存版本。结果页支持数据预览、模型数值编辑、派生求解、候选比较、决策试算与运行资源展示。

当前开发交付以本机后端与Web能启动、展示并运行单问题流程为准。复用已有接口，按修改范围做聚焦检查；公网多人部署、多平台适配和正式发布不属于当前收尾范围。

OptiMUS、CoE、OptiTree、OR-LLM-Agent、AutoFormulation已提供自然语言输入入口，另保留单次生成与反馈修正两个项目基线。OptiMUS的Web入口不要求额外的params／labels文件。方法使用通用外部LLM；源码固定与流程差异见[方法与求解器扩展记录](docs/development/s06-method-expansion.md)。

七个自动建模方法均可选择HiGHS、Gurobi或OR-Tools／SCIP。方法保留各自编排与阶段提示，代码提示由所选建模后端和求解器组合。默认使用Pyomo LP/MILP路径；四个提示流程也支持选择gurobipy后端生成Gurobi原生工厂。实际Gurobi验收限微型size-limited环境。具体组合与证据见[能力矩阵](docs/implementation-plan.md#1-首批能力矩阵)。

NL4Opt、NLP4LP与MAMO已有导入和评测接口；CLI已有批量调度和报告。2026-10-11已按官方DeepSeek API完成三方法×三基准九格真实接入（连接失败清零、4/4数值参考匹配）与99格真实批量取消恢复验收；3格方法性失败如实记录。已有真实记录不代表完整发布已验收。

[可安装Executor](docs/development/s03-executor-registry.md)沿用已有容器／本机进程接口；[可安装ArtifactStore](docs/development/s03-store-registry.md)完成全部插件种类的共同注册。[显式连通性检查](docs/development/s03-connectivity.md)已实现。2026-10-11起真实Provider切换为官方DeepSeek API直连，中转链路TLS中断不再影响新运行；外部可达性仍以实际请求结果为准。

GitHub仓库当前为私有，采用Apache-2.0。详细历史证据见[开发计划](docs/implementation-plan.md)和各切片记录。

## 快速开始

在仓库根目录执行，使用 Python 3.11／3.12：

```bash
uv sync --locked --all-extras                         # 本机开发所需依赖
uv run --locked --all-extras python scripts/build_worker_image.py  # 构建 Docker Worker 镜像（求解在容器内执行）
```

### Web 工作台（推荐入口）

```bash
# 在仓库根目录的 .env 配置 LLM4OM_LLM_BASE_URL / LLM4OM_LLM_MODEL / LLM4OM_LLM_API_KEY（见 .env.example）
uv run --locked --all-extras llm4om serve --workspace runs/web --port 8767 --host 127.0.0.1
```

浏览器打开 `http://127.0.0.1:8767` 即可：输入自然语言问题与数据 → 选择方法 → 观察真实建模步骤 →
查看五元素表述、求解代码、决策结果与运行记录，支持数据预览、模型数值编辑、派生求解、候选比较、
决策试算、人工修订与内置 Benchmark 浏览。样例直接复用 OPT-Agent 已整理的 9 组、2033 条题面，可逐条复制或带入建模，无需上传数据集。详情见[内置样例记录](docs/development/s09-builtin-benchmarks.md)。访问令牌由服务启动时生成，页面自动获取；LLM 凭据只保留在服务端。
`--host 0.0.0.0` 可供局域网访问，但此时 Origin 校验是 CSRF 缓解而非认证，请勿暴露于不受信网络。
页面源码在 `frontend/`（React + TypeScript），仓库自带已构建的静态资源；改前端后 `npm --prefix frontend run build` 重新生成,流程与浏览器测试见 [CONTRIBUTING](CONTRIBUTING.md)与[S09-D](docs/development/s09-frontend-redesign.md)。

### CLI 单次运行

```bash
uv run --locked --all-extras llm4om plugins list
uv run --locked llm4om doctor --config examples/specs/run.yaml
uv run --locked llm4om run --problem examples/specs/problem.json --config examples/specs/run.yaml
uv run --locked llm4om run --offline --problem examples/specs/problem.json --config examples/specs/run.yaml
```

CLI 输出 run_id、bundle_path 和 status。运行目录默认在 `runs/`；查看其中的 `bundle.json`、阶段产物、解向量和 `reports/report.md`。`--output PATH` 可覆盖存储根目录。真实 run 默认使用已构建的 Docker 镜像；solve.yaml 显式选择 trusted_local。两条路径真实得到 A=3、B=2、目标 13，状态 completed；offline run 的 artifact_ready 只表示离线产物已保存。这些配置的 Formulation 来自人工 Mock；外部 LLM 配置见 S05-A。候选求解成功不代表业务语义已验证。

CLI 和 Web 共用 `llm4om.run_problem` 应用入口。安装、SDK、支持范围与错误语义见 [S01](docs/development/s01-offline-run.md)、[S02-A](docs/development/s02-highs.md)、[S03](docs/development/s03-plugins.md)及[S04-A](docs/development/s04-container.md)。本地 LLM 凭据保存在 Git 忽略的 `.env`，变量名见 [.env.example](.env.example)。S05-A 文本 Provider 优先加载配置目录的 `.env`，不存在时加载当前工作目录的 `.env`；进程环境优先。Mock 不读取凭据文件。

### 批量实验与报告

```bash
llm4om benchmark --config examples/specs/experiment.yaml --output runs/experiment
llm4om report --experiment runs/experiment
```

配置和支持范围见[批量实验记录](docs/development/s08-benchmark.md)；批量实验使用 CLI，Web 工作台面向单问题交互（HTTP 实验接口仍在，见[S09-B](docs/development/s09-batch-web.md)）。

## 1.0 目标

- 可插拔接入自动建模方法与不同 LLM，二者独立配置。
- 将自然语言、表格数据和任务配置规范化为统一问题输入。
- 输出可检查的数学模型、代码、假设、需求映射和执行证据。
- 默认按集合、参数、变量、目标和约束组织 Formulation，Code 阶段生成或编译到兼容后端。
- 同时支持结构化 LP/MILP IR 和已有方法的原生代码产物。
- 统一调度求解、隔离执行、预算控制、反馈修正与批量评测。
- 保留问题、插件、数据、模型、配置和运行轨迹的版本与来源。

1.0 的可靠执行范围是 **LP/MILP**；通用扩展接口不等于已经支持任意优化问题。后续版本可以增加非线性、约束规划、不确定性优化、算法选择和算法设计。

## 阅读顺序

| 文档 | 内容 |
|---|---|
| [文档体系与阅读导航](docs/README.md) | 需求说明、需求分析、需求规格、架构、详细设计与验证的关系 |
| [需求分析](docs/requirements/analysis.md) | 已确认目标、领域任务、需求来源、优先级与设计追踪 |
| [需求规格](docs/requirements/v1.0.md) | 用户、范围、场景、功能需求、非功能需求与发布标准 |
| [领域术语](GLOSSARY.md) | 方法、模型、建模语言、求解器、基准与评估证据的统一定义 |
| [架构设计](docs/architecture.md) | 模块职责、插件接入、数据流、执行与恢复 |
| [详细设计](docs/detailed-design.md) | 单问题运行、反馈修正、产物与数据绑定、实验、CLI/Web 的执行细节 |
| [插件与数据契约](docs/plugin-contracts.md) | 接口、核心数据结构、能力声明、兼容性与错误语义 |
| [评测协议](docs/evaluation.md) | 正确性层次、分母、容差、预算、公平比较与数据污染控制 |
| [开发计划](docs/implementation-plan.md) | 可独立验收的开发切片、依赖关系与首批适配矩阵 |
| [验收清单](docs/acceptance.md) | 端到端场景、契约测试、发布证据与需求追踪 |
| [研究综述](docs/research-landscape.md) | 代表性方法、benchmark、评测路线与平台设计依据 |
| [参考资料库](docs/references/README.md) | 论文、代码、数据与出版记录；配套 BibTeX 和机器可读目录 |
| [源码考察记录](docs/references/source-inspection.md) | 固定提交、实际入口、表示与适配分析 |
| [决策与待定项](docs/decisions-and-open-questions.md) | 用户明确要求、设计默认值、后续需确认的事项 |
| [示例规格](examples/README.md) | 一份可手工核验的 MILP 问题、IR、参考解和实验配置 |
| [规格校验记录](docs/spec-validation.md) | 文档链接、编号、JSON/YAML 与手算 fixture 的审阅结果 |
| [开发规范](CODING_STANDARDS.md)与 [贡献流程](CONTRIBUTING.md) | 模块设计、纵向任务、公共入口测试与审阅 |
| [逐文件整理记录](docs/repository-audit.md) | 当前文件职责、事实来源与核验方式 |

## 取消与恢复

S04-B 已通过最新完整回归与独立审查，见 [实现记录](docs/development/s04-resume.md)。

```bash
llm4om cancel --run-id RUN_ID --output runs
llm4om resume --run-id RUN_ID --output runs
llm4om resume --run-id RUN_ID --output runs --strategy rerun
```

SDK 使用 CancellationToken／cancel_run／resume_run，CLI SIGINT 走同一取消路径。
恢复保留原 run、预算与 deadline，复用已完成模型调用和匹配求解记录；未知 HTTP 结果不重发。
不支持内部 checkpoint 且无已完成阶段时，默认 continue 明确拒绝。显式 rerun 创建新运行并保留父历史、累计费用与未知预留；可产生新付费请求，累计预算上限仍有效。支持范围与证据见 [S04-B](docs/development/s04-resume.md)。

## 开发约定

每个插件必须声明能力和兼容矩阵，不允许自动降级后仍把结果标成原方法；每个评估结论必须说明证据级别。**求解器报告最优，只表示候选模型被求解，不证明模型符合业务需求。**

已完成 S01／S02-A／S02-B／S03／S04-A／S04-B／S05-A／S05-B／S07-A／S06-A 当前范围；后续工作与依赖见 [开发计划](docs/implementation-plan.md)。变更功能范围或契约时同步更新规格、示例和验收清单。详细贡献约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 本地 NL4Opt 导入与单样本评测（S07-A）

导入固定官方 snapshot，不自动下载。将 [导入配置](examples/tasks/nl4opt-import.yaml)
复制到本地 competition snapshot 根目录，已有 `generation_data/dev.jsonl` 的原始字节须匹配配置 hash。

```bash
uv run --locked llm4om import --config /path/to/snapshot/nl4opt-import.yaml --output runs/nl4opt-dev
uv run --locked llm4om run --problem runs/nl4opt-dev/public/-640645082.json --config /path/to/public-run.yaml
uv run --locked llm4om evaluate --manifest runs/nl4opt-dev/manifest.json --case-id 'nl4opt:49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea:dev:-640645082' --run runs/RUN_ID --output runs/evaluation-RUN_ID.json
```

运行配置使用现有 Direct／文本 Provider／容器接口，见 [S05-A](docs/development/s05-provider.md)。
SDK 导出 `import_dataset`、`NL4OptAdapter`、`EvaluationCase`、`TaskAdapter`、`Evaluator`、
`NL4OptEvaluator` 和 `evaluate_case`；已有 `run_problem` 直接接受 case 的公开问题路径。
只导出 `public/` 和公开 run bundle；manifest 与 `private/` 留在导入／评测端。
原始标注不是参考最优值。数值目标评测不可用，eligible 分母为零，候选求解证据独立保存。
实际外部模型样本与独立审阅后修复已验收；数值参考条件与其余范围见 [实现证据](docs/development/s07-nl4opt.md)。

## 切片实现索引

各能力的实现记录与验收证据；版本号为对应 SDK／Worker 开发版本。

### 建模方法

- Direct（默认五元素 Formulation，LPIR／python_factory／native 输出）：见快速开始配置与 [S01](docs/development/s01-offline-run.md)。
- 参数化工厂（S02-B）：`output_mode: python_factory` 与版本化独立方法 Code proposal。公开 CSV bytes 按 data ID 传入 `build_model(data)`；只在容器子进程构建 Pyomo ModelHandle，可信 Worker 校验导出实例后独立调用 HiGHS。换数据／revision 可复用相同工厂源模板。旧 LPIR、trusted_local 与独立安装 fixture 行为保持，见 [契约](docs/plugin-contracts.md#10-s02-b-parameterized-factory-interface-sdk-050)与[本地验收记录](docs/development/s02b-factory.md)。
- [公共候选评估](docs/development/s05-public-candidates.md)（0.15.0）：来源链与最终选择。
- [反馈修正方法](docs/development/s05-feedback-repair.md)（0.16.0）：解析失败入账、阶段变化、Code-only 来源复用和共享预算。
- [澄清流程](docs/development/s05-clarification.md)（0.17.0）：显式交互、原声明确认和新问题修订；非交互任务保留 unresolved，不从隐藏答案补齐。
- [角色模型覆盖](docs/development/s05-role-models.md)（0.14.0）与共享预算。
- 固定 OptiMUS 流程见 [S06-B](docs/development/s06b-optimus.md)与[源码考察](docs/development/s06b-optimus-source.md)；CoE 专家路由与原生函数见 [S06-C](docs/development/s06-coe.md)与[源码考察](docs/development/s06c-coe-source.md)。

### 求解与执行

- Gurobi 与原生 Code（S06-A）：LPIR→Pyomo→Gurobi、参数化 Pyomo→Gurobi 和 native gurobipy→Gurobi。真实 SDK 13.0.3 与无许可证挂载的 Linux Docker 已验证微型 LP/MILP；当前实际 availability 为 size_limited，不代表完整学术／商业许可证或 1.0 完成。基础 SDK 可不安装 Gurobi，通过容器运行；选中宿主求解则需可选 gurobi extra。`output_mode: native_gurobipy` 对应 gurobipy Backend／Gurobi Solver／container。原生源码和 Formulation 保留，可信 Worker 重新读取 SDK MPS 并独立求解；提取视图不证明语义。见 [S06-A 实现记录](docs/development/s06-gurobi.md)与[契约](docs/plugin-contracts.md#11-s06-a-gurobi-and-native-code-sdk-060)。

```bash
uv sync --locked --extra dev --extra solve --extra gurobi
uv run --locked --all-extras python scripts/build_worker_image.py
uv run --locked llm4om doctor --config examples/specs/gurobi.yaml
uv run --locked llm4om run --problem examples/specs/problem.json --config examples/specs/gurobi.yaml
```

- 取消与恢复（S04-B）：命令与语义见上文[取消与恢复](#取消与恢复)章节及[实现记录](docs/development/s04-resume.md)。
- Web 并发应用进程与合作取消见 [S09 进程隔离](docs/development/s09-process-isolation.md)。
- 插件注册：[独立文本 Provider](docs/development/s03-provider-registry.md)（0.18.0）、[独立 Task／Evaluator](docs/development/s03-task-registry.md)（0.19.0）、[独立 Compiler](docs/development/s03-compiler-registry.md)（0.20.0）、[Backend／Solver 共同注册](docs/development/s03-solver-registry.md)（0.21.0）、[数据加载与有限视图](docs/development/s03-data-loader.md)（0.22.0）、[Reporter](docs/development/s03-reporters.md)、[可安装 Executor](docs/development/s03-executor-registry.md)与[可安装 ArtifactStore](docs/development/s03-store-registry.md)（完成全部插件种类的共同注册）。
- [显式连通性检查](docs/development/s03-connectivity.md)（0.35.0）：`llm4om doctor --config RUN_CONFIG --check-connectivity`，默认关闭、只读模型目录、不发起文本生成；网页配置区有对应开关。

### 任务基准与评测

- NL4Opt（S07-A）：导入固定官方 snapshot，不自动下载；只导出 `public/` 和公开 run bundle，manifest 与 `private/` 留在导入／评测端。原始标注不是参考最优值，数值目标评测不可用时 eligible 分母为零。导入与单样本评测命令见[实现证据](docs/development/s07-nl4opt.md)。
- [NLP4LP Task／Evaluation](docs/development/s07-nlp4lp.md)（0.11.0）：完整保留 361 个公开描述与参数，参考缺失／损坏分别记录，资格按公开问题与数据评阅冻结。
- [MAMO Task／Evaluation](docs/development/s07-mamo.md)（0.10.0）：保留全部优化问题、公开题面资格评阅和私有数值答案，单样本失败仍计入分母。
- [原问题独立检查器](docs/development/s07-checkers.md)（0.12.0）：独立可行性、原目标重算与有限探测。

### Web 工作台

- 本地 Web 首版见 [S09-A](docs/development/s09-web.md)；网页接口已真实调用指定 DeepSeek 并经容器 HiGHS 求得 13。
- 批量提交、进度、逐样本结果和公共报告下载见 [S09-B](docs/development/s09-batch-web.md)：HTTP 接口保留并由 API 测试覆盖；页面入口已从工作台移除（2026-10-13），日常批量实验走 `llm4om benchmark`／`report` CLI。
- 人工派生编辑见 [S09-C](docs/development/s09-assisted-edits.md)：CLI 使用 `llm4om edit` 导出文档并执行新版本，网页使用“编辑并创建派生版本”；父产物和预算保留，结果明确标记人工辅助。
- [S09 用户体验](docs/development/s09-user-experience.md)：决策试算、候选修正浏览、运行版本选择；数值表单编辑后复用 Compiler／Solver 创建人工辅助版本，保留父记录与累计预算。
- [S09-D 前端重构](docs/development/s09-frontend-redesign.md)：React + Vite + TypeScript 构建链、垂直故事流、结构化结果区与起点页、人话失败诊断、统一设计令牌与键盘可达；后端契约零改动。
- 已保存的单问题可用 `llm4om report --run runs/RUN_ID` 重新呈现，不重调模型／Solver。

### 网络

- 模型接口需要本机 HTTP 代理时，可在服务端 `.env` 填写 `LLM4OM_LLM_PROXY_URL=http://127.0.0.1:7890`。CLI／SDK 使用 LLM 配置的 `proxy_url`；默认仍为直连。地址不包含代理凭据，实际支持见 [显式代理](docs/development/s05-explicit-proxy.md)。
