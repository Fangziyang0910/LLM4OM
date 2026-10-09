# LLM4OM

**自动优化建模集成平台 · A modular platform for automated optimization modeling**

LLM4OM 是面向科研与开发者的自动优化建模集成平台。用户输入自然语言描述与可选数据，指定建模方法、LLM 和兼容求解配置，获得可检查的建模输出与求解结果。平台提供 CLI 与 Web 可视化工作台，持续接入不同 benchmark、建模方法和求解器，作为通用智能优化平台的 1.0。

核心流程：**问题描述与数据 → Formulation（数学表述）→ Code（求解实现）→ Solve → 决策结果与运行记录**。不同方法可以联合生成或往返修正两阶段输出；Benchmark 在同一流程上组织批量实验与方法比较。

**LLM4OM = Large Language Models for Optimization Modeling**，其中 `4` 表示 `for`，`OM` 表示 `Optimization Modeling`，与 LLM4AD 的命名方式对应。仓库名为 `LLM4OM`，Python 包名、命令名与插件命名空间采用 `llm4om`。

完整项目标题：**LLM4OM: A Unified Platform for Automated Optimization Modeling with Large Language Models**。

## 当前状态

已交付 **S01 离线回放、S02-A 真实 HiGHS、S02-B 参数化 Pyomo 工厂、S03 方法发现与预检、S04-A 容器执行、S05-A 真实文本 LLM、S07-A 原始 NL4Opt 导入／单样本评测、S06-A 微型真实 Gurobi／native gurobipy（Python 包 0.6.0，未发布）**，保留 1.0 需求与设计基线（文档修订 0.4.0）。CLI 读取问题与 CSV，回放人工 Mock 五元素表述，将伴随的严格 LPIR 编译为 Pyomo 实现并求解，保存阶段来源、数据 hash、解向量、事件和报告。独立安装的方法可经 entry point 发现并运行，doctor 与 run 共用兼容性和依赖预检。Web 与论文方法仍按开发计划接入。

仓库另有可运行的文档维护工具，检查链接、配置、fixture 和参考资料。它们的用法见 [CONTRIBUTING](CONTRIBUTING.md)，与未来平台命令分别管理。

S05-A 提供 文本 OpenAI-compatible Provider／Gateway 和 Direct 输出适配（最初交付包 0.4.0，当前 SDK 为 0.6.0，未发布）。已用指定外部模型与容器 HiGHS 跑通两个独立 LP/MILP 问题；完整回归与独立审阅记录见 [S05-A 实现记录](docs/development/s05-provider.md)。完整 1.0 任务范围保持不变。

GitHub 仓库当前为私有，项目按未来开源协作设计，采用 Apache-2.0。私有可见性与开源许可证分别管理。

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

## 当前可运行的示例

在仓库根目录执行，使用 Python 3.11／3.12：

```bash
uv sync --locked --extra dev --extra solve
uv run --locked python scripts/build_worker_image.py
uv run --locked --extra solve llm4om plugins list
uv run --locked llm4om doctor --config examples/specs/run.yaml
uv run --locked llm4om run --problem examples/specs/problem.json --config examples/specs/run.yaml
uv run --locked llm4om run --offline --problem examples/specs/problem.json --config examples/specs/run.yaml
```

CLI 输出 run_id、bundle_path 和 status。运行目录默认在 `runs/`；查看其中的 `bundle.json`、阶段产物、解向量和 `reports/report.md`。`--output PATH` 可覆盖存储根目录。真实 run 默认使用已构建的 Docker 镜像；solve.yaml 显式选择 trusted_local。两条路径真实得到 A=3、B=2、目标 13，状态 completed；offline run 的 artifact_ready 只表示离线产物已保存。这些配置的 Formulation 来自人工 Mock；外部 LLM 配置见 S05-A。候选求解成功不代表业务语义已验证。

