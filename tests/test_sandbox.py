"""The sandbox builds generated models and solves them with each code language's solver, and runs check scripts."""

import asyncio
import importlib.util
from pathlib import Path

import pytest

from llm4om.sandbox import WORKER_IMAGE, Sandbox, SolveResult
from tests.conftest import PRODUCTION_CODE

GUROBIPY_CODE = '''import gurobipy as gp
from gurobipy import GRB

def build_model(data):
    m = gp.Model()
    x = m.addVars(["A", "B"], vtype=GRB.INTEGER, name="x")
    m.setObjective(3 * x["A"] + 2 * x["B"], GRB.MAXIMIZE)
    m.addConstr(2 * x["A"] + x["B"] <= 8)
    m.addConstr(x["A"] + 2 * x["B"] <= 8)
    return m
'''
ORTOOLS_CODE = '''from ortools.linear_solver import pywraplp

def build_model(data):
    s = pywraplp.Solver.CreateSolver("SCIP")
    x = {p: s.IntVar(0, s.infinity(), f"x[{p}]") for p in "AB"}
    s.Maximize(3 * x["A"] + 2 * x["B"])
    s.Add(2 * x["A"] + x["B"] <= 8)
    s.Add(x["A"] + 2 * x["B"] <= 8)
    return s
'''
CPMPY_CODE = '''import cpmpy as cp

def build_model(data):
    x = cp.intvar(0, 10, shape=2, name="x")
    m = cp.Model(2 * x[0] + x[1] <= 8, x[0] + 2 * x[1] <= 8)
    m.maximize(3 * x[0] + 2 * x[1])
    return m
'''
PULP_CODE = '''import pulp

def build_model(data):
    problem = pulp.LpProblem("production", pulp.LpMaximize)
    x = pulp.LpVariable.dicts("x", ["A", "B"], lowBound=0, cat="Integer")
    problem += 3 * x["A"] + 2 * x["B"]
    problem += 2 * x["A"] + x["B"] <= 8, "cutting"
    problem += x["A"] + 2 * x["B"] <= 8, "machining"
    return problem
'''
CVXPY_CODE = '''import cvxpy as cp
import numpy as np

def build_model(data):
    x = cp.Variable(2, name="x")
    return cp.Problem(cp.Minimize(cp.sum_squares(x - np.array([1, 2]))), [x >= 0, cp.sum(x) <= 2])
'''
has_gurobi = importlib.util.find_spec("gurobipy") is not None


def solve(code: str, language: str = "pyomo", data: dict[str, str] | None = None) -> SolveResult:
    return asyncio.run(Sandbox("local").solve(code, data or {}, language, time_limit=10))


@pytest.mark.parametrize("language,code,names", [
    pytest.param("pyomo", PRODUCTION_CODE, ("x[A]", "x[B]"), id="pyomo-highs"),
    pytest.param("pywraplp", ORTOOLS_CODE, ("x[A]", "x[B]"), id="pywraplp-scip"),
    pytest.param("cpmpy", CPMPY_CODE, ("x[0]", "x[1]"), id="cpmpy-cpsat"),
    pytest.param("pulp", PULP_CODE, ("x_A", "x_B"), id="pulp-cbc"),
    pytest.param("gurobipy", GUROBIPY_CODE, ("x[A]", "x[B]"), id="gurobipy-gurobi",
                 marks=pytest.mark.skipif(not has_gurobi, reason="gurobipy is not installed"))])
def test_every_language_is_solved_by_its_solver(language: str, code: str, names: tuple[str, str]) -> None:
    result = solve(code, language)
    assert result.error is None, result.error
    assert (result.status, result.objective) == ("optimal", 13)
    assert {name.replace(" ", ""): value for name, value in result.variables.items()} == dict(zip(names, (3, 2)))


def test_cvxpy_solves_a_convex_quadratic_program_with_clarabel() -> None:
    result = solve(CVXPY_CODE, "cvxpy")
    assert result.error is None and result.output == "", (result.error, result.output)  # CVXPY's import warnings stay out
    assert result.status == "optimal" and result.objective == pytest.approx(0.5, abs=1e-6)
    assert result.variables == pytest.approx({"x[0]": 0.5, "x[1]": 1.5}, abs=1e-6)


