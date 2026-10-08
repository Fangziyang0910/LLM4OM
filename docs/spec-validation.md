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

本次结果：参考导出与 69 个源文件校验通过；7 个运行模块的 strict mypy 通过；28 个测试通过（12 个维护 CLI＋16 个平台 CLI）。Python 3.12.3 与 3.11.13 两个独立环境分别运行全部 28 个测试及类型检查，均通过。sdist／wheel 构建通过；wheel 在干净的 Python 3.12.3 环境安装后，从仓库外工作目录分别运行 console script 和 SDK，均返回 artifact_ready。diff 空白检查通过。

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

GitHub CLI 的仓库与标签读取返回 HTTP 401，远程标签尚未核验。本地 tracker／triage 配置已保存；Git 提交与同步状态以仓库记录为准，可见性保持原设置。Standards／Spec 本次采用作者自查与工具验证，没有运行独立审阅代理。
