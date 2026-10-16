# 接口契约

本索引按职责组织字段与接口。核心配置和 Manifest 使用 `0.2.0`；公开问题还支持 JSON 数据的 `0.3.0`；GroundedLPIR 使用 `0.1.0`。插件、表示和评测协议分别管理版本。

| 契约 | 内容 |
|---|---|
| [核心对象与配置](contracts/core.md) | 公开问题、产物引用、两阶段输出、求解记录、RunConfig 和 ExperimentSpec |
| [建模方法](contracts/methods.md) | Context、公开检查、修正、最终选择、澄清与步骤事件 |
| [执行与恢复](contracts/execution.md) | 模型工厂、原生代码、求解器、检查点与资源日志 |
| [LLM](contracts/llm.md) | 文本协议、角色模型、预算、重试、凭据与目录查询 |
| [任务与评测](contracts/tasks.md) | 来源导入、公开/私有投影、资格冻结和独立检查器 |
| [插件扩展](contracts/plugins.md) | Manifest、注册、编译器、后端、求解器、加载器、执行器、存储和报告器 |
| [Web](contracts/web.md) | 页面配置、任务、版本、题库、预览和公开导出 |

领域含义见 [GLOSSARY](../GLOSSARY.md)，调用顺序见[详细设计](detailed-design.md)，指标定义见[评测协议](evaluation.md)。支持组合见[项目说明](../README.md)，验证范围见[支持验证](development/validation.md)。
