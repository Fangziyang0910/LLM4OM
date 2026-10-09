# 调研、需求与设计校验记录

日期：2026-10-09；设计基线：0.4.0。本记录验证科研设计、维护工具与 S01／S02-A／S03／S04-A 实现；完整平台验收由 [AC 清单](acceptance.md)维护。实际范围见 [S01](development/s01-offline-run.md)／[S02-A](development/s02-highs.md)／[S03](development/s03-plugins.md)／[S04-A](development/s04-container.md)。

## 1. 可复算的当前命令

在仓库根目录运行，依赖见 [贡献流程](../CONTRIBUTING.md)：

```bash
uv sync --locked --extra dev --extra solve
uv run --locked --extra dev --extra solve mypy
uv run --locked python scripts/build_worker_image.py
uv run --locked --extra dev --extra solve python scripts/render_references.py --check
uv run --locked --extra dev --extra solve python scripts/check_repository.py
uv run --locked --extra dev --extra solve python -m unittest discover -s tests -v
uv build
git diff --check
```

S01 交付时的结果：参考导出与 69 个源文件校验通过；7 个运行模块的 strict mypy 通过；39 个测试通过（12 个维护 CLI＋27 个平台 CLI）。Python 3.12.3 与 3.11.13 两个独立环境分别运行全部 39 个测试及类型检查，均通过。sdist／wheel 构建通过；wheel 在干净的 Python 3.12.3 环境安装后，从仓库外工作目录分别运行 console script 和 SDK，均返回 artifact_ready。diff 空白检查通过。

S02-A 交付结果：76 个源文件与参考导出通过检查；9 个模块的 strict mypy 通过。Python 3.12.3／3.11.13 分别运行完整 57 个测试，均通过（12 个维护 CLI、27 个离线 CLI、7 个真实求解 CLI、11 个编译／Solver）。solve extra 锁定 Pyomo 6.10.1／highspy 1.15.1；缺 Solver 的独立基础环境仍验证稳定 admission 失败，原离线测试全部保留。

S03 当前结果：86 个源文件检查通过，12 个模块在 Python 3.12.3／3.11.13 的 strict mypy 通过；两个环境分别完整 77 tests passed（原 57 项＋20 项安装／方法／预检 CLI／SDK 行为）。独立方法通过真实 wheel 构建／安装发现，不 mock entry_points。SDK 0.2.0 的 sdist／wheel 构建通过；干净基础安装在仓库外验证离线 doctor／SDK，真实 doctor 在缺 solve extra 时稳定拒绝。安装 solve extra 和独立方法 wheel 后，从仓库外验证发现、doctor、CLI 与 SDK，均得到目标 20、A=3／B=2；完整审阅记录见第 8 节。

S04-A 首次提交结果：93 个源文件、参考导出与 diff 检查通过。Python 3.12.3／3.11.13 各完整 104 tests passed（原 77＋23 Executor＋4 CLI／Worker），各有 14 个模块通过 strict mypy。Docker 29.6.2 的真实测试没有跳过；控制 daemon 卡住另用外部 CLI fixture。SDK 0.3.0 的 sdist／wheel 及公开 Worker 构建命令通过；只安装基础 wheel 的干净宿主没有 Pyomo，仍从仓库外通过 doctor、CLI 和 SDK 得到容器中的目标 13。Worker 为 Python 3.12.15、Pyomo 6.10.1、highspy 1.15.1，镜像 ID 为 sha256:80a5620effb216e176c17e5567d9bb4dd4fafab1a6974d5b485af6df6637ea32。每次运行自己的 admission／execution 记录是其镜像事实来源。独立审阅与修复见第 9 节。

sdist／wheel 构建通过，wheel 在干净的 Python 3.12.3 环境安装后，从仓库外运行 console script 和 SDK，均 completed；真实结果为目标 13、A=3／B=2。项目内演示 run_id 为 `cc1b7c7366a4451d9e6512a84fa668ce`，产物位于忽略的 runs 目录；LP=40/3、常数／域／失败状态另有独立微型测试。公开运行产物扫描不含凭据／oracle sentinel。`.env` 权限为 0600，被 Git 忽略，未提交。

