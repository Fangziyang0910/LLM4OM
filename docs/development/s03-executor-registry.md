# S03 可安装执行器

用途：说明独立安装Executor的实际接口与调用范围。状态：SDK／Worker0.36.0开发实现和本机验收；完整1.0尚未发布。规范来源为[插件契约](../plugin-contracts.md)与[开发规范](../../CODING_STANDARDS.md)。

Executor通过`llm4om.plugins` entry point导出factory实例，Manifest声明`kind: executor`、唯一`execution_modes`和`executor_profile`。`factory.create(config)`返回进程callable。配置由Manifest的config_schema验证；不再按内置插件ID限制注册。

当前复用两个已有进程接口：`container_process/0.1.0`接受`run_container`的参数并返回ContainerExecution；`owned_process/0.1.0`接受`run_owned_process`的参数并返回`(stdout: bytes, stderr: bytes, exit_code: int)`。取消令牌、deadline和资源限制沿用对应函数。应用层继续绑定Solver结果与ExecutionResult，不让执行器重新决定模型正确性。

预检的实际Worker调用、候选求解、方法原生脚本执行和原生结果收集均使用声明的Executor。admission snapshot保存Manifest、安装来源、包身份和实际模式；恢复运行按既有插件身份检查。Executor在可信宿主加载，方法不能获取其低层接口。容器插件必须保留声明的隔离规则；安装包本身仍是可信基础设施。

独立示例见[fixture_executor](../../examples/plugins/fixture_executor/README.md)。本机公共CLI检查通过：安装包分别执行容器与trusted_local路径，预检及实际求解均留下插件收据，HiGHS目标均为13。插件stdout不污染CLI JSON。该检查使用工程Mock表述，不证明LLM质量。类型检查已通过43模块；未运行全量回归、批量benchmark或GitHub Actions。ArtifactStore独立替换已由[S03](s03-store-registry.md)实现。2026-10-11独立Standards／Spec审阅通过：8个注册模块全部PASS／PASS-WITH-NOTES，无P1/P2，仅P3打磨项（报告/tmp/llm4om-reviews/s03-registry-group.md）。

最终Worker0.36.0为`sha256:f6fe0303d92e876a4132a1b087ca030d86817be8287aaf2e28552e62175ef1a4`。本机记录位于`/tmp/llm4om-executor-evidence`，运行数据不纳入版本控制。
2026-10-11 P3 处置：container executor limits 已在 preflight 付费调用前校验（缺失键属 invalid_config），不再可能出现生成后付费调用才失败误导性错误。
