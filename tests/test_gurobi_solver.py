"""Real Gurobi evidence at the public Solver and Backend seams."""
import unittest
from llm4om.linear import compile_ir
from test_linear_solver import model, row


class GurobiSolverTests(unittest.TestCase):
    def test_pyomo_lp_constants_and_closed_bounds(self):
        from llm4om.gurobi import solve_gurobi
        ir = model(lower=1.5, upper=2.5)
        ir['objective']['sense'] = 'min'
        ir['objective']['expression'] = {'constant': 2, 'terms': [{'variable_id': 'x', 'coefficient': 2}]}
        result = solve_gurobi(compile_ir(ir), {})
        self.assertEqual((result['termination'], result['variables'], result['objective_value']),
                         ('optimal', {'x': 1.5}, 5))
        self.assertEqual(result['evidence_origin'], 'trusted_gurobi_api')

    def test_solver_rejects_options_before_import_or_model_construction(self):
        from llm4om.gurobi import solve_gurobi
        from llm4om.contracts import RunError
        code = compile_ir(model(upper=2))
        for options in ({'time_limit_s': float('nan')}, {'time_limit_s': True},
                        {'time_limit_s': -1}, {'time_limit_s': 10**400}, {'Threads': 2}):
            with self.subTest(options=options), self.assertRaises(RunError) as error:
                solve_gurobi(code, options)
            self.assertEqual(error.exception.code, 'invalid_solver_options')

    def test_milp_and_real_terminal_statuses(self):
        from llm4om.gurobi import solve_gurobi
        ir = model('integer', lower=1.5, upper=2.5)
        ir['objective']['expression'] = {'constant': 2, 'terms': [{'variable_id': 'x', 'coefficient': 2}]}
        result = solve_gurobi(compile_ir(ir), {'time_limit_s': 5})
        self.assertEqual((result['variables'], result['objective_value'], result['best_bound'], result['reported_gap']),
                         ({'x': 2}, 6, 6, 0))
        ir = model()
        ir['constraints'] = [row('ge', 2), {**row('le', 1), 'id': 'other'}]
        for case, termination in ((ir, 'infeasible'), (model(), 'unbounded'), (model('binary'), 'time_limit')):
            result = solve_gurobi(compile_ir(case), {'time_limit_s': 0} if termination == 'time_limit' else {})
            self.assertEqual(result['termination'], termination)
            self.assertFalse(result['has_primal_solution'])
            self.assertIsNone(result['objective_value'])
            self.assertIsNone(result['variables'])

    def test_native_transport_rejects_unsupported_actual_sdk_structure(self):
        import gurobipy as gp
        from llm4om.gurobi import environment
        from llm4om.backends import ModelHandle, GurobiFactoryBackend
        from llm4om.contracts import RunError
        with environment() as env, gp.Model(env=env) as native:
            x = native.addVar(lb=0, ub=2, name='x')
            native.setObjective(x * x)
            with self.assertRaises(RunError) as error:
                GurobiFactoryBackend().export(ModelHandle(native, {'x': x}))
            self.assertEqual(error.exception.code, 'unsupported_native_structure')

    def test_genuine_time_limit_with_incumbent_on_bounded_hard_integer_fixture(self):
        import random
        import gurobipy as gp
        from llm4om.gurobi import environment, solve_native
        from llm4om.backends import ModelHandle
        rng = random.Random(606)
        with environment() as env, gp.Model(env=env) as native:
            variables = native.addVars(300, vtype=gp.GRB.BINARY, name='x')
            for var in variables.values():
                var.Start = 0  # Feasible SDK MIP start; actual optimizer must accept it.
            native.setObjective(gp.quicksum(rng.randint(1, 100) * variables[i] for i in range(300)), gp.GRB.MAXIMIZE)
            for _ in range(20):
                coefficients = [rng.randint(1, 100) for _ in range(300)]
                native.addConstr(gp.quicksum(coefficients[i] * variables[i] for i in range(300)) <= sum(coefficients) * .4)
            result = solve_native(ModelHandle(native, {f'x_{i}': variables[i] for i in range(300)}), {'time_limit_s': .05})
            self.assertEqual((result['termination'], result['raw_status'], result['has_primal_solution']), ('time_limit', '9', True))
            self.assertIsNotNone(result['objective_value'])
            self.assertIsNotNone(result['best_bound'])
            self.assertIsNotNone(result['reported_gap'])
            self.assertEqual(len(result['variables']), 300)

    def test_native_mps_roundtrip_keeps_lp_direction_constant_range_and_all_variables(self):
        import gurobipy as gp
        from llm4om.gurobi import environment, read_native, native_instance, solve_native
        from llm4om.backends import ModelHandle, GurobiFactoryBackend
        with environment() as env, gp.Model(env=env) as native:
            x = native.addVar(lb=-2, ub=4, name='x')
            native.addRange(x + 3, 4.5, 5.5, name='range')
            native.setObjective(2*x + 2, gp.GRB.MINIMIZE)
            native.update()
            mapping = {var.VarName: var for var in native.getVars()}
            exported = GurobiFactoryBackend().export(ModelHandle(native, mapping))
            with read_native(exported) as handle:
                view = native_instance(handle)
                result = solve_native(handle, {})
                self.assertEqual((result['objective_sense'], result['objective_value'], result['variables']['x']), ('min', 5, 1.5))
                self.assertEqual(view['objective']['expression']['constant'], 2)
                self.assertEqual(len(view['variables']), 2)  # Gurobi represents a range with a mapped slack variable.
                self.assertEqual(set(result['variables']), set(mapping))

    def test_native_structure_validation_covers_every_excluded_sdk_family(self):
        import gurobipy as gp
        from llm4om.gurobi import environment
        from llm4om.backends import ModelHandle, GurobiFactoryBackend
        from llm4om.contracts import RunError
        for kind in ('quadratic_row', 'general', 'nonlinear', 'multiobjective', 'scenario', 'sos', 'pwl', 'semicontinuous'):
            with self.subTest(kind=kind), environment() as env, gp.Model(env=env) as native:
                x = native.addVar(lb=0, ub=2, name='x')
                y = native.addVar(lb=0, ub=4, name='y')
                native.setObjective(x)
                if kind == 'quadratic_row':
                    native.addQConstr(x*x <= y)
                elif kind == 'general':
                    native.addGenConstrAbs(y, x)
                elif kind == 'nonlinear':
                    native.addGenConstrNL(y, gp.nlfunc.sin(x))
                elif kind == 'multiobjective':
                    native.setObjectiveN(y, 1)
                elif kind == 'scenario':
                    native.NumScenarios = 1
                elif kind == 'sos':
                    native.addSOS(gp.GRB.SOS_TYPE1, [x, y])
                elif kind == 'pwl':
                    native.setPWLObj(x, [0, 1, 2], [0, 2, 1])
                else:
                    x.VType = gp.GRB.SEMICONT
                with self.assertRaises(RunError) as error:
                    GurobiFactoryBackend().export(ModelHandle(native, {'x': x, 'y': y}))
                self.assertEqual(error.exception.code, 'unsupported_native_structure')


