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
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

WORKER = Path(__file__).with_name("worker.py")
RESULT_MARKER = "@@LLM4OM_RESULT@@"
# The image contains worker.py, so a change to worker.py or worker.Dockerfile needs a new tag (and compose.yaml's).
WORKER_IMAGE = "llm4om-worker:14"
START_MARGIN = 60  # seconds beyond the time limit for starting the sandbox, importing libraries and building the model
MAX_STDOUT_BYTES = 32 * 1024 * 1024
MAX_STDERR_BYTES = 1 * 1024 * 1024


@dataclass
class SolveResult:
    status: str  # also distinguishes locally_optimal/locally_infeasible for nonlinear solvers
    objective: float | None = None
    variables: dict[str, float] = field(default_factory=dict)
    output: str = ""
    error: str | None = None
    # For an infeasible model: {tool, items, total, error}. feedback() leaves it out; the platform explains it,
    # and only the project's Feedback Repair opts in. Published methods keep their original feedback.
    diagnosis: dict[str, Any] | None = None
    solver: str | None = None  # actual backend, also when the library selected it automatically

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
        self._catalog: dict[str, Any] | None = None
        self._catalog_lock = asyncio.Lock()

    @staticmethod
    def _to_result(payload: dict[str, Any]) -> SolveResult:
        allowed = {item.name for item in fields(SolveResult)}
        filtered = {key: value for key, value in payload.items() if key in allowed}
        if not isinstance(filtered.get("status"), str):
            return SolveResult("error", error="The sandbox returned an invalid result payload.")
        try:
            return SolveResult(**filtered)
        except TypeError as error:
            return SolveResult("error", error=f"The sandbox returned an invalid result payload: {error}")

    async def solve(self, code: str, data: dict[str, str], language: str, time_limit: float, *,
                    solver: str | None = None) -> SolveResult:
        """Build the model from `code` with `data` and solve it with the language's solver, within `time_limit`."""
        from llm4om.languages import CodeTarget

        target = CodeTarget(language, solver)
        return self._to_result(await self._run({"code": code, "data": data, "language": target.language,
                                                "solver": target.solver, "time_limit": time_limit}, time_limit))

    async def run_script(self, script: str, time_limit: float) -> SolveResult:
        """Run a script as __main__; `output` holds what it printed and any traceback."""
        return self._to_result(await self._run({"script": script}, time_limit))

    async def catalog(self) -> dict[str, Any]:
        """One native capability discovery per service process, in the actual solving environment."""
        async with self._catalog_lock:
            if self._catalog is None:
                result = await self._run({"catalog": True}, 120)
                if result.get("error"):
                    raise RuntimeError(result['error'])
                self._catalog = result
            return self._catalog

    def _command(self, name: str) -> list[str]:
        if self.kind == "local":
            return [sys.executable, "-I", str(WORKER)]
        command = ["docker", "run", "--rm", "-i", "--pull", "never", "--name", name, "--network", "none", "--memory", "2g",
                   "--cpus", "2", "--pids-limit", "256", "--read-only", "--tmpfs", "/tmp:rw,size=256m",
                   "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "-e", "HOME=/tmp",
                   "-e", "OPENBLAS_NUM_THREADS=1", "-e", "OMP_NUM_THREADS=2"]
        for variable, destination in [("GRB_LICENSE_FILE", "/opt/gurobi/gurobi.lic"),
                                      ("MOSEKLM_LICENSE_FILE", "/opt/mosek/mosek.lic")]:
            license_file = os.environ.get(variable)
            if license_file and Path(license_file).is_file():
                command += ["-v", f"{Path(license_file).resolve()}:{destination}:ro", "-e", f"{variable}={destination}"]
        # Mount only COPT's two license files, never the entire installation or home directory.
        license_dir = os.environ.get("COPT_LICENSE_DIR")
        if license_dir:
            mounted = False
            for filename in ("license.dat", "license.key"):
                path = Path(license_dir, filename)
                if path.is_file():
                    command += ["-v", f"{path.resolve()}:/opt/copt/{filename}:ro"]
                    mounted = True
            if mounted:
                command += ["-e", "COPT_LICENSE_DIR=/opt/copt"]
        return command + [self.image, "python", "-I", "/opt/llm4om/worker.py"]

    @staticmethod
    async def _communicate(process: Any, payload: bytes) -> tuple[bytes, bytes]:
        if getattr(process, "stdin", None) is None or getattr(process, "stdout", None) is None or getattr(process, "stderr", None) is None:
            return await process.communicate(payload)

        async def feed() -> None:
            try:
                process.stdin.write(payload)
                await process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                with contextlib.suppress(Exception):
                    process.stdin.close()

        async def read_stdout() -> bytes:
            chunks: list[bytes] = []
            total = 0
            while chunk := await process.stdout.read(65536):
                total += len(chunk)
                if total > MAX_STDOUT_BYTES:
                    raise OverflowError("The sandbox produced too much stdout output and was stopped.")
                chunks.append(chunk)
            return b"".join(chunks)

        async def read_stderr() -> bytes:
            tail = bytearray()
            while chunk := await process.stderr.read(65536):
                tail.extend(chunk)
                if len(tail) > MAX_STDERR_BYTES:
                    del tail[:-MAX_STDERR_BYTES]
            return bytes(tail)

        _, stdout, stderr = await asyncio.gather(feed(), read_stdout(), read_stderr())
        await process.wait()
        return stdout, stderr

    async def _run(self, request: dict[str, Any], time_limit: float) -> dict[str, Any]:
        async with self._slots:
            timeout = time_limit + START_MARGIN
            name = "llm4om-" + uuid.uuid4().hex[:12]
            env = {key: os.environ[key] for key in ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "GRB_LICENSE_FILE",
                                                   "MOSEKLM_LICENSE_FILE", "COPT_LICENSE_DIR")
                   if key in os.environ} if self.kind == "local" else None
            if env is not None:
                env.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="2")
            process = await asyncio.create_subprocess_exec(*self._command(name), stdin=asyncio.subprocess.PIPE,
                                                           stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=env)

            async def cleanup() -> None:
                with contextlib.suppress(ProcessLookupError):
                    process.kill()
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(process.wait(), timeout=10)
                if self.kind == "docker":
                    with contextlib.suppress(Exception):
                        rm = await asyncio.create_subprocess_exec(
                            "docker", "rm", "--force", name,
                            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
                        )
                        await asyncio.wait_for(rm.wait(), timeout=15)

            async def run_cleanup() -> None:
                task = asyncio.create_task(cleanup())
                while not task.done():
                    try:
                        await asyncio.shield(task)
                    except asyncio.CancelledError:
                        pass

            try:
                stdout, stderr = await asyncio.wait_for(self._communicate(process, json.dumps(request).encode()), timeout)
            except (asyncio.TimeoutError, asyncio.CancelledError, OverflowError) as error:
                await run_cleanup()
                if isinstance(error, asyncio.CancelledError):
                    raise
                if isinstance(error, OverflowError):
                    return {"status": "error", "error": str(error)}
                return {"status": "error", "error": f"Execution exceeded {timeout:g} seconds and was stopped."}
            for line in reversed(stdout.decode(errors="replace").splitlines()):
                if line.startswith(RESULT_MARKER):
                    try:
                        parsed = json.loads(line[len(RESULT_MARKER):])
                    except json.JSONDecodeError as error:
                        return {"status": "error", "error": f"The sandbox returned malformed JSON: {error}"}
                    if not isinstance(parsed, dict):
                        return {"status": "error", "error": "The sandbox returned an invalid JSON result."}
                    return parsed
            detail = stderr.decode(errors="replace").strip()[-2000:]
            hint = " Build it with `llm4om build-worker`." if "Unable to find image" in detail else ""
            return {"status": "error", "error": f"The sandbox did not return a result (exit code {process.returncode}).{hint}\n{detail}"}
