# The LLM4OM server. It starts sandbox containers (llm4om-worker) through the host's Docker socket; see compose.yaml.
FROM python:3.12-slim AS dependencies
RUN python -m pip install --no-cache-dir uv==0.12.19
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --extra web --no-install-project

FROM dependencies AS package
COPY README.md LICENSE NOTICE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv build --wheel --out-dir /dist

FROM python:3.12-slim
# Only the client: `docker run` and `docker kill` for the sandbox.
COPY --from=docker:29.8.1-cli /usr/local/bin/docker /usr/local/bin/docker
COPY --from=dependencies /app/.venv /app/.venv
# Keep the workbench wheel in its own layer so app updates can reuse the locked runtime.
RUN --mount=from=package,source=/dist,target=/dist \
    python -m pip --python /app/.venv/bin/python install --no-cache-dir --no-deps --no-index /dist/*.whl
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
