# LLM4OM 工作约定

- 开工前读 [README](README.md)、[GLOSSARY](GLOSSARY.md)及相关需求和 ADR。当前功能与使用方式由 README 说明。
- 修改文件前读 [CODING_STANDARDS](CODING_STANDARDS.md)；开发、校验和交付时读 [CONTRIBUTING](CONTRIBUTING.md)。
- 按可演示的用户行为交付。当前范围是本机后端与单用户 Web；用户明确指令优先，常规实现选择无需额外审批。
- 方法、LLM、数据、阶段产物、建模后端、求解器和评估器通过声明接口协作。
- 自动建模分别记录 Formulation 和 Code，保留实际步骤与来源；缺失阶段如实标明。
- 研究方法保留核心编排和提示，记录固定来源与适配差异。支持范围由实际兼容路径和验证确定。
- 隐藏参考评测材料与密钥不进入方法输入、生成代码环境或公开导出。
- 字段、范围或评测口径变化同步契约、示例和验收。确定性测试与真实接入证据分别报告。
- 密钥、运行数据和商业许可证不提交。保持当前仓库可见性。

## Agent skills

### Issue tracker

读取或发布工作项时，先读 [issue-tracker.md](docs/agents/issue-tracker.md)。功能规格和任务使用 GitHub Issues。

### Triage labels

分类或迁移 triage 状态时，先读 [triage-labels.md](docs/agents/triage-labels.md)。

### Domain docs

探索领域或修改术语、架构时，先读 [domain.md](docs/agents/domain.md)。本仓库保留一个 GLOSSARY 和一组 ADR。

### Task routing

选择工程技能时读 [workflow.md](docs/agents/workflow.md)。各技能按任务调用。
