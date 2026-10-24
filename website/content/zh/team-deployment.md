团队部署把工作台、模型服务配置和运行记录集中在一台服务器上，成员通过浏览器使用。推荐先完成[单机启动](../installation/)，再配置共享访问。

## 使用 Docker Compose

服务器需要 Docker 和 Compose v2.24 或更新版本。克隆仓库、准备 `.env`，填写模型服务信息后启动：

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

工作台与 LangGraph 服务运行在 app 容器中，每次求解启动独立 Worker 沙箱。数据卷 `llm4om-data` 保存模型预设与全部运行记录。

## 配置访问与 HTTPS

工作台没有内置登录或用户级权限；能访问服务的人能使用共享额度并管理共享记录。限制团队 IP，或使用带登录的反向代理。

有域名时，可使用 Compose 自带的 Caddy 服务：

```dotenv
LLM4OM_DOMAIN=llm4om.example.edu
LLM4OM_PORT=127.0.0.1:8767
LLM4OM_TRUST_PROXY=1
```

将域名解析到服务器并开放 80、443 端口，然后运行：

```bash
docker compose --profile https up -d --build
```

示例域名需要换成实际域名。没有域名时可以在受控网络中使用 HTTP。

## 理解求解隔离

生成代码在无网络、只读、非 root 的沙箱内执行，完成后删除沙箱。app 需要挂载宿主机 Docker socket；这赋予其很高的宿主机权限，应部署在适合该权限边界的机器上。`--sandbox local` 不提供这种代码隔离，只用于开发。

## 更新与保留数据

```bash
git pull
docker compose up -d --build
```

`docker compose down` 停止服务但保留数据卷。不要为了更新而删除数据卷。修改模型环境变量后，重新创建 app 使配置生效。并发、用量和备份见[配置指南](../configuration/)，商业后端见[许可证](../backends/)。
