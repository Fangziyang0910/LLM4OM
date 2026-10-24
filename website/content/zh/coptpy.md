coptpy 构建 COPT 原生模型，适用于 LP、MILP、凸二次和相应锥模型。它同时提供标量表达与矩阵接口，实际引擎是 COPT。

## 什么时候考虑原生接口

当团队已经使用 COPT、希望沿用原生模型和求解环境时，coptpy 能保持代码与引擎的一致关系。

索引生产模型可用 `addVars` 按产品建立命名变量，再沿产品索引汇总利润和资源使用。矩阵接口则用数组组织相同的系数关系。

## 完整生产模型

```python
import coptpy as cp
from coptpy import COPT

def build_model(data):
    model = cp.Envr().createModel("production")
    a = model.addVar(lb=0, vtype=COPT.INTEGER, name="A")
    b = model.addVar(lb=0, vtype=COPT.INTEGER, name="B")
    model.setObjective(3*a + 2*b, COPT.MAXIMIZE)
    model.addConstr(2*a + b <= 8, name="cutting")
    model.addConstr(a + 2*b <= 8, name="finishing")
    return model
```

代码返回模型，平台负责求解。正确整数结果为 A=3、B=2、利润13。索引模型可使用 `addVars`，大矩阵可使用原生矩阵写法，仍需核对维度。

## 凸二次与整数域怎样影响选择

线性生产模型可以先通过小样例核对。加入二次成本后，应检查目标的凸性和所选引擎支持范围；加入整数决策后，还需要支持相应混合整数问题。

```demo
production
```

将整数域切为连续域时，案例数值会变化。可在交互例中直接查看对应的变量和目标值。

## 许可与部署

按 [COPT 安装指南](https://guide.coap.online/copt/en-doc/install.html)获取与所装主版本匹配的许可，部署使用 `license.dat` 和 `license.key` 两个文件。

部署使用 `COPT_LICENSE_DIR`，为沙箱只读挂载具体的 `license.dat` 和 `license.key`。实际可用性要看运行反馈，安装 Python 包、加载原生库和许可验证是不同步骤，见[后端与许可证](../backends/)。

## 结果核对与资料

核对实际引擎、状态、目标方向和所有非零变量。时限停止时区分已有可行方案与已证明最优。对线性案例可用手算资源核对，复杂问题则保留完整模型与导出结果供复查。

原生表达和矩阵接口见 [COPT Python 文档](https://guide.coap.online/copt/en-doc/pythoninterface.html)，许可条件见 [安装指南](https://guide.coap.online/copt/en-doc/install.html)。
