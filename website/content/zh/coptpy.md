coptpy 是 COPT 的原生 Python 接口。平台将它作为一个建模库，标量、表达式和矩阵写法都返回 COPT 模型。

## 建模范围

当前代码指引覆盖 LP、MILP、凸二次和锥优化。模型是否可求解取决于原生能力与实际版本。选择建模方法时，也要同时满足方法本身的问题范围。

## 在平台中选择

选择 coptpy，原生引擎为 COPT。代码通过环境创建模型，定义 `build_model(data)` 并返回模型，不直接调用 solve。平台读取实际目标、变量和原生状态。

这条路径使用 COPT 模型本身；若在 CVXPY 等库选择 COPT 后端，建模库仍是 CVXPY，两种表达方式不会被重复计为额外库。

## 许可证配置

当前部署可以在运行时允许的小规模非商业模式下检查示例；更大模型和商业部署需要合适许可。使用 `COPT_LICENSE_DIR` 指定许可证路径，通常包含 `license.dat` 和 `license.key`。Compose 部署还需挂载相同宿主机路径。

求解沙箱只读挂载实际许可文件，仍不访问网络。安装 SDK、插件加载与许可有效分别检查，缺许可时不会换其他引擎冒充成功。

## 官方资料

参阅 [COPT Python 接口](https://guide.coap.online/copt/en-doc/pythoninterface.html)和[安装与许可](https://guide.coap.online/copt/en-doc/install.html)。平台挂载示例见[后端与许可证](../backends/)。
