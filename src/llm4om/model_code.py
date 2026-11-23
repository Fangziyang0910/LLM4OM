"""Native Python fragments shared by methods that assemble models from parts."""

import re
import textwrap
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from llm4om.languages import CodeTarget


IMPORTS = {
    'pyomo': 'import pyomo.environ as pyo\nfrom pyomo.environ import quicksum',
    'ortools': 'from ortools.linear_solver import pywraplp\nquicksum = sum',
    'mathopt': 'from ortools.math_opt.python import mathopt\nquicksum = sum',
    'cp_sat': 'from ortools.sat.python import cp_model\nquicksum = sum',
    'cvxpy': 'import cvxpy as cp\nquicksum = sum',
    'pyscipopt': 'from pyscipopt import Model, quicksum',
    'casadi': 'import casadi as ca\nquicksum = sum',
}

VARIABLES = {
    'pyomo': '''variable = pyo.Var(domain={'CONTINUOUS': pyo.Reals, 'INTEGER': pyo.Integers, 'BINARY': pyo.Binary}[kind], bounds=(lb, ub))
{model}.add_component('var_' + name, variable)
return variable''',
    'ortools': '''factory = {model}.NumVar if kind == 'CONTINUOUS' else {model}.IntVar
return factory(-{model}.infinity() if lb is None else lb, {model}.infinity() if ub is None else ub, name)''',
    'mathopt': '''return {model}.add_variable(lb=-float('inf') if lb is None else lb, ub=float('inf') if ub is None else ub,
                             is_integer=kind != 'CONTINUOUS', name=name)''',
    'cp_sat': '''if kind == 'CONTINUOUS':
    raise ValueError('CP-SAT cannot represent continuous decision variables.')
if lb is None or ub is None or not (math.isfinite(lb) and math.isfinite(ub)):
    raise ValueError('CP-SAT requires finite integer bounds derived from the problem.')
if not (float(lb).is_integer() and float(ub).is_integer()):
    raise ValueError('CP-SAT requires integer bounds derived from the problem.')
return {model}.new_int_var(int(lb), int(ub), name)''',
    'cvxpy': '''variable = cp.Variable(name=name, integer=kind == 'INTEGER', boolean=kind == 'BINARY')
if lb is not None:
    {model}_constraints.append(variable >= lb)
if ub is not None:
    {model}_constraints.append(variable <= ub)
return variable''',
    'pyscipopt': '''return {model}.addVar(name=name, vtype={'CONTINUOUS': 'C', 'INTEGER': 'I', 'BINARY': 'B'}[kind], lb=lb, ub=ub)''',
    'casadi': '''variable = {model}.variable()
if kind != 'CONTINUOUS':
    {model}.set_domain(variable, 'integer')
    {model}_integers.append(variable)
if lb is not None:
    {model}.subject_to(variable >= lb)
if ub is not None:
    {model}.subject_to(variable <= ub)
return variable''',
}