def test_clarabel_rejects_integer_variables() -> None:
    result = solve("import cvxpy as cp\n\ndef build_model(data):\n    y = cp.Variable(integer=True, name='y')\n"
                   "    return cp.Problem(cp.Minimize(y), [y >= 1])\n", "cvxpy")
    assert result.error is not None and "[solve]" in result.error and "mixed-integer" in result.error


# Two demands that the capacity cannot both meet; `spare` is a constraint outside the conflict.
CONFLICTS = {
    # Gurobi's presolve calls this model "infeasible or unbounded"; the worker settles which.
    "gurobipy": GUROBIPY_CODE.replace("    return m", "    m.addConstr(x['A'] >= 5, 'needA')\n    m.addConstr(x['B'] >= 5, 'needB')\n"
                                      "    return m"),
    "pyomo": PRODUCTION_CODE.replace("    return m", "    m.needA = pyo.Constraint(expr=m.x['A'] >= 5)\n"
                                     "    m.needB = pyo.Constraint(expr=m.x['B'] >= 5)\n    return m"),
    "pywraplp": ORTOOLS_CODE.replace("    return s", "    s.Add(x['A'] >= 5, 'needA')\n    s.Add(x['B'] >= 5, 'needB')\n    return s"),
    "pulp": PULP_CODE.replace("    return problem", "    problem += x['A'] >= 5, 'needA'\n    problem += x['B'] >= 5, 'needB'\n"
                              "    return problem"),
    "cpmpy": CPMPY_CODE.replace("    m.maximize", "    m += x[0] >= 5\n    m += x[1] >= 5\n    m.maximize"),
}


@pytest.mark.parametrize("language", [pytest.param(language, marks=pytest.mark.skipif(
    language != "cpmpy" and not has_gurobi, reason="the IIS of linear models comes from Gurobi")) for language in CONFLICTS])
def test_an_infeasible_model_shows_its_conflict_but_feedback_leaves_it_out(language: str) -> None:
    result = solve(CONFLICTS[language], language)
    assert result.status == "infeasible" and result.diagnosis is not None, (result.error, result.output)
    assert result.diagnosis["error"] is None and result.diagnosis["total"] == len(result.diagnosis["items"]) >= 2
    text = " ".join(result.diagnosis["items"])
    assert ("needA" in text and "needB" in text) if language != "cpmpy" else (">= 5" in text)
    assert "machining" not in text or "cutting" not in text  # one capacity row is enough for the conflict
    assert "needA" not in result.feedback() and "IIS" not in result.feedback()


def test_cpmpy_satisfaction_problem_has_a_solution_without_objective() -> None:
    code = "import cpmpy as cp\n\ndef build_model(data):\n    x = cp.intvar(1, 3, shape=3, name='x')\n" \
           "    return cp.Model(cp.AllDifferent(x), x[0] > x[1])\n"
    result = solve(code, "cpmpy")
    assert (result.status, result.objective, result.has_solution) == ("feasible", None, True)
    assert sorted(result.variables.values()) == [1, 2, 3] and "x[0]" in result.feedback()


def test_code_in_another_language_is_reported() -> None:
    result = solve(PRODUCTION_CODE, "pywraplp")
    assert result.error is not None and "pywraplp.Solver" in result.error and "ConcreteModel" in result.error


def test_data_files_reach_build_model() -> None:
    code = PRODUCTION_CODE.replace('3 * m.x["A"]', 'float(data["profit.csv"].split(",")[1]) * m.x["A"]')
    assert solve(code, data={"profit.csv": "A,30"}).objective == 120  # x = (4, 0)


def test_all_variables_are_returned_even_past_two_thousand() -> None:
    code = '''import pyomo.environ as pyo
def build_model(data):
    m = pyo.ConcreteModel()
    m.x = pyo.Var(range(2001), bounds=(0, 1))
    m.c = pyo.Constraint(range(2001), rule=lambda m, i: m.x[i] == int(i == 2000))
    m.obj = pyo.Objective(expr=sum(m.x.values()))
    return m
'''
    result = solve(code)
    assert result.objective == 1 and len(result.variables) == 2001
    assert result.variables["x[2000]"] == 1


