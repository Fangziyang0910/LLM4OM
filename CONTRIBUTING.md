# 贡献指南

本文说明如何修改和验证 LLM4OM。产品功能与使用方式见 [README](README.md)。当前开发范围是本机后端与单用户 Web，支持继续开发。

## 开始修改

先读 [GLOSSARY](GLOSSARY.md) 和 [CODING_STANDARDS](CODING_STANDARDS.md)。再按[文档导航](docs/README.md)读取相关需求、ADR、接口和验收场景。

功能规格和工作项使用 [GitHub Issues](docs/agents/issue-tracker.md)。已明确的小范围维护可以直接执行。较大的功能按用户可观察结果拆分；每个任务贯通所需的输入、处理和输出，并有独立验收条件。

方法、LLM、建模后端、求解器和评估器通过共同接口协作。复用已有模块，只为实际变化增加适配器。修改字段、状态或指标时，同步契约、调用方、示例和测试。

研究方法接入保留核心编排和提示，记录固定上游提交及适配差异。第三方代码和数据保留来源与许可。新增领域词更新 GLOSSARY；难以逆转且有真实取舍的决定记录为 ADR。

## 开发环境

在仓库根目录执行，使用 Python 3.11 或 3.12：

```bash
uv sync --locked --all-extras
uv run --locked --all-extras python scripts/build_worker_image.py
```

依赖由 `pyproject.toml` 声明，`uv.lock` 锁定。当前完整隔离验证环境是 Linux Docker。Worker 构建参数及测试插件镜像见[测试指南](docs/development/testing.md)。

修改前端时执行：

```bash
npm --prefix frontend install
npm --prefix frontend run build
```

前端源码在 `frontend/`。构建输出到 `src/llm4om/web_assets/`，随 Python 包分发。浏览器测试使用这些构建文件。

更新 Python 后端后，按原工作区和启动参数重启 Web 服务，再刷新页面。长驻进程在启动时加载配置模板和校验代码；重启后才能与新执行程序保持一致。

## 验证修改

选择能验证本次行为的公共入口。非平凡行为先建立失败用例，再实现和验证。文档改动使用链接、示例和资料导出检查；无需重复执行完整求解回归。

```bash
uv run --locked --all-extras python scripts/check_repository.py
uv run --locked --all-extras python -m unittest discover -s tests -p test_repository_checks.py -v
```

Python、容器、浏览器和完整交付检查见[测试指南](docs/development/testing.md)。确定性测试验证工程流程；真实 LLM 和求解器支持由实际请求和求解记录证明。

修改 `docs/references/catalog.json` 后，运行 `uv run --locked python scripts/render_references.py`，再检查生成结果。固定上游字节、许可原文和数据哈希保持不变。

## 审阅与交付

审阅分别检查开发规范和任务要求。报告改动、实际检查、未验证条件和影响范围。相关任务完成后再更新工作项；完整发布按[验收清单](docs/acceptance.md)核对。

密钥、运行数据和商业许可证保留在 Git 忽略的本地位置。当前开发不要求公网多人部署或多平台适配。GitHub Actions 仅在需要时手动触发；正式发布和仓库可见性由对应任务决定。

按需使用[技能路由](docs/agents/workflow.md)。用户明确指令优先于工程默认值，常规实现选择无需增加审批。
