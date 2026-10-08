# 仓库文件职责与核验索引

日期：2026-10-08；文档修订：0.4.0。当前包含 58 个源文件，维护研究资料、需求与设计基线和文档工具；平台尚未实现。

规范由 [CODING_STANDARDS](../CODING_STANDARDS.md)维护，任务流程由 [CONTRIBUTING](../CONTRIBUTING.md)维护。文件按当前职责组织；生成文件只修改来源并重建。

## 1. 当前文件

| 文件 | 职责／事实来源 | 核验方式与保留理由 |
|---|---|---|
| `.editorconfig` | 编辑器格式 | UTF-8、LF、缩进；授权原文例外 |
| `.gitattributes` | Git 文本格式 | 全部当前文本类型使用 LF |
| `.github/ISSUE_TEMPLATE/feature-spec.md` | 功能规格入口 | 完整 spec 字段、用户故事与公共测试入口 |
| `.github/ISSUE_TEMPLATE/vertical-slice.md` | 纵向工作项入口 | parent、行为、验收与实际 blockers |
| `.github/PULL_REQUEST_TEMPLATE.md` | PR 交付入口 | Summary、Evidence、Door／Blast Radius |
| `.gitignore` | 本地与运行产物边界 | 密钥、运行数据、缓存、下载材料保持忽略 |
| `AGENTS.md` | 常驻项目约束与技能路由 | 保留科研项目约束；单个 Agent skills 块与按需指针 |
| `CODING_STANDARDS.md` | 开发规范 | 深模块、真实 Seam、单一来源、格式、测试与 review |
| `CONTRIBUTING.md` | 任务生命周期与维护命令 | 规格→纵向任务→公共测试→review→交付 |
| `GLOSSARY.md` | 领域定义的唯一来源 | single-context；短定义与 Avoid；不含实现待办 |
| `LICENSE` | Apache-2.0 授权原文 | 与整理前 SHA-256 一致 |
| `NOTICE` | 项目归属与第三方声明 | 与整理前 SHA-256 一致 |
| `README.md` | 项目概览与阅读入口 | 产品主线、当前可运行维护工具、未来平台命令分别说明 |
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
| `examples/specs/data/capacities.csv` | 原始容量数据 | 固定字节、表头和 hash；独立整数／LP 核验 |
| `examples/specs/data/products.csv` | 原始利润和资源数据 | 固定字节、表头和 hash；作为独立绑定依据 |
| `examples/specs/formulation.json` | 五元素数学表述 | 0.2.0 核心对象；关联人工 LPIR，未声称从文本编译 |
| `examples/specs/model-artifact.json` | 两阶段共同封装 | 表述可用、Code 待生成；源文件引用含 hash／大小 |
| `examples/specs/expected-evaluation.json` | 预期断言 | 两阶段预期断言；不是实际 run；semantic not_available |
| `examples/specs/experiment.yaml` | benchmark 配置草案 | 安全加载、direct 参数 schema、私有 oracle 入口 |
| `examples/specs/model-ir.json` | 人工 grounded LPIR | 两空格布局；变量域、数据绑定、系数和引用核验 |
| `examples/specs/oracle.json` | 私有参考规格 | 两空格布局；参考数值与规则说明；checker 仍 planned |
| `examples/specs/plugin-manifest.json` | direct 能力与配置草案 | 0.2.0 能力与阶段配置；JSON Schema 拒绝不支持模式 |
| `examples/specs/problem.json` | 公开问题规格 | 两空格布局；revision、需求与数据 hash 核验 |
| `examples/specs/run.yaml` | 单问题配置草案 | Mock 响应改为两阶段封装；无实验／oracle 字段 |
| `requirements-dev.txt` | 维护工具依赖 | 当前环境精确版本；与未来平台依赖分开 |
| `scripts/check_repository.py` | 仓库公开校验 CLI | 格式、链接、JSON、配置、数学、编号、引用与覆盖 |
| `scripts/render_references.py` | 公开参考资料生成 CLI | catalog 生成两份导出；check 模式只读 |
| `tests/test_repository_checks.py` | 维护工具公共入口测试 | 临时副本；坏链接、hash、配置、绑定、重复键、引用漂移、五元素与阶段引用 |

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
