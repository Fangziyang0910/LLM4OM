# S03 可安装 ArtifactStore

用途：说明独立安装运行存储的实际接口与调用范围。状态：SDK／Worker0.37.0开发实现和本机验收；独立审阅待完成；完整1.0尚未发布。规范来源为 [插件契约](../plugin-contracts.md)、[开发规范](../../CODING_STANDARDS.md)与 [S03](../implementation-plan.md#s03-插件发现配置与预检)。

## 实际接口

ArtifactStore通过`llm4om.plugins` entry point导出factory实例，Manifest声明`kind: artifact_store`、`store_profile: run_store/0.1.0`、输入`store_bytes`与输出`artifact_ref`。`factory.create(config)`返回opener：`opener(root, *, resume=None, cancellation=None, versioned=True)`，返回实现RunStore成员（run_id、path、refs、events、state、projections、identity、cancellation、write、json、emit、checkpoint、close、accept_publications）的运行存储。opener在打开时校验该成员契约。

内置`llm4om.stores.filesystem`是同一注册表中的builtin插件，行为与原RunStore完全一致；RunConfig的`store.plugin_id`不再限定为它。运行、恢复、报告、澄清派生与人工辅助编辑都先读取运行保存的admission `store`绑定，用同一插件重新打开；早期运行无绑定时按内置filesystem回退。公开配置中的`store.config.root`投影为`.`的行为仅在配置含`root`时执行。

存储选择无法解析（含任一安装插件Manifest损坏导致发现失败）时，run_problem仍以内置filesystem打开运行目录，admission把具体错误（unknown_plugin／invalid_plugin_manifest等）保存为失败bundle；解析成功但opener打开失败时错误原样传播，OSError保持CLI退出码2的store_unavailable语义。admission快照新增`store`绑定；恢复按既有身份规则整体比较，0.36.0保存的运行在新快照下按checkpoint_incompatible拒绝。

## 本机验收

[tests/test_store_registry.py](../../tests/test_store_registry.py)从公共CLI验收三项行为：内置filesystem在plugins list中显示artifact_store／run_store/0.1.0且默认运行完成；独立安装的[fixture_store](../../examples/plugins/fixture_store/README.md)记录每次打开、完成容器HiGHS目标13、admission绑定origin=installed且公开配置保留其plugin_id；未知store插件保存unknown_plugin失败bundle且llm_attempts为0。相关CLI、resume、崩溃恢复、辅助编辑、实验与Web绑定聚焦套件共109项通过；mypy44模块通过。

Worker0.37.0镜像身份为`sha256:f09ee34f89be81ca62ede2fd210820911f801ddc16c2206257c9748f1c1b98fa`。本机证据位于`/tmp/llm4om-official-test`与测试临时目录，运行数据不纳入版本控制。未运行全量回归、批量benchmark或GitHub Actions；独立Standards／Spec审阅仍待完成。
