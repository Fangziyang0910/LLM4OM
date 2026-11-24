# Runtime setup

Run `uv --version` and `docker info` in the agent's terminal if the runner reports an environment problem. The first command needs access to the pinned LLM4OM source and Python packages. The first solve needs Docker access to build the solver image from its packaged recipe. Later runs reuse uv's cache and the local image. If the same runtime and all its dependencies are already cached, use `uv run --offline --script` during a network outage.

| Symptom | Action |
| --- | --- |
| `uv` is missing | Install [uv](https://docs.astral.sh/uv/getting-started/installation/) in the agent's execution environment and reopen the terminal. |
| Docker is missing or unreachable | Start Docker and check that this user can access the configured engine. Retry the same command. |
| Download or build fails | Read the error on stderr, restore access to the reported source or registry, then retry. |
| A commercial backend requests a license | Configure that backend's license or choose an available open-source backend supported by the problem. |

Supply paths from the user's current workspace. Keep session artifacts there; the installed skill directory may be read-only. Updating the skill updates its runtime pin. Finish active sessions with the version that started them.
