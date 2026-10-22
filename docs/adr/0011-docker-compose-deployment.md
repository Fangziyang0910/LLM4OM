# 整套服务用 Docker Compose 部署

## 背景

服务器部署原来需要在宿主机上安装 Python 和 uv，再用 Docker 运行沙箱。课题组希望服务器上只装 Docker。服务本身要为每次求解启动一个沙箱容器，所以服务进了容器之后，仍然需要一种启动容器的方式。

## 决定

- `Dockerfile` 构建 `llm4om` 镜像：锁定依赖安装到虚拟环境，加上 Docker 命令行客户端，以非 root 用户运行，数据目录是 `/data`。
- `compose.yaml` 有两个服务：`worker` 只构建沙箱镜像（如 `llm4om-worker:10`）；`app` 运行服务器，挂载宿主机的 `/var/run/docker.sock`，通过宿主机的 Docker 启动同级沙箱容器。
- `app` 以 root 启动，只做两件事：读取 socket 的用户组，把 `/data` 交给用户 `llm4om`；然后用 `setpriv` 切换到该用户并清空 capability。容器只授予这两步需要的 capability，根文件系统只读，并设置 `no-new-privileges`。socket 的用户组因宿主机而异，因此在启动时读取，不需要配置。
- `worker.py` 构建进沙箱镜像。同级容器的挂载路径按宿主机解析，`app` 容器内的文件无法挂载给沙箱。
- 预设模型和运行记录放在命名卷 `llm4om-data` 中；默认预设由 `.env` 的 `LLM4OM_LLM_*` 给出。

## 取舍

- 挂载 Docker socket 等于让 `app` 容器拥有宿主机的 root 权限。生成代码仍只在沙箱容器中运行，因此风险集中在服务器本身的漏洞上。Docker-in-Docker 需要特权容器，风险相同而更复杂；Socket 代理无法阻止创建特权容器，没有实际收益。
- Gurobi 许可证必须在 `app` 容器内外使用相同路径，因为沙箱容器按宿主机路径挂载它。
- 修改 `worker.py` 后必须更换沙箱镜像标签，否则旧镜像中的 Worker 会继续运行。测试检查 `compose.yaml` 与 `WORKER_IMAGE` 的标签一致。
