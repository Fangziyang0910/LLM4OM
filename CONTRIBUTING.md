# 贡献与开发流程

本仓库维护 LLM4OM 的研究、需求与设计基线，以及文档维护工具。平台开发从 [S01](docs/implementation-plan.md#s01-统一问题契约与离线纵向流程) 开始；每个任务交付可演示的纵向行为。

规范见 [CODING_STANDARDS](CODING_STANDARDS.md)，领域词见 [GLOSSARY](GLOSSARY.md)。按 [文档导航](docs/README.md)读取当前任务涉及的 FR/NFR、契约、详细设计与验收。方法或 benchmark 接入另读 [资料库](docs/references/README.md)及 [源码考察](docs/references/source-inspection.md)。

## 1. 从需求到工作项

新功能先明确问题、目标行为、用户故事、实现取舍、公共测试入口与范围。功能规格和工作项使用 [GitHub Issues 约定](docs/agents/issue-tracker.md)，引用仓库基线。已明确的文档修复和小范围维护可以直接执行。

规格按用户可观察结果拆成 tracer-bullet 切片。每个切片贯通需要的输入、处理和输出，独立验收；其阻塞项只列实际无法绕开的前置行为。选择依赖已完成、尚未领取的切片。父规格、子任务与验收证据相互关联。

远程创建、评论与状态迁移按当前用户请求或显式调用的技能进行。本地规划不等于已发布 issue；认证失败保留本地结果并说明失败操作。

## 2. 实现与研究接入

在编码前确定公共 Interface／Seam 和测试预期。新行为采用一个测试 red → 最小实现 green → 必要重构的小循环。测试从用户入口或真实公共契约观察结果；确定性 fixture 验证工程流程，真实 Provider／Solver 支持仍需真实验收。

实现复用已有模块，新增 Adapter 对应真实变化维度。Formulation／Code 的公共输入输出和真实来源分别检查；修改阶段语义时读 ADR-0004 和契约。改变领域词时更新 glossary；发生需要留存的架构取舍时写简短 ADR。字段、状态、版本或指标变化同步其事实来源、使用方、fixture 与验收项。

研究方法接入固定上游提交，记录提示、流程、预算和依赖差异。改变算法行为使用方法变体；忠实适配保留其实际输出和支持矩阵。第三方代码与数据记录来源和许可。论文元数据、未知状态和阅读范围在 catalog 中维护。

## 3. 维护工具的当前命令

需要 Python 3.11 或更新版本。依赖仅用于仓库校验，不构成平台依赖或已验证的平台环境：

```bash
python3 -m pip install -r requirements-dev.txt
python3 scripts/render_references.py --check
python3 scripts/check_repository.py
python3 -m unittest discover -s tests -v
```

修改 `docs/references/catalog.json` 后先运行 `python3 scripts/render_references.py` 生成资料页与 BibTeX，再执行检查。JSON 使用两空格布局；CSV 和授权原文保持字节稳定。所有纳入仓库的文件都在 [逐文件整理记录](docs/repository-audit.md)中说明职责与校验方式，新增文件同步记录。

仓库检查覆盖文本格式、本地链接、JSON、示例配置、阶段引用、数据绑定、独立数学核验、参考资料导出与编号追踪。它不运行设计中的 CLI，也不替代隔离、预算、恢复或真实 benchmark 验收。

## 4. Review 与交付

Review 分开回答两个问题：Standards 是否符合开发规范和相关契约；Spec 是否完成用户要求或 issue。显式调用 code-review 时按技能执行独立审阅；若当前环境无法运行独立审阅者，说明实际采用的自查范围。

交付先完成对应检查，再报告变化、证据和剩余条件。PR 使用 [仓库模板](.github/PULL_REQUEST_TEMPLATE.md)说明 Summary、Evidence 与 Merge Danger。用户请求提交或 PR 时保存完整改动并关联工作项；平台实现完成后才建立平台 CI、发行包与发布标签。

技能选择与触发条件见 [任务工作流](docs/agents/workflow.md)。常规实现选择无需额外审批；用户明确指令优先于工程默认值。
