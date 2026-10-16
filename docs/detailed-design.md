# 详细设计

本索引按运行行为组织时序和不变量。字段在[接口契约](plugin-contracts.md)维护，模块职责见[架构](architecture.md)，需求编号见[需求规格](requirements/v1.0.md)。

| 编号 | 行为 | 文档 |
|---|---|---|
| DD-01 | 单问题建模与求解 | [建模流程](design/modeling-methods.md#dd-01-单问题建模与求解) |
| DD-02 | 生成、修正与选择 | [方法编排](design/modeling-methods.md#dd-02-方法内部生成修正与选择) |
| DD-03 | 插件与能力匹配 | [执行流程](design/execution.md#dd-03-插件接入与兼容路径) |
| DD-04 | 阶段产物与数据绑定 | [产物来源](design/execution.md#dd-04-建模输出与数据绑定) |
| DD-05 | 构建、执行与求解 | [可信求解](design/execution.md#dd-05-编译执行与求解结果) |
| DD-06 | 评测数据与实验展开 | [实验](design/experiments-and-interfaces.md#dd-06-benchmark-与实验展开) |
| DD-07 | 保存、恢复与报告 | [持久化](design/experiments-and-interfaces.md#dd-07-持久化恢复与报告) |
| DD-08 | CLI 与 Web | [应用入口](design/experiments-and-interfaces.md#dd-08-cli-与-web-共用应用接口) |
