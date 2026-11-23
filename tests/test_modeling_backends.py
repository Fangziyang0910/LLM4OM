"""Real backend dispatch through the libraries' native adapters, including optional SDKs."""

import asyncio
import os

import pytest

from llm4om.sandbox import Sandbox

LP = {
    'pyomo': '''import pyomo.environ as pyo
def build_model(data):
    m=pyo.ConcreteModel()
    m.x=pyo.Var(bounds=(1,4))
    m.obj=pyo.Objective(expr=m.x)
    return m
''',
    'cvxpy': '''import cvxpy as cp
def build_model(data):
    x=cp.Variable(name='x')
    return cp.Problem(cp.Minimize(x),[x>=1,x<=4])
''',
}
CASE_BACKENDS = {
    'pyomo': ['highs', 'appsi_highs', 'cbc', 'glpk', 'gurobi_direct', 'gurobi_persistent', 'gurobi_direct_v2',
              'gurobi_persistent_v2', 'cplex_direct', 'cplex_persistent', 'appsi_cplex', 'scip_direct', 'scip_persistent',
              'xpress_direct', 'xpress_persistent'],
    'cvxpy': ['CLARABEL', 'OSQP', 'SCS', 'SCIPY', 'HIGHS', 'SCIP', 'GUROBI', 'CPLEX', 'XPRESS', 'CVXOPT', 'GLPK',
              'GLPK_MI', 'CBC', 'ECOS', 'ECOS_BB', 'DAQP', 'PIQP', 'PROXQP', 'QOCO', 'QPALM', 'GLOP', 'PDLP'],
}


@pytest.fixture(scope='module', params=['local', pytest.param('docker', marks=[pytest.mark.docker,
    pytest.mark.skipif(not os.environ.get('LLM4OM_TEST_DOCKER'), reason='set LLM4OM_TEST_DOCKER=1')])])
def sandbox(request):
    return Sandbox(request.param)


@pytest.fixture(scope='module')
def catalog(sandbox):
    return asyncio.run(sandbox.catalog())['libraries']


@pytest.mark.parametrize('library,backend', [(library, backend) for library, names in CASE_BACKENDS.items() for backend in names])
def test_native_backend(library: str, backend: str, catalog, sandbox) -> None:
    installed = next((item for item in catalog[library] if item['id'] == backend), None)
    if not installed or not installed['available']:
        pytest.skip('Native plugin reports unavailable in this environment')
    result = asyncio.run(sandbox.solve(LP[library], {}, library, 10, solver=backend))
    assert result.executed and result.has_solution, result.error or result.feedback()
    assert result.objective == pytest.approx(1, abs=1e-3)


@pytest.mark.docker
@pytest.mark.skipif(not os.environ.get('LLM4OM_TEST_DOCKER'), reason='set LLM4OM_TEST_DOCKER=1')
def test_docker_catalog_uses_the_actual_installed_runtime() -> None:
    libraries = asyncio.run(Sandbox().catalog())['libraries']
    assert len(libraries) == 5
    for name in ('GLOP', 'PDLP'):
        assert next(row for row in libraries['cvxpy'] if row['id'] == name)['available']


@pytest.mark.parametrize('backend', ['GLOP', 'CLP', 'PDLP', 'SCIP', 'CBC', 'SAT', 'BOP', 'GSCIP', 'HIGHS', 'CP_SAT',
    'KNAPSACK_64ITEMS_SOLVER', 'KNAPSACK_BRUTE_FORCE_SOLVER', 'KNAPSACK_DIVIDE_AND_CONQUER_SOLVER',
    'KNAPSACK_DYNAMIC_PROGRAMMING_SOLVER', 'KNAPSACK_MULTIDIMENSION_BRANCH_AND_BOUND_SOLVER',
    'KNAPSACK_MULTIDIMENSION_CBC_MIP_SOLVER', 'KNAPSACK_MULTIDIMENSION_CP_SAT_SOLVER', 'KNAPSACK_MULTIDIMENSION_SCIP_MIP_SOLVER'])
def test_ortools_native_backends(sandbox, catalog, backend) -> None:
    if not next(row for row in catalog['ortools'] if row['id'] == backend)['available']:
        pytest.skip('Native backend is unavailable')
    if backend.startswith('KNAPSACK_'):
        code = 'def build_model(data):\n    return {"values":[6,10,12],"weights":[[1,2,3]],"capacities":[5]}\n'
        expected = 22
    elif backend in ('GSCIP', 'HIGHS'):
        code = '''from ortools.math_opt.python import mathopt
def build_model(data):
    m=mathopt.Model()
    x=m.add_variable(lb=1,ub=4,name='x')
    m.minimize(x)
    return m
'''
        expected = 1
    elif backend == 'CP_SAT':
        code = '''from ortools.sat.python import cp_model
def build_model(data):
    m=cp_model.CpModel()
    x=m.new_int_var(1,4,'x')
    m.minimize(x)
    return m
'''
        expected = 1
    else:
        code = '''from ortools.linear_solver import pywraplp
def build_model(data):
    m=pywraplp.Solver.CreateSolver('SCIP')
    x=m.BoolVar('x')
    m.Add(x>=1)
    m.Minimize(x)
    return m
'''
        if backend in ('GLOP', 'CLP', 'PDLP'):
            code = code.replace("m.BoolVar('x')", "m.NumVar(0,1,'x')")
        expected = 1
    result = asyncio.run(sandbox.solve(code, {}, 'ortools', 5, solver=backend))
    assert result.has_solution and result.objective == pytest.approx(expected), result.error or result.feedback()
    assert result.solver == backend
