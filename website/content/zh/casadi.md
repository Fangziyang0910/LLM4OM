CasADi 用符号表达式与原生插件建立并求解优化问题。常见路径是 Opti 与 Ipopt，用于光滑连续非线性模型。

## 支持的接口

平台支持 Opti NLP、Opti Conic，以及 `nlpsol`、`qpsol`、`conic` 原生问题字典。Opti 返回模型；低层接口还需返回问题结构、数值参数、可选插件名和配置。结果变量按原生顺序解释。

## 在平台中选择

选择 CasADi，常用默认是 Ipopt。使用平滑表达式，按题面设置有意义的边界与初值。整数域需要 Bonmin 等兼容插件，Ipopt 不能代替整数求解。

平台从 CasADi 原生插件读取并检查加载情况。插件可以加载，不表示商业许可已验证；具体参数仍遵循插件原生 API。

## 最大化与状态

CasADi 的最小化接口处理最大化时，需要最小化负目标，并在返回字典中带 `objective_sign: -1`，让平台恢复原目标值。例如：

```python
return {"model": model, "objective_sign": -1}
```

非凸问题中 Ipopt 通常给出局部结果。`locally_optimal` 不是全局最优证书，局部不可行也不证明整个问题不可行。结果页保留这些含义。

## 官方资料

参阅 [CasADi 官方文档](https://web.casadi.org/docs/)和[插件 API](https://web.casadi.org/python-api/)。如果需要全局结论，应选择适合模型的全局求解方式，并核对该插件在部署中的实际能力。
