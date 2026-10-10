# S05 连接诊断

用途：记录Provider传输异常的可读诊断与实际连接观察。状态：SDK／Worker0.34.0开发实现。规范来源为[插件契约](../plugin-contracts.md#provider连接诊断)、FR-16／32和NFR-06／09；用户界面工作项为[#64](https://github.com/Fangziyang0910/LLM4OM/issues/64)。

## 实际观察

用户反馈修正运行814e86b0918e4a25b711936050ee0c80在首个模型请求后失败，错误码provider_connection_error。实际配置包含指定DeepSeek模型、正确endpoint和本机显式HTTP代理；记录为1次外部attempt、0次Solver、Token总量未知，10754预留保留。原运行没有具体连接异常类别，不能事后补写。

通过同一代理对供应方/models进行三次不收费GET检查，前两次约5秒后SSLEOFError，第三次HTTP状态200。观察支持间歇性TLS连接中断，没有证据说明建模算法造成网络失败；尚不能区分代理上游路线与供应方连接。Mihomo保持原规则模式、全局配置与选中出口，项目.env和密钥未修改。没有重跑失败建模，也不将/models成功作为完整生成验收。

## 实现

隔离传输将标准异常映射为固定诊断类别。Gateway在原有资源结算中保存类别，继续保留未知usage、费用和Token预留；不增加重试，不更改错误码或账本分母。资源恢复校验允许此已验证可选字段，原journal链和不可变请求身份不变。

网页在当前错误对应的公开attempt中读取类别，分别解释TLS中断、证书校验、DNS、拒绝连接、重置和超时。旧记录无此字段时显示通用连接错误。其他阶段或预算错误不套用先前连接诊断。原始异常文本和凭据不进入公共记录。

## 本机验收

tests/test_provider_proxy.py新增CLI场景：本机合成代理接受CONNECT后关闭连接，触发真实TLS中断。原0.33.0路径缺少connection_diagnostic，修复后记录tls_interrupted；只有一次attempt，status仍unknown、预留大于0、总Token为null、Solver为0，公共JSON不含合成密钥。该fixture不访问外部模型。

四项Provider聚焦检查2.524s通过，同时保留Chat／Messages显式代理、NO_PROXY和配置凭据拒绝。42模块类型检查通过。tests/web_connection_flow.cjs通过公开UI.decision输入验证TLS提示、未知用量说明、旧记录回退和预算错误不被误标；浏览器零POST／模型调用。既有公共HTTP单问题入口以确定性Provider和新Worker0.34.0容器HiGHS求得13，单项5.205s通过。

Worker0.34.0单次构建身份为sha256:dcab276d11cc394ea0d95103dd54a20a61f9ff5970b0365c459244ca3111f95d。证据位于/tmp/llm4om-connection-evidence，不提交用户运行数据。依赖下载曾遇到同类TLS中断，后续使用锁文件和本机缓存离线完成；没有更改依赖版本。

未运行真实模型生成、批量benchmark、全量重复回归或GitHub Actions。外部连接仍存在间歇性故障；本切片使后续故障可诊断，不声称控制了代理或供应方的稳定性。
