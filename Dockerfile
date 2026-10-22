# The LLM4OM server. It starts sandbox containers (llm4om-worker) through the host's Docker socket; see compose.yaml.
FROM python:3.12-slim AS build
RUN python -m pip install --no-cache-dir uv==0.12.19
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

FROM python:3.12-slim
# Only the client: `docker run` and `docker kill` for the sandbox.
COPY --from=docker:29.8.1-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=build /app/.venv /app/.venv
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/llm4om-entrypoint
# pip is unused at run time; removing it drops its advisories. The entrypoint switches to the llm4om user.
RUN python -m pip uninstall -y pip && useradd --system --uid 10001 --user-group --home-dir /data --create-home llm4om
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8767
VOLUME /data
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8767/ok', timeout=4)"]
ENTRYPOINT ["llm4om-entrypoint"]
CMD ["llm4om", "serve", "--workspace", "/data", "--port", "8767"]
