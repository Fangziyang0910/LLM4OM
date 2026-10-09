"""Bounded raw-script child; all captures remain untrusted model proposals."""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import selectors
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

from llm4om.contracts import RunError, parse_json, read_public_bytes


def _capture_child(request_path: Path, scratch: Path) -> int:
    # Only this untrusted container child imports and executes generated Python.
    import gurobipy as gp
    from llm4om.backends import GurobiFactoryBackend, ModelHandle
    request = parse_json(read_public_bytes(request_path))
    source = read_public_bytes(request_path.parent / "model.py")
    os.chdir(scratch)
    original = gp.Model.optimize
    original_init = gp.Model.__init__
    calls = 0
    models = 0
    capture: dict[str, Any] = {"schema_version": "0.1.0", "source_sha256": request["source_sha256"],
                               "optimize_calls": 0, "model_count": 0, "transport": None, "error": None}

    def initialize(model: Any, *args: Any, **kwargs: Any) -> None:
        nonlocal models
        original_init(model, *args, **kwargs)
        models += 1
        capture["model_count"] = models
        if models > 1:
            capture.update(transport=None, error="multiple_script_models")
            (scratch / "capture.json").write_text(json.dumps(capture, allow_nan=False))

    def optimize(model: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        capture["optimize_calls"] = calls
        try:
            if models != 1:
                raise RunError("multiple_script_models", "execution", "Capture requires exactly one model.")
            if calls != 1 or args or kwargs:
                raise RunError("unsupported_script_capture", "execution", "Capture supports one plain optimize call.")
            model.update()
            handle = ModelHandle(model, {var.VarName: var for var in model.getVars()})
            capture["transport"] = GurobiFactoryBackend().export(handle)
        except Exception as error:
            capture["transport"] = None
            capture["error"] = error.code if isinstance(error, RunError) else "capture_failed"
        (scratch / "capture.json").write_text(json.dumps(capture, allow_nan=False))
        if calls > 1:
            raise RunError("script_solver_budget_exhausted", "execution", "This execution admits one source optimize call.")
        # Capture failure is not a source failure and must not create a debug request.
        return original(model, *args, **kwargs)

    setattr(gp.Model, "optimize", optimize)
    setattr(gp.Model, "__init__", initialize)
    namespace = {"__name__": "__main__", "__file__": "code.py"}
    exec(compile(source, "code.py", "exec"), namespace)
    return 0


def _bounded_file(path: Path, limit: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            raise RunError("invalid_script_capture", "execution", "Capture must be a bounded regular file.")
        data = os.read(descriptor, limit + 1)
        if len(data) > limit:
            raise RunError("invalid_script_capture", "execution", "Capture exceeds its byte limit.")
        return data
    finally:
        os.close(descriptor)


def execute_script(path: Path) -> dict[str, Any]:
    """Worker interface; invoke only inside the isolated container."""
    request = parse_json(read_public_bytes(path))
    if (set(request) != {"schema_version", "source_sha256", "data_json", "wall_time_s", "output_limit_bytes"}
            or request["schema_version"] != "0.1.0" or not isinstance(request["data_json"], str)):
        raise RunError("invalid_worker_request", "execution", "Invalid raw-script request.")
    parse_json(request["data_json"].encode())
    seconds, limit = request["wall_time_s"], request["output_limit_bytes"]
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 0 < seconds <= 86400
            or type(limit) is not int or not 1 <= limit <= 8 * 1024 * 1024):
        raise RunError("invalid_worker_request", "execution", "Invalid raw-script limits.")
    if hashlib.sha256(read_public_bytes(path.parent / "model.py")).hexdigest() != request["source_sha256"]:
        raise RunError("code_hash_mismatch", "execution", "Script source differs from the admitted proposal.")
    if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:
        raise RunError("script_isolation_unavailable", "execution", "Cannot protect supervisor memory and descriptors.")
    with tempfile.TemporaryDirectory() as directory:
        scratch = Path(directory)
        (scratch / "data.json").write_bytes(request["data_json"].encode())
        child = subprocess.Popen([sys.executable, "-I", "-m", "llm4om.script_worker", str(path), str(scratch)],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
            start_new_session=True, env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})
        output, diagnostic = bytearray(), bytearray()
        deadline = time.monotonic() + seconds
        status = "completed"
        try:
            with selectors.DefaultSelector() as selector:
                assert child.stdout is not None and child.stderr is not None
                selector.register(child.stdout, selectors.EVENT_READ, output)
                selector.register(child.stderr, selectors.EVENT_READ, diagnostic)
                while selector.get_map() or child.poll() is None:
                    if time.monotonic() >= deadline:
                        status = "timeout"
                        break
                    for key, _ in selector.select(0.05):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                        else:
                            remaining = max(0, limit - len(output) - len(diagnostic))
                            key.data.extend(chunk[:remaining])
                            if len(chunk) > remaining:
                                status = "output_limit"
                                break
                    if status != "completed":
                        break
        finally:
            try:
                os.killpg(child.pid, 9)
            except ProcessLookupError:
                pass
            child.wait()
            if child.stdout is not None:
                child.stdout.close()
            if child.stderr is not None:
                child.stderr.close()
        capture = None
        capture_error = None
        try:
            capture = parse_json(_bounded_file(scratch / "capture.json", limit))
            if (set(capture) != {"schema_version", "source_sha256", "optimize_calls", "model_count", "transport", "error"}
                    or capture["schema_version"] != "0.1.0" or capture["source_sha256"] != request["source_sha256"]
                    or type(capture["optimize_calls"]) is not int or capture["optimize_calls"] < 1):
                raise ValueError("Invalid capture identity.")
        except (OSError, ValueError):
            capture = None
            capture_error = "capture_missing_or_invalid"
        return {"schema_version": "0.1.0", "source_sha256": request["source_sha256"],
                "source": {"status": status, "exit_code": child.returncode,
                           "stdout": output.decode(errors="replace"), "stderr": diagnostic.decode(errors="replace")},
                "capture": capture, "capture_error": capture_error,
                "measurement_origin": "untrusted_capture_hook/0.1.0", "unobserved_optimize_calls": None}


def main() -> int:
    try:
        if len(sys.argv) == 3:
            return _capture_child(Path(sys.argv[1]), Path(sys.argv[2]))
        print(json.dumps(execute_script(Path(sys.argv[1])), allow_nan=False))
        return 0
    except RunError as error:
        print(json.dumps({"error": {"code": error.code, "stage": error.stage, "message": str(error)}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
