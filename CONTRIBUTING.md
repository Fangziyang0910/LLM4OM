# 贡献与开发流程

本仓库维护 LLM4OM 的研究设计和平台实现。已交付 [S01](docs/development/s01-offline-run.md) 离线单问题流程与 [S02-A](docs/development/s02-highs.md) 真实 HiGHS 求解、[S03](docs/development/s03-plugins.md) 方法发现／预检及 [S04-A](docs/development/s04-container.md) 容器执行及 [S05-A](docs/development/s05-provider.md) 真实文本 LLM及 [S07-A](docs/development/s07-nl4opt.md) NL4Opt 导入／评测；每个任务交付可演示的纵向行为。[S02-B](docs/development/s02b-factory.md) 已实现参数化工厂的本地 CLI/SDK／容器验收，真实外部模型／重绑定与独立审阅后修复已验收。S06-A 新增实际微型 Gurobi／native Code，见 [实现记录](docs/development/s06-gurobi.md)。

SDK／Worker 0.8.0 已完成 [S04-B 取消／恢复](docs/development/s04-resume.md)和 [S05-B Messages](docs/development/s05b-messages.md)集成验收；241项本机回归与独立审阅通过，包未发布。

S06-B 正在验收 SDK/Worker0.9.0 的完整固定 OptiMUS 主流程；支持与证据见 [实现记录](docs/development/s06b-optimus.md)。已验收0.8.0 基线与开发版本分别记录。

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
uv run --locked --extra dev --extra solve --extra gurobi python scripts/render_references.py --check
uv run --locked --extra dev --extra solve --extra gurobi python scripts/check_repository.py
uv run --locked --extra dev --extra solve --extra gurobi python -m unittest discover -s tests -v
uv build
```

修改 `docs/references/catalog.json` 后先运行 `uv run --locked --extra dev --extra solve --extra gurobi python scripts/render_references.py` 生成资料页与 BibTeX，再执行检查。JSON 使用两空格布局；CSV 和授权原文保持字节稳定。所有纳入仓库的文件都在 [逐文件整理记录](docs/repository-audit.md)中说明职责与校验方式，新增文件同步记录。

仓库检查覆盖文本格式、本地链接、JSON、示例配置、阶段引用、数据绑定、独立数学核验、参考资料导出与编号追踪。容器测试要求可访问的 Docker daemon 和已构建的 Worker 镜像；真实测试不自动跳过。Linux 为当前完整隔离验证环境，macOS／Windows 尚未验收。平台测试从 CLI／SDK 与编译／Solver 公共接口验证离线、真实求解、独立方法安装及预检；维护检查不替代真实隔离测试、完整预算执行、恢复或 benchmark 验收。基础安装可省略 solve extra，完整测试须安装 solve 与 gurobi extras；Gurobi 实测仅证明当前 size-limited 微型环境。

## 4. Review 与交付

Review 分开回答两个问题：Standards 是否符合开发规范和相关契约；Spec 是否完成用户要求或 issue。显式调用 code-review 时按技能执行独立审阅；若当前环境无法运行独立审阅者，说明实际采用的自查范围。

交付先完成对应检查，再报告变化、证据和剩余条件。PR 使用 [仓库模板](.github/PULL_REQUEST_TEMPLATE.md)说明 Summary、Evidence 与 Merge Danger。用户请求提交或 PR 时保存完整改动并关联工作项。日常验收以本机测试和真实 Provider／Solver 运行为依据：开发中运行聚焦测试，切片交付时运行一次所需完整回归、类型／仓库检查和包构建；只有新改动或未解决故障才重复。GitHub Actions 仅手动触发，供必要的环境交叉验证；push／PR 不自动重跑完整矩阵，也不将远程 CI 作为每次开发推进的门槛。发布标签与公开包发布依据真实验收和用户授权进行。

技能选择与触发条件见 [任务工作流](docs/agents/workflow.md)。常规实现选择无需额外审批；用户明确指令优先于工程默认值。

S07-C 的 SDK/Worker0.10.0 开发实现、固定数据来源和本机数值验收见 [MAMO 记录](docs/development/s07-mamo.md)。
