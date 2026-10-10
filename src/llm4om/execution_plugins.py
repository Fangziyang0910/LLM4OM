"""Resolve a compatible construction/solve pair and bind its actual execution."""

from dataclasses import dataclass
from copy import deepcopy
from typing import Any, cast
import json
import jsonschema

from llm4om.backends import ModelBackend, ModelHandle
from llm4om.solvers import SolverBackend
from llm4om.plugins import Plugin, discover_plugins, resolve_configured_plugin, _quiet, _exception_details
from llm4om.contracts import RunError, validate_worker_response
from llm4om.compilers import compiler_identity


def checked_solver_runtime(solver: SolverBackend, packages: dict[str, str]) -> dict[str, Any]:
    try:
        with _quiet():
            runtime = solver.runtime()
        if not isinstance(runtime, dict) or not isinstance(runtime.get("packages"), dict):
            raise ValueError("Expected Solver package/runtime evidence.")
        if any(name in runtime["packages"] and runtime["packages"][name] != value for name, value in packages.items()):
            raise ValueError("Solver runtime and installed package versions differ.")
        runtime = {**runtime, "packages": {**runtime["packages"], **packages}}
        if not all(isinstance(name, str) and name and isinstance(value, str) and value for name, value in runtime["packages"].items()):
            raise ValueError("Runtime requires explicit package versions.")
        json.dumps(runtime, allow_nan=False)
        return runtime
    except RunError as error:
        raise RunError(error.code, error.stage, "Registered Solver runtime rejected the environment.", details=_exception_details(error)) from error
    except (Exception, SystemExit) as error:
        raise RunError("solver_unavailable", "admission", "Registered Solver runtime check failed.", details=_exception_details(error)) from error


@dataclass(frozen=True)
class ExecutionResources:
    backend: ModelBackend
    solver: SolverBackend
    backend_binding: dict[str, Any]
    solver_binding: dict[str, Any]
    allowed_types: tuple[str, ...]

    @property
    def result_profile(self) -> str:
        return cast(str, self.solver_binding["manifest"]["capabilities"]["result_profile"])

    def identity(self) -> dict[str, Any]:
        return {name: {key: value for key, value in compiler_identity(binding).items() if key != "packages"}
            for name, binding in (("model_backend", self.backend_binding), ("solver", self.solver_binding))}

    def runtime(self) -> dict[str, Any]:
        return checked_solver_runtime(self.solver, {**self.backend_binding["packages"], **self.solver_binding["packages"]})

    def solve(self, handle: ModelHandle, options: dict[str, Any]) -> dict[str, Any]:
        _validate_options(self.solver_binding["manifest"], options)
        try:
            with _quiet():
                if self.backend_binding["manifest"]["capabilities"]["handle_profile"] == "pyomo_linear/0.1.0":
                    actual_type = self.backend.export(handle)["problem_type"]
                else:
                    from llm4om.gurobi import native_instance
                    actual_type = native_instance(handle)["problem_type"]
                if actual_type not in self.allowed_types:
                    raise RunError("capability_mismatch", "solve", "Actual model type is outside the admitted scope.")
                runtime = self.runtime()
                result = self.solver.solve(handle, deepcopy(options))
            if not isinstance(result, dict):
                raise ValueError("Expected a normalized Solver result.")
            if result.get("options") != options:
                raise ValueError("Solver result does not identify the options actually requested.")
            result = {**result, "solver_id": self.solver_binding["manifest"]["plugin_id"],
                "model_backend": self.backend_binding["manifest"]["plugin_id"]}
            json.dumps(result, allow_nan=False)
            validate_worker_response({"schema_version": "0.2.0", "runtime": runtime, "result": result,
                "resources": {"cpu_time_s": 0, "peak_memory_bytes": 0}}, runtime,
                solver_id=result["solver_id"], model_backend=result["model_backend"], result_profile=self.result_profile)
            if result["variables"] is not None and set(result["variables"]) != set(handle.decision_map):
                raise ValueError("Solver omitted or invented a public decision.")
            return result
        except RunError as error:
            raise RunError(error.code, error.stage, "Registered Solver rejected the model or result.", details=_exception_details(error)) from error
        except (Exception, SystemExit) as error:
            raise RunError("solver_error", "solve", "Registered Solver failed or returned invalid output.", details=_exception_details(error)) from error


def _validate_options(manifest: dict[str, Any], options: dict[str, Any]) -> None:
    try:
        jsonschema.Draft202012Validator(manifest["options_schema"]).validate(options)
    except (jsonschema.ValidationError, jsonschema.exceptions.RefResolutionError, RecursionError) as error:
        raise RunError("invalid_solver_options", "admission", "Solver options do not match the selected Manifest.") from error


def resolve_execution_resources(backend_selection: dict[str, Any], solver_selection: dict[str, Any],
        allowed_types: list[str], *, inventory: dict[tuple[str, str], Plugin] | None = None,
        expected: dict[str, Any] | None = None, check_dependencies: bool = True) -> ExecutionResources:
    inventory = discover_plugins() if inventory is None else inventory
    try:
        backend, backend_binding = resolve_configured_plugin("model_backend", backend_selection, inventory=inventory,
            expected=expected.get("model_backend") if expected else None, check_dependencies=check_dependencies)
        solver, solver_binding = resolve_configured_plugin("solver_backend", solver_selection, inventory=inventory,
            expected=expected.get("solver") if expected else None, check_dependencies=check_dependencies)
    except RunError as error:
        if error.code == "dependency_missing":
            raise RunError("solver_unavailable", "admission", "The execution environment lacks a required Backend/Solver dependency.") from error
        raise
    backend_caps = backend_binding["manifest"]["capabilities"]
    solver_caps = solver_binding["manifest"]["capabilities"]
    if (backend_caps["handle_profile"] not in solver_caps["handle_profiles"]
            or not set(allowed_types) <= set(backend_caps["problem_types"])
            or not set(allowed_types) <= set(solver_caps["problem_types"])):
        raise RunError("capability_mismatch", "admission", "Backend/Solver do not support the configured handle and problem types.")
    _validate_options(solver_binding["manifest"], solver_selection.get("options", {}))
    if (not callable(getattr(backend, "load", None)) or not callable(getattr(backend, "export", None))
            or not callable(getattr(solver, "runtime", None)) or not callable(getattr(solver, "solve", None))):
        raise RunError("invalid_plugin_manifest", "admission", "Execution adapters do not implement their declared interfaces.")
    if backend_caps["handle_profile"] == "gurobipy_linear/0.1.0" and not callable(getattr(backend, "read_transport", None)):
        raise RunError("invalid_plugin_manifest", "admission", "Native Backend requires an independent transport reader.")
    return ExecutionResources(cast(ModelBackend, backend), cast(SolverBackend, solver), backend_binding, solver_binding, tuple(allowed_types))
