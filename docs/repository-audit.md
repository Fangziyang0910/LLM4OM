# 仓库文件职责与核验索引

日期：2026-10-10；SDK／Worker 开发版本：0.23.0。当前包含 226 个源文件；切片验收范围见各实现记录，完整1.0尚在开发。

规范由 [CODING_STANDARDS](../CODING_STANDARDS.md)维护，任务流程由 [CONTRIBUTING](../CONTRIBUTING.md)维护。文件按当前职责组织；生成文件只修改来源并重建。

## 1. 当前文件

| 文件 | 职责／事实来源 | 核验方式与保留理由 |
|---|---|---|
| `.editorconfig` | 编辑器格式 | UTF-8、LF、缩进；授权原文例外 |
| `docs/development/s05-clarification.md` | 澄清、原声明确认与显式修订的实际支持 | CLI／SDK、真实Solver、父历史与恢复证据 |
| `src/llm4om/clarification.py` | 公开请求、锚点与回答的信任边界 | 有界／唯一／原文绑定、确认与新信息分开 |
| `tests/test_clarification.py` | 公共交互、修订及落盘恢复验收 | HTTP、HiGHS、拒绝、unresolved与OS硬退出 |
| `docs/development/s05-public-candidates.md` | 公共候选评估、来源链、预算与最终选择的实际范围 | 本机 CLI／HiGHS／容器、恢复证据与剩余 S05-C 范围 |
| `tests/test_candidate_feedback.py` | 安装方法使用候选资源的公共行为验收 | 真实 HiGHS、预算、身份、最终选择、硬退出与 publication 恢复 |
| `docs/development/s05-feedback-repair.md` | 公共反馈修正方法、阶段来源与验收范围 | 本机 HTTP／真实 Solver、预算、声明比较和恢复证据 |
| `examples/specs/feedback-repair.yaml` | 外部文本模型的反馈修正配置 | 显式 Provider／模型、共享预算、真实隔离及无密钥模板 |
| `src/llm4om/feedback_repair.py` | 项目自编的有界公开反馈方法 | 共用 Direct 输出约定、候选资源、无 oracle 选择与版本化状态 |
| `tests/test_feedback_repair.py` | CLI 的真实修正流程验收 | HTTP／HiGHS／Gurobi、失败入账、代码修复、约束变化与崩溃重放 |
| `.env.example` | 本地 LLM 凭据变量模板 | 无真实密钥；S05-A 非执行加载，进程环境优先 |
| `.gitattributes` | Git 文本格式 | 全部当前文本类型使用 LF |
| `.github/ISSUE_TEMPLATE/feature-spec.md` | 功能规格入口 | 完整 spec 字段、用户故事与公共测试入口 |
| `.github/ISSUE_TEMPLATE/vertical-slice.md` | 纵向工作项入口 | parent、行为、验收与实际 blockers |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 交付入口 | Summary、Evidence、Door／Blast Radius |
| `.github/workflows/checks.yml` | 平台 CI | 仅手动触发；本机验收为主。Python 3.11／3.12；构建 Worker、真实隔离／HiGHS、锁定依赖、类型、仓库和包构建 |
| `.gitignore` | 本地与运行产物边界 | 密钥、运行数据、缓存、下载材料保持忽略 |
| `AGENTS.md` | 常驻项目约束与技能路由 | 保留科研项目约束；单个 Agent skills 块与按需指针 |
| `CODING_STANDARDS.md` | 开发规范 | 深模块、真实 Seam、单一来源、格式、测试与 review |
| `CONTRIBUTING.md` | 任务生命周期与维护命令 | 规格→纵向任务→公共测试→review→交付 |
| `GLOSSARY.md` | 领域定义的唯一来源 | single-context；短定义与 Avoid；不含实现待办 |
| `LICENSE` | Apache-2.0 授权原文 | 与整理前 SHA-256 一致 |
| `NOTICE` | 项目归属与第三方声明 | 与整理前 SHA-256 一致 |
| `README.md` | 项目概览与阅读入口 | 产品主线、S01／S02-A 实际命令与后续能力分别说明 |
| `docs/README.md` | 文档责任与阅读分支 | 软件工程与科研文档职责；按任务读取 |
| `docs/acceptance.md` | 平台验收与需求追踪 | 保留 AC-01～25 和未执行清单；阶段引用仍有效 |
| `docs/adr/0001-dual-artifact-paths.md` | 双产物路径取舍 | 三句背景／选择／原因符合 ADR 规范 |
| `docs/adr/0002-oracle-isolation.md` | 参考材料隔离取舍 | 简短 ADR；记录权限边界 |
| `docs/adr/0003-independent-plugin-axes.md` | 独立变化维度取舍 | 简短 ADR；记录配置与职责决定 |
| `docs/adr/0004-formulation-and-code.md` | 两阶段及默认五元素取舍 | 阶段分别观察，保留方法策略与严格 IR 语义 |
| `docs/agents/domain.md` | 领域文档路由 | 根 glossary＋ADR；契约字段独立维护 |
| `docs/agents/issue-tracker.md` | GitHub Issues 操作配置 | 指定仓库、正文文件、依赖前沿、认证失败处理 |
| `docs/agents/triage-labels.md` | triage 标签配置 | 五种状态、类别／状态规则、AI 来源声明 |
| `docs/agents/workflow.md` | 按任务选择技能 | 触发条件与结果；不强制运行所有技能 |
| `docs/architecture.md` | 系统职责与数据流 | 目标接口、真实变化维度、分层依赖与 ADR 指针 |
| `docs/decisions-and-open-questions.md` | 用户要求与工程默认值 | 确认设置、真实待验证条件；去掉重复变更历史 |
| `docs/design/execution.md` | DD-03/04/05 插件与求解 | 完整搬迁；相对链接调整，字段转向契约 |
| `docs/design/experiments-and-interfaces.md` | DD-06/07/08 实验、恢复和入口 | 完整搬迁；批量与 Web 使用同一应用流程 |
| `docs/design/modeling-methods.md` | DD-01/02 时序与方法策略 | 完整搬迁；方法内部选择与公开反馈规则 |
| `docs/detailed-design.md` | 详细设计索引与需求编号 | DD-01～08 用于需求追踪，按需进入三个页面 |
| `docs/development/s01-offline-run.md` | S01 实现与交付记录 | 实际支持范围、CLI／SDK、证据与下一可执行任务 |
| `docs/development/s02-highs.md` | S02-A 实现与真实证据 | 严格 IR、Pyomo／HiGHS、trusted_local、实际状态与未验证条件 |
| `docs/development/s03-plugins.md` | S03 实现与运行 profile | 独立安装、兼容预检、真实方法来源、SDK 和未实现范围 |
| `docs/development/s05-provider.md` | S05-A 实现与真实验收记录 | 文本 Provider、compact 输出、资源恢复、实际外部模型与本机验收 |
| `docs/development/s06-gurobi-research.md` | S06-A 官方 API／许可证研究与独立临时 SDK 实测 | PyPI 13.0.3、真实 LP/MILP、MPS 往返、无解时限和 10010 受限许可证证据；运行材料留在 /tmp |
| `docs/development/s07-nl4opt.md` | S07-A 固定来源与真实单样本验收 | 官方固定提交、文件／记录 hash、参考可用性、公共测试与真实外部模型样本 |
| `docs/evaluation.md` | 指标、证据与分母的唯一来源 | 公开检查／隐藏协议、失败分母、未知成本保持原口径 |
| `docs/implementation-plan.md` | 本地纵向任务与 blocking edges | 24 个任务；首个 CLI、独立 Web、真实支持验收 |
| `docs/plugin-contracts.md` | 接口、字段、版本和错误的唯一来源 | 目标 Protocol、小 Interface、能力与错误语义；统一术语 |
| `docs/references/README.md` | 生成的逐项资料页 | 由 catalog 渲染；事实、链接、阅读范围与未知状态 |
| `docs/references/catalog.json` | 书目元数据与注释的唯一来源 | 29 项；新增生成字段来自原资料；数字／身份／引用键保留 |
| `docs/references/references.bib` | 生成的引用导出 | 同一 catalog；完整作者、出版字段、引用键与括号校验 |
| `docs/references/search-log.md` | 研究出处与读取限制 | 可核验记录：查询批次、更正、不可用项和证据范围 |
| `docs/references/source-inspection.md` | 固定提交源码观察 | 可核验记录：考察范围与真实接入状态分别说明 |
| `docs/repository-audit.md` | 当前文件职责与核验索引 | 全部仓库源文件有一行；后续新增同步记录 |
| `docs/requirements/analysis.md` | 需求来源与领域分析 | 保留科研机制、设计追踪、研究引用与核心问题 |
| `docs/requirements/v1.0.md` | 产品范围和 FR/NFR 唯一来源 | 36 FR／12 NFR；软件工程格式与领域表述并存 |
| `docs/research-landscape.md` | 机制比较与设计依据 | 论文观察、源码观察与设计判断分开；保持来源 |
| `docs/spec-validation.md` | 校验证据与适用范围 | 当前可复算命令；不将维护工具当作平台验收 |
| `examples/README.md` | fixture 用法与独立数学依据 | 方法输入权限、工程 Mock、绑定反例与维护命令 |
| `examples/plugins/fixture_method/README.md` | 独立方法安装与运行说明 | 实际命令、目标偏移用途和公开接口 |
| `examples/plugins/fixture_method/pyproject.toml` | 独立方法包与 entry point | SDK >=0.7.0,<0.9.0 依赖、自己的版本／构建和发现入口 |
| `examples/plugins/fixture_method/src/llm4om_fixture_method/__init__.py` | 第二个实际 Method Adapter | 独立配置、async run、目标常数变体、cooperative 取消与内部 checkpoint 拒绝 |
| `examples/plugins/fixture_method/src/llm4om_fixture_method/manifest.json` | 独立方法 Manifest | 当前能力、配置 schema、工程来源和变体 |
| `examples/specs/data/capacities.csv` | 原始容量数据 | 固定字节、表头和 hash；独立整数／LP 核验 |
| `examples/specs/data/products.csv` | 原始利润和资源数据 | 固定字节、表头和 hash；作为独立绑定依据 |
| `examples/specs/expected-evaluation.json` | 预期断言 | 两阶段预期断言；不是实际 run；semantic not_available |
| `examples/specs/experiment.yaml` | benchmark 配置草案 | 安全加载、direct 参数 schema、私有 oracle 入口 |
| `examples/specs/formulation.json` | 五元素数学表述 | 0.2.0 核心对象；关联人工 LPIR，未声称从文本编译 |
| `examples/specs/model-artifact.json` | 两阶段共同封装 | 表述可用、Code 待生成；源文件引用含 hash／大小 |
| `examples/specs/model-ir.json` | 人工 grounded LPIR | 两空格布局；变量域、数据绑定、系数和引用核验 |
| `examples/specs/oracle.json` | 私有参考规格 | 两空格布局；参考数值与规则说明；checker 仍 planned |
| `examples/specs/plugin-manifest.json` | direct 能力与配置草案 | 0.2.0 能力与阶段配置；JSON Schema 拒绝不支持模式 |
| `examples/specs/plugin-run.yaml` | S03 独立方法运行配置 | 安装后使用当前公开输入，目标常数偏移明确标记 |
| `examples/specs/problem.json` | 公开问题规格 | 两空格布局；revision、需求与数据 hash 核验 |
| `examples/specs/run.yaml` | S01 单问题配置 | --offline 回放两阶段封装；无实验／oracle 字段 |
| `examples/specs/solve.yaml` | S02-A 真实求解配置 | 显式 trusted_local，人工表述／IR 与真实 HiGHS 分别标明 |
| `docker/worker.Dockerfile` | 可信 Worker 镜像 | 固定基础 digest、带 hash 依赖和 SDK wheel；无源码／密钥构建上下文 |
| `docs/development/s04-container.md` | S04-A 交付记录 | 实际容器流程、资源／权限、真实故障测试与支持边界 |
| `pyproject.toml` | 包与依赖声明 | 运行／开发依赖、CLI 入口、类型检查与源码布局 |
| `scripts/build_worker_image.py` | 公开镜像构建 CLI | 临时上下文只包含固定 wheel、依赖和 Dockerfile；真实镜像构建验证 |
| `scripts/check_repository.py` | 仓库公开校验 CLI | 格式、链接、JSON、配置、数学、编号、引用与覆盖 |
| `scripts/render_references.py` | 公开参考资料生成 CLI | catalog 生成两份导出；check 模式只读 |
| `src/llm4om/__init__.py` | 公开应用导出 | RunResult／run_problem；CLI 与后续 Web 共用入口 |
| `src/llm4om/__main__.py` | 模块 CLI 入口 | 与安装后的 console script 使用同一命令 |
| `src/llm4om/tasks.py` | S07-A 公共 Task/Evaluation 接口与固定 NL4Opt 快照 | CLI/SDK 导入、来源身份、hash、重复 ID、隔离测试 |
| `src/llm4om/evaluation.py` | S07-A 单样本后置评测 | 公共运行结果、Code 实际来源、失败、checker error、零 eligible 与无 oracle 导出 |
| `tests/test_task_evaluation.py` | S07-A 公共接口验收 | 独立 fixture 身份、实际 HTTP／Docker／HiGHS、篡改与失败记录 |
| `examples/tasks/nl4opt-import.yaml` | 官方固定 dev split 的本地导入配置 | 已下载源字节 hash；路径以配置目录为根，不自动 fetch |
| `src/llm4om/application.py` | 单问题应用流程 | 公开输入、候选与阶段原子完成事件；共用引用图校验，恢复完整 Formulation 及 Execution 的实际产物／绑定／Solver 证据 |
| `src/llm4om/cli.py` | 用户 CLI | 参数解析、离线显式选择、JSON 摘要与退出码 |
| `src/llm4om/contracts.py` | 运行边界校验 | 严格 JSON／YAML、CSV、路径、引用、五元素、输入绑定与 Worker 响应 |
| `src/llm4om/executors.py` | 真实容器执行 Module | 公共 bytes、权限与资源、有界控制／清理、真实限制证据 |
| `src/llm4om/highs.py` | 真实 Solver 边界 | Pyomo 线性表示转原生 HiGHS；域、数值阈值、状态、解与版本 |
| `src/llm4om/linear.py` | 严格 IR 公共编译入口 | 结构／数值校验、重复项合并、固定工厂与 symbol map |
| `src/llm4om/mock.py` | 离线方法响应读取 | 明确 fixture、来源与数据 revision；不执行代码或读取参考答案 |
| `src/llm4om/methods.py` | 当前方法公共 profile | ModelProposal／MethodOutcome／Context／LLMResponse 和实际 direct Adapter |
| `src/llm4om/plugins.py` | 方法发现与运行 Module | 动态 factory、版本／唯一键、JSON schema、同步／异步桥接与脱敏异常 |
| `src/llm4om/preflight.py` | 共用运行 admission | 方法配置、实际能力、依赖、预算和固定计划；不发 Provider HTTP 请求 |
| `src/llm4om/providers.py` | Provider 与共享 Gateway | 公共 HTTP seam、literal 凭据加载、原子资源／恢复和私有回复 |
| `src/llm4om/storage.py` | 运行文件存储 | 独占目录、祖先项 fsync、不可变引用与中断发布收据；不解释 Execution／Solve 语义 |
| `src/llm4om/worker.py` | 镜像可信入口 | 严格 IR／实际代码 hash 核对、后端 API 求解、资源测量 |
| `tests/test_cli_run.py` | S01 公共 CLI 行为测试 | 成功、失败、数据、路径、引用、配置、隐私、报告和存储 |
| `tests/test_container_executor.py` | S04-A 公共 Executor 测试 | 真实网络／文件／资源／清理；控制命令外部 fixture 验证有限返回 |
| `tests/test_container_run.py` | S04-A 公共 CLI／Worker 测试 | 真实目标 13、代码替换拒绝、超限保留证据而无伪造解 |
| `tests/test_linear_solver.py` | 编译／Solver 公共行为测试 | 独立微型 LP/MILP，真实常数、域、状态和数值拒绝 |
| `tests/test_plugins.py` | S03 公共 CLI／SDK 行为测试 | 真实独立包构建／安装、预检、预算、坏输出、来源与异常 |
| `tests/test_provider.py` | S05-A 公共 Provider／Gateway 测试 | 本地 HTTP、预算／隐私；公共 MethodPlugin 未保存 checkpoint 修改不污染资源提交 |
| `tests/test_provider_pipeline.py` | S05-A 公共 CLI 测试 | 未付费 doctor admission、MILP=13／无数据 LP 的 HTTP fixture 到真实 HiGHS、截断与嵌套配置凭据 |
| `tests/test_repository_checks.py` | 维护工具公共入口测试 | 临时副本；坏链接、hash、配置、绑定、重复键、引用漂移、五元素与阶段引用 |
| `tests/test_solve_run.py` | S02-A 公共 CLI 行为测试 | 真实 MILP／LP、缺依赖、预算、失败阶段与证据引用 |
| `uv.lock` | 完整依赖解析 | 由 uv 生成；PyPI 来源、版本和校验值；locked 安装 |

