# 贡献与开发流程

本仓库维护 LLM4OM 的研究设计和平台实现。已交付 [S01](docs/development/s01-offline-run.md) 离线单问题流程与 [S02-A](docs/development/s02-highs.md) 真实 HiGHS 求解、[S03](docs/development/s03-plugins.md) 方法发现／预检及 [S04-A](docs/development/s04-container.md) 容器执行及 [S05-A](docs/development/s05-provider.md) 真实文本 LLM及 [S07-A](docs/development/s07-nl4opt.md) NL4Opt 导入／评测；每个任务交付可演示的纵向行为。[S02-B](docs/development/s02b-factory.md) 已实现参数化工厂的本地 CLI/SDK／容器验收，真实外部模型／重绑定与独立审阅后修复已验收。S06-A 新增实际微型 Gurobi／native Code，见 [实现记录](docs/development/s06-gurobi.md)。

SDK／Worker 0.8.0 已完成 [S04-B 取消／恢复](docs/development/s04-resume.md)和 [S05-B Messages](docs/development/s05b-messages.md)集成验收；241项本机回归与独立审阅通过，包未发布。

S06-B 已完成完整固定 OptiMUS 主流程的真实运行／本机回归；独立审阅仍待完成。支持与证据见 [实现记录](docs/development/s06b-optimus.md)。已验收0.8.0 基线与开发版本分别记录。

规范见 [CODING_STANDARDS](CODING_STANDARDS.md)，领域词见 [GLOSSARY](GLOSSARY.md)。按 [文档导航](docs/README.md)读取当前任务涉及的 FR/NFR、契约、详细设计与验收。方法或 benchmark 接入另读 [资料库](docs/references/README.md)及 [源码考察](docs/references/source-inspection.md)。

## 1. 从需求到工作项

新功能先明确问题、目标行为、用户故事、实现取舍、公共测试入口与范围。功能规格和工作项使用 [GitHub Issues 约定](docs/agents/issue-tracker.md)，引用仓库基线。已明确的文档修复和小范围维护可以直接执行。

规格按用户可观察结果拆成 tracer-bullet 切片。每个切片贯通需要的输入、处理和输出，独立验收；其阻塞项只列实际无法绕开的前置行为。选择依赖已完成、尚未领取的切片。父规格、子任务与验收证据相互关联。

远程创建、评论与状态迁移按当前用户请求或显式调用的技能进行。本地规划不等于已发布 issue；认证失败保留本地结果并说明失败操作。

## 2. 实现与研究接入

在编码前确定公共 Interface／Seam 和测试预期。新行为采用一个测试 red → 最小实现 green → 必要重构的小循环。测试从用户入口或真实公共契约观察结果；确定性 fixture 验证工程流程，真实 Provider／Solver 支持仍需真实验收。

实现复用已有模块，新增 Adapter 对应真实变化维度。Formulation／Code 的公共输入输出和真实来源分别检查；修改阶段语义时读 ADR-0004 和契约。改变领域词时更新 glossary；发生需要留存的架构取舍时写简短 ADR。字段、状态、版本或指标变化同步其事实来源、使用方、fixture 与验收项。

研究方法接入固定上游提交，记录提示、流程、预算和依赖差异。改变算法行为使用方法变体；忠实适配保留其实际输出和支持矩阵。第三方代码与数据记录来源和许可。论文元数据、未知状态和阅读范围在 catalog 中维护。

## 3. 开发与校验

当前平台使用 Python 3.11／3.12。依赖声明由 pyproject.toml 维护，完整解析由 uv.lock 固定；维护工具复用其中的 PyYAML／jsonschema。推荐执行：

```bash
uv sync --locked --extra dev --extra solve --extra gurobi
uv run --locked --extra dev --extra solve --extra gurobi mypy
uv run --locked python scripts/build_worker_image.py
uv build examples/plugins/fixture_execution --wheel --out-dir dist/fixtures
EXECUTION_TEST_IMAGE="$(uv run --locked python -c 'from llm4om.executors import DEFAULT_IMAGE; print(DEFAULT_IMAGE + "-with-execution")')"
uv run --locked python scripts/build_worker_image.py --tag "$EXECUTION_TEST_IMAGE" --plugin-wheel dist/fixtures/llm4om_fixture_execution-0.1.0-py3-none-any.whl
uv run --locked --extra dev --extra solve --extra gurobi python scripts/render_references.py --check
uv run --locked --extra dev --extra solve --extra gurobi python scripts/check_repository.py
uv run --locked --extra dev --extra solve --extra gurobi python -m unittest discover -s tests -v
uv build
```

修改 `docs/references/catalog.json` 后先运行 `uv run --locked --extra dev --extra solve --extra gurobi python scripts/render_references.py` 生成资料页与 BibTeX，再执行检查。JSON 使用两空格布局；CSV 和授权原文保持字节稳定。所有纳入仓库的文件都在 [逐文件整理记录](docs/repository-audit.md)中说明职责与校验方式，新增文件同步记录。

