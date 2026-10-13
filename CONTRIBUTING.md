# 贡献与开发流程

本仓库维护LLM4OM的研究设计与平台实现。当前可用功能和支持范围见[README](README.md)，切片状态与证据见[开发计划](docs/implementation-plan.md)。完整1.0尚未发布。

规范见[CODING_STANDARDS](CODING_STANDARDS.md)，领域词见[GLOSSARY](GLOSSARY.md)。按[文档导航](docs/README.md)读取当前任务涉及的FR/NFR、契约、详细设计与验收。方法或benchmark接入另读[资料库](docs/references/README.md)及[源码考察](docs/references/source-inspection.md)。历史版本与验收数量保留在对应切片记录，不在开发流程中重复维护。

## 1. 从需求到工作项

新功能先明确问题、目标行为、用户故事、实现取舍、公共测试入口与范围。功能规格和工作项使用 [GitHub Issues 约定](docs/agents/issue-tracker.md)，引用仓库基线。已明确的文档修复和小范围维护可以直接执行。

规格按用户可观察结果拆成 tracer-bullet 切片。每个切片贯通需要的输入、处理和输出，独立验收；其阻塞项只列实际无法绕开的前置行为。选择依赖已完成、尚未领取的切片。父规格、子任务与验收证据相互关联。

远程创建、评论与状态迁移按当前用户请求或显式调用的技能进行。本地规划不等于已发布 issue；认证失败保留本地结果并说明失败操作。

## 2. 实现与研究接入

在编码前确定公共 Interface／Seam 和测试预期。新行为采用一个测试 red → 最小实现 green → 必要重构的小循环。测试从用户入口或真实公共契约观察结果；确定性 fixture 验证工程流程，真实 Provider／Solver 支持仍需真实验收。

按用户2026-10-10的明确指令，当前先编写并交付核心功能和用户界面，再逐步补齐细节与聚焦检查。保留必要信任边界校验、避免数据丢失的错误处理与可访问性；不因每个小改动重复整套回归。用户明确的开发顺序优先于默认的测试顺序。

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

### 前端构建与浏览器流程测试

Workbench 前端源在 `frontend/`（React + Vite + TypeScript），构建产物以固定文件名输出到 `src/llm4om/web_assets/` 随包分发。修改前端后必须重新构建，流程测试跑在构建产物上：

```bash
npm --prefix frontend install
npm --prefix frontend run build   # tsc --noEmit + vite build → web_assets/{index.html,app.js,style.css}
```

浏览器流程测试（Playwright `.cjs`）使用本机确定性 guidance 服务器（真实 `serve_web` + 工程 Provider）。工作区必须为**空的一次性目录**，重启需换新目录；每个测试族从全新工作区开始：

```bash
# 终端1：启动 fixture（默认 8774=web、8775=Provider）
uv run --locked --extra solve python tests/helpers/web_guidance_server.py --workspace /tmp/llm4om-web-fixture

# 终端2：运行流程测试（以 story 为例）
LLM4OM_WEB_TEST_URL=http://127.0.0.1:8774 \
LLM4OM_WEB_TEST_PROVIDER_URL=http://127.0.0.1:8775 \
LLM4OM_WEB_TEST_WORKSPACE=/tmp/llm4om-web-fixture/jobs \
LLM4OM_BROWSER_MODULE=frontend/node_modules/playwright \
LLM4OM_BROWSER_EXECUTABLE="$HOME/.cache/ms-playwright/chromium-*/chrome-linux*/chrome" \
node tests/web_story_flow.cjs
```

- 直接读运行目录的用例（`web_edit_flow`／`web_model_edit_flow`／`web_clarification_flow`）要求 `LLM4OM_WEB_TEST_WORKSPACE` 指向 `<workspace>/jobs`（其下即 `<job_id>/`）；其余用例只需该变量存在。
- fixture 顺序：`web_clarification_flow` 先跑（其末尾修订生成 revision-2 运行），`web_edit_flow` 依赖该已完成运行；story／start／failure／keyboard 等自成体系，可独立工作区运行。
- `web_decision/data/process/links/runtime/candidates/connectivity_check/history` 依赖一次性真实历史运行数据，当前需另行准备真实记录工作区（对照证据见 [#87](https://github.com/Fangziyang0910/LLM4OM/issues/87)）。
- Chrome 路径按本机 Playwright 安装调整；`LLM4OM_BROWSER_MODULE` 指向 `frontend/node_modules/playwright`（devDependency）。

## 4. Review 与交付

Review 分开回答两个问题：Standards 是否符合开发规范和相关契约；Spec 是否完成用户要求或 issue。显式调用 code-review 时按技能执行独立审阅；若当前环境无法运行独立审阅者，说明实际采用的自查范围。

交付先完成对应检查，再报告变化、证据和剩余条件。PR 使用 [仓库模板](.github/PULL_REQUEST_TEMPLATE.md)说明 Summary、Evidence 与 Merge Danger。用户请求提交或 PR 时保存完整改动并关联工作项。日常验收以本机测试和真实 Provider／Solver 运行为依据。开发中验证新增行为及受影响路径；相关小切片集中到可使用的交付节点，再执行一次必要完整回归、类型／仓库检查和包构建。同一实现快照不重复源码、wheel或镜像验收；源码或执行身份发生变化、出现实际失败时，只重验受影响范围。每个交付节点先展示可使用的功能和实际运行结果。GitHub Actions 仅手动触发，供必要的环境交叉验证；push／PR 不自动重跑完整矩阵，也不将远程 CI 作为每次开发推进的门槛。发布标签与公开包发布依据真实验收和用户授权进行。

技能选择与触发条件见 [任务工作流](docs/agents/workflow.md)。常规实现选择无需额外审批；用户明确指令优先于工程默认值。
