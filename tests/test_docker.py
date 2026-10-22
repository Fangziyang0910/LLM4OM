"""Real worker integration: LLM4OM_TEST_DOCKER=1 pytest tests/test_docker.py."""

import asyncio
import os

import pytest

from llm4om.sandbox import Sandbox
from tests.conftest import PRODUCTION_CODE
from tests.test_sandbox import CPMPY_CODE, CVXPY_CODE, GUROBIPY_CODE, ORTOOLS_CODE, PULP_CODE

pytestmark = [pytest.mark.docker, pytest.mark.skipif(os.environ.get("LLM4OM_TEST_DOCKER") != "1",
                                                  reason="set LLM4OM_TEST_DOCKER=1 with the worker image built")]


@pytest.mark.parametrize("language,code,objective", [("pyomo", PRODUCTION_CODE, 13), ("pywraplp", ORTOOLS_CODE, 13),
    ("cpmpy", CPMPY_CODE, 13), ("pulp", PULP_CODE, 13), ("gurobipy", GUROBIPY_CODE, 13), ("cvxpy", CVXPY_CODE, 0.5)])
def test_worker_solves_each_language(language: str, code: str, objective: float) -> None:
    result = asyncio.run(Sandbox().solve(code, {}, language, 10))
    assert result.error is None, result.error
    assert result.objective == pytest.approx(objective, abs=1e-6) and result.variables


def test_worker_is_nonroot_readonly_and_has_no_network_or_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM4OM_LLM_API_KEY", "synthetic-secret")
    script = '''import os, socket
assert os.getuid() != 0
assert 'LLM4OM_LLM_API_KEY' not in os.environ
try:
    open('/worker-write-test', 'w')
except OSError:
    pass
else:
    raise AssertionError('root filesystem is writable')
with open('/tmp/worker-write-test', 'w') as file:
    file.write('ok')
try:
    socket.create_connection(('192.0.2.1', 80), timeout=0.5)
except OSError:
    pass
else:
    raise AssertionError('network is enabled')
print('isolated')
'''
    result = asyncio.run(Sandbox().run_script(script, 5))
    assert result.executed and result.output.strip() == "isolated", result.error


def test_cancelling_a_docker_worker_removes_its_container(monkeypatch: pytest.MonkeyPatch) -> None:
    async def check() -> None:
        sandbox = Sandbox()
        command = sandbox._command
        names = []

        def capture(name: str) -> list[str]:
            names.append(name)
            return command(name)

        monkeypatch.setattr(sandbox, "_command", capture)
        task = asyncio.create_task(sandbox.run_script("import time; time.sleep(60)", 60))

        async def inspect() -> tuple[int, str]:
            process = await asyncio.create_subprocess_exec("docker", "inspect", "--format", "{{.State.Running}}", names[0],
                                                          stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            stdout, _ = await process.communicate()
            return process.returncode, stdout.decode().strip()

        async def ready() -> None:
            while not names or (await inspect())[1] != "true":
                await asyncio.sleep(0.05)

        try:
            await asyncio.wait_for(ready(), 10)
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert (await inspect())[0] != 0

    asyncio.run(check())