CLI 和未来 Web 共用 `llm4om.run_problem` 应用入口。安装、SDK、支持范围与错误语义见 [S01](docs/development/s01-offline-run.md)、[S02-A](docs/development/s02-highs.md)、[S03](docs/development/s03-plugins.md)及 [S04-A](docs/development/s04-container.md)。本地 LLM 凭据保存在 Git 忽略的 `.env`，变量名见 [.env.example](.env.example)。S05-A 文本 Provider 优先加载配置目录的 `.env`，不存在时加载当前工作目录的 `.env`；进程环境优先。Mock 不读取凭据文件。

## 后续使用方式

以下命令仍是开发目标：

```bash
llm4om benchmark --config experiments/benchmark.yaml
llm4om resume --run-id RUN_ID
llm4om report --experiment-id EXPERIMENT_ID --format markdown
```

本地 Web 工作台将复用已有单问题应用入口。首批论文方法优先 `optimus` 和 `coe`，`direct` 提供工程对照，`feedback_repair` 为可选对照。模型主要使用通用外部 LLM，暂不集成任务专用训练权重；训练类工作的提示或建模流程可另作明确变体，未来专用模型仍走共同 LLM 接口。

首批基准为 NL4Opt、NLP4LP 和 MAMO 的 EasyLP／ComplexLP 中符合 LP/MILP 范围的实例。求解器仍为 HiGHS 与 Gurobi，建模后端为 Pyomo／gurobipy。具体方法与求解器组合见 [能力矩阵](docs/implementation-plan.md#1-首批能力矩阵)。

## 开发约定

每个插件必须声明能力和兼容矩阵，不允许自动降级后仍把结果标成原方法；每个评估结论必须说明证据级别。**求解器报告最优，只表示候选模型被求解，不证明模型符合业务需求。**

已完成 S01／S02-A／S02-B／S03／S04-A／S05-A／S07-A／S06-A 当前范围；当前前沿与后续依赖见 [开发计划](docs/implementation-plan.md)。变更功能范围或契约时同步更新规格、示例和验收清单。详细贡献约定见 [CONTRIBUTING.md](CONTRIBUTING.md)。

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

## 参数化工厂（S02-B）

S02-B 在 SDK／Worker 0.5.0 新增 Direct `output_mode: python_factory` 与版本化独立方法 Code proposal。
公开 CSV bytes 按 data ID 传入 `build_model(data)`；只在容器子进程构建 Pyomo ModelHandle，
可信 Worker 校验导出实例后独立调用 HiGHS。换数据／revision 可复用相同工厂源模板，形成新的
绑定与实际解。原 Formulation 与 method-generated Code 保留，提取实例不冒充语义证明。
旧 LPIR、trusted_local 与独立安装 fixture 行为保持。配置、工厂返回值与独立安装示例见
[契约](docs/plugin-contracts.md#10-s02-b-parameterized-factory-interface-sdk-050)及
[本地验收记录](docs/development/s02b-factory.md)；真实外部模型、重绑定与独立审阅后修复已验收，见该实现记录。


## Gurobi 与原生 Code（S06-A）

SDK／默认 Worker 0.6.0（未发布）支持 LPIR→Pyomo→Gurobi、参数化 Pyomo→Gurobi 和
native gurobipy→Gurobi。真实 SDK 13.0.3 与无许可证挂载的 Linux Docker 已验证微型 LP/MILP；
当前实际 availability 为 size_limited，不代表完整学术／商业许可证或 1.0 完成。

```bash
uv sync --locked --extra dev --extra solve --extra gurobi
uv run --locked python scripts/build_worker_image.py
uv run --locked llm4om doctor --config examples/specs/gurobi.yaml
uv run --locked llm4om run --problem examples/specs/problem.json --config examples/specs/gurobi.yaml
```

基础 SDK 可不安装 Gurobi，通过容器运行；选中宿主求解则需可选 gurobi extra。
Direct 的 `output_mode: native_gurobipy` 对应 gurobipy Backend／Gurobi Solver／container。
原生源码和 Formulation 保留，可信 Worker 重新读取 SDK MPS 并独立求解；提取视图不证明语义。
能力矩阵、公开 proposal／返回值、许可证分类和真实验收边界见
[S06-A 实现记录](docs/development/s06-gurobi.md)与[契约](docs/plugin-contracts.md#11-s06-a-gurobi-and-native-code-sdk-060)。
