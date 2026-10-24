Use a Skill with your current Codex or Claude Code model, or open the Web workbench. If you already have a team service address, open it in a browser. Docker Compose installs your own workbench, server and solver environment.

## Prepare an environment

| Setup | Requirements | Use |
|---|---|---|
| Host Skill | uv, Git, Node.js 22.20+, Docker, Codex or Claude Code | Current host model; no platform API key or Web deployment |
| Docker Compose | Docker, Compose v2.24+, model-service configuration | Personal or team service |
| Python service | Python 3.11–3.13, uv, Docker, model-service configuration | Development or existing Python setup |

Data lives in a workspace or Compose volume. Choose a machine with persistent storage and access to the model service.

## Use the current Codex or Claude Code model

Install the CLI, solver environment and Skill from the same release:

```bash
uv tool install --python 3.12 git+https://github.com/Fangziyang0910/LLM4OM@v0.43.0
llm4om build-worker
npx skills add https://github.com/Fangziyang0910/LLM4OM/tree/v0.43.0/skills/llm4om --skill llm4om -g -a codex -a claude-code
```

Confirm `llm4om --version` reports `LLM4OM 0.43.0` and `llm4om backends` can query the worker. Open a new host session and invoke `$llm4om` in Codex or `/llm4om` in Claude Code. Give the agent the production problem from the [quickstart](../quickstart/), optionally requesting Feedback Repair and Pyomo. The expected optimum is A=3, B=2, profit=13.

The current host model performs the reasoning, writes code and explains actual results. The CLI preserves method stages and runs tools and solvers locally. No `.env`, platform model preset or Web server is required. `npx` installs skill files; it does not install the CLI or Docker.

Keep only the matching `-a` option for one host. Full examples, upgrades, removal and setup problems are covered in the [bilingual host-model guide](https://github.com/Fangziyang0910/LLM4OM/blob/v0.43.0/docs/host-modeling.md). Linux installation is verified; full macOS and Windows installation has not been verified.

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
uv sync --all-extras
uv run llm4om build-worker
uv run llm4om serve --workspace runs/web --port 8767
```

This uses bundled workbench build files and Docker solver sandboxes. `runs/web` retains history and presets; use `--workspace` for another location.

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