## 2. 授权原文与固定数据

以下 SHA-256 标识当前固定输入：

- `LICENSE`：`c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4`。
- `NOTICE`：`c28123c11d0a85232717650c2f69dfc3286ea4a99a24c7d775c8455c82b4279e`。
- `examples/specs/data/products.csv`：`74ad23f699830b8bbf6d32948c9ff9209fc39ff9ddbaa5c64c97140850249064`。
- `examples/specs/data/capacities.csv`：`3aa7ec045769676457aa38cd1732b78fcd4b6926aa1db9916cc453cb6dfaaf47`。

## 3. Standards 与 Spec 核对

Standards：glossary 统一定义，ADR 记录四项实际取舍，代理按任务读取分支文档。详细设计分为方法、执行、实验与入口三个页面；资料以 catalog 为来源；维护工具通过公开 CLI 验证。

Spec：需求覆盖 36 FR、12 NFR、25 AC 与 DD-01～08。建模按 Formulation／Code 记录，默认五元素；原生表述、严格 IR 和代码保留真实来源。首批方法为 direct／OptiMUS／CoE，主要使用通用外部 LLM；基准为 NL4Opt／NLP4LP／MAMO 的 LP/MILP 子集。24 个开发任务有公共测试入口和直接 blockers。

这是作者自查与工具核验。实际命令、结果、研究读取范围和未验证条件统一记录于 [校验记录](spec-validation.md)。

