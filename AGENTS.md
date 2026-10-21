# LLM4OM 工作约定

- 开工前读 [README](README.md)、[GLOSSARY](GLOSSARY.md) 和 [架构](docs/architecture.md)。
- 修改文件前读 [CODING_STANDARDS](CODING_STANDARDS.md)；开发、测试和交付时读 [CONTRIBUTING](CONTRIBUTING.md)。
- 平台只管建模、求解和记录。能用 LangChain、LangGraph 或现有库完成的，不自建；先用最简单的实现。
- 研究方法保留核心编排和提示，记录固定来源与适配差异（[建模方法](docs/methods.md)）。改变机制的改动先确认。
- 密钥不进入方法输入、生成代码环境或运行记录。
- 确定性测试与真实接入证据分别报告。
- 密钥、运行数据和商业许可证不提交。

## Agent skills

### Issue tracker

读取或发布工作项时，先读 [issue-tracker.md](docs/agents/issue-tracker.md)。

### Triage labels

分类或迁移 triage 状态时，先读 [triage-labels.md](docs/agents/triage-labels.md)。

### Domain docs

修改术语或架构时，先读 [domain.md](docs/agents/domain.md)。本仓库保留一个 GLOSSARY 和一组 ADR。

### Task routing

选择工程技能时读 [workflow.md](docs/agents/workflow.md)。
