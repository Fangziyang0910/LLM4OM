If your team already provides a platform address, open it in your browser. To run your own service, Docker Compose provides the shortest setup.

## Use Docker Compose

Install Docker with Compose v2.24 or later. The server does not need a separate Python, uv or Node.js installation.

```bash
git clone https://github.com/Fangziyang0910/LLM4OM.git
cd LLM4OM
cp .env.example .env
chmod 600 .env
```

Edit `.env` with the actual provider, endpoint, model ID and API key. See [Configure LLM presets](../model-presets/) for the fields. Then start the service:

```bash
docker compose up -d --build
```

Open `http://localhost:8767`. The first build downloads dependencies and creates the solver sandbox image. Wait for the service to finish starting before opening the workbench.

## Use a local Python environment

Install Python 3.11–3.13, [uv](https://docs.astral.sh/uv/) and Docker. In your cloned repository, run:

```bash
uv sync --all-extras
uv run llm4om build-worker
uv run llm4om serve --workspace runs/web --port 8767
```

The repository includes the built workbench, so regular use does not require Node.js. This Python service still solves in Docker sandboxes. The `--sandbox local` option executes generated code on the host and is intended for development.

## After launch

Check that an LLM preset is available, then follow [Your first plan](../quickstart/) to test the complete workflow. Devices on the same network can use the server's IP address and port. See [Team deployment](../team-deployment/) for shared use, access controls and HTTPS.

GitHub Pages hosts the product website and this documentation. The full platform's LLM calls, Python service and solvers run separately.
