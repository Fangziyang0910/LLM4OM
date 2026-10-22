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
# The image contains worker.py, so a change to worker.py or worker.Dockerfile needs a new tag (and compose.yaml's).
WORKER_IMAGE = "llm4om-worker:10"
START_MARGIN = 60  # seconds beyond the time limit for starting the sandbox, importing libraries and building the model


@dataclass
class SolveResult:
    status: str  # also distinguishes locally_optimal/locally_infeasible for nonlinear solvers
    objective: float | None = None
    variables: dict[str, float] = field(default_factory=dict)
    output: str = ""
    error: str | None = None
    # For an infeasible model: {tool, items, total, error}, the constraints that conflict. Shown to people only;
    # feedback() leaves it out, so no method gets help the original method did not have.
    diagnosis: dict[str, Any] | None = None

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

    def __init__(self, kind: str = "docker", image: str = WORKER_IMAGE, max_jobs: int = 4) -> None:
        if kind not in ("docker", "local"):
            raise ValueError("The sandbox must be 'docker' or 'local'.")
        self.kind, self.image = kind, image
        if max_jobs < 1:
            raise ValueError("The sandbox concurrency must be at least 1.")
        self._slots = asyncio.Semaphore(max_jobs)

    async def solve(self, code: str, data: dict[str, str], language: str, time_limit: float) -> SolveResult:
        """Build the model from `code` with `data` and solve it with the language's solver, within `time_limit`."""
        return await self._run({"code": code, "data": data, "language": language, "time_limit": time_limit}, time_limit)

    async def run_script(self, script: str, time_limit: float) -> SolveResult:
        """Run a script as __main__; `output` holds what it printed and any traceback."""
        return await self._run({"script": script}, time_limit)

    def _command(self, name: str) -> list[str]:
        if self.kind == "local":
            return [sys.executable, "-I", str(WORKER)]
        command = ["docker", "run", "--rm", "-i", "--pull", "never", "--name", name, "--network", "none", "--memory", "2g",
                   "--cpus", "2", "--pids-limit", "256", "--read-only", "--tmpfs", "/tmp:rw,size=256m",
                   "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-e", "HOME=/tmp"]
        for variable, destination in [("GRB_LICENSE_FILE", "/opt/gurobi/gurobi.lic"),
                                      ("MOSEKLM_LICENSE_FILE", "/opt/mosek/mosek.lic")]:
            license_file = os.environ.get(variable)
            if license_file and Path(license_file).is_file():
                command += ["-v", f"{Path(license_file).resolve()}:{destination}:ro", "-e", f"{variable}={destination}"]
        # Mount only COPT's two license files, never the entire installation or home directory.
        license_dir = os.environ.get("COPT_LICENSE_DIR")
        if license_dir:
            for filename in ("license.dat", "license.key"):
                path = Path(license_dir, filename)
                if path.is_file():
                    command += ["-v", f"{path.resolve()}:/opt/copt/{filename}:ro"]
            command += ["-e", "COPT_LICENSE_DIR=/opt/copt"]
        return command + [self.image, "python", "-I", "/opt/llm4om/worker.py"]

    async def _run(self, request: dict[str, Any], time_limit: float) -> SolveResult:
        async with self._slots:
            return await self._execute(request, time_limit)

    async def _execute(self, request: dict[str, Any], time_limit: float) -> SolveResult:
        timeout = time_limit + START_MARGIN
        name = "llm4om-" + uuid.uuid4().hex[:12]
        env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "GRB_LICENSE_FILE",
                                               "MOSEKLM_LICENSE_FILE", "COPT_LICENSE_DIR")
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
                await (await asyncio.create_subprocess_exec("docker", "rm", "--force", name, stdout=asyncio.subprocess.DEVNULL,
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
