# 调研、需求与设计校验记录

日期：2026-10-09；设计基线：0.4.0。本记录验证科研设计、维护工具与 S01 离线实现；完整平台验收由 [AC 清单](acceptance.md)维护。S01 范围与证据见 [实现记录](development/s01-offline-run.md)。

## 1. 可复算的当前命令

在仓库根目录运行，依赖见 [贡献流程](../CONTRIBUTING.md)：

```bash
uv sync --locked --extra dev
uv run --locked mypy
uv run --locked python scripts/render_references.py --check
uv run --locked python scripts/check_repository.py
uv run --locked python -m unittest discover -s tests -v
uv build
git diff --check
```

本次结果：参考导出与 69 个源文件校验通过；7 个运行模块的 strict mypy 通过；39 个测试通过（12 个维护 CLI＋27 个平台 CLI）。Python 3.12.3 与 3.11.13 两个独立环境分别运行全部 39 个测试及类型检查，均通过。sdist／wheel 构建通过；wheel 在干净的 Python 3.12.3 环境安装后，从仓库外工作目录分别运行 console script 和 SDK，均返回 artifact_ready。diff 空白检查通过。

测试从 CLI 与公开文件观察行为；维护负例在临时仓库副本运行。没有调用运行模块的私有函数或以内部 mock 关系作验收。CI 已配置相同 Python 矩阵，GitHub runner 尚未运行。

## 2. 文档与任务结构

- 当前 37 份 Markdown、8 份 JSON、3 份 YAML 文件均进入检查；所有源文件进入 [逐文件记录](repository-audit.md)。本地链接、标题／显式锚点、围栏、UTF-8、LF 和结尾换行通过检查。
- 36 FR、12 NFR、25 AC 编号连续且无重复。LP/MILP 执行范围保留；首批方法调整为 direct／OptiMUS／CoE，基准调整为 NL4Opt／NLP4LP／MAMO LP/MILP 子集。
- DD-01～DD-08 用于需求追踪，详细设计按方法、执行、实验／入口分支读取。
- S01～S10 保持阶段编号，拆为 24 个纵向任务。每项有可观察结果、公共测试入口与直接 blockers；S01 已完成离线工程范围；当前可执行前沿为 S02-A／S03-A。
- AGENTS 只有一个 Agent skills 块；glossary 是领域定义来源，四份简短 ADR 记录当前取舍，ADR-0004 明确两阶段选择。
- 5 个 Mermaid 图块的源码围栏已检查。本次没有运行专用渲染器。

已删除重复领域入口 CONTEXT.md，所有当前定义和阅读指针直接使用 GLOSSARY。未实现草案的迁移说明已移除，版本验收聚焦拒绝不支持的声明版本与固定评测口径。

## 3. 配置与数学 fixture

JSON 检查拒绝重复键、NaN／Infinity 与格式漂移。两份 YAML 使用 safe_load；direct 参数按 Manifest 的 JSON Schema 验证。预算的计数、正数墙钟时间、至少一个并发及实验 repeats 按契约核对。

单问题 run.yaml 没有 task、methods 列表、experiment_id、repeats 或 oracle_path。两份配置使用同一 direct 参数与统一的 Mock response_artifact 名称。Mock 来源和隐藏参考入口分别标识。

核心对象／配置／Manifest 使用草案 0.2.0，LPIR 保持 0.1.0。新增五元素 Formulation 与共同封装，源问题／表述／IR 引用的 hash、大小、revision 和 schema 一致。Code 当前为 pending，后续编译预期才为 available；没有生成实际 CodeArtifact。

数据 hash 与模型绑定一致。维护工具以 CSV 为独立依据核对 IR 系数与资源约束，枚举固定两产品问题的整数点：最优 A=3/B=2、目标 13。LP 松弛 A=B=8/3、目标 40/3；使用可行点与非负对偶权重 4/3、1/3 核对相同上下界。

交换利润后，候选选择 A=2/B=3、自报目标 13；按原利润为 12。该反例用于检查绑定和评测口径。expected-evaluation 仍是预期断言，semantic_equivalence 为 not_available；oracle 中的通用检查器实现仍为 planned。

测试覆盖正常仓库，以及坏链接、数据 hash 改变、重复 JSON 键、非法方法配置、错误目标绑定、零并发、参考导出漂移、缺少逐文件记录、缺失五元素字段和错误阶段引用 hash、已删除跟踪文件。它们验证维护行为，不计作真实 LLM／Solver 测试。

LICENSE、NOTICE 与两份 CSV 的 SHA-256 和整理前快照一致；具体值见整理记录。

## 4. 科研来源与生成导出

catalog 中的 29 个资料 ID 和 citation_key 唯一；资料页与 29 个 BibTeX 条目来自同一来源，检查模式拒绝陈旧导出。BibTeX 键与括号结构一致。

原调研核验过程保留：25 项相关 arXiv 元数据、三项其他官方记录；同名 OptiBench 分开；匿名投稿缺失作者与发表决定保持未核验；无关 arXiv 2409.16709 未进入目录。四个系统及 OptiMUS 0.3 分支的固定提交、读取范围与许可观察见 [源码记录](references/source-inspection.md)。

本轮补充 OptiDSL 方法／评测及 PDF 附录提示，复核 LLMOPT 五元素／Code 模板、NLP4LP 作者数据卡和 MAMO README，补读 CoE 固定提交的 main.py／ProgrammingExpert。原资料的引用键、作者、年份、身份和固定提交保留，阅读范围按实际增补；没有重跑论文实验。研究出处与读取失败见 [检索记录](references/search-log.md)。

## 5. 验证边界

维护工具验证科研设计与 fixture，平台 CLI 测试验证 S01 工程流程。真实 Provider／Solver 兼容、隔离、预算执行、恢复、编译语义与方法效果仍须在后续切片中按 AC 验证。Math fixture 检查仅针对这份固定生产实例，不提供一般 IR 验证器或语义等价证明。五元素与 LPIR 是同一问题的独立人工示例，不是已完成文本编译。

GitHub CLI 的仓库与标签读取返回 HTTP 401，远程标签尚未核验。本地 tracker／triage 配置已保存；Git 提交与同步状态以仓库记录为准，可见性保持原设置。设计基线此前采用作者自查；S01 实现新增两个独立只读审阅进程，结果见下一节。

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
