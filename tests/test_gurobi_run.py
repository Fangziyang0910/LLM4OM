"""Gurobi paths through shared CLI/SDK admission and isolated execution."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import yaml
from llm4om import run_problem

ROOT = Path(__file__).resolve().parents[1]


class GurobiRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        shutil.copytree(ROOT / 'examples/specs', self.inputs)
        self.config = yaml.safe_load((self.inputs / 'run.yaml').read_text())
        self.config['solver']['plugin_id'] = 'llm4om.solvers.gurobi'

    def run_case(self, offline=False):
        path = self.inputs / 'gurobi.yaml'
        path.write_text(yaml.safe_dump(self.config))
        result = run_problem(self.inputs / 'problem.json', path, offline=offline, output_root=self.root / 'runs')
        bundle = json.loads((result.bundle_path / 'bundle.json').read_text())
        return result.bundle_path, bundle

    def test_grounded_pyomo_gurobi_real_container(self):
        path, bundle = self.run_case()
        self.assertEqual(bundle['status'], 'completed', bundle.get('error'))
        solve = json.loads((path / 'checks/001/solve-result.json').read_text())
        solution = json.loads((path / 'checks/001/solution.json').read_text())
        self.assertEqual((solve['termination'], solve['objective_value'], solution['variables']),
                         ('optimal', 13, {'qty_A': 3, 'qty_B': 2}))
        self.assertEqual(solve['evidence_origin'], 'trusted_container_worker')

    def test_native_highs_and_noncontainer_reject_before_generation(self):
        self.config['method']['config']['output_mode'] = 'native_gurobipy'
        self.config['model_backend']['plugin_id'] = 'llm4om.model_backends.gurobipy'
        for solver, executor, offline in (('highs', 'container', False), ('gurobi', 'trusted_local', False),
                                          ('gurobi', 'container', True)):
            self.config['solver']['plugin_id'] = 'llm4om.solvers.' + solver
            self.config['executor'] = ({'plugin_id': 'llm4om.executors.trusted_local', 'config': {}}
                                       if executor == 'trusted_local' else yaml.safe_load((self.inputs / 'run.yaml').read_text())['executor'])
            path, bundle = self.run_case(offline)
            self.assertEqual(bundle['error']['code'], 'capability_mismatch')
            ledger = json.loads((path / 'budget-ledger.json').read_text())
            self.assertEqual((ledger['checks'], ledger['external_llm_requests'], ledger['solver_calls']), (0, 0, 0))

    def save_config(self):
        path = self.inputs / 'gurobi.yaml'
        path.write_text(yaml.safe_dump(self.config))
        return path

    def serve_candidate(self, mode, source):
        import test_factory_run as factory_tests
        self.config['method']['config']['output_mode'] = mode
        if mode == 'native_gurobipy':
            self.config['model_backend']['plugin_id'] = 'llm4om.model_backends.gurobipy'
        factory_tests.FactoryRunTests.start_provider(self, source)
        self.reply[mode] = self.reply.pop('python_factory')

    def run_cli(self):
        import test_factory_run as factory_tests
        return factory_tests.FactoryRunTests.run_cli(self)

    def test_parameterized_pyomo_gurobi_rebinds_data(self):
        self.serve_candidate('python_factory', (ROOT / 'examples/factories/production.py').read_text())
        path, bundle = self.run_cli()
        self.assertEqual(bundle['status'], 'completed', bundle.get('error'))
        result = json.loads((path / 'checks/001/solve-result.json').read_text())
        self.assertEqual(result['objective_value'], 13)
        # New public revision, same source template: resource capacity now allows A=2, B=2.
        raw = (self.inputs / 'data/capacities.csv').read_bytes().replace(b'8', b'6')
        (self.inputs / 'data/capacities.csv').write_bytes(raw)
        problem = json.loads((self.inputs / 'problem.json').read_text())
        import hashlib
        problem['revision'] = 's06-new-data'
        for ref in problem['data_refs']:
            if ref['data_id'] == 'capacities':
                ref['sha256'] = hashlib.sha256(raw).hexdigest()
        (self.inputs / 'problem.json').write_text(json.dumps(problem))
        path, bundle = self.run_cli()
        self.assertEqual(bundle['status'], 'completed', bundle.get('error'))
        self.assertEqual(json.loads((path / 'checks/001/solve-result.json').read_text())['objective_value'], 10)
        self.assertEqual((path / 'checks/001/model.py').read_text(), self.source)

    def test_native_gurobi_retains_source_and_uses_independent_sdk(self):
        source = (ROOT / 'examples/factories/production_gurobi.py').read_text()
        source += '\nimport llm4om.gurobi as solver\nsolver.solve_native = lambda *args, **kwargs: {"objective_value":999999}\n'
        source += '\ngp.Model.optimize = lambda *args, **kwargs: None\n'
        self.serve_candidate('native_gurobipy', source)
        path, bundle = self.run_cli()
        self.assertEqual(bundle['status'], 'completed', bundle.get('error'))
        result = json.loads((path / 'checks/001/solve-result.json').read_text())
        self.assertEqual((result['objective_value'], result['raw_status'], result['best_bound']), (13, '2', 13))
        self.assertEqual((path / 'checks/001/model.py').read_text(), source)
        self.assertTrue((path / 'checks/001/native-model.mps').is_file())
        code = json.loads((path / 'checks/001/code-artifact.json').read_text())
        self.assertEqual((code['representation_kind'], code['provenance']['origin']), ('native_code', 'method_generated'))
        formulation = json.loads((path / 'checks/001/formulation.json').read_text())
        self.assertIsNone(formulation['structured_ir_ref'])
        view = json.loads((path / 'checks/001/factory-instance.json').read_text())
        self.assertEqual(view['provenance']['origin'], 'native_exported_instance')
        self.assertEqual(json.loads((path / 'checks/001/solution.json').read_text())['variables'], {'qty_A': 3, 'qty_B': 2})

    def test_native_quadratic_mps_cannot_bypass_the_trusted_collector(self):
        source = (ROOT / 'examples/factories/production_gurobi.py').read_text()
        source = source.replace('    return ModelHandle', '    model.setObjective(qty["A"] ** 2)\n    model.update()\n    return ModelHandle')
        # A hostile child bypasses its own checker; the collector must inspect fresh SDK objects.
        source += '\nimport llm4om.gurobi as solver\nsolver.validate_native = lambda *args: None\n'
        self.serve_candidate('native_gurobipy', source)
        path, bundle = self.run_cli()
        self.assertEqual(bundle['error']['code'], 'unsupported_native_structure')
        self.assertIsNone(bundle['solve_result_ref'])
        self.assertEqual((path / 'checks/001/model.py').read_text(), source)

    def test_native_stdout_and_construction_limits_cannot_create_solver_results(self):
        source = (ROOT / 'examples/factories/production_gurobi.py').read_text()
        self.serve_candidate('native_gurobipy', source)
        for changed, code, wall in (
            (source + '\nimport sys\nsys.__stdout__.write("{\\\"result\\\":{\\\"objective_value\\\":999999}}\\n")\n', 'invalid_factory_export', 30),
            (source + '\nraise ValueError("native fixture failed")\n', 'factory_exception', 30),
            (source + '\nwhile True: pass\n', 'execution_timeout', 1.5),
            (source + '\nprint("X"*200000)\n', 'execution_output_limit', 30),
        ):
            with self.subTest(code=code):
                self.reply['native_gurobipy'] = changed
                self.config['executor']['config']['wall_time_s'] = wall
                self.config['executor']['config']['output_limit_bytes'] = 65536
                path, bundle = self.run_cli()
                self.assertEqual(bundle['error']['code'], code)
                self.assertIsNone(bundle['solve_result_ref'])
                self.assertEqual((path / 'checks/001/model.py').read_text(), changed)
