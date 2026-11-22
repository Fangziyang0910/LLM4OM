# 文档导航

本文是仓库文档的维护入口。面向使用者的双语文档中心位于 [在线 Docs](https://fangziyang0910.github.io/LLM4OM/docs/zh/introduction/)；第一次使用可从 [README](../README.md#快速开始) 安装并完成一个有明确答案的生产案例。

## 按任务阅读

| 当前任务 | 建议顺序 | 完成标志 |
|---|---|---|
| 第一次求解 | 安装 → 模型预设 → 生产案例 | 核对 A=3、B=2、利润 13，能打开模型与代码 |
| 整理业务需求 | 需求对话 → 数据编辑 → 建模 | 决策、目标、单位、变量域和约束明确 |
| 使用已有结果 | 求解结果 → 方案对话 → 调整与对比 | 新方案保留原方案，差异可追溯 |
| 排查运行问题 | 失败阶段 → 完整错误 → 部署与配置 | 区分模型请求、Worker 执行和业务建模问题 |
| 维护或扩展系统 | 开发指南 → 模块架构 → 方法适配 → 测试 | 有对应回归，确定性与真实接入证据分别记录 |

在线文档的[快速开始](https://fangziyang0910.github.io/LLM4OM/docs/zh/quickstart/)和[故障排查](https://fangziyang0910.github.io/LLM4OM/docs/zh/troubleshooting/)提供分步操作。源码检出中的功能可能先于已发布的网站；本地生成与预览见 [网站维护](../website/README.md)。

## 仓库参考文档

| 我想…… | 文档 |
|---|---|
| 了解平台、快速启动 | [README](../README.md) · [English](../README.en.md) |
| 用工作台、命令行或 Python 求解问题 | [使用指南](user-guide.md) |
| 在 Codex / Claude Code 中用当前模型建模，无需 Web | [宿主模型与 Skills](host-modeling.md) |
| 部署给课题组或团队使用 | [部署指南](deployment.md) |
| 修改代码、接入新方法、发布版本 | [开发指南](../CONTRIBUTING.md) · [开发规范](../CODING_STANDARDS.md) |
| 理解模块、方法接口、沙箱和运行记录 | [架构](architecture.md) |
| 了解各方法的流程、固定来源和适配差异 | [建模方法](methods.md) |
| 了解重要的架构取舍 | [ADR 索引](adr/README.md) |
| 查术语 | [GLOSSARY](../GLOSSARY.md) |
| 看版本变化 | [CHANGELOG](../CHANGELOG.md) |
| 报告安全问题 | [SECURITY](../SECURITY.md) |

工作项使用 GitHub Issues。代理按任务读取[工作项约定](agents/issue-tracker.md)、[领域文档约定](agents/domain.md)和[技能路由](agents/workflow.md)。

## 研究资料

[参考资料库](references/README.md)提供论文、代码和数据链接。[资料核验说明](references/search-log.md)说明来源和读取范围。

[方法与求解器接入调查](references/methods-solvers.md)对照现有实现，说明哪些候选能补充建模和求解能力、需要哪些接入条件。

论文元数据在 `references/catalog.json` 中维护。修改后运行 `python3 scripts/render_references.py`，重新生成资料页和 BibTeX。

## 图片

`assets/` 中有 README 和使用指南用的横幅、截图和演示动图。更新方法见[开发指南](../CONTRIBUTING.md#文档)。

九个建模库的原生 API、后端发现与验证见[接口清单](references/modeling-libraries.md)；代码与执行的边界见 [ADR 0013](adr/0013-modeling-libraries.md)。

## 文档维护与验收

- 用户任务、配置步骤和排错操作在 `website/content/zh/` 与 `website/content/en/` 同步维护；目录与文章映射位于 `website/docs-manifest.json`。
- 模块契约、术语、研究方法来源和适配差异分别以架构、GLOSSARY、建模方法及 ADR 为准；用户文章链接到这些参考，避免复制容易漂移的实现细节。
- 修改源稿后，按[网站维护](../website/README.md#生成文档)生成 HTML 与搜索索引；不直接修改生成页面。提交同时包含源稿和必要产物。
- 验收包括内部链接、锚点、中英文对应、代码与公式显示，以及按快速开始核对结果。截图或文档交互示例不能代替真实 LLM 接入证据。
- 说明当前限制：界面语言不改写原记录；原始模型日志可能包含英文；阅读译文可能有误；求解器“最优”只证明当前数学模型。运行数据、密钥和许可证不进入文档或 Git。
