"""Each public modeling interface must build, execute and expose a numerical solution."""

import asyncio
import os
import re

import pytest

from llm4om.languages import LANGUAGES, CodeTarget
from llm4om.sandbox import Sandbox
from tests.modeling_examples import REFERENCES
from tests.test_sandbox import ORTOOLS_CODE


def test_nine_libraries_keep_api_choice_in_the_code() -> None:
    assert set(LANGUAGES) == {'pyomo', 'gurobipy', 'ortools', 'cpmpy', 'pulp', 'cvxpy', 'pyscipopt', 'casadi', 'coptpy'}
    assert all(not hasattr(item, 'interfaces') for item in LANGUAGES.values())
    old = CodeTarget('cvxpy_osqp')
    assert (old.language, old.solver) == ('cvxpy', 'OSQP')
    assert CodeTarget('pywraplp').language == 'ortools'
    assert CodeTarget('ortools').solver == 'AUTO'
    assert 'CpModel' in CodeTarget('ortools', 'CP_SAT').prompt
    with pytest.raises(ValueError, match='identifier'):
        CodeTarget('pyomo', solver='/tmp/executable')


@pytest.mark.parametrize('key,objective', [
    ('pyomo.kernel', 2), ('gurobipy.matrix', 13), ('ortools.mathopt', 13), ('ortools.cp_sat', 13),
    ('ortools.model_builder', 12), ('ortools.routing', 15), ('ortools.constraint', None),
    ('ortools.max_flow', 3), ('ortools.min_cost_flow', 6), ('ortools.assignment', 8), ('ortools.knapsack', 22),
    ('cpmpy.solver', 13), ('pulp.column', 6), ('cvxpy.dgp', 1), ('cvxpy.dqcp', 0.5), ('pyscipopt.matrix', 13),
    ('casadi.opti_conic', 2), ('casadi.nlpsol', 0), ('casadi.qpsol', 2), ('casadi.conic', 2), ('coptpy.matrix', 13),
])
@pytest.mark.parametrize('kind', ['local', pytest.param('docker', marks=[pytest.mark.docker,
    pytest.mark.skipif(not os.environ.get('LLM4OM_TEST_DOCKER'), reason='set LLM4OM_TEST_DOCKER=1')])])
def test_official_modeling_interfaces(key: str, objective: float | None, kind: str) -> None:
    library, interface = key.split('.')
    target = CodeTarget(library)
    backend = {'casadi.opti_conic': 'qrqp', 'casadi.qpsol': 'qrqp', 'casadi.conic': 'qrqp'}.get(key, LANGUAGES[library].solver)
    # The first paragraph is the executable example; subsequent paragraphs describe its contract.
    code = re.split(r'\n(?=[A-Z][A-Za-z]+(?: |/))', REFERENCES[key], maxsplit=1)[0].replace('{solver}', backend)
    if key == 'casadi.opti_conic':
        code = code.replace('return m', 'return {"model": m, "solver": "qrqp"}')
    elif key in ('casadi.qpsol', 'casadi.conic'):
        code = code.replace('return {', 'return {"solver": "qrqp", ')
    compile(code, 'example.py', 'exec')
    result = asyncio.run(Sandbox(kind).solve(code, {}, library, 5, solver=target.solver))
    assert result.executed and result.has_solution, result.error or result.feedback()
    assert result.objective is None if objective is None else result.objective == pytest.approx(objective, abs=1e-3)
    assert result.solver
    if key == 'ortools.routing':
        assert result.status == 'feasible'  # a short heuristic route is not a proof of optimality


@pytest.mark.parametrize('library,interface,backend', [('pyomo','algebraic','missing_solver'),
    ('cvxpy','dcp','MISSING_SOLVER'), ('pulp','row','MISSING_SOLVER'), ('gurobipy','model','highs')])
def test_unavailable_or_wrong_backends_are_not_replaced(library: str, interface: str, backend: str) -> None:
    code = 'def build_model(data):\n    return object()\n'
    result = asyncio.run(Sandbox('local').solve(code, {}, library, 5, solver=backend))
    assert not result.executed and result.solver == backend and result.error


@pytest.mark.parametrize('interface,code', [('linear', ORTOOLS_CODE), ('model_builder',
    'from ortools.linear_solver.python import model_builder\n'
    'def build_model(data):\n'
    '    m=model_builder.ModelBuilder()\n'
    '    x=m.new_int_var(0,10,"x")\n'
    '    m.add(2*x<=3)\n'
    '    m.maximize(x)\n'
    '    return m\n')])
def test_lp_backend_cannot_silently_relax_an_integer_model(interface: str, code: str) -> None:
    result = asyncio.run(Sandbox('local').solve(code, {}, 'ortools', 5, solver='GLOP'))
    assert not result.executed and result.objective is None and not result.variables
    assert 'refusing to relax' in result.error


def test_auto_preserves_the_backend_chosen_in_native_code() -> None:
    code = '''from ortools.linear_solver import pywraplp
def build_model(data):
    m=pywraplp.Solver.CreateSolver('GLOP')
    x=m.NumVar(1,4,'x')
    m.Minimize(x)
    return m
'''
    result = asyncio.run(Sandbox('local').solve(code, {}, 'ortools', 5))
    assert result.status == 'optimal' and result.objective == 1
    assert result.solver == 'GLOP'