## 4. 维护规则

新增或删除源文件时同步本表，检查工具拒绝漏项与陈旧路径。领域定义、字段契约、评测口径和工作流程分别在其事实来源维护；当前草案可以直接修正，无需兼容未实现的旧设计。

| `src/llm4om/backends.py` | Worker-local ModelHandle／Pyomo 与 native gurobipy 构建及模型导出 | CLI/SDK 的真实容器验收；域／表达式／决策映射失败 |
| `src/llm4om/factory_worker.py` | 隔离工厂子进程与可信选中 Solver 收集器 | 原始 bytes／hash、父进程保护、有界子输出、重新校验与独立求解 |
| `tests/test_factory_run.py` | S02-B 公开 CLI/SDK 验收 | HTTP fixture、真实 Docker/HiGHS、独立安装方法、revision、伪造攻击与失败保留 |
| `examples/factories/production.py` | 真正按公开 CSV 构建模型的参数化工厂 fixture | 同源模板交换利润改变整数解；明确手工来源 |
| `docs/adr/0005-factory-collector-isolation.md` | 工厂构建与求解证据隔离取舍 | 子进程导出、可信重构求解、不声称语义等价 |
| `docs/development/s02b-factory.md` | S02-B 实现、验收与实际限制 | 公共 seams 的 red/green、Docker 数值证据、已完成外部模型／重绑定与独立审阅后修复 |

