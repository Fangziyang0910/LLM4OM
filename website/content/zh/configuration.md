服务器配置决定默认模型、并发、共享用量和数据保存位置。页面里的运行配置记录实际采用的设置，不包含密钥。

## 常用环境变量

| 变量 | 作用 |
|---|---|
| `LLM4OM_LLM_PROVIDER` | 默认预设的服务商 |
| `LLM4OM_LLM_BASE_URL` | 模型服务接口地址 |
| `LLM4OM_LLM_MODEL` | 实际请求使用的模型 ID |
| `LLM4OM_LLM_API_KEY` | 默认预设密钥 |
| `LLM4OM_LLM_NAME` | 预设的显示名称 |
| `LLM4OM_LLM_EXTRA_BODY` | 服务商额外请求体，使用 JSON |
| `LLM4OM_DAILY_TOKENS` | 每个预设每天的输入与输出 token 总上限 |
| `LLM4OM_RUNS_PER_HOUR` | 每个客户端地址每小时的运行上限 |
| `LLM4OM_SANDBOX_JOBS` | 服务中同时执行的求解和检查脚本上限，默认 4，必须大于 0 |
| `TZ` | 每日用量的换日时区，例如 `Asia/Shanghai` |
| `LLM4OM_TRUST_PROXY` | 可信反向代理后按转发客户端地址计数 |
| `LLM4OM_SEARCH_API_KEY` | 独立搜索服务密钥 |
| `LLM4OM_SEARCH_BASE_URL` | 独立搜索服务地址 |

每日 token 和每小时运行上限为 0 或未设置时不限制。每日额度用完会在下一次大模型调用前停止，已经完成的结果仍保留。完整字段以仓库 `.env.example` 为准。

## 并发与排队

`llm4om serve --jobs` 控制同时活动的运行数，默认 4，其余排队。沙箱并发另由 `LLM4OM_SANDBOX_JOBS` 限制，覆盖所有运行，包括 AutoFormulation 的并行检查。等待沙箱仍计入运行总时限。

一个工作区供一个服务进程使用。要保留历史，持续使用同一个 `--workspace` 或 Compose 数据卷。

## 备份与恢复

数据包含预设密钥，应限制备份访问权限。先停止 app，复制完整工作区，再恢复服务：

```bash
docker compose stop app
docker compose cp app:/data ./llm4om-backup
chmod -R go-rwx ./llm4om-backup
docker compose start app
```

恢复时先停服务，再复制备份内容到 `/data/`，避免退出写回覆盖恢复数据。正常保存按周期和退出时执行；强制终止可能丢失最近尚未落盘的变化。具体恢复命令见[原部署指南](https://github.com/Fangziyang0910/LLM4OM/blob/main/docs/deployment.md)。

## 可选追踪

启用 LangSmith 会把问题、数据和模型回答发送到追踪服务。仅在允许这类数据传输时设置 `LANGSMITH_TRACING` 与相关密钥。普通平台记录不需要开启外部追踪。