仓库检查覆盖文本格式、本地链接、JSON、示例配置、阶段引用、数据绑定、独立数学核验、参考资料导出与编号追踪。容器测试要求可访问的 Docker daemon 和已构建的 Worker 镜像；真实测试不自动跳过。Linux 为当前完整隔离验证环境，macOS／Windows 尚未验收。平台测试从 CLI／SDK 与编译／Solver 公共接口验证离线、真实求解、独立方法安装及预检；维护检查不替代真实隔离测试、完整预算执行、恢复或 benchmark 验收。基础安装可省略 solve extra，完整测试须安装 solve 与 gurobi extras；Gurobi 实测仅证明当前 size-limited 微型环境。

## 4. Review 与交付

Review 分开回答两个问题：Standards 是否符合开发规范和相关契约；Spec 是否完成用户要求或 issue。显式调用 code-review 时按技能执行独立审阅；若当前环境无法运行独立审阅者，说明实际采用的自查范围。

交付先完成对应检查，再报告变化、证据和剩余条件。PR 使用 [仓库模板](.github/PULL_REQUEST_TEMPLATE.md)说明 Summary、Evidence 与 Merge Danger。用户请求提交或 PR 时保存完整改动并关联工作项。日常验收以本机测试和真实 Provider／Solver 运行为依据。开发中验证新增行为及受影响路径；相关小切片集中到可使用的交付节点，再执行一次必要完整回归、类型／仓库检查和包构建。同一实现快照不重复源码、wheel或镜像验收；源码或执行身份发生变化、出现实际失败时，只重验受影响范围。每个交付节点先展示可使用的功能和实际运行结果。GitHub Actions 仅手动触发，供必要的环境交叉验证；push／PR 不自动重跑完整矩阵，也不将远程 CI 作为每次开发推进的门槛。发布标签与公开包发布依据真实验收和用户授权进行。

技能选择与触发条件见 [任务工作流](docs/agents/workflow.md)。常规实现选择无需额外审批；用户明确指令优先于工程默认值。

S07-C 的 SDK/Worker0.10.0 开发实现、固定数据来源和本机数值验收见 [MAMO 记录](docs/development/s07-mamo.md)。

S07-B 的 SDK/Worker0.11.0 开发实现与固定 NLP4LP 数据、公开参数绑定和私有参考边界见 [实现记录](docs/development/s07-nlp4lp.md)。

S07-D 的 SDK/Worker0.12.0 原问题检查与有限探测见 [实现记录](docs/development/s07-checkers.md)。沿用本机聚焦测试→一次完整回归；GitHub Actions 仅手动补充。

S06-C使用本机 Method／HTTP／Gurobi聚焦测试和一次交付回归；0.13.0的真实模型与流程差异见 [记录](docs/development/s06-coe.md)。

S05-D1角色模型配置见 [实现记录](docs/development/s05-role-models.md)；公共反馈修正与澄清分别见下方 S05-C2／D2 记录，独立审阅仍待完成。

S05-C1公共候选资源见 [实现记录](docs/development/s05-public-candidates.md)。开发使用本机聚焦 red→green，稳定切片执行一次必要完整回归；GitHub Actions仅手动补充。

S05-C2公开反馈修正见 [实现记录](docs/development/s05-feedback-repair.md)。解析、阶段来源与实际 Solver 行为从 CLI 验证；不使用隐藏评分指导修正或选择。

S05-D2澄清与问题修订见 [实现记录](docs/development/s05-clarification.md)。交互通过保存的request_id接受确认；新信息需要显式revision与派生run。本机聚焦检查和一次完整回归为主要验收。

S03-C1独立Provider按已确认的CLI／HTTP／Solver接口验证；本机聚焦red→green、一次必要完整回归和干净wheel为主要验收，见 [记录](docs/development/s03-provider-registry.md)。

S03-C2采用本机CLI／Task／Evaluation／Solver／文件系统验收；隐藏材料仅在导入与评估端，见 [记录](docs/development/s03-task-registry.md)。

S03-C3a的独立Compiler在CLI／Compiler／Worker／真实Solver接口验收，可信插件wheel进入不可变镜像，见 [记录](docs/development/s03-compiler-registry.md)。

S03-C4使用CLI／SDK、MethodContext、公开HTTP、Task和OS接口验收原始数据与有限视图；本机聚焦测试、干净wheel和真实容器求解见 [记录](docs/development/s03-data-loader.md)。GitHub Actions仅手动补充。

按用户2026-10-10的明确指令，当前先编写并交付可使用的功能代码，再逐渐补齐细节与聚焦测试。必要信任边界校验与错误处理保持完整；不会因每个小改动重复运行整套回归。

批量任务展开、分组报告和复用记录通过已有CLI／Task／Evaluation／Solver接口验证，见 [S08](docs/development/s08-benchmark.md)。按用户要求先实现功能，以本机聚焦检查与实际运行收敛，不逐次重复全量回归。

网页批量入口使用公共HTTP加实际HiGHS验收，并复用实验控制，见 [S09-B](docs/development/s09-batch-web.md)。一次聚焦检查覆盖提交、分组、导出和完成复用；浏览器视觉验收与独立审阅分别记录。
