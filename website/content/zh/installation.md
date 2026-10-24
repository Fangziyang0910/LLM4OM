已有团队平台地址时，可以直接在浏览器中使用。要运行自己的服务，Docker Compose 是最少步骤的方式。

## 使用 Docker Compose

需要 Docker，以及 Compose v2.24 或更新版本。服务器不需要另装 Python、uv 或 Node.js。

```bash
git clone https://github.com/Fangziyang0910/LLM4OM.git
cd LLM4OM
cp .env.example .env
chmod 600 .env
```

编辑 `.env`，填写实际的模型服务商、接口地址、模型 ID 和密钥。默认预设的字段见[配置大模型](../model-presets/)。然后启动：

```bash
docker compose up -d --build
```

打开 `http://localhost:8767`。首次构建需要下载依赖并创建求解沙箱镜像，等待服务启动完成后再进入页面。

## 使用本地 Python 环境

需要 Python 3.11–3.13、[uv](https://docs.astral.sh/uv/) 和 Docker。在已经克隆的仓库中运行：

```bash
uv sync --all-extras
uv run llm4om build-worker
uv run llm4om serve --workspace runs/web --port 8767
```

仓库包含工作台构建文件，正常使用不需要 Node.js。这里的 Python 服务仍通过 Docker 沙箱求解。`--sandbox local` 会在本机执行生成代码，只用于开发环境。

## 启动后做什么

确认模型预设可用，然后按[完成第一个方案](../quickstart/)测试一条完整建模流程。同一局域网中的设备可使用服务器 IP 和端口访问；团队共享、访问限制和 HTTPS 见[团队部署](../team-deployment/)。

GitHub Pages 承载官网和这些文档。完整平台的模型调用、Python 服务和求解器需要单独运行。