| `src/llm4om/gurobi.py` | 可选实际 Gurobi LP/MILP API、许可证微型分类与原生 MPS 读取／检查 | Solver/Backend 手算 LP/MILP、真实状态、原生结构／map、派生视图 |
| `src/llm4om/solvers.py` | 两个实际 Solver 的选择与依赖 runtime | 同一 CLI/SDK 与 Worker 的 HiGHS/Gurobi 路径，无空 registry |
| `tests/test_gurobi_solver.py` | 真实 SDK 的 Solver／Backend 行为 | 手算常数／域／range、结构拒绝、真实 infeasible/unbounded/time_limit 与 incumbent |
| `tests/test_gurobi_run.py` | Gurobi 的 CLI/SDK／隔离 Worker 验收 | 三路径、数据绑定、原生来源、可信结果、攻击／资源失败与提前拒绝 |
| `examples/factories/production_gurobi.py` | 手工 native gurobipy 参数化 fixture | 公开 CSV／显式每变量 map，保留源码，不自报解 |
| `examples/specs/gurobi.yaml` | 当前可运行人工 Mock LPIR→容器 Gurobi 配置 | doctor/run 目标13；实际 size_limited，不调用外部 LLM |
| `docs/development/s06-gurobi.md` | S06-A 实现、支持矩阵和真实环境边界 | CLI/SDK、Backend/Solver 与 Executor 本地验收，报告／证据在任务目录 |
| `docs/development/s07-benchmark-research.md` | S07-B/C NLP4LP／MAMO 固定来源与字段考察 | 实际提交、文件 hash、样本数量、公开／私有投影、参考损坏与评测边界；MAMO／NLP4LP 后续实现与验收分别见 S07-C／B |

