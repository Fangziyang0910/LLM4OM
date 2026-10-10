"""Trusted image entry point; derive a model from strict IR and collect API evidence."""

import argparse
import hashlib
import json
import resource
import sys
import platform
from importlib.metadata import version
from pathlib import Path
from typing import cast

from llm4om.contracts import RunError, parse_json, read_public_bytes
from llm4om.solvers import solver_runtime, solver_packages, solve
from llm4om.linear import compile_ir
from llm4om.compilers import resolve_compiler, compiler_identity
from llm4om.execution_plugins import resolve_execution_resources
from llm4om.backends import NativeModelBackend


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", action="store_true")
    parser.add_argument("--runtime-stdin", action="store_true")
    parser.add_argument("--execution-runtime", type=Path)
    parser.add_argument("--compiler-runtime", type=Path)
    parser.add_argument("--solver", default="llm4om.solvers.highs")
    parser.add_argument("--solve", type=Path)
    parser.add_argument("--collect-native", type=Path)
    parser.add_argument("--solve-stdin", action="store_true")
    args = parser.parse_args()
    try:
        request = None
        selection = None
        if args.runtime_stdin:
            selection = parse_json(sys.stdin.buffer.read())
        elif args.execution_runtime is not None:
            selection = parse_json(read_public_bytes(args.execution_runtime))
        elif not args.runtime and (args.solve_stdin or args.solve is not None or args.collect_native is not None):
            request = parse_json(sys.stdin.buffer.read() if args.solve_stdin else read_public_bytes(args.collect_native or args.solve))
            selection = request.get("execution")
        try:
            execution = resolve_execution_resources(selection["model_backend"], selection["solver"], selection["allowed_problem_types"]) if selection else None
        except RunError as error:
            if args.runtime:
                raise RunError("execution_plugin_unavailable", "admission", "Worker cannot load the selected Backend/Solver.") from error
            raise
        if execution is not None and request is not None and execution.identity() != request.get("execution_identity"):
            raise RunError("checkpoint_incompatible", "execution", "Worker Backend/Solver differs from the admitted identities.")
        runtime = {"python": platform.python_version(), "llm4om": version("llm4om"),
                   **(execution.runtime() if execution else {"packages": solver_packages(args.solver)} if args.collect_native is not None else solver_runtime(args.solver))}
        if args.runtime:
            compiler_runtime = {}
            if args.compiler_runtime is not None:
                selection = parse_json(read_public_bytes(args.compiler_runtime))
                try:
                    compiler = resolve_compiler(selection["compiler"], selection["target_backend"])
                except RunError as error:
                    raise RunError("compiler_unavailable", "admission", "Worker cannot load the selected compiler.") from error
                compiler_runtime["compiler_identity"] = compiler_identity(compiler.binding)
            print(json.dumps({"schema_version": "0.2.0", "runtime": runtime, **compiler_runtime,
                **({"execution_identity": execution.identity()} if execution else {})}, allow_nan=False))
            return 0
        if args.solve is None and not args.solve_stdin and args.collect_native is None:
            parser.error("--solve or --runtime is required")
        assert request is not None
        factory = None
        if args.collect_native is not None:
            from llm4om.gurobi import read_native, native_instance, solve_native
            collector_fields = {"schema_version", "transport", "source_sha256", "solver_options", "allowed_problem_types"}
            if ((execution is None and args.solver != "llm4om.solvers.gurobi") or set(request) not in (collector_fields, collector_fields | {"execution", "execution_identity"})
                    or request["schema_version"] != "0.1.0"):
                raise RunError("invalid_worker_request", "execution", "Invalid native collector request.")
            if execution and execution.backend_binding["manifest"]["capabilities"]["handle_profile"] != "gurobipy_linear/0.1.0":
                raise RunError("capability_mismatch", "execution", "Captured native transport requires a native Backend.")
            with (cast(NativeModelBackend, execution.backend).read_transport(request["transport"]) if execution else read_native(request["transport"])) as handle:
                instance = native_instance(handle)
                if instance["problem_type"] not in request["allowed_problem_types"]:
                    raise RunError("capability_mismatch", "execution", "Captured model type is outside admission.")
                result = execution.solve(handle, request["solver_options"]) if execution else solve_native(handle, request["solver_options"])
        elif not args.solve_stdin and request.get("kind") in ("python_factory/0.1.0", "native_gurobipy/0.1.0"):
            from llm4om.factory_worker import solve_factory
            result, factory = solve_factory(args.solve, solver_id=args.solver)
        else:
            if set(request) not in ({"ir", "source_sha256", "solver_options"}, {"ir", "source_sha256", "symbol_map", "solver_options", "compiler", "compiler_identity", "target_backend"},
                    {"ir", "source_sha256", "symbol_map", "solver_options", "compiler", "compiler_identity", "target_backend", "execution", "execution_identity"}):
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
            result = execution.solve(execution.backend.load(compiled, {}), request["solver_options"]) if execution else solve(compiled, request["solver_options"], args.solver)
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
