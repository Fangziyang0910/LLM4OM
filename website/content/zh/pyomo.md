Pyomo 用集合、参数、变量、目标和约束表达代数模型。它可以连接多个原生后端；模型写法与实际求解引擎分别选择。

## 支持的接口

平台识别 `ConcreteModel`、已经实例化的 `AbstractModel` 和 `pyomo.kernel` 模型。GDP、DAE 等组件仍属于代数建模范围，不是额外的库选项；是否可求解取决于模型变换和所选后端。

## 在平台中选择

选择建模库 Pyomo，后端可用 AUTO 或实际列表中的原生 ID。通常代数模型默认使用 HiGHS，Kernel 自动使用支持其模型类型的 CBC。非线性模型需要对应的已安装后端。

```bash
uv run llm4om run --problem "你的完整问题" --method direct --language pyomo --solver highs
```

## 生成代码的要求

`build_model(data)` 返回已经构建的原生模型，平台负责求解。变量域和上下界应明确，例如非负整数与允许负数的连续变量不能混用；构建模型时不能先读取尚未求解的变量值。

线性模型有条件地支持 Gurobi IIS 冲突证据，具体依赖许可与诊断路径，见[无解解释](../conflicts/)。

## 继续阅读

参阅 [Pyomo 官方建模文档](https://pyomo.readthedocs.io/en/stable/explanation/modeling/index.html)、[Kernel API](https://pyomo.readthedocs.io/en/stable/api/pyomo.kernel.html)和平台的[后端说明](../backends/)。服务从原生注册表发现实际引擎，不把分解算法名称直接列作可执行后端。
