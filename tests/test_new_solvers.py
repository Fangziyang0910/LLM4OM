"""Real native SCIP, Ipopt and CVXPY solver paths."""

import asyncio
import os
from pathlib import Path

import pytest

from llm4om.languages import CodeTarget
from llm4om.sandbox import Sandbox
from tests.test_sandbox import CVXPY_CODE, solve

SCIP_CODE = '''from pyscipopt import Model
def build_model(data):
    m = Model()
    x = {p: m.addVar(name=f"x[{p}]", vtype="I", lb=0) for p in "AB"}
    m.setObjective(3*x["A"]+2*x["B"], "maximize")
    m.addCons(2*x["A"]+x["B"]<=8)
    m.addCons(x["A"]+2*x["B"]<=8)
    return m
'''
IPOPT_CODE = '''import casadi as ca
def build_model(data):
    m = ca.Opti()
    x = m.variable(2)
    m.minimize((1-x[0])**2 + 100*(x[1]-x[0]**2)**2)
    m.subject_to(m.bounded(-2,x,2))
    m.set_initial(x,[0,0])
    return m
'''


@pytest.mark.parametrize("language,code", [("pyscipopt", SCIP_CODE)])
def test_native_milp_solvers(language: str, code: str) -> None:
    result = solve(code, language)
    assert (result.status, result.objective) == ("optimal", 13), result.error
    assert sorted(result.variables.values()) == [2, 3]


@pytest.mark.parametrize("language,code,extra", [
    ("pyscipopt", SCIP_CODE, "m.addCons(x['A'] >= 10)"),
    ("casadi", IPOPT_CODE, "m.subject_to(x[0] >= 10)"),
])
def test_infeasibility_is_distinguished_from_execution_errors(language: str, code: str, extra: str) -> None:
    result = solve(code.replace("    return m", "    " + extra + "\n    return m"), language)
    assert result.executed and result.objective is None and not result.variables, result.error
    assert result.status == ("locally_infeasible" if language == "casadi" else "infeasible")


def test_native_scip_solves_nonlinear_constraints() -> None:
    code = '''from pyscipopt import Model
def build_model(data):
    m = Model()
    x = m.addVar(name="x", lb=0, ub=3)
    m.addCons(x*x<=2)
    m.setObjective(x, "maximize")
    return m
'''
    result = solve(code, "pyscipopt")
    assert result.status == "optimal" and result.objective == pytest.approx(2**0.5, abs=1e-6), result.error


def test_ipopt_reports_local_optimality_and_all_components() -> None:
    result = solve(IPOPT_CODE, "casadi")
    assert result.status == "locally_optimal" and result.objective == pytest.approx(0, abs=1e-6), result.error
    assert result.variables == pytest.approx({"opti0_x_1[0]": 1, "opti0_x_1[1]": 1}, abs=1e-5)


def test_ipopt_does_not_report_an_unfinished_iterate_as_a_solution() -> None:
    result = asyncio.run(Sandbox("local").solve(IPOPT_CODE, {}, "casadi", 1e-10))
    assert result.status == "time_limit" and not result.has_solution and not result.variables, result.error


def test_scs_handles_semidefinite_constraints_and_osqp_rejects_them() -> None:
    code = '''import cvxpy as cp
import numpy as np
def build_model(data):
    x = cp.Variable((2,2), symmetric=True, name="x")
    return cp.Problem(cp.Minimize(cp.trace(x)), [x >> np.eye(2)])
'''
    result = solve(code, "cvxpy_scs")
    assert result.status == "optimal" and result.objective == pytest.approx(2, abs=1e-4), result.error
    assert result.variables == pytest.approx({"x[0,0]": 1, "x[0,1]": 0, "x[1,0]": 0, "x[1,1]": 1}, abs=1e-4)
    rejected = solve(code, "cvxpy_osqp")
    assert not rejected.executed and "[solve]" in rejected.error


@pytest.mark.parametrize("language", ["cvxpy_osqp", "cvxpy_scs"])
def test_cvxpy_solver_variants(language: str) -> None:
    result = solve(CVXPY_CODE, language)
    assert result.status == "optimal" and result.objective == pytest.approx(0.5, abs=1e-5), result.error
    assert result.variables == pytest.approx({"x[0]": 0.5, "x[1]": 1.5}, abs=1e-5)
    prompt = CodeTarget(language).prompt
    assert "Clarabel" not in prompt and "no integer" in prompt


def test_mosek_reports_missing_license_without_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOSEKLM_LICENSE_FILE", str(tmp_path / "absent.lic"))
    result = solve(CVXPY_CODE, "cvxpy_mosek")
    assert not result.executed and result.objective is None
    assert "license" in result.error.lower()


@pytest.mark.skipif(not os.environ.get("LLM4OM_TEST_MOSEK"), reason="set LLM4OM_TEST_MOSEK=1 with a valid MOSEK license")
def test_licensed_mosek_solves_convex_problem() -> None:
    result = solve(CVXPY_CODE, "cvxpy_mosek")
    assert result.status == "optimal" and result.objective == pytest.approx(0.5, abs=1e-5), result.error


def test_license_mounts_are_readonly_and_only_include_license_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    gurobi, mosek = tmp_path / "gurobi.lic", tmp_path / "mosek.lic"
    for path in (gurobi, mosek, tmp_path / "private.txt"):
        path.write_text("synthetic")
    monkeypatch.setenv("GRB_LICENSE_FILE", str(gurobi))
    monkeypatch.setenv("MOSEKLM_LICENSE_FILE", str(mosek))
    command = Sandbox()._command("test")
    mounts = [command[i + 1] for i, arg in enumerate(command) if arg == "-v"]
    assert len(mounts) == 2 and all(mount.endswith(":ro") for mount in mounts)
    assert not any("private" in mount or mount.startswith(str(tmp_path) + ":") for mount in mounts)
    result = asyncio.run(Sandbox("local").run_script("import os\nassert os.environ['GRB_LICENSE_FILE']\n"
                                                   "assert os.environ['MOSEKLM_LICENSE_FILE']\n", 5))
    assert result.executed


@pytest.mark.parametrize("kind", ["local", pytest.param("docker", marks=[pytest.mark.docker,
    pytest.mark.skipif(not os.environ.get("LLM4OM_TEST_DOCKER"), reason="set LLM4OM_TEST_DOCKER=1")])])
@pytest.mark.parametrize("bounds,valid", [((0, 1), False), ((5, 10), True)])
def test_limited_cvxpy_iterate_must_satisfy_the_original_constraints(kind, bounds, valid):
    low, high = bounds
    code = f"""import cvxpy as cp
def build_model(data):
    x = cp.Variable(name="x")
    return cp.Problem(cp.Minimize(cp.square(x - 6)), [x >= {low}, x <= {high}])
"""
    # Stop Clarabel on its first iterate, without relying on machine speed or a large test problem.
    result = asyncio.run(Sandbox(kind).solve(code, {}, "cvxpy", 1e-9, solver="CLARABEL"))
    assert result.status == "time_limit" and result.error is None, result
    if valid:
        assert low <= result.variables["x"] <= high
        assert result.objective == pytest.approx((result.variables["x"] - 6) ** 2)
    else:
        assert result.objective is None and result.variables == {}
