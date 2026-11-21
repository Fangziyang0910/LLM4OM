"""Deterministic tests for AutoCO: 12-family sandbox solver pool, KG validation, LangGraph workflow & multi-objective Pareto."""

from __future__ import annotations

import asyncio
import importlib.util
import json
from typing import Any

import pytest

from llm4om.graph import run
from llm4om.host import resume as host_resume
from llm4om.host import start as host_start
from llm4om.methods import methods
from llm4om.methods.autoco.knowledge import DEFAULT_KG
from llm4om.runtime import Limits
from llm4om.sandbox import Sandbox
from tests.conftest import tool_call

has_cma = importlib.util.find_spec("cma") is not None
has_pymoo = importlib.util.find_spec("pymoo") is not None

SINGLE_OBJ_CODE = '''import numpy as np
from autoco import Problem, VarSpec

def build_model(data):
    profit_a = float(data["profit.csv"].split(",")[1]) if "profit.csv" in data else 3.0
    def evaluate(x):
        a, b = int(x[0]), int(x[1])
        obj = profit_a * a + 2.0 * b
        v1 = max(0.0, 2 * a + b - 8)
        v2 = max(0.0, a + 2 * b - 8)
        return float(obj), float(v1 + v2)

    def decode(x):
        return {"A": int(x[0]), "B": int(x[1])}

    return Problem(
        name="production",
        variables=[VarSpec("x", "integer", size=2, lb=0, ub=8)],
        evaluate=evaluate,
        senses=["max"],
        decode=decode,
    )
'''

MULTI_OBJ_CODE = '''import numpy as np
from autoco import Problem, VarSpec

def build_model(data):
    def evaluate(x):
        v = float(x[0])
        return np.array([v ** 2, (v - 2.0) ** 2], dtype=float), 0.0

    def decode(x):
        v = float(x[0])
        return {"x": round(v, 4), "f1": round(v ** 2, 4), "f2": round((v - 2.0) ** 2, 4)}

    return Problem(
        name="bi_obj_tradeoff",
        variables=[VarSpec("x", "continuous", size=1, lb=0.0, ub=2.0)],
        evaluate=evaluate,
        senses=["min", "min"],
        decode=decode,
    )
'''

SEMANTIC_JSON = json.dumps({
    "parameters": ["Two products A and B with profits 3 and 2", "Cutting and machining capacities of 8 each"],
    "objectives": ["Maximize total profit 3*A + 2*B"],
    "constraints": ["2*A + B <= 8", "A + 2*B <= 8", "A, B are nonnegative integers"],
    "assumptions": [],
})

FORMULATION_JSON = json.dumps({
    "scale_level": "small",
    "parameters": [{"name": "cap", "description": "Resource capacity", "value": "8"}],
    "variables": [{"name": "x", "var_type": "integer", "domain": "[0, 8]", "shape": "(2,)", "description": "Production quantities of A and B."}],
    "objectives": [{"name": "profit", "sense": "max", "form": "linear", "expr": "3*x[0] + 2*x[1]", "description": "Total profit"}],
    "constraints": [
        {"name": "cutting", "category": "capacity", "expr": "2*x[0] + x[1] <= 8", "description": "Cutting capacity"},
        {"name": "machining", "category": "capacity", "expr": "x[0] + 2*x[1] <= 8", "description": "Machining capacity"},
    ],
})

MULTI_FORMULATION_JSON = json.dumps({
    "scale_level": "small",
    "parameters": [{"name": "bound", "description": "Upper bound", "value": "2.0"}],
    "variables": [{"name": "x", "var_type": "continuous", "domain": "[0, 2]", "shape": "(1,)", "description": "Scalar trade-off decision."}],
    "objectives": [
        {"name": "cost", "sense": "min", "form": "quadratic", "expr": "x[0]**2", "description": "Cost"},
        {"name": "risk", "sense": "min", "form": "quadratic", "expr": "(x[0] - 2)**2", "description": "Risk"},
    ],
    "constraints": [],
})

REVIEW_PASS = json.dumps({"passed": True, "issues": []})


def test_autoco_method_is_registered_as_self_contained() -> None:
    autoco = methods()["autoco"]
    assert autoco.builtin_solver and autoco.languages == frozenset()
    assert autoco.code_target("pyomo") is None
    assert autoco.code_target("nonexistent-lib") is None


