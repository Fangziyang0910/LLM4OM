"""The sandbox: builds and solves generated code, or runs a method's check script, away from the platform.

`worker.py` does the work inside the sandbox; it imports nothing from llm4om. Docker (the default) isolates it with no
network and a read-only file system; `local` runs it as a subprocess, for development and tests.
"""

import asyncio
import contextlib
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

WORKER = Path(__file__).with_name("worker.py")
RESULT_MARKER = "@@LLM4OM_RESULT@@"
WORKER_IMAGE = "llm4om-worker:3"
START_MARGIN = 60  # seconds beyond the time limit for starting the sandbox, importing libraries and building the model


@dataclass
class SolveResult:
    status: str  # optimal, feasible, infeasible, unbounded, infeasible_or_unbounded, time_limit, executed or error
    objective: float | None = None
    variables: dict[str, float] = field(default_factory=dict)
    output: str = ""
    error: str | None = None

    @property
    def executed(self) -> bool:
        """The code ran: it built a model and the solver returned a status, or the script finished."""
        return self.error is None and self.status != "error"

    @property
    def has_solution(self) -> bool:
        """A solution was found; a satisfaction problem (CPMpy without objective) has no objective value."""
        return self.objective is not None or (self.status == "feasible" and bool(self.variables))

    def feedback(self, max_variables: int = 60) -> str:
        """Plain-text execution feedback for prompts."""
        lines = [f"Status: {self.status}"]
        if self.error:
            lines.append("Error:\n" + self.error)
        if self.objective is not None:
            lines.append(f"Objective value: {self.objective:g}")
        if self.has_solution:
            nonzero = [(name, value) for name, value in self.variables.items() if value]
            shown = "\n".join(f"  {name} = {value:g}" for name, value in nonzero[:max_variables])
            more = f"\n  ... {len(nonzero) - max_variables} more nonzero variables" if len(nonzero) > max_variables else ""
            lines.append(f"Nonzero variables ({len(nonzero)} of {len(self.variables)}):\n{shown}{more}")
        if self.output.strip():
            lines.append("Printed output:\n" + self.output.strip()[-3000:])
        return "\n".join(lines)


class Sandbox:
    """Runs generated code in Docker (`docker`) or as a local subprocess (`local`)."""

    def __init__(self, kind: str = "docker", image: str = WORKER_IMAGE) -> None:
        if kind not in ("docker", "local"):
            raise ValueError("The sandbox must be 'docker' or 'local'.")
        self.kind, self.image = kind, image

    async def solve(self, code: str, data: dict[str, str], language: str, time_limit: float) -> SolveResult:
        """Build the model from `code` with `data` and solve it with the language's solver, within `time_limit`."""
        return await self._run({"code": code, "data": data, "language": language, "time_limit": time_limit}, time_limit)

    async def run_script(self, script: str, time_limit: float) -> SolveResult:
        """Run a script as __main__; `output` holds what it printed and any traceback."""
        return await self._run({"script": script}, time_limit)

    def _command(self, name: str) -> list[str]:
        if self.kind == "local":
            return [sys.executable, "-I", str(WORKER)]
        command = ["docker", "run", "--rm", "-i", "--name", name, "--network", "none", "--memory", "2g",
                   "--cpus", "2", "--pids-limit", "256", "--read-only", "--tmpfs", "/tmp:rw,size=256m",
                   "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-e", "HOME=/tmp",
                   "-v", f"{WORKER}:/opt/llm4om/worker.py:ro"]
        license_file = os.environ.get("GRB_LICENSE_FILE")
        if license_file and Path(license_file).is_file():
            command += ["-v", f"{license_file}:/opt/gurobi/gurobi.lic:ro", "-e", "GRB_LICENSE_FILE=/opt/gurobi/gurobi.lic"]
        return command + [self.image, "python", "-I", "/opt/llm4om/worker.py"]

    async def _run(self, request: dict[str, Any], time_limit: float) -> SolveResult:
        timeout = time_limit + START_MARGIN
        name = "llm4om-" + uuid.uuid4().hex[:12]
        env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "GRB_LICENSE_FILE")
               if key in os.environ} if self.kind == "local" else None
        process = await asyncio.create_subprocess_exec(*self._command(name), stdin=asyncio.subprocess.PIPE,
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(json.dumps(request).encode()), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError) as error:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            if self.kind == "docker":
                await (await asyncio.create_subprocess_exec("docker", "kill", name, stdout=asyncio.subprocess.DEVNULL,
                                                            stderr=asyncio.subprocess.DEVNULL)).wait()
            if isinstance(error, asyncio.CancelledError):
                raise
            return SolveResult("error", error=f"Execution exceeded {timeout:g} seconds and was stopped.")
        for line in reversed(stdout.decode(errors="replace").splitlines()):
            if line.startswith(RESULT_MARKER):
                return SolveResult(**json.loads(line[len(RESULT_MARKER):]))
        detail = stderr.decode(errors="replace").strip()[-2000:]
        hint = " Build it with `llm4om build-worker`." if "Unable to find image" in detail else ""
        return SolveResult("error", error=f"The sandbox did not return a result (exit code {process.returncode}).{hint}\n{detail}")