测试从 CLI 与公开文件观察行为；维护负例在临时仓库副本运行。没有调用运行模块的私有函数或以内部 mock 关系作验收。代码提交 6ffde5d 的 [push CI](https://github.com/Fangziyang0910/LLM4OM/actions/runs/37878496065) 与 [PR CI](https://github.com/Fangziyang0910/LLM4OM/actions/runs/37878529552) 已在 GitHub runner 完成，Python 3.11／3.12 两个 job 均 success。交付分支为 codex/s02-highs，草稿 [PR #2](https://github.com/Fangziyang0910/LLM4OM/pull/2) 关联 Issue #1。

## 2. 文档与任务结构

- 当前 41 份 Markdown、9 份 JSON、5 份 YAML 文件均进入检查；所有源文件进入 [逐文件记录](repository-audit.md)。本地链接、标题／显式锚点、围栏、UTF-8、LF 和结尾换行通过检查。
- 36 FR、12 NFR、25 AC 编号连续且无重复。LP/MILP 执行范围保留；首批方法调整为 direct／OptiMUS／CoE，基准调整为 NL4Opt／NLP4LP／MAMO LP/MILP 子集。
- DD-01～DD-08 用于需求追踪，详细设计按方法、执行、实验／入口分支读取。
- S01～S10 保持阶段编号，拆为 24 个纵向任务。每项有可观察结果、公共测试入口与直接 blockers；S01 已完成离线工程范围；S02-A 已完成严格 IR 与真实 HiGHS 范围；S03 当前方法发现／预检已完成；S04-A 已完成当前 grounded 容器范围；当前前沿见开发计划。
- AGENTS 只有一个 Agent skills 块；glossary 是领域定义来源，四份简短 ADR 记录当前取舍，ADR-0004 明确两阶段选择。
- 5 个 Mermaid 图块的源码围栏已检查。本次没有运行专用渲染器。

已删除重复领域入口 CONTEXT.md，所有当前定义和阅读指针直接使用 GLOSSARY。未实现草案的迁移说明已移除，版本验收聚焦拒绝不支持的声明版本与固定评测口径。

## 3. 配置与数学 fixture

JSON 检查拒绝重复键、NaN／Infinity 与格式漂移。四份示例 YAML 使用 safe_load；三个 direct 配置与独立工程方法分别按各自 Manifest 的 JSON Schema 验证。预算的计数、正数墙钟时间、至少一个并发及实验 repeats 按契约核对。

单问题 run.yaml／solve.yaml／plugin-run.yaml 没有 task、methods 列表、experiment_id、repeats 或 oracle_path。三个原配置使用同一 direct 参数；plugin-run.yaml 使用独立工程方法；四份配置均为统一的 Mock response_artifact。Mock 来源和隐藏参考入口分别标识。

核心对象／配置／Manifest 使用草案 0.2.0，LPIR 保持 0.1.0。新增五元素 Formulation 与共同封装，源问题／表述／IR 引用的 hash、大小、revision 和 schema 一致。源 fixture 的 Code 为 pending；S02-A 在运行目录中产生 available 的真实 CodeArtifact，不改写人工源文件。

数据 hash 与模型绑定一致。维护工具以 CSV 为独立依据核对 IR 系数与资源约束，枚举固定两产品问题的整数点：最优 A=3/B=2、目标 13。LP 松弛 A=B=8/3、目标 40/3；使用可行点与非负对偶权重 4/3、1/3 核对相同上下界。

交换利润后，候选选择 A=2/B=3、自报目标 13；按原利润为 12。该反例用于检查绑定和评测口径。expected-evaluation 仍是预期断言，semantic_equivalence 为 not_available；oracle 中的通用检查器实现仍为 planned。

测试覆盖正常仓库，以及坏链接、数据 hash 改变、重复 JSON 键、非法方法配置、错误目标绑定、零并发、参考导出漂移、缺少逐文件记录、缺失五元素字段和错误阶段引用 hash、已删除跟踪文件。它们验证维护行为，不计作真实 LLM／Solver 测试。

LICENSE、NOTICE 与两份 CSV 的 SHA-256 和整理前快照一致；具体值见整理记录。

## 4. 科研来源与生成导出

catalog 中的 29 个资料 ID 和 citation_key 唯一；资料页与 29 个 BibTeX 条目来自同一来源，检查模式拒绝陈旧导出。BibTeX 键与括号结构一致。

原调研核验过程保留：25 项相关 arXiv 元数据、三项其他官方记录；同名 OptiBench 分开；匿名投稿缺失作者与发表决定保持未核验；无关 arXiv 2409.16709 未进入目录。四个系统及 OptiMUS 0.3 分支的固定提交、读取范围与许可观察见 [源码记录](references/source-inspection.md)。

本轮补充 OptiDSL 方法／评测及 PDF 附录提示，复核 LLMOPT 五元素／Code 模板、NLP4LP 作者数据卡和 MAMO README，补读 CoE 固定提交的 main.py／ProgrammingExpert。原资料的引用键、作者、年份、身份和固定提交保留，阅读范围按实际增补；没有重跑论文实验。研究出处与读取失败见 [检索记录](references/search-log.md)。

## 5. 验证边界

维护工具验证科研设计与 fixture；平台测试验证 S01 离线、S02-A 严格 IR／真实 HiGHS，以及 S03 独立方法安装／预检。真实 Provider、Gurobi、隔离、完整预算执行、恢复与方法效果仍须按 AC 验证。维护工具的数学核验只针对固定生产实例；运行编译器另行校验通用的当前 grounded LPIR 结构。五元素与 LPIR 是人工示例，未实现自由文本到 IR 的转换，也不提供一般语义等价证明。

S01 交付时 GitHub CLI 返回 HTTP 401。用户重新登录后已验证仓库读取、ADMIN 权限和 PRIVATE 可见性，并按 to-tickets 将 S02-A 发布为 [Issue #1](https://github.com/Fangziyang0910/LLM4OM/issues/1)，使用 enhancement／ready-for-agent 标签。没有变更仓库可见性；Git 提交与同步状态以仓库记录为准。设计基线此前采用作者自查；S01 实现新增两个独立只读审阅进程，结果见下一节。

## 6. 独立审阅与修复

审阅比较 `da360913…` 与首次实现 `147c1c4`。Standards 和 Spec 使用分别初始化的 Codex CLI 进程，互不共享审阅结论；均只读，没有发布消息或修改仓库。以下分别保留每路发现，重叠项不合并排序。

### Standards

首次审阅报告四项硬问题，没有额外有意义的 smell：

1. P1：client_secret、reference_model 等字段能进入公开问题。契约要求 metadata 不含 oracle 或模型秘密。已在持久化前拒绝已声明 oracle 字段和凭据别名，CLI 负例检查整个公开目录不含 sentinel。
2. P2：只有 ID 的变量／约束仍收到 structural pass。已要求集合、参数、变量和约束的结构内容，并检查索引集合与数据来源列。
3. P2：optional_views 中的 fixture 引用没有投影到运行目录。S01 已拒绝未支持的额外引用；provenance、trace 和 IR 同样检查。
4. P2：产物写入 OSError 被归为 invalid_input，CLI 退出 1。已将输入读取转为领域错误，并保留存储 OSError 给 SDK／CLI；通过 OS 文件系统边界注入单次 rename 失败验证退出 2，不 mock 内部模块。

### Spec

首次审阅报告五项 P2，没有额外范围：

1. symlink 循环使可写存储中只留下 start event，没有 RunBundle。已把路径解析错误转为 unsafe_path，并验证失败 bundle。
2. 附加视图可保留越界或失效引用。已拒绝未支持引用，覆盖模型封装与附加字段。
3. 同数据 hash 的外问题／revision IR 能被接受。已同时核对 IR 的 problem_id 和 problem_revision。
4. 五元素内部内容缺失仍标为结构通过。已补齐结构要求；结构检查没有增加数学语义正确的声明。
5. max_solver_calls=0 被拒绝，与非负计数契约不符。已允许零次求解／token 预算；实际需要的 Mock attempt 与 candidate 槽分别 admission。

全部发现都有公共 CLI 回归证据。作者另外修正数值型 CSV 主键的等价去重，避免整数 1 与 1.0 被当成不同键。初次独立审阅没有重跑完整测试或真实资源测试；修复后的工程验证使用本记录第 1 节命令。

复核分别确认 Standards 三项已修复、Spec 四项已修复，并共同指出参数 null／空来源列仍需校验。后续已限制参数字面值为有限数值或数值表，拒绝 null／boolean 叶子与空来源列；CLI 同时验证数值 0 和完整数值表合法。公开 metadata 的未声明字段在保存前拒绝，遵循新增业务字段经版本化的约定。这些最后修复经作者自查与新增 CLI 回归验证，没有再次启动独立审阅。

## 7. S02-A 独立审阅与修复

两个独立 Codex CLI 只读进程分别审 Standards 和 Spec，固定比较 `32adf6f…4822a1c`，规格来自 Issue #1 和已批准 S02-A。两路没有共享发现或修改文件，后续工作区修复排除在初次结论之外。审阅者均运行 10 个首次提交的编译／Solver 测试及独立边界探针；只读沙箱不允许临时文件，因此没有重跑 CLI／存储测试。以下按两个轴分别保存结论和修复。

### Standards

4 项规范问题，另有 1 项判断性 smell：

1. P2：整数界转 double 丢失精度，固定 9007199254740993 的变量返回了 9007199254740992。违反契约的界保持。编译现在校验整数字面值可准确表示，失败为 invalid_ir。
2. P2：time_limit_s=10**400 使公共 Solver 抛裸 OverflowError。违反边界错误语义。现在捕获转换溢出，返回 invalid_solver_options。
3. P3：S02 交付证据实际仍指向 S01。违反可复查交付要求。已增加本切片环境、完整测试、构建、真实运行和两路审阅记录。
4. P3：README 同时声称 S02-A 已完成和“下一步 S02-A”。违反单一事实来源。已改为当前开发计划指针。
5. 判断性 Possible Duplicated Code：应用两处重复写 evaluation.json。现按最终阶段状态写一次，未新增包装 Module。

### Spec

4 项规格问题；未发现额外范围：

1. P2：重复项 9007199254740993 与 -9007199254740992 被先转 double，和从 1 变成 0。违反重复项保持。现在整数项用整数求和，不能准确转换的输入／合并结果拒绝；浮点项保留 fsum。
2. P2：不可用的 MIP dual bound 默认值 0 被导出。违反“缺少解不制造数值”。现在检查原生 MIP 统计是否实际可用，不可用 bound／gap 为 null。
3. P3：time_limit_s=2147483648 失败，而相同 float 成功。违反有效选项执行。现在以有限 double 秒数调用 HiGHS，原请求仍留在结果中。
4. P2：本切片缺少实际交付证据。已补齐，完整 1.0 未验证项仍保持未完成。

Standards 共 5 项、Spec 共 4 项，分别保留，均已处理。实际回归在公共 CLI／Compiler／Solver 完成，不以私有函数或内部 mock 作验收。作者另增加极小非零目标系数 admission：原生容差可能让 max 1e-12·x（无上界）报告 optimal，当前明确拒绝这一数值范围。

初次独立结论针对 4822a1c；后续修复由作者运行公共回归、两版本完整检查和最终 wheel 验证，没有再次启动独立审阅。

## 8. S03 独立审阅与修复

Standards／Spec 使用两个独立只读 Codex CLI 进程，固定比较 7a0d78c…b8e66dd，规格来自工作项 #3／#4 和已批准 S03-A／B。审阅者检查已提交源码，后续修复不计入初次结论；使用内存 entry point／CLI／SDK 探针，不重跑需要临时写盘的安装和完整测试。

### Standards

3 项规范问题，另有 1 项判断性 smell：

1. P2：悬空本地 schema 引用与无进展递归使 doctor 抛裸异常。违反边界错误语义。发现阶段现检查本地引用是否解析，配置评估时将解析／递归异常转为 invalid_plugin_manifest。
2. P2：factory.create 缺少依赖被归为 method_error／formulation。违反构造错误的依赖／配置语义。构造与 run 分开处理，ImportError／OSError 为 dependency_missing，其余构造错误为 invalid_config，阶段为 admission。
3. P3：负例通过精确替换示例方法源码注入错误，内部变量改名会使注入失效。违反行为测试应经得住内部重构。负例现独立构建错误方法／factory，仍通过真实 wheel 安装与同一公开 CLI／SDK 观察行为。
4. 判断性 Possible Duplicated Code：成功测试与 configured_run 重复配置／运行逻辑。已复用 helper，不新增生产抽象。

### Spec

4 项问题；未发现额外范围：

1. P2：悬空 schema 引用让 doctor 失去 JSON 报告。已补本地引用检查及稳定 admission 错误，覆盖悬空与递归场景。
2. P2：admission 失败未保存请求方法与参数。现保存经 JSON／私有字段检查的 requested-config.json，并在失败／成功 bundle 中保留 requested_config_ref；预检仍在方法调用之前。
3. P2：describe 错误缺少异常类别与脱敏 frame。import／describe／create／run 现复用安全诊断，发现错误另关联 entry point；不保存错误参数和源码行，Python 输出被抑制。
4. P3：S03 审阅证据仍指向待补章节。现补齐实际两路发现、修复、验证范围及独立安装证据。源码没有伪报真实 LLM、原生路径或容器已实现。

Standards 共 4 项、Spec 共 4 项，分别保留并已处理；最后修复由作者在公开入口回归，未再次启动独立审阅。S03 工程示例 run_id 为 3c8f0b29cadb42d38038a4f9c9e22d14，来源为独立方法 0.1.0、SDK 0.2.0 和人工 Mock；目标偏移有意为 20，语义验证为 not_available。GitHub #4 已用 native blocked_by 关联 #3；没有关闭或修改父工作项。

S03 代码提交 b5b3ef5 的 [push CI](https://github.com/Fangziyang0910/LLM4OM/actions/runs/37884375652) 已 success；草稿 [PR #5](https://github.com/Fangziyang0910/LLM4OM/pull/5) 基于 S02 的 codex/s02-highs，独立展示 S03 差异。PR CI 的最终状态以 GitHub Checks 为准。

## 9. S04-A 独立审阅与修复

两个独立只读 Codex CLI 进程分别审 Standards／Spec，固定比较 79f8966…aee19ab。规格为已批准 S04-A 和 Issue #6；两路没有共享发现或编辑源码。只读环境没有 Docker 权限；审阅者采用源码与纯内存探针，真实 Docker 和完整测试由作者执行。

### Standards

2 项规范问题，另有 1 项判断性 smell：

1. P2：应用没有校验 Worker 求解响应版本及必需字段，把不完整的 999.0.0 响应改标为 0.2.0。违反契约第 6 节的版本校验、第 3.7 节的 SolveResult 必需字段及边界校验规范。现在先校验 envelope、运行时、求解身份／字段／解可用性和资源；非法响应为 worker_protocol_error，不生成 SolveResult。公共 CLI 负例覆盖未知版本和正确版本的缺字段响应，保留 ExecutionResult。
2. P2：inspect 未读到 OOMKilled 时默认 false。违反缺失测量不可伪造的规则。现在初始值为 null，实际观察后才保存 boolean；已有 timeout＋inspect 卡住负例先失败，再验证未知 OOM 与其他诊断共同保留。
3. 判断性 Possible Duplicated Code：构建器与 Executor 重复定义默认镜像。构建器现复用已有 DEFAULT_IMAGE，避免版本更新时不同步。

### Spec

2 项证据缺口；未发现额外范围或明确的隔离实现错误：

1. P2：“真实 fixture 验证网络、越界读写”缺少实际宿主私有读取目标。已在公开暂存目录外创建可读的人工 sentinel，真实容器分别尝试绝对路径、/input/.. 和 /proc/1/root 路径，均不能读取；公开输出不含 sentinel。
2. P2：“终止后清理容器／子进程”只覆盖单进程 timeout 和主动回收的 fork fixture。真实 timeout fixture 现在创建两个仍在睡眠的子进程，再强制终止；验证容器被删除及下一任务正常运行。

Standards 共 3 项、Spec 共 2 项，分别保留并已处理。后续修复由作者通过公共 CLI／Executor 回归；没有再次启动独立审阅。

修复后 Python 3.12.3／3.11.13 各完整 105 tests passed（77 原有＋23 Executor＋5 CLI／Worker），两环境的 14 个模块 strict mypy、93 个源文件、参考导出、diff 检查及 sdist／wheel 构建均通过。公开构建 CLI 已生成修复后镜像 sha256:faa2fd3bace65ed53ca6a19e101661ccbcfb6d496a43256ea58fafce8ba5e912。干净基础 wheel 安装从仓库外得到目标 13，run_id 为 9ef42f257cc24c9ba28080d7da64982e；执行证据确认该镜像、无 OOM 和无控制／清理诊断。真实测试后没有遗留带 llm4om.execution 标签的容器。取消／恢复、完整运行预算、真实 LLM、原生路径与完整 1.0 均未标为验收完成。