| `src/llm4om/control.py` | S04-B 协作 CancellationToken 与私有异步监督 | run／owner 身份绑定、CLI／SDK 控制文件，不向宿主 PID 发信号 |
| `tests/test_resume_run.py` | S04-B CLI／SDK／Provider HTTP／Executor 行为 | 取消、SIGINT、真实 Docker 清理、成功／未知回复、阶段复用、锁、损坏与 deadline |
| `docs/development/s04-resume.md` | S04-B 当前实现与本机验收范围 | 公开入口、checkpoint／预算／身份、默认拒绝／显式派生及实际支持边界 |
| `docs/development/s06b-optimus-source.md` | 固定 OptiMUS 0.3 主流程、提示、原生输出与适配接缝研究 | 19 份源码／文档 hash、16 份检索资源 hash、真实默认模式与 paper/source 区分；实现与验收见 S06-B 记录 |
| `docs/development/s06c-coe-source.md` | 固定 CoE 角色路由、协作／反思、函数输出与输入分类研究 | 30 份源文件 hash、真实选择／反馈语义、无许可材料的观察与原生接口需求；未集成 |
| `tests/test_resume_crash.py` | S04-B 真实硬崩溃与派生恢复 | CLI／SDK、独立安装无 checkpoint Method、合成 HTTP、OS fsync／rename；Formulation／Code 完成提交、早期产物与 Execution 复用、收据保留及累计资源 |
| `tests/test_async_control.py` | 公共 Method 任务监督行为 | 取消等待清理、SystemExit 诊断与 Python 3.11 兼容 |
| `docs/development/s05b-anthropic-research.md` | Anthropic Messages 官方协议与已配置服务的真实小探针 | 同一指定模型、Messages HTTP200、真实 usage／未知成本、私有原始回复；仅探针证据，实现另见 S05-B |

| `tests/test_anthropic.py` | S05-B 独立 Messages 协议与应用行为 | 真实 loopback HTTP、CLI/SDK、OS 硬退出、未知用量／预算、凭据回显与损坏拒绝 |
| `examples/specs/messages.yaml` | Messages 文本配置模板 | 指定模型、占位 HTTPS 端点、共同预算与 container 路径；doctor 不付费 |
| `docs/development/s05b-messages.md` | S05-B 实现与实际支持 | 本地 red/green、SDK/Worker 版本与真实验收／独立审查的待办边界 |