@dataclass(frozen=True)
class ModelCode:
    target: 'CodeTarget'
    name: str = 'model'

    @property
    def api(self) -> str:
        if self.target.language == 'ortools':
            if self.target.solver == 'CP_SAT':
                return 'cp_sat'
            if self.target.solver in ('HIGHS', 'GSCIP', 'OSQP', 'ECOS', 'SCS'):
                return 'mathopt'
        return self.target.language

    @property
    def imports(self) -> str:
        return 'import csv\nimport io\nimport itertools\nimport json\nimport math\nimport numpy as np\n' + IMPORTS[self.api]

    @property
    def setup(self) -> str:
        model = self.name
        factory = {
            'pyomo': 'pyo.ConcreteModel()\n{model}.constraints = pyo.ConstraintList()',
            'ortools': 'pywraplp.Solver.CreateSolver("SCIP")',
            'mathopt': 'mathopt.Model()', 'cp_sat': 'cp_model.CpModel()',
            'pyscipopt': 'Model("optimization")', 'casadi': 'ca.Opti()',
        }
        if self.api == 'cvxpy':
            setup = f'{model}_constraints = []\n{model}_objective = cp.Minimize(0)'
        else:
            setup = f'{model} = ' + factory[self.api].replace('{model}', model)
        if self.api == 'casadi':
            setup += f'\n{model}_integers = []\n{model}_objective_sign = 1'
        native = VARIABLES[self.api].replace('{model}', model)
        # Component generation and deterministic emitters use the same native variable factory.
        helper = '''def _new_var(vtype, name, lb=0, ub=None):
    vtype = str(vtype).lower().rsplit('.', 1)[-1]
    if vtype in ('b', 'bool', 'boolean', 'binary'):
        kind = 'BINARY'
    elif vtype in ('i', 'int', 'integer', 'integers', 'nonnegativeintegers'):
        kind = 'INTEGER'
    elif vtype in ('c', 'float', 'real', 'reals', 'continuous', 'nonnegativereals'):
        kind = 'CONTINUOUS'
    else:
        raise ValueError('Unsupported variable type: ' + vtype)
    if kind == 'BINARY':
        lb = max(0, lb) if lb is not None else 0
        ub = min(1, ub) if ub is not None else 1
'''
        return setup + '\n\n' + helper + textwrap.indent(native, '    ') + '\n'

    def new_var(self, kind: str, name: str, lb: str = '0', ub: str = 'None') -> str:
        """An expression; names and bounds are Python source, evaluated only in the sandbox."""
        return f'_new_var({kind!r}, {name}, {lb}, {ub})'

    def variables(self, symbol: str, ranges: list[str], kind: str, lb: str = '0', ub: str = 'None',
                  *, indices: list[str] | None = None) -> str:
        if not ranges:
            return f'{symbol} = {self.new_var(kind, repr(symbol), lb, ub)}\n'
        if indices is None:
            referenced = set(re.findall(r'\b[A-Za-z_]\w*\b', ' '.join((*ranges, lb, ub))))
            defaults = ['i', 'j', 'k'][:len(ranges)] if len(ranges) <= 3 else [f'i{n}' for n in range(len(ranges))]
            indices = [f'_idx_{n}' if name in referenced else name for n, name in enumerate(defaults)]
        key = indices[0] if len(indices) == 1 else '(' + ', '.join(indices) + ')'
        label = "f'" + symbol + '[' + ','.join('{' + index + '}' for index in indices) + "]'"
        loops = ' '.join(f'for {index} in {space}' for index, space in zip(indices, ranges, strict=True))
        return f'{symbol} = {{{key}: {self.new_var(kind, label, lb, ub)} {loops}}}\n'

    def constraint(self, expression: str, name: str = "''") -> str:
        model = self.name
        templates = {'pyomo': '{model}.constraints.add({expr})',
                     'ortools': '{model}.Add({expr}, {name})', 'mathopt': '{model}.add_linear_constraint({expr}, name={name})',
                     'cp_sat': '{model}.add({expr}).with_name({name})', 'cvxpy': '{model}_constraints.append({expr})',
                     'pyscipopt': '{model}.addCons({expr}, name={name})', 'casadi': '{model}.subject_to({expr})'}
        return templates[self.api].format(model=model, expr=expression, name=name)

    def objective(self, expression: str, sense: str) -> str:
        normalized = sense.strip().lower()
        if normalized in ('max', 'maximize', 'maximization'):
            maximum = True
        elif normalized in ('min', 'minimize', 'minimization'):
            maximum = False
        else:
            raise ValueError(f'Unsupported objective sense: {sense!r}')
        model = self.name
        if self.api == 'pyomo':
            return f'{model}.objective = pyo.Objective(expr={expression}, sense=pyo.{"maximize" if maximum else "minimize"})'
        if self.api == 'cvxpy':
            return f'{model}_objective = cp.{"Maximize" if maximum else "Minimize"}({expression})'
        if self.api == 'casadi':
            return f'{model}_objective_sign = {"-1" if maximum else "1"}\n{model}.minimize({model}_objective_sign * ({expression}))'
        if self.api == 'pyscipopt':
            return f'{model}.setObjective({expression}, {"maximize" if maximum else "minimize"!r})'
        verb = ('Maximize' if maximum else 'Minimize') if self.api == 'ortools' else ('maximize' if maximum else 'minimize')
        return f'{model}.{verb}({expression})'

    @property
    def result(self) -> str:
        if self.api == 'cvxpy':
            return f'cp.Problem({self.name}_objective, {self.name}_constraints)'
        if self.api == 'casadi':
            solver = repr(self.target.solver) if self.target.solver != 'AUTO' else f'"bonmin" if {self.name}_integers else "ipopt"'
            return '{"model": ' + self.name + ', "solver": ' + solver + ', "objective_sign": ' + self.name + '_objective_sign}'
        return self.name

    def assemble(self, parts: list[str]) -> str:
        body = '\n\n'.join([self.setup, *parts, 'return ' + self.result])
        return self.imports + '\n\ndef build_model(data):\n' + textwrap.indent(body, '    ') + '\n'

    @property
    def variable_rules(self) -> str:
        return ('Use type strings CONTINUOUS, INTEGER or BINARY for variable metadata. '
                'Optional lower_bound and upper_bound fields are Python expressions of known parameters; '
                'default bounds are 0 and None. Preserve variable domains. '
                + ('Every nonbinary variable needs finite integer bounds derived from the problem. '
                   'Include separate lower_bound and upper_bound fields alongside type and shape/iteration_space; '
                   'bounds mentioned only in description text are not executable. For example: '
                   '{"type": "INTEGER", "lower_bound": "0", "upper_bound": "capacity"}. '
                   'Use actual problem parameters. Do not invent large bounds or discretize real decisions.'
                   if self.api == 'cp_sat' else 'State any bounds required by the problem.'))

    @property
    def prompt(self) -> str:
        return (f'Use {self.target.library} ({self.api}) Python fragments inside build_model(data).\n'
                f'These imports and setup already exist; do not repeat them:\n```python\n{self.imports}\n{self.setup}```\n'
                'Declare variables with _new_var("CONTINUOUS"/"INTEGER"/"BINARY", name, lb=0, ub=None). '
                'For indexed variables use dictionaries with scalar or tuple keys. Preserve the original variable domains. '
                f'{self.variable_rules}\n'
                f'Add constraints like:\n```python\n{self.constraint("x <= capacity", repr("capacity"))}\n```\n'
                f'Set a minimizing objective like:\n```python\n{self.objective("quicksum(cost[i]*x[i] for i in I)", "min")}\n```\n'
                f'For maximization use:\n```python\n{self.objective("profit", "max")}\n```\n'
                'Return only the requested fragments, not a complete build_model function. Do not solve, print or return; '
                f'the platform assembles the function and returns {self.result}.')
