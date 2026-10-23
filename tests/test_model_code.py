"""The shared assembly must preserve variable domains and objective values in every native library."""

import asyncio

import pytest

from llm4om.languages import LANGUAGES, CodeTarget
from llm4om.methods.autoformulation.codegen import model_code
from llm4om.model_code import ModelCode
from llm4om.sandbox import Sandbox


@pytest.mark.parametrize('library', list(LANGUAGES))
def test_native_fragment_assembly_preserves_a_mixed_integer_problem(library: str) -> None:
    target = CodeTarget(library)
    code = ModelCode(target)
    source = code.assemble([code.variables('x', [], 'INTEGER', '0', '8'), code.variables('y', [], 'INTEGER', '0', '8'),
                            code.constraint('2*x+y<=8', repr('cutting')), code.constraint('x+2*y<=8', repr('machining')),
                            code.objective('3*x+2*y', 'max')])
    result = asyncio.run(Sandbox('local').solve(source, {}, library, 10))
    assert result.executed and result.has_solution, result.error or result.feedback()
    assert result.objective == pytest.approx(13)
    assert all(abs(value-round(value)) < 1e-6 for value in result.variables.values())


@pytest.mark.parametrize('library,backend', [('ortools','CP_SAT'), ('ortools','HIGHS'), ('ortools','GSCIP')])
def test_backend_specific_native_fragments(library: str, backend: str) -> None:
    code = ModelCode(CodeTarget(library, backend))
    source = code.assemble([code.variables('x', [], 'INTEGER', '0', '8'), code.constraint('2*x<=3'), code.objective('x', 'max')])
    result = asyncio.run(Sandbox('local').solve(source, {}, library, 10, solver=backend))
    assert result.executed and result.objective == 1, result.error or result.feedback()


@pytest.mark.parametrize('library,backend', [('cpmpy','AUTO'), ('ortools','CP_SAT')])
@pytest.mark.parametrize('kind,ub,message', [('CONTINUOUS','8','continuous'), ('INTEGER','None','finite')])
def test_incompatible_domains_are_rejected_instead_of_changed(library: str, backend: str, kind: str, ub: str, message: str) -> None:
    code = ModelCode(CodeTarget(library, backend))
    source = code.assemble([code.variables('x', [], kind, '0', ub), code.objective('x', 'max')])
    result = asyncio.run(Sandbox('local').solve(source, {}, library, 5, solver=backend))
    assert not result.executed and message.lower() in result.error.lower()


@pytest.mark.parametrize('library', list(LANGUAGES))
def test_indexed_variables_keep_negative_bounds_and_fixed_binary_values(library: str) -> None:
    code = ModelCode(CodeTarget(library))
    source = code.assemble([code.variables('x', ['range(2)', 'range(2)'], 'INTEGER', '-2', '3'),
                           code.variables('active', [], 'BINARY', '1', '1'),
                           code.constraint('quicksum(x.values()) >= -7'),
                           code.objective('quicksum(x.values()) + 2*active', 'min')])
    result = asyncio.run(Sandbox('local').solve(source, {}, library, 10))
    assert result.has_solution and result.objective == pytest.approx(-5), result.error or result.feedback()


@pytest.mark.parametrize('library', list(LANGUAGES))
def test_autoformulation_keeps_parameter_bounds_for_each_variable_index(library: str) -> None:
    form = {'parameters': {'products': ['A', 'B'], 'limit': {'A': 1, 'B': 3}},
            'decision_variables': {'x': {'type': 'INTEGER', 'description': 'production',
                'iteration_space': '[product for product in products]', 'lower_bound': 0, 'upper_bound': 'limit[product]'}},
            'objective': {'max': 'sum(x.values())'}, 'equality_constraints': {None: None},
            'inequality_constraints': {'total': 'sum(x.values()) <= 8'}}
    source = model_code(CodeTarget(library), form)
    result = asyncio.run(Sandbox('local').solve(source, {}, library, 10))
    assert result.has_solution and result.objective == pytest.approx(4), result.error or result.feedback()


def test_unknown_variable_types_do_not_silently_become_continuous() -> None:
    code = ModelCode(CodeTarget('pyomo'))
    source = code.assemble([code.variables('x', [], 'unknown'), code.objective('x', 'max')])
    result = asyncio.run(Sandbox('local').solve(source, {}, 'pyomo', 5))
    assert not result.executed and 'Unsupported variable type' in result.error