| `src/llm4om/method_resources.py` | 运行拥有的脚本执行、预算、公开 artifact/event 与执行复用 | SDK 合成 HTTP＋实际 Gurobi，取消／结果收据／未知执行 |
| `src/llm4om/optimus.py` | 固定 OptiMUS main 方法适配与 Gateway／资源驱动 | 实际固定 main 的同 tape 六状态／提示／修正／选择对照 |
| `src/llm4om/optimus_runtime.py` | 受控固定源码加载与资源桥、独立 main 对照 | 原始 hash、公共输入、提示状态与 execution tape |
| `src/llm4om/script_worker.py` | 原生脚本隔离执行与不可信 capture | 真实容器、source 诊断、MPS 捕获与新 collector 独立求解 |
| `docs/development/s06b-optimus.md` | S06-B 开发实现与证据范围 | 实际支持、固定源码差异、本机验收及剩余条件 |
| `examples/optimus/README.md` | OptiMUS 公开微型问题操作说明 | 明确付费流程、人工数学预期、占位端点和本地配置 |
| `examples/optimus/problem.json` | 公开人工 MILP 规格 | ProblemSpec0.3.0、JSON 数据 hash 与公开来源 |
| `examples/optimus/params.json` | 公开参数元数据与数值 | 保留 value／shape／definition 与手算目标12 |
| `examples/optimus/labels.json` | 公开人工领域与问题类型标签 | 明确公开来源，无 oracle 推导 |
| `examples/optimus/run.yaml` | OptiMUS 容器／外部文本 LLM 配置模板 | 明确 no-RAG、Solver/修正预算与占位 Provider 端点 |
| `tests/test_optimus_method.py` | 固定源码流程忠实度 | 公共 MethodContext、实际 main 同 tape、quirks／修正／最终选择 |
| `tests/test_optimus_run.py` | OptiMUS SDK 本机端到端验收 | 合成 HTTP、实际 Gurobi／Docker、预算、取消和未知／完整恢复 |
| `tests/test_public_json.py` | JSON 公开数据与原生 Formulation 契约 | 原始 state、不合法键／数值／oracle／schema |
| `tests/test_script_worker.py` | 原生脚本 Worker 与可信 collector 公共行为 | 原始 bytes、多个模型拒绝、exit 诊断与独立 API 结果 |
| `src/llm4om/optimus_source/LICENSE.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/constraint.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/constraint_model.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/execute_code.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/generate_code.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/main.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/manifest.json` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/objective.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/objective_model.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/parameters.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/rag__rag_utils.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/target_code.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |
| `src/llm4om/optimus_source/utils.py.txt` | 固定 MIT 上游源码／提示／授权或 manifest | 固定 e182e9e 提交；逐文件原始 URL、SHA-256、大小，保留字节 |

| `src/llm4om/mamo.py` | MAMO 固定来源投影、公开资格评阅与私有数值比较 | SDK／CLI、原始 hash／ID／许可、真实 HiGHS、舍入／零答案／失败分母 |
| `tests/test_mamo.py` | MAMO Task／Evaluation 公开行为测试 | 导入隔离、选择／资格、损坏／缺失、真实求解与数值协议边界 |
| `docs/development/s07-mamo.md` | S07-C 实现与实际验收记录 | 来源／协议／真实 Solver 微型证据与剩余检查明确区分 |

| `src/llm4om/nlp4lp.py` | 固定 NLP4LP 导入、公开参数与私有参考、资格与数值评测 | 真实来源／ID／hash／类型／缺失损坏，SDK／CLI 与真实 Solver |
| `src/llm4om/nlp4lp_source.json` | 固定首方发布的自生成 hash／大小／URL 元数据 | 2,127文件固定提交；不含问题、答案或代码内容；固定 manifest hash |
| `src/llm4om/task_policy.py` | MAMO／NLP4LP 公开数学评阅与数值容差共用规则 | 公共问题／参数绑定、范围／舍入、原始参考不改写；实际边界回归 |
| `tests/test_nlp4lp.py` | NLP4LP Task／Evaluation 的公开行为验收 | nested JSON／类型／原始 bytes／私有隔离、故障、资格、真实 HiGHS与绑定 |
| `docs/development/s07-nlp4lp.md` | S07-B 实现与实际证据范围 | 来源／公开私有投影／指标分母／本机验收与剩余条件 |
| `docs/development/s07-checkers.md` | 原问题独立检查与有限探测实现 | 公共 Task/Evaluation、真实 Solver、分母与本机验收 |
| `examples/specs/import-checker.json` | 独立原问题生产任务导入配置 | 公开问题／私有 policy hash 与不可覆盖快照 |
| `src/llm4om/checker_tasks.py` | 冻结原问题任务与评测 | 私有映射／参考边界、分层状态、有限点与分母 |
| `src/llm4om/checkers.py` | 原问题检查与受信任扩展接口 | 独立 CSV／Decimal 规则、版本／来源与输出校验 |
| `tests/test_checker_evaluation.py` | 公共导入／评测与真实求解反例 | HiGHS／Gurobi、CLI 安装插件、错误状态与私有隔离 |
| `tests/test_checkers.py` | 独立原问题数学检查 | 原始业务域／容量／利润与多最优解 |
| `docs/development/s06-coe.md` | CoE 公开输入／执行／契约证据 | 公开 Source/Method/CLI/SDK／真实 Gurobi 验收；来源、参数与阶段独立记录 |
| `examples/coe/README.md` | CoE 公开输入／执行／契约证据 | 公开 Source/Method/CLI/SDK／真实 Gurobi 验收；来源、参数与阶段独立记录 |
| `examples/coe/data/capacities.csv` | CoE 公开输入／执行／契约证据 | 公开 Source/Method/CLI/SDK／真实 Gurobi 验收；来源、参数与阶段独立记录 |
| `examples/coe/data/products.csv` | CoE 公开输入／执行／契约证据 | 公开 Source/Method/CLI/SDK／真实 Gurobi 验收；来源、参数与阶段独立记录 |
| `examples/coe/problem.json` | CoE 公开输入／执行／契约证据 | 公开 Source/Method/CLI/SDK／真实 Gurobi 验收；来源、参数与阶段独立记录 |
| `examples/coe/public-interface.json` | CoE 公开输入／执行／契约证据 | 公开 Source/Method/CLI/SDK／真实 Gurobi 验收；来源、参数与阶段独立记录 |
| `examples/coe/run.yaml` | CoE 公开输入／执行／契约证据 | 公开 Source/Method/CLI/SDK／真实 Gurobi 验收；来源、参数与阶段独立记录 |
| `src/llm4om/coe.py` | CoE 原创流程与原生调用 | 公开 Source/Method/CLI/SDK／真实 Gurobi 验收；来源、参数与阶段独立记录 |
| `tests/test_coe_method.py` | CoE 公开输入／执行／契约证据 | 公开 Source/Method/CLI/SDK／真实 Gurobi 验收；来源、参数与阶段独立记录 |
| `tests/test_coe_run.py` | CoE 公开输入／执行／契约证据 | 公开 Source/Method/CLI/SDK／真实 Gurobi 验收；来源、参数与阶段独立记录 |
| `docs/development/s05-role-models.md` | 角色模型配置与共享资源证据 | 公共配置／Gateway／HTTP／SDK、身份与预算验收 |
| `tests/test_role_models.py` | 角色模型配置与共享资源证据 | 公共配置／Gateway／HTTP／SDK、身份与预算验收 |
| `tests/test_role_pipeline.py` | 角色模型配置与共享资源证据 | 公共配置／Gateway／HTTP／SDK、身份与预算验收 |