def test_solves_and_scripts_share_capacity_and_queued_cancellation_releases_it(monkeypatch: pytest.MonkeyPatch) -> None:
    async def check() -> None:
        sandbox = Sandbox("local", max_jobs=2)
        release, full = asyncio.Event(), asyncio.Event()
        active = peak = 0

        async def execute(*args):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 2:
                full.set()
            try:
                await release.wait()
                return SolveResult("executed")
            finally:
                active -= 1

        monkeypatch.setattr(sandbox, "_execute", execute)
        first = asyncio.create_task(sandbox.solve("", {}, "pyomo", 1))
        second = asyncio.create_task(sandbox.run_script("", 1))
        await asyncio.wait_for(full.wait(), 1)
        queued = asyncio.create_task(sandbox.run_script("", 1))
        await asyncio.sleep(0)
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        release.set()
        await asyncio.gather(first, second)
        assert (await sandbox.run_script("", 1)).executed and peak == 2 and active == 0

    asyncio.run(check())


def test_infeasible_model_is_a_solver_status_not_an_error() -> None:
    result = solve(PRODUCTION_CODE.replace("<= 8)\n    return", "<= 8)\n    m.need = pyo.Constraint(expr=m.x['A'] >= 9)\n    return"))
    assert result.executed and result.status in ("infeasible", "infeasible_or_unbounded")
    assert result.objective is None


def test_errors_point_at_the_generated_code() -> None:
    result = solve(PRODUCTION_CODE.replace("return m", "return m.missing"))
    assert not result.executed
    assert result.error is not None and "[build]" in result.error and 'File "model.py"' in result.error
    assert "worker.py" not in result.error


def test_code_without_build_model_is_rejected() -> None:
    assert "build_model" in (solve("x = 1").error or "")


def test_a_script_runs_as_main_and_reports_its_output() -> None:
    result = asyncio.run(Sandbox("local").run_script("if __name__ == '__main__':\n    print(6 * 7)\n", time_limit=10))
    assert result.executed and result.output.strip() == "42"


def test_printed_output_does_not_break_the_result() -> None:
    result = solve(PRODUCTION_CODE.replace("    return m", "    print('hello', flush=True)\n    return m"))
    assert result.objective == 13 and "hello" in result.output


def test_local_worker_does_not_inherit_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM4OM_LLM_API_KEY", "synthetic-secret")
    monkeypatch.setenv("UNRELATED_SECRET", "another-synthetic-secret")
    script = "import os\nassert 'LLM4OM_LLM_API_KEY' not in os.environ\nassert 'UNRELATED_SECRET' not in os.environ\n"
    result = asyncio.run(Sandbox("local").run_script(script, time_limit=5))
    assert result.executed, result.error


def test_cancelling_a_worker_reaps_its_process(monkeypatch: pytest.MonkeyPatch) -> None:
    create = asyncio.create_subprocess_exec

    async def check() -> None:
        started = asyncio.Event()
        processes = []

        async def capture(*args, **kwargs):
            process = await create(*args, **kwargs)
            processes.append(process)
            started.set()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", capture)
        task = asyncio.create_task(Sandbox("local").run_script("import time; time.sleep(30)", 60))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert processes[0].returncode is not None

    asyncio.run(check())


def test_small_values_keep_solver_precision() -> None:
    code = '''import pyomo.environ as pyo

def build_model(data):
    m = pyo.ConcreteModel()
    m.x = pyo.Var(bounds=(0, 1))
    m.goal = pyo.Objective(expr=1e-10 + m.x)
    return m
'''
    result = solve(code)
    assert result.executed and result.objective == pytest.approx(1e-10, rel=1e-9, abs=0)


def test_a_solver_error_is_not_successful_execution() -> None:
    assert not SolveResult('error').executed


def test_compose_builds_the_worker_image_the_sandbox_runs() -> None:
    compose = (Path(__file__).parents[1] / "compose.yaml").read_text(encoding="utf-8")
    assert f"image: {WORKER_IMAGE}\n" in compose
