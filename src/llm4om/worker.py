"""Trusted image entry point; derive a model from strict IR and collect API evidence."""

import argparse
import hashlib
import json
import resource
import sys
import platform
from importlib.metadata import version
from pathlib import Path

from llm4om.contracts import RunError, parse_json, read_public_bytes
from llm4om.solvers import solver_runtime, solver_packages, solve
from llm4om.linear import compile_ir
from llm4om.compilers import resolve_compiler, compiler_identity


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--compiler-runtime", type=Path)
    parser.add_argument("--solver", default="llm4om.solvers.highs")
    parser.add_argument("--solve", type=Path)
    parser.add_argument("--collect-native", type=Path)
    parser.add_argument("--solve-stdin", action="store_true")
    args = parser.parse_args()
    try:
        runtime = {"python": platform.python_version(), "llm4om": version("llm4om"),
                   **({"packages": solver_packages(args.solver)} if args.collect_native is not None else solver_runtime(args.solver))}
        if args.runtime:
            compiler_runtime = {}
            if args.compiler_runtime is not None:
                selection = parse_json(read_public_bytes(args.compiler_runtime))
                compiler = resolve_compiler(selection["compiler"], selection["target_backend"])
                compiler_runtime["compiler_identity"] = compiler_identity(compiler.binding)
            print(json.dumps({"schema_version": "0.2.0", "runtime": runtime, **compiler_runtime}, allow_nan=False))
            return 0
        if args.solve is None and not args.solve_stdin and args.collect_native is None:
            parser.error("--solve or --runtime is required")
        request = parse_json(sys.stdin.buffer.read() if args.solve_stdin else read_public_bytes(args.collect_native or args.solve))
        factory = None
        if args.collect_native is not None:
            from llm4om.gurobi import read_native, native_instance, solve_native
            if (args.solver != "llm4om.solvers.gurobi" or set(request) != {
                    "schema_version", "transport", "source_sha256", "solver_options", "allowed_problem_types"}
                    or request["schema_version"] != "0.1.0"):
                raise RunError("invalid_worker_request", "execution", "Invalid native collector request.")
            with read_native(request["transport"]) as handle:
                instance = native_instance(handle)
                if instance["problem_type"] not in request["allowed_problem_types"]:
                    raise RunError("capability_mismatch", "execution", "Captured model type is outside admission.")
                result = solve_native(handle, request["solver_options"])
        elif not args.solve_stdin and request.get("kind") in ("python_factory/0.1.0", "native_gurobipy/0.1.0"):
            from llm4om.factory_worker import solve_factory
            result, factory = solve_factory(args.solve, solver_id=args.solver)
        else:
            if set(request) not in ({"ir", "source_sha256", "solver_options"}, {"ir", "source_sha256", "symbol_map", "solver_options", "compiler", "compiler_identity", "target_backend"}):
                raise RunError("invalid_worker_request", "execution", "Worker accepts strict IR, source hash and Solver options only.")
            if "compiler" in request:
                compiler = resolve_compiler(request["compiler"], request["target_backend"])
                if compiler_identity(compiler.binding) != request["compiler_identity"]:
                    raise RunError("checkpoint_incompatible", "execution", "Worker compiler differs from the admitted implementation/config.")
                compiled = compiler.compile(request["ir"])
                if compiled.symbol_map != request["symbol_map"]:
                    raise RunError("code_hash_mismatch", "execution", "Worker symbols differ from the admitted CodeArtifact.")
            else:
                compiled = compile_ir(request["ir"])
            actual_source = compiled.source.encode() if args.solve_stdin else read_public_bytes(args.solve.parent / "model.py")
            if (hashlib.sha256(compiled.source.encode()).hexdigest() != request["source_sha256"]
                    or hashlib.sha256(actual_source).hexdigest() != request["source_sha256"]):
                raise RunError("code_hash_mismatch", "execution", "CodeArtifact does not match deterministic IR compilation.")
            result = solve(compiled, request["solver_options"], args.solver)
        usage = resource.getrusage(resource.RUSAGE_SELF)
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        print(json.dumps({"schema_version": "0.2.0", "runtime": runtime, "result": result,
            "resources": {"cpu_time_s": usage.ru_utime + usage.ru_stime + children.ru_utime + children.ru_stime,
                          "peak_memory_bytes": max(usage.ru_maxrss, children.ru_maxrss) * 1024},
            **({"factory": factory} if factory is not None else {})},
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