def test_knowledge_graph_detects_conflicts_and_validates_configs() -> None:
    query = DEFAULT_KG.query_knowledge(["pfeat:precedence", "pfeat:permutation"])
    assert any(r["relation"] == "CONFLICTS_WITH" and r["algorithm_feature"] == "afeat:segment_reversing_move"
               for r in query["problem_to_algorithm_relations"])

    ok, errs, warnings = DEFAULT_KG.validate_configuration(
        "SA",
        {"neighborhood": "2opt", "init_strategy": "random"},
        {},
        {"objective_mode": "single", "variable_types": ["permutation"], "constraint_categories": ["precedence"]},
    )
    assert ok and not errs
    assert len(warnings) >= 2

    ok_bad, errs_bad, _ = DEFAULT_KG.validate_configuration(
        "NSGA-II",
        {},
        {},
        {"objective_mode": "single", "variable_types": ["binary"]},
    )
    assert not ok_bad and errs_bad


def test_sandbox_solves_autoco_single_objective_with_data_attachment() -> None:
    result = asyncio.run(
        Sandbox("local").solve(SINGLE_OBJ_CODE, {"profit.csv": "A,30"}, "autoco", time_limit=1.0, solver="GA")
    )
    assert result.error is None, result.error
    assert result.status == "feasible"
    assert result.solver == "GA"
    assert result.objective == pytest.approx(120.0)
    assert result.variables["x[0]"] == pytest.approx(4.0)
    assert result.pareto is None
    assert "Decoded solution" in result.output


def test_sandbox_solves_autoco_multi_objective_pareto_front() -> None:
    alg = "NSGA-II" if has_pymoo else "MOEA/D"
    result = asyncio.run(Sandbox("local").solve(MULTI_OBJ_CODE, {}, "autoco", time_limit=1.2, solver=alg))
    assert result.error is None, result.error
    assert result.status == "feasible"
    assert result.solver == alg
    assert result.objective is None  # Multi-objective reports Pareto front instead of a misleading scalar
    assert result.has_solution
    assert result.pareto is not None
    assert result.pareto["total"] >= 3
    assert len(result.pareto["objectives"]) == 2
    assert any(item["knee"] for item in result.pareto["solutions"])
    assert "Pareto front:" in result.feedback()


@pytest.mark.skipif(not has_cma, reason="cma not installed in host venv")
def test_sandbox_solves_continuous_problem_with_cma_es() -> None:
    code = '''import numpy as np
from autoco import Problem, VarSpec

def build_model(data):
    return Problem(
        name="sphere",
        variables=[VarSpec("x", "continuous", size=2, lb=-5.0, ub=5.0)],
        evaluate=lambda x: (float(np.sum((x - np.array([1.0, -2.0])) ** 2)), 0.0),
        senses=["min"],
    )
'''
    result = asyncio.run(Sandbox("local").solve(code, {}, "autoco", time_limit=1.5, solver="CMA-ES"))
    assert result.error is None, result.error
    assert result.status == "feasible" and result.solver == "CMA-ES"
    assert result.objective is not None and result.objective < 1e-2


