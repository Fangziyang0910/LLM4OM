"""The actual server keeps an interrupted method's public work across a graceful restart."""

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

import httpx

ROOT = Path(__file__).parents[1]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def until(read: Callable[[], Any], timeout: float = 20) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if result := read():
                return result
        except httpx.HTTPError:
            pass
        time.sleep(0.05)
    raise AssertionError("Server did not reach the expected state")


@contextmanager
def server(command: list[str], port: int, ready: str, env: dict[str, str], log: Path) -> Iterator[httpx.Client]:
    with log.open("w") as output, httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=5) as client:
        process = subprocess.Popen([sys.executable, *command], cwd=ROOT, env=env, stdout=output, stderr=output)
        try:
            until(lambda: client.get(ready).is_success)
            yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                raise AssertionError(f"Server did not stop gracefully; see {log}") from None


def test_cancelled_method_survives_a_server_restart(tmp_path: Path) -> None:
    llm_port, port = free_port(), free_port()
    env = {**os.environ, "PYTHON_DOTENV_DISABLED": "1", "LLM4OM_LLM_PROVIDER": "openai_compatible",
           "LLM4OM_LLM_API_KEY": "restart-test-key", "LLM4OM_LLM_MODEL": "mock-model",
           "LLM4OM_LLM_BASE_URL": f"http://127.0.0.1:{llm_port}/v1", "LLM4OM_LLM_EXTRA_BODY": "{}",
           "LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"}
    command = ["-m", "llm4om.cli", "serve", "--host", "127.0.0.1", "--port", str(port), "--sandbox", "local",
               "--workspace", str(tmp_path / "workspace")]
    with server([str(ROOT / "frontend/e2e/mock_llm.py"), str(llm_port)], llm_port, "/v1/models", env, tmp_path / "llm.log"):
        with server(command, port, "/api/options", env, tmp_path / "first.log") as client:
            thread = client.post("/threads", json={"metadata": {"title": "restart-test"}}).json()["thread_id"]
            run = client.post(f"/threads/{thread}/runs", json={"assistant_id": "feedback_repair",
                "input": {"description": "E2E_PAUSE_REPAIR"}, "context": {"language": "pyomo", "preset": "env"}}).json()
            query = {"namespace": "llm4om.progress", "key": thread}

            def repairing() -> bool:
                saved = client.get("/store/items", params=query).json()
                return bool(saved and any(step["title"] == "repair" for step in saved["value"]["steps"]))

            until(repairing)
            response = client.post(f"/threads/{thread}/runs/{run['run_id']}/cancel", params={"wait": "true"})
            response.raise_for_status()
            before = client.get("/store/items", params=query).json()["value"]
            assert "return m.missing" in before["code"] and before["timing"]["finished_at"]

        with server(command, port, "/api/options", env, tmp_path / "restarted.log") as client:
            after = client.get("/store/items", params=query).json()["value"]
            assert after == before
            assert "restart-test-key" not in str(after)
            assert client.get(f"/threads/{thread}").json()["metadata"]["title"] == "restart-test"
            client.delete(f"/threads/{thread}").raise_for_status()
            assert client.get("/store/items", params=query).json() is None
            assert client.delete(f"/threads/{thread}").status_code == 404

            thread = client.post("/threads", json={}).json()["thread_id"]
            client.post(f"/threads/{thread}/runs", json={"assistant_id": "feedback_repair",
                "input": {"description": "E2E_PAUSE_REPAIR"}, "context": {"language": "pyomo", "preset": "env"}}).raise_for_status()
            query = {"namespace": "llm4om.progress", "key": thread}
            until(repairing)
            client.post("/threads/prune", json={"thread_ids": [thread]}).raise_for_status()
            assert client.get(f"/threads/{thread}").status_code == 404
            assert client.get("/store/items", params=query).json() is None
