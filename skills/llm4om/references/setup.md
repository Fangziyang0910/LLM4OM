# Local execution setup

The skill contains instructions. The CLI contains method graphs and execution tools. The worker image contains modeling libraries and solver backends. Installing this skill does not install Python packages or Docker.

Prepare uv, Git, Node.js 22.20 or newer, and a running Docker installation. The CLI supports Python 3.11–3.13. Install this release with Python 3.12:

```bash
uv tool install --python 3.12 git+https://github.com/Fangziyang0910/LLM4OM@v0.43.0
llm4om build-worker
llm4om --version
llm4om methods
llm4om backends
```

The version should be `LLM4OM 0.43.0`. If `llm4om` is not found, run `uv tool update-shell` and open a new terminal. If Docker cannot connect, start it and confirm `docker info` works. The first worker build downloads solver dependencies and can take several minutes.

For a local development checkout, run the following from the repository root, not the skill directory:

```bash
uv tool install --python 3.12 .
```

Keep the skill and CLI on the same published revision. Host sessions also record the package version and method parameters; a changed installation must start a new session.

The base CLI needs no LLM provider package, API key, model preset, Node build, Web server, or listening port. `llm4om[llm]` enables the separate API-model `run` command. `llm4om[web]` enables the existing Web workbench. Neither extra is needed for this skill.

If Docker is unavailable, a developer can install the `solve` and `autoformulation` extras into the CLI's Python environment and use `--sandbox local`. This runs generated code without container isolation. All libraries used by the code and all selected solver plugins must exist in that environment. Commercial solver licensing follows the same rules as the existing worker.

Install the skill from a local checkout:

```bash
npx skills add . --skill llm4om -g -a codex -a claude-code
```

Install the published skill for both hosts:

```bash
npx skills add https://github.com/Fangziyang0910/LLM4OM/tree/v0.43.0/skills/llm4om --skill llm4om -g -a codex -a claude-code
```

Keep only the matching `-a` option when one host is used. Open a new host session after installing. To upgrade, reinstall both CLI and skill from the same release; add `--force` to `uv tool install` when replacing an existing installation, then start a new modeling session.

Release v0.43.0 also provides `llm4om-0.43.0-py3-none-any.whl` and `llm4om-skill-0.43.0.zip` under `https://github.com/Fangziyang0910/LLM4OM/releases/download/v0.43.0/`. These URLs can replace the Git sources in the `uv tool install` and `npx skills add` commands. The Docker worker still needs to be built.

An IDE must support both skills and command execution to run the complete workflow. A skills-only document viewer can read the methods but cannot execute solvers. Linux installation is verified; full macOS and Windows installation has not been verified.