def test_autoco_method_end_to_end_with_kg_pilot_and_sandbox(make_resources: Any, preset: Any) -> None:
    preset("AUTOCO", max_modeling_revisions=1, max_instantiate_attempts=2, max_kg_steps=4, enable_pilot=True)
    kg_step = 0

    def script(role: str, messages: list[Any], tools: list[str]) -> Any:
        nonlocal kg_step
        if role == "semantic_grounding":
            return SEMANTIC_JSON
        if role == "formulate":
            return FORMULATION_JSON
        if role == "review_formulation":
            return REVIEW_PASS
        if role == "instantiate":
            return f"```python\n{SINGLE_OBJ_CODE}```"
        if role == "kg_agent":
            kg_step += 1
            if kg_step == 1:
                assert {"query_knowledge", "inspect_solver_specs", "pilot_verify", "commit_configuration"} <= set(tools)
                return tool_call("query_knowledge", concepts=["pfeat:integer", "pfeat:capacity"])
            if kg_step == 2:
                return tool_call(
                    "pilot_verify",
                    candidates=[{"algorithm": "SA", "operators": {"init_strategy": "greedy"}}, {"algorithm": "GA"}],
                    trial_seconds=0.5,
                )
            # Verify pilot tool returned real sandboxed metrics in ToolMessage
            assert any("evals_per_sec" in str(m.content) for m in messages)
            return tool_call(
                "commit_configuration",
                algorithm="GA",
                operators={"init_strategy": "mixed", "constraint_handling": "feasibility"},
                hyperparameters={"pop_size": 20},
                rationale="Compact integer problem suited to memetic GA.",
            )
        raise AssertionError(f"Unexpected role {role}")

    resources = make_resources(script, limits=Limits(solve_time_limit=5.5))
    record = asyncio.run(run("Maximize 3A + 2B subject to 2A+B<=8, A+2B<=8.", method="autoco", resources=resources))
    assert not record.get("failure"), record.get("failure")
    assert record["spec"]["language"] == "autoco"
    assert record["solve"]["status"] == "feasible"
    assert record["solve"]["solver"] == "GA"
    assert record["solve"]["objective"] == pytest.approx(13.0)
    assert "AUTOCO_CONFIG" in record["code"]
    assert record["usage"]["solves"] == 1


def test_autoco_method_multi_objective_emits_pareto_front(make_resources: Any, preset: Any) -> None:
    preset("AUTOCO", max_modeling_revisions=0, enable_pilot=False)

    def script(role: str, messages: list[Any], tools: list[str]) -> Any:
        if role == "semantic_grounding":
            return json.dumps({
                "parameters": ["x in [0, 2]"],
                "objectives": ["Minimize cost = x^2", "Minimize risk = (x-2)^2"],
                "constraints": [],
                "assumptions": [],
            })
        if role == "formulate":
            return MULTI_FORMULATION_JSON
        if role == "instantiate":
            return f"```python\n{MULTI_OBJ_CODE}```"
        if role == "kg_agent":
            return tool_call(
                "commit_configuration",
                algorithm="MOEA/D",
                operators={"aggregation": "tchebycheff", "init_strategy": "mixed"},
                hyperparameters={"pop_size": 20},
                rationale="Bi-objective continuous trade-off solved with MOEA/D.",
            )
        raise AssertionError(f"Unexpected role {role}")

    resources = make_resources(script, limits=Limits(solve_time_limit=1.5))
    record = asyncio.run(run("Minimize x^2 and (x-2)^2 for x in [0,2].", method="autoco", resources=resources))
    assert not record.get("failure"), record.get("failure")
    solve = record["solve"]
    assert solve["status"] == "feasible" and solve["solver"] == "MOEA/D"
    assert solve["objective"] is None
    assert solve["pareto"]["objectives"] == [{"name": "cost", "sense": "min"}, {"name": "risk", "sense": "min"}]
    assert solve["pareto"]["total"] >= 3


def test_autoco_works_in_host_mode(tmp_path: Any, preset: Any) -> None:
    preset("AUTOCO", max_modeling_revisions=0, enable_pilot=False)
    session = tmp_path / "autoco-host"
    state = asyncio.run(host_start(session, "Maximize 3A + 2B.", method="autoco", sandbox="local", time_limit=1.5))
    assert state["status"] == "waiting" and state["spec"]["language"] == "autoco"

    answers = {
        "semantic_grounding": {"content": SEMANTIC_JSON},
        "formulate": {"content": FORMULATION_JSON},
        "instantiate": {"content": f"```python\n{SINGLE_OBJ_CODE}```"},
        "kg_agent": {
            "content": "",
            "tool_calls": [{
                "name": "commit_configuration",
                "args": {"algorithm": "GA", "operators": {}, "hyperparameters": {"pop_size": 20}, "rationale": "Host test."},
            }],
        },
    }
    while state["status"] == "waiting":
        reply_map = {item["id"]: answers[item["role"]] for item in state["pending"]}
        state = asyncio.run(host_resume(session, reply_map))

    assert state["status"] == "completed", state.get("failure")
    assert state["solve"]["status"] == "feasible" and state["solve"]["solver"] == "GA"
    assert state["solve"]["objective"] == pytest.approx(13.0)
