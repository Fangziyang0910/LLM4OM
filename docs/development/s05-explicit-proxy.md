# S05 显式 HTTP 代理

用途：记录SDK／Worker0.31.0的模型连接修复及支持范围。规范来源为 [Provider契约](../plugin-contracts.md)、[用户界面](s09-user-experience.md)和 [贡献流程](../../CONTRIBUTING.md)。本切片不修改建模方法、提示、求解器或评估协议。

## 目标行为

在本机Mihomo fake-IP环境中，模型接口的强制直连发生TLS中断；同一授权模型列表经本机代理返回200。现在内置Chat与Messages的配置可显式声明`proxy_url: http://127.0.0.1:7890`。默认仍不读取OS代理来选择路由。隔离的传输子进程忽略NO_PROXY对已声明路由的覆盖；SDK调用者的环境保持不变。

HTTP代理使用标准库，HTTPS目标仍经过TLS证书验证。重定向拒绝、请求超时、取消、资源预算和未知结果规则保持。代理支持HTTP地址及HTTPS CONNECT，不支持SOCKS、代理URL认证、非根路径、查询串或fragment。包含凭据或不支持路由字段的公开URL在输入边界拒绝，不进入请求配置的公开快照。

Web从服务端`.env`的可选`LLM4OM_LLM_PROXY_URL`读取路线；LLM API key仍只在服务端。例：

```dotenv
LLM4OM_LLM_PROXY_URL=http://127.0.0.1:7890
```

CLI／SDK通过RunConfig.llm.config.proxy_url声明同一配置。第三方HTTPTextFactory子类可复用此接口；其他Provider仅按各自Manifest声明，不自动声称支持代理。

## 验收与身份

本机3项公共Provider检查验证Chat／Messages实际走声明代理、NO_PROXY不覆盖、非法路线拒绝与公开输入不接受URL凭据。原CLI凭据拒绝及取消回收各1项通过；不是重复全量回归。42模块类型检查通过。

Worker0.31.0只构建一次，镜像身份为`sha256:c8962043ffd31a365208f53762820fc7ab02176a3d817f62c45ee397a391cfec`。旧Worker0.30.0和失败历史保留，不进行旧checkpoint迁移。真实网页建模验收单独记录，不把只读模型列表200当作生成或求解成功。

连接环境的来源说明见 [Mihomo DNS配置](https://wiki.metacubex.one/config/dns/)；本机观察与项目支持分别记录。该文档并不证明模型生成质量。

真实网页验收：run `6dcbd8fc00a746daa8614d449d1d08b6`，指定DeepSeek通过显式代理生成数学表述和严格IR，实际容器HiGHS目标13。一次真实LLM attempt／一次Solver／1134 Tokens／cost=null／零预留；浏览器观察到真实进行中步骤与完成结果，无页面错误。检查实际IR保留整数非负域、两类容量8以及利润系数3／2，解为A=3、B=2。没有将此前失败运行改写为成功，没有付费重试或批量实验。

另一次OptiMUS inline受限预算运行`dff75c58bdf54aa2988f0c13222d972d`完成16次真实请求（10767 Tokens），形成目标与约束的原生中间表述后，触及明确设置的16次请求上限，状态failed/budget_exhausted、零Solver；该失败保留，不重置预算或重复付费跑到成功。它验证代理可供分步方法使用，不作为完整OptiMUS成功声明。原用户默认预算的OptiMUS成功记录仍保留在原Web工作区。
