"""Selection of the two supported deterministic Solver adapters and runtimes."""

from typing import Any
from llm4om.contracts import RunError
from llm4om.linear import CompiledCode


def solver_runtime(solver_id: str) -> dict[str, Any]:
    if solver_id == "llm4om.solvers.gurobi":
        from llm4om.gurobi import runtime_versions, availability
        packages = runtime_versions()
        return {"packages": packages, "solver_environment": availability()}
    if solver_id == "llm4om.solvers.highs":
        from llm4om.highs import runtime_versions as highs_versions
        return {"packages": highs_versions()}
    raise RunError("capability_mismatch", "admission", "Unsupported Solver selection.")


def solve(code: CompiledCode, options: dict[str, Any], solver_id: str) -> dict[str, Any]:
    if solver_id == "llm4om.solvers.gurobi":
        from llm4om.gurobi import solve_gurobi
        return solve_gurobi(code, options)
    if solver_id == "llm4om.solvers.highs":
        from llm4om.highs import solve_highs
        return solve_highs(code, options)
    raise RunError("capability_mismatch", "admission", "Unsupported Solver selection.")
