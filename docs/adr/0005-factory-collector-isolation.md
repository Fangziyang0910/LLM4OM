# 隔离工厂构建与求解证据收集

任意 Python 工厂与 Solver 收集器共享进程时，工厂可以修改模块并伪造求解证据。S02-B 在只读、无网络的 Worker 容器内用子进程构建 ModelHandle 并导出具体线性实例；可信父进程拒绝非契约输出，校验实例，再复用严格 IR／HiGHS 路径独立求解，且禁止子进程访问父进程内存与文件描述符。导出视图明确标为 factory_exported_instance，不替代原 Formulation，也不证明导出与原问题的语义等价；字段由 [插件契约](../plugin-contracts.md)维护。
