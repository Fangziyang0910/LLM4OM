# 部署指南

本文说明怎样把 LLM4OM 部署在服务器上，供课题组或团队使用。只在自己电脑上用时，按 [README](../README.md#快速开始) 启动即可。

## 推荐方式：Docker Compose

服务器上只需要 Docker（含 Compose v2.24 或更新版本），不需要 Python、uv 或 Node.js。

```bash
git clone https://github.com/Fangziyang0910/LLM4OM.git && cd LLM4OM
cp .env.example .env && chmod 600 .env    # 填写默认预设的服务商、地址、模型和密钥
docker compose up -d --build
```

在防火墙或云服务器安全组中放行端口 8767。其他人用 `http://<服务器 IP>:8767` 访问。

| 设置 | 作用 |
|---|---|
| `LLM4OM_PORT` | 对外端口，默认 `8767`。写成 `127.0.0.1:8767` 时只在本机监听 |
| `DOCKER_SOCKET` | Docker socket 路径。使用 rootless Docker 时设置 |
| `LLM4OM_LLM_*` | 默认预设：服务商、接口地址、模型、密钥和额外请求参数。见 [.env.example](../.env.example) |

### 组成

```text
浏览器 ──HTTP(S)──► app 容器（工作台 + LangGraph 服务器，用户 llm4om）
                      │  通过宿主机的 Docker socket，每次求解启动一个沙箱
                      ▼
                    沙箱容器 llm4om-worker:7（无网络、只读、非 root，用完即删）

数据卷 llm4om-data：预设模型（含密钥）和全部运行记录
```

| 组成 | 说明 |
|---|---|
| `app` 容器（镜像 `llm4om`） | 工作台和 LangGraph 服务器。启动脚本读取 Docker socket 的用户组，整理 `/data` 的属主，然后以用户 `llm4om`（uid 10001）运行服务，不保留任何 capability。根文件系统只读，日志自动轮转，崩溃或服务器重启后自动恢复 |
| 沙箱镜像 `llm4om-worker:7` | 由 `worker` 服务构建。每次求解，`app` 通过宿主机的 Docker 启动一个沙箱容器 |
| 数据卷 `llm4om-data` | 预设模型（含密钥）和全部运行记录。`docker compose down` 不会删除它 |

`app` 容器挂载了宿主机的 Docker socket，相当于拥有宿主机的 root 权限。生成代码只在沙箱容器中运行，不在 `app` 中运行。不要把这台服务器放在需要保护的内网中。取舍见 [ADR 0011](adr/0011-docker-compose-deployment.md)。

### 常用命令

| 任务 | 命令 |
|---|---|
| 更新 | `git pull && docker compose up -d --build` |
| 查看日志 | `docker compose logs -f app` |
| 查看状态 | `docker compose ps` |
| 重启 | `docker compose restart app` |
| 停止 | `docker compose down`（数据卷保留） |

修改 `.env` 后，运行 `docker compose up -d app` 使它生效。

## HTTPS

服务器有域名时，`compose.yaml` 中的 `https` 服务（Caddy）自动申请证书，并把 HTTPS 请求转给 `app`，包括运行的实时流。在 `.env` 中设置：

```bash
LLM4OM_DOMAIN=llm4om.example.edu    # 域名需解析到这台服务器，并放行 80 和 443 端口
LLM4OM_PORT=127.0.0.1:8767          # app 只在本机监听，外部只能经 HTTPS 访问
LLM4OM_TRUST_PROXY=1                # 按代理转发的客户端地址计算运行上限
```

然后运行 `docker compose --profile https up -d --build`。证书保存在 `caddy-data` 卷中。

没有域名时，可以继续用 HTTP 访问。工作台在 HTTP 下的全部功能都可用。

## 给多人使用

服务器 `.env` 中的模型就是大家共用的默认预设。

工作台没有登录和权限控制，适合信任范围内的小组。能访问端口的人可以：

- 用任一预设发起运行，消耗该预设的额度；
- 添加和删除页面上添加的预设（`.env` 的预设不能删除）；
- 查看、备注和删除全部运行记录。

访客读不到任何密钥。需要限制访问时，只放行课题组的 IP，或在前面加带登录的反向代理。

### 用量上限

在 `.env` 中设置。值为 0 或不设置，表示不限制。

| 变量 | 作用 |
|---|---|
| `LLM4OM_DAILY_TOKENS` | 每个预设每天最多使用的 token（输入加输出）。用完后，使用该预设的运行在下一次 LLM 调用前停止，页面提示换预设或次日再试。“预设模型”对话框显示各预设当天的用量 |
| `LLM4OM_RUNS_PER_HOUR` | 每个客户端地址每小时最多发起的运行数。超过时，服务器拒绝新运行。服务在反向代理之后时，同时设置 `LLM4OM_TRUST_PROXY=1` |
| `TZ` | 每日用量按这个时区换日，例如 `Asia/Shanghai`。Docker 容器默认用 UTC |

内部测试时，可以把每日 token 设得很大，例如 `LLM4OM_DAILY_TOKENS=1000000000`，并且不设每小时上限。

### 并发

同时执行的运行数由 `llm4om serve --jobs` 控制，默认是 4，其余运行排队。Docker 部署中，在 `compose.override.yaml` 里改 `app` 的 `command`：

```yaml
services:
  app:
    command: ["llm4om", "serve", "--workspace", "/data", "--port", "8767", "--jobs", "8"]
```

## Gurobi 许可证

没有许可证时，gurobipy 写法和线性模型的冲突诊断只能处理小规模模型。使用完整许可证时，把许可证挂载进 `app` 容器，并在 `.env` 中设置 `GRB_LICENSE_FILE=/opt/gurobi/gurobi.lic`。

**容器内外的路径必须相同**，因为沙箱容器由宿主机的 Docker 按宿主机路径挂载许可证：

```yaml
# compose.override.yaml
services:
  app:
    volumes:
      - /opt/gurobi/gurobi.lic:/opt/gurobi/gurobi.lic:ro
```

Gurobi 学术许可证一般只限本人使用。供他人使用前，请确认许可范围。

## 备份与恢复

数据卷 `llm4om-data` 保存全部运行记录和预设模型（含密钥）。服务每 10 秒和正常停止时把记录写入磁盘。写入先写临时文件再改名。进程被强制结束时，最多丢失最近约 10 秒的变化。

备份前先停止服务，保证记录完整：

```bash
docker compose stop app && docker compose cp app:/data ./llm4om-backup && docker compose start app
chmod -R go-rwx ./llm4om-backup    # 备份中有密钥
```

恢复：

```bash
docker compose stop app && docker compose cp ./llm4om-backup/. app:/data/ && docker compose start app
```

从直接运行的 `llm4om serve` 迁移到 Docker 时，用同样的方法把原工作区复制进数据卷。先停止服务，避免它退出时覆盖导入的记录：

```bash
docker compose stop app && docker compose cp runs/web/. app:/data/ && docker compose start app
```

## 运行追踪（可选）

需要在 LangSmith 中查看每次 LLM 调用时，在 `.env` 中设置 `LANGSMITH_TRACING=true`、`LANGSMITH_API_KEY` 和 `LANGSMITH_PROJECT`，然后重启。开启后，问题、数据和模型回答都会发送到 LangSmith。只在允许数据离开服务器时使用。

## 不用 Docker 部署

服务器上有 Python 3.11–3.13、uv 和 Docker 时，可以直接运行服务：

```bash
uv sync --all-extras
uv run llm4om build-worker
uv run llm4om serve --workspace /srv/llm4om --port 8767 --jobs 4
```

服务默认监听 `0.0.0.0`。用 systemd 等工具让它开机启动。沙箱仍然需要 Docker。

## 故障排查

| 现象 | 检查 |
|---|---|
| 其他机器打不开页面 | 防火墙和安全组是否放行端口；`LLM4OM_PORT` 是否写成了 `127.0.0.1:…` |
| 运行失败，提示找不到镜像 | `docker compose up -d --build` 会构建 `llm4om-worker:7`；直接运行时执行 `uv run llm4om build-worker` |
| 运行失败，提示无法连接 Docker | rootless Docker 需要设置 `DOCKER_SOCKET`；查看 `docker compose logs app` |
| 预设模型报 401 或 404 | 密钥、接口地址或模型 ID 有误。删掉预设，重新添加 |
| HTTPS 证书申请失败 | 域名是否解析到本机；80 和 443 端口是否放行；查看 `docker compose logs https` |
