Use a Skill with your current Codex or Claude Code model, or open the Web workbench. If you already have a team service address, open it in a browser. Docker Compose installs your own workbench, server and solver environment.

## Prepare an environment

| Setup | Requirements | Use |
|---|---|---|
| Host Skill | uv, Git, Node.js 22.20+, Docker, Codex or Claude Code | Current host model; no platform API key or Web deployment |
| Docker Compose | Docker, Compose v2.24+, model-service configuration | Personal or team service |
| Python service | Python 3.11–3.13, uv, Docker, model-service configuration | Development or existing Python setup |

Data lives in a workspace or Compose volume. Choose a machine with persistent storage and access to the model service.

## Use the current Codex or Claude Code model

Install with Node.js 22.20+ and Git. Select your agent when prompted. To run the skill, the agent needs shell and workspace access, [uv](https://docs.astral.sh/uv/getting-started/installation/), and a running Docker engine.

```bash
npx skills add Fangziyang0910/LLM4OM --skill llm4om -g
```

Open a new session, invoke `$llm4om` in Codex or `/llm4om` in Claude Code, then describe your problem and attach your data. Your current model formulates the problem and explains the solution. The skill downloads its pinned runtime on first use and builds and reuses the Docker solver image on demand. No separate LLM4OM CLI, model API key, or Web service is required.

For a worked example, session recovery, and upgrades, see the [host modeling guide](https://github.com/Fangziyang0910/LLM4OM/blob/main/docs/host-modeling.md).

## Start with Docker Compose

```bash
git clone https://github.com/Fangziyang0910/LLM4OM.git
cd LLM4OM
cp .env.example .env
chmod 600 .env
```

Edit `.env` with provider, endpoint, model ID and key; see [LLM presets](../model-presets/). Then run:

```bash
docker compose up -d --build
docker compose ps
```

After building, open `http://localhost:8767`. Initial setup downloads dependencies and builds the Worker. Inspect startup with `docker compose logs -f app`.

## Confirm setup in the workbench

Check the default preset and backend options. Complete the production [quickstart](../quickstart/); the run should retain quantities, formulation, code and stages.

Then add attachments or try Optimization chat. Other devices can use the server address. See [team deployment](../team-deployment/) for shared access and HTTPS.

## Start from Python

In the cloned repository:

```bash
uv sync --extra web
uv run llm4om build-worker
uv run llm4om serve --workspace runs/web --port 8767
```

This uses bundled workbench build files and Docker solver sandboxes. Solver dependencies are installed in the Worker image; the host only needs Web dependencies, without every commercial or platform-specific solver. `runs/web` retains history and presets; use `--workspace` for another location.

## Maintenance commands

| Action | Command |
|---|---|
| Status | `docker compose ps` |
| Logs | `docker compose logs -f app` |
| Update | `git pull`, then `docker compose up -d --build` |
| Apply environment changes | `docker compose up -d app` |
| Stop, retaining data volume | `docker compose down` |

See [presets](../model-presets/) for connections, [backends](../backends/) for solver setup and [backups](../configuration/) for persistent data.

## Website and platform addresses

GitHub Pages serves the website and Docs. The complete platform runs Python and solver services on the configured machine. Team members calculate through that deployed service address.
