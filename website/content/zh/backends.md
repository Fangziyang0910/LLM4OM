后端列表来自实际求解沙箱的原生注册表。先确认模型类型与所选接口兼容，再检查依赖、可执行程序和许可证。

## 常见引擎怎样区分

| 引擎 | 常见用途与条件 |
|---|---|
| HiGHS、CBC、GLPK | 各自支持的 LP/MIP；通过兼容建模库接入 |
| SCIP | LP/MIP；通过 PySCIPOpt 可使用原生非线性约束 |
| CP-SAT | 整数、布尔、逻辑与离散排程 |
| Gurobi、COPT | 原生数学规划引擎，能力与许可按部署检查 |
| Clarabel、SCS | 兼容的连续锥模型 |
| OSQP | 连续凸二次规划与线性约束 |
| MOSEK | 兼容的数学规划模型，需要许可证 |
| Ipopt | 光滑连续非线性，通常是局部结论 |
| Bonmin | CasADi 等接口中的兼容混合整数非线性插件 |
| SAT、SMT、MiniZinc 等路径 | 通过 CPMpy 原生后端使用，以实际安装为准 |

这个表说明引擎家族；准确 ID 和可用原因应查看平台当前后端列表。同一引擎可以有不同库与接口标识。

## AUTO、安装与错误

AUTO 按建模库与返回模型的原生逻辑选择。显式指定后端时，平台保留该选择，不会在失败后换引擎。LP 后端不支持整数模型时直接报错。

后端依赖或许可证改变后，需要重启服务刷新缓存。注册表中存在名称，不表示已经安装完整可执行程序；插件加载成功也不代表商业许可有效。GPU 或独立商业运行时需另外满足其环境要求。

## 挂载许可证

Gurobi 使用 `GRB_LICENSE_FILE`，MOSEK 使用 `MOSEKLM_LICENSE_FILE`，COPT 使用 `COPT_LICENSE_DIR`。app 与宿主机的绝对路径要对应，沙箱才能只读挂载所需文件。例如：

```yaml
services:
  app:
    volumes:
      - /opt/gurobi/gurobi.lic:/opt/gurobi/gurobi.lic:ro
      - /opt/mosek/mosek.lic:/opt/mosek/mosek.lic:ro
```

只保留实际使用的挂载，并在 `.env` 填写对应变量。COPT 挂载具体的 `license.dat` 与 `license.key` 文件。沙箱无网络，这条部署路径需要能离线使用且适合容器及实际用途的许可。

## 官方许可说明

参阅 [Gurobi 文档](https://docs.gurobi.com/projects/optimizer/en/current/)、[MOSEK 客户端配置](https://docs.mosek.com/latest/licensing/client-setup.html)和[COPT 安装与许可](https://guide.coap.online/copt/en-doc/install.html)。许可证与密钥不提交到仓库；完整的容器配置见[原部署指南](https://github.com/Fangziyang0910/LLM4OM/blob/main/docs/deployment.md)。