| `tests/test_provider_plugins.py` | 独立Provider公共入口验收 | CLI、HTTP、真实HiGHS、恢复与安全诊断 |
| `docs/development/s03-provider-registry.md` | Provider注册支持与本机证据 | 安装、协议、包身份与剩余范围 |
| `examples/plugins/fixture_provider/pyproject.toml` | 独立Provider包声明 | SDK版本、构建与共同entry point |
| `examples/plugins/fixture_provider/README.md` | 独立Provider安装说明 | 真实构建命令、配置与可信插件边界 |
| `examples/plugins/fixture_provider/src/llm4om_fixture_provider/__init__.py` | 独立文本协议Adapter | 共同Manifest、自有ID、已有HTTP/Gateway复用 |

| `src/llm4om/task_plugins.py` | 任务／评估注册、冻结选择与公共结果约束 | Registry、私有seal、字段／分母／安全错误 |
| `tests/test_task_plugins.py` | 独立安装任务与评分器的公共验收 | CLI／HiGHS、身份、私有字段、失败分母 |
| `docs/development/s03-task-registry.md` | Task／Evaluator切片范围及证据 | 实际接口、旧格式和剩余范围 |
| `examples/plugins/fixture_task/pyproject.toml` | 独立Task／Evaluator包 | SDK约束及共同entry points |
| `examples/plugins/fixture_task/README.md` | 独立benchmark插件用法 | 构建、配置hash、公开／私有边界 |
| `examples/plugins/fixture_task/src/llm4om_fixture_task/__init__.py` | 独立微型任务与数值比较器 | 原输入保留、隐藏参考和共同核验接口 |

| `src/llm4om/compilers.py` | Compiler选择、身份与输出校验 | 共同Registry、严格IR／语法／映射和安全错误 |
| `tests/test_compiler_plugins.py` | 独立Compiler公共行为验收 | CLI／真实HiGHS、Worker、包身份、能力和恢复 |
| `docs/development/s03-compiler-registry.md` | Compiler支持与本机证据 | 实际profile、可信镜像、检查范围和剩余条件 |
| `examples/plugins/fixture_compiler/pyproject.toml` | 独立Compiler包声明 | SDK版本约束、构建和共同entry point |
| `examples/plugins/fixture_compiler/README.md` | 独立Compiler使用说明 | 安装／选择／可信镜像和配置 |
| `examples/plugins/fixture_compiler/src/llm4om_fixture_compiler/__init__.py` | 独立源码格式Compiler | AST格式变换、明确配置、原数学转换复用 |

| `src/llm4om/execution_plugins.py` | Backend／Solver选择、兼容性与执行身份 | Manifest／配置、依赖环境、实际结果profile与安全错误 |
| `tests/test_backend_solver_plugins.py` | 构建／求解插件的公共行为验收 | 实际Handle／SDK、独立wheel／CLI／Worker |
| `docs/development/s03-solver-registry.md` | 构建／求解注册的开发状态 | 已接入路径、本机证据和未完成范围 |
| `examples/plugins/fixture_execution/pyproject.toml` | 独立Backend／Solver包声明 | SDK版本约束、共同entry points与构建 |
| `examples/plugins/fixture_execution/README.md` | 独立构建／求解插件操作说明 | 实际组件变换、配置及可信镜像 |
| `examples/plugins/fixture_execution/src/llm4om_fixture_execution/__init__.py` | 独立组件重命名与真实HiGHS插件 | 保持决策映射、检查配置组件后实际求解 |

