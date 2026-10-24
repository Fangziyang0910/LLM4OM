A shared deployment centralizes the workbench, model configuration and run records on one server. Members use it through a browser. Complete a [single-machine launch](../installation/) before configuring shared access.

## Use Docker Compose

The server needs Docker and Compose v2.24 or later. Clone the repository, prepare `.env` with actual model-service details and start:

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f app
```

The app container runs the workbench and LangGraph service. Each solve uses a separate Worker sandbox. The `llm4om-data` volume stores presets and run history.

## Configure access and HTTPS

The workbench has no built-in login or user-level permissions. People with access can spend shared usage and manage shared records. Restrict team IPs or place an authenticated reverse proxy in front.

With a domain, use the included Caddy service:

```dotenv
LLM4OM_DOMAIN=llm4om.example.edu
LLM4OM_PORT=127.0.0.1:8767
LLM4OM_TRUST_PROXY=1
```

Point the domain to the server, allow ports 80 and 443, then run:

```bash
docker compose --profile https up -d --build
```

Replace the example domain with your actual domain. Without one, HTTP can be used on an access-controlled network.

## Understand execution isolation

Generated code runs in network-disabled, read-only, non-root sandboxes that are deleted after completion. The app mounts the host Docker socket, giving it substantial host privileges; deploy on a machine appropriate for that boundary. `--sandbox local` does not provide this code isolation and is for development.

## Update and retain data

```bash
git pull
docker compose up -d --build
```

`docker compose down` stops services while retaining the data volume. Do not remove that volume merely to update. Recreate the app after changing model environment variables. See [Configuration](../configuration/) for concurrency, usage and backups, and [Licenses](../backends/) for commercial engines.
