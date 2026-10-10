"""Selection of the two supported deterministic Solver adapters and runtimes."""

from typing import Any, Protocol, cast
from llm4om.contracts import RunError
from llm4om.linear import CompiledCode
from llm4om.backends import ModelHandle


class SolverBackend(Protocol):
    def runtime(self) -> dict[str, Any]: ...
    def solve(self, handle: ModelHandle, options: dict[str, Any]) -> dict[str, Any]: ...


class HighsSolverBackend:
    def runtime(self) -> dict[str, Any]:
        from llm4om.highs import runtime_versions
        return {"packages": runtime_versions()}

    def solve(self, handle: ModelHandle, options: dict[str, Any]) -> dict[str, Any]:
        from llm4om.highs import solve_highs_handle
        return solve_highs_handle(handle, options)


class GurobiSolverBackend:
    def runtime(self) -> dict[str, Any]:
        from llm4om.gurobi import runtime_versions, availability
        return {"packages": runtime_versions(), "solver_environment": availability()}

    def solve(self, handle: ModelHandle, options: dict[str, Any]) -> dict[str, Any]:
        from llm4om.gurobi import solve_gurobi_handle, solve_native
        import pyomo.environ as pyo
        if isinstance(handle.model, pyo.ConcreteModel):
            return solve_gurobi_handle(handle, options)
        return solve_native(handle, options)


class HighsSolverFactory:
    plugin_id = "llm4om.solvers.highs"
    handle_profiles = ["pyomo_linear/0.1.0"]
    result_profile = "highs_api/0.1.0"
    dependencies = ["Pyomo", "highspy"]

    def describe(self) -> dict[str, Any]:
        return {"schema_version": "0.2.0", "plugin_id": self.plugin_id, "kind": "solver_backend",
            "plugin_version": "0.1.0", "contract_range": ">=0.2.0,<0.3.0", "display_name": self.plugin_id,
            "description": "Actual numerical optimization over explicitly supported Worker-local handles.",
            "capabilities": {"solver_profile": "model_handle/0.1.0", "handle_profiles": self.handle_profiles,
                "result_profile": self.result_profile, "problem_types": ["lp", "milp"],
                "input_artifact_kinds": ["model_handle"], "output_artifact_kinds": ["solve_result"]},
            "config_schema": {"type": "object", "additionalProperties": False},
            "options_schema": {"type": "object", "properties": {"time_limit_s": {"type": "number", "minimum": 0}}, "additionalProperties": False},
            "dependencies": {"python": self.dependencies}, "source": None}

    def create(self, config: dict[str, Any]) -> SolverBackend:
        if config:
            raise RunError("invalid_config", "admission", "The built-in Solver has no configuration options.")
        return HighsSolverBackend()


class GurobiSolverFactory(HighsSolverFactory):
    plugin_id = "llm4om.solvers.gurobi"
    handle_profiles = ["pyomo_linear/0.1.0", "gurobipy_linear/0.1.0"]
    result_profile = "gurobi_api/0.1.0"
    dependencies = ["Pyomo", "gurobipy"]

    def create(self, config: dict[str, Any]) -> SolverBackend:
        if config:
            raise RunError("invalid_config", "admission", "The built-in Solver has no configuration options.")
        return GurobiSolverBackend()


def solver_packages(solver_id: str, *, config: dict[str, Any] | None = None) -> dict[str, str]:
    from typing import cast
    return cast(dict[str, str], solver_runtime(solver_id, config=config)["packages"])


def solver_runtime(solver_id: str, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    from llm4om.execution_plugins import checked_solver_runtime
    from llm4om.plugins import resolve_configured_plugin
    solver, binding = resolve_configured_plugin("solver_backend", {"plugin_id": solver_id, "config": config or {}})
    return checked_solver_runtime(cast(SolverBackend, solver), binding["packages"])


def solve(code: CompiledCode, options: dict[str, Any], solver_id: str, *,
          config: dict[str, Any] | None = None, backend_selection: dict[str, Any] | None = None) -> dict[str, Any]:
    from llm4om.execution_plugins import resolve_execution_resources
    resources = resolve_execution_resources(backend_selection or {"plugin_id": "llm4om.model_backends.pyomo_factory"},
        {"plugin_id": solver_id, "config": config or {}, "options": options}, ["lp", "milp"])
    return resources.solve(resources.backend.load(code, {}), options)