class GurobiContractTests(unittest.TestCase):
    def test_native_backend_accepts_readonly_decision_mapping(self):
        from types import MappingProxyType
        import gurobipy as gp
        from llm4om.backends import ModelHandle, GurobiFactoryBackend
        from llm4om.gurobi import environment
        with environment() as env, gp.Model(env=env) as native:
            x = native.addVar(lb=0, ub=1, name='x')
            native.setObjective(x)
            exported = GurobiFactoryBackend().export(ModelHandle(native, MappingProxyType({'decision': x})))
            self.assertEqual(exported['decision_map'], {'decision': 'x'})

    def test_finite_bounds_cannot_be_silently_replaced_with_infinity(self):
        from llm4om.gurobi import solve_gurobi
        from llm4om.contracts import RunError
        for lower, upper in ((0, 1e20), (0, 1e30), (-1e20, None), (-1e30, None)):
            with self.subTest(lower=lower, upper=upper), self.assertRaises(RunError) as caught:
                solve_gurobi(compile_ir(model(lower=lower, upper=upper)), {})
            self.assertEqual(caught.exception.code, 'unsupported_numeric_range')

    def test_finite_row_rhs_cannot_be_silently_ignored(self):
        from llm4om.gurobi import solve_gurobi
        from llm4om.contracts import RunError
        for sense, rhs in (('le', 1e20), ('ge', -1e20)):
            case = model()
            case['constraints'] = [row(sense, rhs)]
            with self.subTest(sense=sense), self.assertRaises(RunError) as caught:
                solve_gurobi(compile_ir(case), {})
            self.assertEqual(caught.exception.code, 'unsupported_numeric_range')
