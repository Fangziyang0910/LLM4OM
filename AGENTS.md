# LLM4OM（通用智能优化求解器）

通用科研思维与沟通内核继承自大本营 [AGENTS.md](../AGENTS.md)。

## 项目约定
- 开工前读 [README](README.md)、[GLOSSARY](GLOSSARY.md) 与 [架构](docs/architecture.md)；改代码前读 [CODING_STANDARDS](CODING_STANDARDS.md)，交付与测试看 [CONTRIBUTING](CONTRIBUTING.md)。
- 平台只管建模、求解与记录；能用 LangChain、LangGraph 或现有库完成的直接复用，先做最简实现。
- 研究方法保留核心编排与提示，记录固定来源与适配差异（见 [建模方法](docs/methods.md)）；涉及机制变更先确认。
- 密钥不进入方法输入、生成代码环境或运行记录；确定性测试与真实接入证据分开报告；密钥、运行数据与商业许可证不提交。

## Agent skills
- Issue 读写：[issue-tracker.md](docs/agents/issue-tracker.md)；Triage 状态：[triage-labels.md](docs/agents/triage-labels.md)。
- 术语与架构（单一 GLOSSARY + ADR）：[domain.md](docs/agents/domain.md)；工程技能路由：[workflow.md](docs/agents/workflow.md)。
