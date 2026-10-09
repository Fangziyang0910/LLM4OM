"""Run container processes with explicit public inputs and enforced limits."""

import json
import math
import os
import selectors
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from time import monotonic, sleep, time
from typing import Any, Mapping
from uuid import uuid4

from llm4om.contracts import RunError, parse_json


DEFAULT_IMAGE = "llm4om-worker:0.5.0"
_CONTROL_TIMEOUT_S = 2.0
_REAP_TIMEOUT_S = 0.5
_CONTROL_OUTPUT_BYTES = 1048576


@dataclass(frozen=True)
class ContainerExecution:
    status: str
    exit_code: int | None
    stdout: bytes
    stderr: bytes
    wall_time_s: float
    output_truncated: bool
    oom_killed: bool | None
    image_id: str
    container_id: str
    restrictions: dict[str, Any]
    diagnostics: tuple[str, ...] = ()
    oom_evidence: str | None = None


def _diagnostic(operation: str, error: Exception) -> str:
    if isinstance(error, subprocess.TimeoutExpired):
        return f"{operation}: Docker command timed out."
    if isinstance(error, subprocess.CalledProcessError):
        return f"{operation}: Docker command exited with code {error.returncode}."
    return f"{operation}: {type(error).__name__}."


def _dispose(process: subprocess.Popen[bytes], operation: str, diagnostics: list[str]) -> None:
    # Descendants can retain pipes even after the CLI exits; terminate the owned process group.
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as error:
        diagnostics.append(_diagnostic(f"{operation} terminate", error))
    try:
        process.wait(timeout=_REAP_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as error:
        diagnostics.append(_diagnostic(f"{operation} reap", error))
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            try:
                stream.close()
            except OSError as error:
                diagnostics.append(_diagnostic(f"{operation} close", error))


def _check_deadline(deadline: float | None) -> None:
    if deadline is not None and time() >= deadline:
        raise RunError("deadline_exhausted", "execution", "No shared run deadline remains for Worker admission.")


def _docker(arguments: list[str], diagnostics: list[str], *, deadline: float | None = None) -> bytes:
    _check_deadline(deadline)
    process = subprocess.Popen(["docker", *arguments], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    captured = [bytearray(), bytearray()]
    total = 0
    control_deadline = monotonic() + min(_CONTROL_TIMEOUT_S, deadline - time() if deadline is not None else _CONTROL_TIMEOUT_S)
    try:
        with selectors.DefaultSelector() as selector:
            assert process.stdout is not None and process.stderr is not None
            selector.register(process.stdout, selectors.EVENT_READ, 0)
            selector.register(process.stderr, selectors.EVENT_READ, 1)
            while selector.get_map() or process.poll() is None:
                if monotonic() >= control_deadline:
                    _check_deadline(deadline)
                    raise subprocess.TimeoutExpired(process.args, _CONTROL_TIMEOUT_S)
                for key, _ in selector.select(timeout=0.05):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        total += len(chunk)
                        if total > _CONTROL_OUTPUT_BYTES:
                            raise ValueError("Docker control output exceeded its limit.")
                        captured[key.data].extend(chunk)
        code = process.wait(timeout=_REAP_TIMEOUT_S)
        if code != 0:
            raise subprocess.CalledProcessError(code, process.args)
        return bytes(captured[0])
    finally:
        _dispose(process, arguments[0], diagnostics)


def container_runtime(image: str = DEFAULT_IMAGE, *, deadline: float | None = None) -> dict[str, Any]:
    diagnostics: list[str] = []
    operation = "version"
    try:
        version = _docker(["version", "--format", "{{.Server.Version}}"], diagnostics, deadline=deadline).decode().strip()
        operation = "image inspect"
        raw = _docker(["image", "inspect", image], diagnostics, deadline=deadline)
        info = json.loads(raw)[0]
        if not version or not isinstance(info["Id"], str) or not info["Id"] or diagnostics:
            raise ValueError("Docker runtime evidence is incomplete.")
        return {"docker": version, "image_id": info["Id"], "image": image, "labels": info["Config"].get("Labels") or {}}
    except RunError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        diagnostics.append(_diagnostic(operation, error))
        raise RunError("executor_unavailable", "admission",
            "Docker or the requested local Worker image is unavailable; build the image explicitly.",
            details={"diagnostics": diagnostics}) from error


def run_container(command: list[str], inputs: Mapping[str, bytes], limits: dict[str, Any],
                  *, image: str = DEFAULT_IMAGE, deadline: float | None = None) -> ContainerExecution:
    _validate_request(command, inputs, limits, image, deadline)
    runtime = container_runtime(image, deadline=deadline)
    name = f"llm4om-{uuid4().hex}"
    maximum_output = limits.get("output_limit_bytes", 1048576)
    pids = limits.get("pids_limit", 64)
    started = monotonic()
    _check_deadline(deadline)
    wall_time_s = min(limits["wall_time_s"], deadline - time() if deadline is not None else limits["wall_time_s"])
    event_start = datetime.now(timezone.utc).isoformat()
    status = "completed"
    captured = [bytearray(), bytearray()]
    total = 0
    diagnostics: list[str] = []
    container_id = ""
    exit_code: int | None = None
    oom_killed: bool | None = None
    oom_evidence = None
    restrictions: dict[str, Any] = {"output_limit_bytes": maximum_output}
    failure: Exception | None = None
    operation = "public inputs"
    create_attempted = False
    directory: tempfile.TemporaryDirectory[str] | None = None
    process: subprocess.Popen[bytes] | None = None
    stopper: subprocess.Popen[bytes] | None = None
    stop_deadline: float | None = None
    kill_observed = False
    try:
        directory = tempfile.TemporaryDirectory(prefix="llm4om-public-")
        root = Path(directory.name)
        root.chmod(0o755)
        for path, content in inputs.items():
            target = root / path
            parent = root
            for part in PurePosixPath(path).parts[:-1]:
                parent /= part
                parent.mkdir(exist_ok=True)
                parent.chmod(0o755)
            target.write_bytes(content)
            target.chmod(0o444)
        args = ["create", "--name", name, "--label", "llm4om.execution=true", "--pull", "never",
                "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--user", "65532:65532", "--pids-limit", str(pids), "--cpus", str(limits["cpu_limit"]),
                "--memory", f"{limits['memory_limit_mb']}m", "--memory-swap", f"{limits['memory_limit_mb']}m",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777", "--log-driver", "none",
                "--mount", f"type=bind,src={root},dst=/input,readonly", "--workdir", "/tmp",
                "--entrypoint", command[0], runtime["image_id"], *command[1:]]
        operation = "create"
        create_attempted = True
        container_id = _docker(args, diagnostics, deadline=deadline).decode().strip()
        if not container_id:
            raise ValueError("Docker did not return a container ID.")
        operation = "attach"
        _check_deadline(deadline)
        process = subprocess.Popen(["docker", "start", "-a", name], stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        with selectors.DefaultSelector() as selector:
            assert process.stdout is not None and process.stderr is not None
            selector.register(process.stdout, selectors.EVENT_READ, 0)
            selector.register(process.stderr, selectors.EVENT_READ, 1)
            while selector.get_map() or process.poll() is None:
                if status == "completed" and monotonic() - started >= wall_time_s:
                    status = "timeout"
                if status != "completed" and stop_deadline is None:
                    stop_deadline = monotonic() + _CONTROL_TIMEOUT_S
                    try:
                        stopper = subprocess.Popen(["docker", "kill", name], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    except OSError as error:
                        diagnostics.append(_diagnostic("kill", error))
                if stopper is not None and not kill_observed and stopper.poll() is not None:
                    kill_observed = True
                    if stopper.returncode != 0:
                        diagnostics.append(f"kill: Docker command exited with code {stopper.returncode}.")
                if stop_deadline is not None and monotonic() >= stop_deadline:
                    diagnostics.append("attach: Docker attach did not finish after termination.")
                    break
                # Keep draining both streams while kill runs so pipe backpressure cannot block it.
                for key, _ in selector.select(timeout=0.05):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    remaining = max(0, maximum_output - total)
                    captured[key.data].extend(chunk[:remaining])
                    total += len(chunk)
                    if total > maximum_output and status == "completed":
                        status = "output_limit"
        attach_code = process.poll()
        _dispose(process, "attach", diagnostics)
        process = None
        operation = "inspect"
        info = json.loads(_docker(["inspect", name], diagnostics))[0]
        state = info["State"]
        if not isinstance(state["OOMKilled"], bool):
            raise ValueError("Docker returned invalid exit evidence.")
        oom_killed = state["OOMKilled"]
        oom_evidence = "docker_state" if oom_killed else None
        if status == "completed" and oom_killed:
            status = "oom"
            oom_evidence = "docker_state"
        if (isinstance(state["ExitCode"], bool) or not isinstance(state["ExitCode"], int)
                or not isinstance(state["Running"], bool)):
            raise ValueError("Docker returned invalid exit evidence.")
        exit_code = None if state["Running"] else state["ExitCode"]
        if state["Running"]:
            diagnostics.append("inspect: Worker is still running.")
        if status == "completed" and exit_code == 137 and oom_killed is False:
            # Docker can publish the exit before its asynchronous OOM event.
            evidence_deadline = monotonic() + _CONTROL_TIMEOUT_S
            while monotonic() < evidence_deadline:
                sleep(0.05)
                observed = json.loads(_docker(["inspect", name], diagnostics))[0]["State"]["OOMKilled"]
                if not isinstance(observed, bool):
                    raise ValueError("Docker returned invalid OOM evidence.")
                if observed:
                    oom_killed = True
                    oom_evidence = "docker_state"
                    status = "oom"
                    break
            if not oom_killed:
                events = _docker(["events", "--since", event_start, "--until", datetime.now(timezone.utc).isoformat(),
                    "--filter", f"container={container_id}", "--filter", "event=oom", "--format", "{{json .}}"], diagnostics)
                for line in events.splitlines():
                    event = json.loads(line)
                    if not isinstance(event, dict) or not isinstance(event.get("Actor"), dict):
                        raise ValueError("Docker returned invalid event evidence.")
                    if event.get("Type") == "container" and event.get("Action") == "oom" and event["Actor"].get("ID") == container_id:
                        oom_killed = True
                        oom_evidence = "docker_event"
                        status = "oom"
                        break
        if status == "completed":
            if attach_code != 0 or exit_code != 0:
                status = "failed"
        config = info["HostConfig"]
        restrictions = {"network": config["NetworkMode"], "read_only": config["ReadonlyRootfs"],
            "user": info["Config"]["User"], "memory_bytes": config["Memory"], "memory_swap_bytes": config["MemorySwap"],
            "nano_cpus": config["NanoCpus"], "pids_limit": config["PidsLimit"], "cap_drop": config["CapDrop"],
            "security_options": config["SecurityOpt"], "mounts": [{"destination": item["Destination"], "rw": item["RW"]}
                for item in info["Mounts"]], "output_limit_bytes": maximum_output}
    except RunError:
        raise
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, IndexError, TypeError) as error:
        diagnostics.append(_diagnostic(operation, error))
        if status not in ("timeout", "output_limit", "oom"):
            status = "failed"
            failure = error
    finally:
        if process is not None:
            _dispose(process, "attach", diagnostics)
        if stopper is not None:
            try:
                stopper.wait(timeout=max(0, (stop_deadline or monotonic()) - monotonic()))
                if not kill_observed and stopper.returncode != 0:
                    diagnostics.append(f"kill: Docker command exited with code {stopper.returncode}.")
            except (OSError, subprocess.SubprocessError) as error:
                diagnostics.append(_diagnostic("kill", error))
            _dispose(stopper, "kill", diagnostics)
        if create_attempted:
            try:
                _docker(["rm", "-f", name], diagnostics)
            except (OSError, subprocess.SubprocessError, ValueError) as error:
                diagnostics.append(_diagnostic("remove", error))
        if directory is not None:
            try:
                directory.cleanup()
            except OSError as error:
                diagnostics.append(_diagnostic("public inputs cleanup", error))
    if failure is not None or (status == "completed" and diagnostics):
        raise RunError("executor_error", "execution", "Cannot start, observe or collect the isolated Worker.",
            details={"status": status, "container_id": container_id, "container_name": name,
                "image_id": runtime["image_id"], "exit_code": exit_code, "oom_killed": oom_killed, "oom_evidence": oom_evidence,
                "stdout": bytes(captured[0]).decode(errors="replace"), "stderr": bytes(captured[1]).decode(errors="replace"),
                "output_truncated": total > maximum_output, "restrictions": restrictions,
                "diagnostics": diagnostics}) from failure
    return ContainerExecution(status, exit_code, bytes(captured[0]), bytes(captured[1]),
        monotonic() - started, total > maximum_output, oom_killed, runtime["image_id"], container_id,
        restrictions, tuple(diagnostics), oom_evidence)


def _validate_request(command: list[str], inputs: Mapping[str, bytes], limits: dict[str, Any], image: str,
                      deadline: float | None = None) -> None:
    allowed = {"network", "cpu_limit", "memory_limit_mb", "wall_time_s", "output_limit_bytes", "pids_limit", "image"}
    try:
        if deadline is not None and (isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline)):
            raise ValueError("Shared deadline requires a finite timestamp.")
        if not isinstance(command, list) or not command or not all(
                isinstance(item, str) and item and "\0" not in item for item in command):
            raise ValueError("Command requires text arguments.")
        for item in command:
            item.encode("utf-8")
        if not isinstance(inputs, Mapping) or not isinstance(limits, dict):
            raise ValueError("Public files and limits require mappings.")
        for reference in (image, limits.get("image", image)):
            if (not isinstance(reference, str) or not reference or reference.startswith("-")
                    or any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in reference)):
                raise ValueError("Image requires a nonempty text reference.")
            reference.encode("utf-8")
        if set(limits) - allowed or limits["network"] is not False:
            raise ValueError("Unsupported restriction.")
        for key in ("cpu_limit", "memory_limit_mb", "wall_time_s", "output_limit_bytes", "pids_limit"):
            value = limits.get(key, 1048576 if key == "output_limit_bytes" else 64 if key == "pids_limit" else None)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Limits must be positive finite numbers.")
            if key not in ("cpu_limit", "wall_time_s") and not isinstance(value, int):
                raise ValueError("Counts must be integers.")
        for name, content in inputs.items():
            if not isinstance(name, str) or any(ord(char) < 32 or ord(char) == 127 for char in name):
                raise ValueError("Input names require safe text.")
            name.encode("utf-8")
            path = PurePosixPath(name)
            if (path.is_absolute() or not path.parts or path.as_posix() != name
                    or any(part in (".", "..") for part in path.parts) or "\\" in name or "," in name):
                raise ValueError("Input names must be safe relative paths.")
            if not isinstance(content, bytes):
                raise ValueError("Inputs must be public bytes.")
            if any(parent.as_posix() in inputs for parent in path.parents if parent != PurePosixPath(".")):
                raise ValueError("Input files cannot also be directories.")
    except (ValueError, TypeError, KeyError, OverflowError) as error:
        raise RunError("invalid_execution_request", "admission", "Container command, public files or limits are invalid.") from error


def worker_runtime(limits: dict[str, Any], *, deadline: float | None = None) -> dict[str, Any]:
    execution = run_container(["python", "-I", "-m", "llm4om.worker", "--runtime"], {}, limits,
                              image=limits.get("image", DEFAULT_IMAGE), deadline=deadline)
    try:
        data = parse_json(execution.stdout)
        runtime = data["runtime"]
        if (execution.status != "completed" or execution.exit_code != 0 or data["schema_version"] != "0.2.0"
                or not isinstance(runtime, dict) or set(runtime) != {"python", "llm4om", "packages"}
                or runtime["llm4om"] != version("llm4om") or not isinstance(runtime["python"], str)
                or not runtime["python"].startswith(("3.11.", "3.12."))
                or not isinstance(runtime["packages"], dict) or set(runtime["packages"]) != {"Pyomo", "highspy"}
                or not all(isinstance(value, str) and value for value in runtime["packages"].values())):
            raise ValueError("Worker did not pass dependency preflight.")
        return {**runtime, "image_id": execution.image_id, "restrictions": execution.restrictions}
    except (ValueError, KeyError, TypeError) as error:
        raise RunError("executor_unavailable", "admission", "Worker image cannot load the required Solver runtime.") from error
