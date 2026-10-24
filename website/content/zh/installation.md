已有团队平台地址时，直接打开浏览器即可使用。要运行自己的服务，可以用 Docker Compose 完成工作台、服务和求解环境的安装。

## 准备环境

| 方式 | 需要的环境 | 适合用途 |
|---|---|---|
| Docker Compose | Docker、Compose v2.24或更新版本、模型服务配置 | 个人或团队运行 |
| Python启动 | Python 3.11–3.13、uv、Docker、模型服务配置 | 开发或已有Python环境 |

运行数据保存在工作区或Compose数据卷中。安装前选择一台可持续保存数据并访问模型服务的机器。

## 使用 Docker Compose 启动

```bash
git clone https://github.com/Fangziyang0910/LLM4OM.git
cd LLM4OM
cp .env.example .env
chmod 600 .env
```

在编辑器中打开 `.env`，填写服务商、接口地址、模型ID与密钥。示例字段见[模型预设](../model-presets/)。然后运行：

```bash
docker compose up -d --build
docker compose ps
```

构建完成后打开 `http://localhost:8767`。首次运行会下载依赖并构建 Worker；启动日志可通过 `docker compose logs -f app` 查看。

## 从页面确认安装

打开工作台，检查默认模型预设和运行设置中的后端选项。按[快速开始](../quickstart/)输入生产题，完成一次生成与求解；页面应保存产量、模型、代码和运行步骤。

之后可添加附件、尝试优化对话，或在另一台设备使用服务器地址访问。共享访问和HTTPS见[团队部署](../team-deployment/)。

## 使用 Python 环境启动

在已经克隆的仓库中执行：

```bash
uv sync --all-extras
uv run llm4om build-worker
uv run llm4om serve --workspace runs/web --port 8767
```

该方式使用仓库提供的工作台构建文件，Python服务通过Docker沙箱完成求解。工作区 `runs/web` 保存历史与预设；使用其他位置时通过 `--workspace` 指定。

## 常用维护命令

| 操作 | 命令 |
|---|---|
| 查看运行状态 | `docker compose ps` |
| 查看服务日志 | `docker compose logs -f app` |
| 应用更新 | `git pull` 后执行 `docker compose up -d --build` |
| 应用环境变量变化 | `docker compose up -d app` |
| 停止服务并保留数据卷 | `docker compose down` |

模型连接问题见[预设配置](../model-presets/)，后端问题见[求解环境](../backends/)，历史数据备份见[配置与备份](../configuration/)。

## 官网与平台地址

GitHub Pages 发布官网和Docs。完整平台使用上述机器运行Python服务与求解环境；团队成员使用部署后的服务地址计算自己的问题。
