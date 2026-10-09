# 隔离工厂构建与求解证据收集

任意 Python 工厂与 Solver 收集器共享进程时，工厂可以修改模块并伪造求解证据。S02-B 在只读、无网络的 Worker 容器内用子进程构建 ModelHandle 并导出具体线性实例；可信父进程拒绝非契约输出，校验实例，再复用严格 IR／HiGHS 路径独立求解，且禁止子进程访问父进程内存与文件描述符。导出视图明确标为 factory_exported_instance，不替代原 Formulation，也不证明导出与原问题的语义等价；字段由 [插件契约](../plugin-contracts.md)维护。


S06-A 延续此边界：Pyomo 导出实例可独立选择 Gurobi；native gurobipy 以 SDK MPS 和显式变量映射
传递候选模型，可信父进程使用新的 SDK 对象检查 LP/MILP 结构并求解。原生提取视图标为
native_exported_instance；原 Code／Formulation 和原生身份保留，导出不证明源码语义。
