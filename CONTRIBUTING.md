# 贡献指南

先读 [GLOSSARY](GLOSSARY.md)、[CODING_STANDARDS](CODING_STANDARDS.md) 和 [架构](docs/architecture.md)。工作项使用 [GitHub Issues](docs/agents/issue-tracker.md)。

## 开发环境

```bash
uv sync --all-extras
uv run llm4om build-worker
```

修改 Worker 依赖时，同步修改 `src/llm4om/sandbox/worker.Dockerfile` 和镜像标签 `WORKER_IMAGE`，再重新构建。

修改前端时使用 Node.js 22.13 或更新版本：

```bash
npm --prefix frontend ci
npm --prefix frontend run dev      # 开发服务器，/api、/threads、/assistants 代理到 8767
npm --prefix frontend run lint     # ESLint（含 React Hooks 规则）
npm --prefix frontend test         # Vitest：步骤分组、断流回归、公式渲染
npm --prefix frontend run build    # 输出到 src/llm4om/server/web_assets/
```

更新服务端代码后重启 `llm4om serve`。

调试方法图时可以用 LangGraph Studio：在仓库根目录运行 `uv run langgraph dev`，它读取 `langgraph.json`，注册与 `llm4om serve` 相同的图。

## 测试

```bash
uv run ruff check
uv run pytest
```

测试不调用真实 LLM，也不需要 Docker：方法使用脚本化聊天模型，求解使用本机 Worker（需要 `solve` 可选依赖）。AutoFormulation 的等价判断测试需要 `autoformulation` 可选依赖（Z3、SymPy）。

真实运行使用 `.env` 中的模型：

```bash
uv run llm4om run --problem "……" --method trival
```

确定性测试与真实运行的结果分别报告。

## 接入研究方法

1. 在 `src/llm4om/methods/` 中把方法写成 LangGraph 图（状态继承 `ModelingState`），定义 `Method`，加入 `methods()`。
2. 记录固定的上游提交，填入 `Method.source`。
3. 忠实移植核心建模逻辑：编排、提示、解析和停止条件。只做适配、避错和必要的修正，在 [建模方法](docs/methods.md) 和源码（`llm4om:` 注释）中逐条记录。原提示写死某个库时，为每种代码写法准备方言，gurobipy 方言保留原文；方法的建模范围只覆盖部分写法时（例如原提示要求 MILP），设置 `Method.languages`。
4. 在 `tests/test_methods.py` 中用脚本化模型跑通主要路径。
5. 用真实 LLM 至少跑通一个问题，把结果写入 [建模方法](docs/methods.md#验证)。

第三方代码和数据保留来源与许可，并更新 [NOTICE](NOTICE)。

## 资料

修改 `docs/references/catalog.json` 后运行 `python3 scripts/render_references.py`。

## 交付

密钥、运行数据和商业许可证不提交。报告改动、实际执行的检查和未验证的条件。
