gurobipy 是 Gurobi 的原生 Python 建模接口。它支持标量表达式和矩阵写法，两者都返回同一种 Gurobi 模型。

## 在平台中选择

选择建模库 gurobipy，原生引擎为 Gurobi。这个原生模型不会接到任意其他引擎后面。需要使用 HiGHS 或 CBC 时，应选择具有对应原生适配器的建模库。

Gurobi 的模型表达能力取决于安装版本与问题类型。平台保留原生约束和表达式；生成代码仍需正确表达变量域、目标与条件。

## 代码与结果

代码定义 `build_model(data)`，返回 `gurobipy.Model`，不调用 `optimize()`。平台实际求解后读取目标、变量、状态和可用诊断。标量、矩阵接口可以在同一模型中使用。

当前模型不可行时，Gurobi IIS 可以提供一组冲突约束，供[无解解释](../conflicts/)使用。证据针对当前数学模型，仍需核对模型与业务要求的对应关系。

## 许可证

没有完整许可时，只能在运行时允许的规模范围内使用。大规模模型、团队共享和容器运行需要适合实际用途的许可。配置采用 `GRB_LICENSE_FILE`，宿主机、app 容器和求解沙箱中的挂载路径需要对应，详见[后端与许可证](../backends/)。

## 官方资料

参阅 [Gurobi Python API](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/overview.html)和[矩阵变量 MVar](https://docs.gurobi.com/projects/optimizer/en/current/reference/python/mvar.html)。安装成功或后端显示可用，不能代替实际求解时的许可证校验。