| `docs/development/s03-data-loader.md` | DataLoader／有限视图的实际范围与证据 | CLI／SDK、真实原始绑定、来源与剩余验收 |
| `src/llm4om/data_loaders.py` | 公共bytes加载、限制与独立视图契约校验 | 原始格式／值／来源不改写；全数据与摘要区别 |
| `examples/specs/data-view.yaml` | 显式有限视图与真实HiGHS工程配置 | Mock输出与LLM准确率分开；原始数据绑定 |
| `examples/plugins/fixture_data_loader/README.md` | 独立加载器示例职责与配置 | 列顺序变化与原始bytes分别验收 |
| `examples/plugins/fixture_data_loader/pyproject.toml` | 独立wheel／entry point／SDK范围 | 真实安装与完整来源身份 |
| `examples/plugins/fixture_data_loader/src/llm4om_fixture_data_loader/__init__.py` | 真正改变CSV暴露列顺序的工程Adapter | 配置生效、路径无关输入、核心独立校验 |
| `tests/test_data_loader_plugins.py` | 公开数据加载与真实LLM视图验收 | HTTP、HiGHS／容器、原始检查、拒绝与恢复 |

| `src/llm4om/web.py` | 本地Web工作区与公共HTTP接口 | 复用核心运行／恢复、限制公开引用、凭据留服务端 |
| `src/llm4om/web_assets/index.html` | 结构化本地研究工作台 | 原生控件、问题／配置／阶段／候选与结果 |
| `src/llm4om/web_assets/app.js` | 公共接口调用与已保存结果展示 | 安全文本渲染、事件轮询、上传和控制 |
| `src/llm4om/web_assets/style.css` | 本地工作台布局与响应式样式 | 焦点、表格与阶段卡片；视觉验收继续补齐 |
| `docs/development/s09-web.md` | Web功能与真实运行支持记录 | 真实Provider／Solver与未验证范围分开 |

| `tests/test_web_bind.py` | 显式远程IPv4监听的公共HTTP行为 | 页面／bootstrap、同源检查、既有请求token |
| `src/llm4om/experiments.py` | 冻结批量调度与公共分组报告 | 独立进程、显式排除、硬预算、冻结分母与恢复 |
| `tests/test_experiments.py` | 公共批量运行行为 | 实际并发 HiGHS、原问题评估、分母、预算与输入漂移 |
| `examples/specs/benchmark-run.yaml` | 真实外部模型／HiGHS 批量配置 | 无凭据、显式资源与预算 |
| `docs/development/s08-benchmark.md` | 批量功能、使用入口与证据范围 | 接口与评测协议一致；剩余验收不冒称完成 |

| `tests/test_web_experiments.py` | 公共HTTP批量入口验收 | SyntheticProvider、真实HiGHS、原问题检查、报告与完成继续 |
| `docs/development/s09-batch-web.md` | 网页实验功能和实际支持 | 共同应用接口、私有边界、剩余验收 |

| `src/llm4om/assisted.py` | 公开编辑文档、共同Method适配和派生用例 | 父引用、原始数据、表示契约、预算与assisted来源 |
| `tests/test_assisted_edits.py` | SDK/CLI人工编辑行为 | 实际HiGHS/Gurobi、容器、父不可变、预算与负例 |
| `tests/test_web_assisted.py` | 公共HTTP编辑流程 | Problem revision、Code、实际Solver、请求计数与父记录 |
| `docs/development/s09-assisted-edits.md` | 人工修订使用与支持记录 | 契约、真实入口证据与未验收范围 |

| `tests/test_optimus_inline.py` | 明确输入变体的公共Method契约 | 固定main fidelity、空参数声明、原数据hash与原接口 |
| `examples/specs/optimus-inline.yaml` | 真实外部模型的inline-public配置 | 独立变体、公开输入、Gurobi与预算 |
| `docs/development/s08-common-input.md` | 共同输入与三基准比较证据 | 原始来源、预选子集、未提供指标与变体 |

| `docs/development/s09-process-isolation.md` | Web并发／取消功能与证据 | 共同应用入口、进程控制和待验收范围 |

| `scripts/acceptance_load.py` | 真实离线批量性能验收 | cgroup4vCPU／8GiB、直接基线、1000终态与P95 |
| `scripts/acceptance_faults.py` | 100个CLI任务的故障集合 | 合成HTTP／实际HiGHS、取消／显式重跑与父预算 |
| `docs/development/s08-load-acceptance.md` | 性能／故障证据与完成边界 | 原始记录、准确入口范围与剩余验收 |
