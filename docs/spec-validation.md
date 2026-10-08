# 需求文档与示例校验记录

日期：2026-10-08。此记录只验证需求文档及自建 fixture 的一致性，不是平台功能验收或方法 benchmark。

- 36 项功能需求、12 项非功能需求编号连续且无重复。
- 开发计划含 S01～S10 共 10 个切片；验收表含 AC-01～AC-22 共 22 个场景。
- 本地文件链接及指向标题已检查；代码围栏成对。
- 5 个 JSON fixture 可解析；问题／模型／参考材料 ID、变量引用、需求映射及数据绑定一致。
- YAML 经 PyYAML 解析；必需配置字段齐全，direct 配置通过 Manifest JSON Schema，并检查不支持的输出模式会被拒绝。
- CSV 文件 hash 与问题／模型中的 sha256 匹配。
- 用独立整数枚举核验示例：A=3、B=2，最优目标 13；用分数运算核验 LP 松弛目标 40/3。
- 预期结果明确标为 fixture assertions；semantic_equivalence 为 not_available，没有虚构实际实验。
- 文档与 fixture 扫描未发现实际 API token、私钥或未填充的 hash 占位符。

Markdown／JSON／YAML 检查脚本是本次工作目录中的审阅工具，不属于规划中的平台测试套件。实现时仍须按各插件的配置契约验证全部字段、实际路径与兼容组合。
