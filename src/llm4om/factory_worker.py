"""Trusted collector: bounded child export, validated IR, independent HiGHS solve."""

import ctypes
import hashlib
import os
from pathlib import Path
import selectors
import subprocess
import sys
import time
from typing import Any

from llm4om.contracts import RunError, parse_json, read_public_bytes, validate_bindings, validate_csv, validate_formulation, validate_problem
from llm4om.linear import compile_ir
from llm4om.highs import solve_highs


def solve_factory(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    request = parse_json(read_public_bytes(path))
    fields = {"kind", "source_sha256", "solver_options", "problem", "formulation", "data_bindings",
              "data_refs", "allowed_problem_types", "wall_time_s", "output_limit_bytes"}
    if set(request) != fields or request["kind"] != "python_factory/0.1.0":
        raise RunError("invalid_worker_request", "execution", "Factory request does not match version 0.1.0.")
    public = request["problem"]
    validate_problem(public)
    validate_formulation(request["formulation"], public)
    validate_bindings(request, public)
    if request["data_refs"] != public["data_refs"]:
        raise RunError("artifact_data_mismatch", "execution", "Factory data references differ from the public problem.")
    source = read_public_bytes(path.parent / "model.py")
    if hashlib.sha256(source).hexdigest() != request["source_sha256"]:
        raise RunError("code_hash_mismatch", "execution", "Factory source differs from the Code proposal.")
    for ref in public["data_refs"]:
        raw = read_public_bytes(path.parent / ref["path"])
        if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
            raise RunError("data_hash_mismatch", "execution", "Public data bytes differ from the factory binding.")
        validate_csv(raw, ref["schema"])
    # Prevent a same-UID child from accessing collector memory or /proc parent fds.
    if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:
        raise RunError("factory_isolation_unavailable", "execution", "Cannot protect the collector from the factory child.")
    timer = time.monotonic()
    limit = request["output_limit_bytes"]
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 8 * 1024 * 1024:
        raise RunError("invalid_worker_request", "execution", "Invalid factory output limit.")
    seconds = request["wall_time_s"]
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool) or not 0 < seconds <= 86400:
        raise RunError("invalid_worker_request", "execution", "Invalid factory deadline.")
    output, diagnostic = bytearray(), bytearray()
    child = subprocess.Popen([sys.executable, "-I", "-m", "llm4om.backends", str(path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, close_fds=True,
        start_new_session=True, env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})
    selector = selectors.DefaultSelector()
    try:
        assert child.stdout is not None and child.stderr is not None
        selector.register(child.stdout, selectors.EVENT_READ, output)
        selector.register(child.stderr, selectors.EVENT_READ, diagnostic)
        while selector.get_map():
            remaining = seconds - (time.monotonic() - timer)
            if remaining <= 0:
                raise RunError("execution_timeout", "execution", "Factory construction exceeded the Worker deadline.")
            for key, _ in selector.select(min(remaining, 0.1)):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                else:
                    key.data.extend(chunk)
                    if len(output) + len(diagnostic) > limit:
                        raise RunError("execution_output_limit", "execution", "Factory construction exceeded its bounded output.")
        child.wait(timeout=max(0.001, seconds - (time.monotonic() - timer)))
    except subprocess.TimeoutExpired as error:
        raise RunError("execution_timeout", "execution", "Factory construction exceeded the Worker deadline.") from error
    finally:
        try:
            os.killpg(child.pid, 9)
        except ProcessLookupError:
            pass
        child.wait()
        selector.close()
        if child.stdout is not None:
            child.stdout.close()
        if child.stderr is not None:
            child.stderr.close()
        # Child output is diagnostics, never the trusted Worker's result protocol.
        if diagnostic:
            sys.stderr.write(diagnostic[:limit].decode(errors="replace"))
    try:
        exported = parse_json(bytes(output))
    except (ValueError, RunError) as error:
        raise RunError("invalid_factory_export", "execution", "Factory did not export one valid instance object.") from error
    if set(exported) == {"error"}:
        value = exported["error"]
        if not isinstance(value, dict) or set(value) != {"code", "stage", "message"} or any(not isinstance(v, str) for v in value.values()):
            raise RunError("invalid_factory_export", "execution", "Malformed factory diagnostic.")
        raise RunError(value["code"], value["stage"], value["message"])
    if child.returncode != 0 or set(exported) != {"instance"} or not isinstance(exported["instance"], dict):
        raise RunError("invalid_factory_export", "execution", "Factory did not successfully export an instance.")
    instance = exported["instance"]
    if set(instance) != {"variables", "objective", "constraints", "decision_map", "problem_type"}:
        raise RunError("invalid_factory_export", "execution", "Factory export contains unsupported fields.")
    decisions = instance.pop("decision_map")
    if (not isinstance(decisions, dict) or any(not isinstance(value, str) or not value for value in decisions.values())
            or len(set(decisions.values())) != len(decisions)):
        raise RunError("invalid_decision_map", "execution", "Export must contain an explicit one-to-one decision map.")
    instance.update(schema_version="0.1.0", ir_kind="grounded_lp", model_id="factory-instance-001",
        problem_id=public["problem_id"], problem_revision=public["revision"], data_bindings=request["data_bindings"],
        assumptions=[], provenance={"origin": "factory_exported_instance", "source_sha256": request["source_sha256"],
        "relationship": "extracted_instance_not_source_formulation_or_semantic_proof"})
    compiled = compile_ir(instance)
    if set(decisions) != set(compiled.symbol_map["variables"]):
        raise RunError("invalid_decision_map", "execution", "Exported decision map differs from the validated variables.")
    if instance["problem_type"] not in request["allowed_problem_types"]:
        raise RunError("capability_mismatch", "execution", "Factory instance type is outside the admitted types.")
    remaining = seconds - (time.monotonic() - timer)
    if remaining <= 0:
        raise RunError("execution_timeout", "execution", "No Worker deadline remains for independent solving.")
    options = dict(request["solver_options"])
    options["time_limit_s"] = min(options.get("time_limit_s", remaining), remaining)
    result = solve_highs(compiled, options)
    return result, {"instance": instance, "decision_map": decisions, "source_sha256": request["source_sha256"]}
