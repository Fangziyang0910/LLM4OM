"""Trusted image entry point; derive a model from strict IR and collect API evidence."""

import argparse
import hashlib
import json
import resource
import platform
from importlib.metadata import version
from pathlib import Path

from llm4om.contracts import RunError, parse_json, read_public_bytes
from llm4om.highs import runtime_versions, solve_highs
from llm4om.linear import compile_ir


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--solve", type=Path)
    args = parser.parse_args()
    try:
        packages = runtime_versions()
        runtime = {"python": platform.python_version(), "llm4om": version("llm4om"), "packages": packages}
        if args.runtime:
            print(json.dumps({"schema_version": "0.2.0", "runtime": runtime}, allow_nan=False))
            return 0
        if args.solve is None:
            parser.error("--solve or --runtime is required")
        request = parse_json(read_public_bytes(args.solve))
        if set(request) != {"ir", "source_sha256", "solver_options"}:
            raise RunError("invalid_worker_request", "execution", "Worker accepts strict IR, source hash and Solver options only.")
        compiled = compile_ir(request["ir"])
        actual_source = read_public_bytes(args.solve.parent / "model.py")
        if (hashlib.sha256(compiled.source.encode()).hexdigest() != request["source_sha256"]
                or hashlib.sha256(actual_source).hexdigest() != request["source_sha256"]):
            raise RunError("code_hash_mismatch", "execution", "CodeArtifact does not match deterministic IR compilation.")
        result = solve_highs(compiled, request["solver_options"])
        usage = resource.getrusage(resource.RUSAGE_SELF)
        print(json.dumps({"schema_version": "0.2.0", "runtime": runtime, "result": result,
            "resources": {"cpu_time_s": usage.ru_utime + usage.ru_stime, "peak_memory_bytes": usage.ru_maxrss * 1024}},
            ensure_ascii=False, allow_nan=False))
        return 0
    except RunError as error:
        print(json.dumps({"schema_version": "0.2.0", "error": {"code": error.code, "stage": error.stage,
                                                              "message": str(error)}}))
        return 1
    except (ValueError, TypeError, KeyError, RuntimeError, ArithmeticError):
        print(json.dumps({"schema_version": "0.2.0", "error": {"code": "worker_error", "stage": "execution",
                          "message": "Cannot construct or solve the Worker request."}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
