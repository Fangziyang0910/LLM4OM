"""Public editing interfaces with actual solves and immutable parent evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

from llm4om import run_problem, export_edit, edit_run, resume_run
from llm4om.contracts import RunError


class AssistedEditTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        fixture = Path(__file__).resolve().parents[1] / 'examples/specs'
        shutil.copytree(fixture, self.root / 'input')
        config = yaml.safe_load((fixture / 'solve.yaml').read_text())
        config['budget'].update(max_checks=4, max_solver_calls=4)
        (self.root / 'input/run.json').write_text(json.dumps(config))
        self.parent = run_problem(self.root / 'input/problem.json', self.root / 'input/run.json', output_root=self.root / 'runs')
        self.assertEqual(self.parent.status, 'completed')
        self.before = {str(path.relative_to(self.parent.bundle_path)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in self.parent.bundle_path.rglob('*') if path.is_file() and path.name not in {'control.json', 'owner.json', 'owner.lock', 'cancel.json', 'cancel.lock'}}

    def write(self, document):
        path = self.root / 'edits.json'
        path.write_text(json.dumps(document))
        return path

    def objective(self, child):
        bundle = json.loads((child.bundle_path / 'bundle.json').read_text())
        self.assertEqual(child.status, 'completed', bundle['error'])
        self.assertTrue(bundle['assisted'])
        solve = json.loads((child.bundle_path / bundle['solve_result_ref']['relative_path']).read_text())
        lineage = json.loads((child.bundle_path / bundle['lineage_ref']['relative_path']).read_text())
        self.assertEqual(lineage['parent_run_id'], self.parent.run_id)
        self.assertEqual(lineage['operation'], 'assisted_revision')
        ledger = json.loads((child.bundle_path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['llm_attempts'], 1)
        self.assertEqual(ledger['solver_calls'], 2)
        self.assertEqual(ledger['checks'], 2)
        self.assertEqual(ledger['evidence_origin'], 'assisted')
        for relative, digest in self.before.items():
            self.assertEqual(hashlib.sha256((self.parent.bundle_path / relative).read_bytes()).hexdigest(), digest, relative)
        return solve['objective_value']

    def test_edit_ir_compiles_and_preserves_parent_and_usage(self):
        value = export_edit(self.parent.bundle_path, operation='formulation')
        value['reason'] = 'Bound each modeled product quantity by one.'
        for variable in value['structured_ir']['variables']:
            variable['upper_bound'] = 1
        value['formulation']['representation']['variables'][0]['upper_bound'] = 1
        child = edit_run(self.parent.bundle_path, self.write(value))
        self.assertEqual(self.objective(child), 5)
        continued = resume_run(child.bundle_path)
        self.assertEqual(continued.run_id, child.run_id)
        self.assertEqual(json.loads((child.bundle_path / 'budget-ledger.json').read_text())['solver_calls'], 2)

    def test_runs_saved_with_the_candidate_layout_are_read_only(self):
        value = export_edit(self.parent.bundle_path, operation='formulation')
        value['reason'] = 'Edit a run saved before ADR-0006.'
        checkpoint = self.parent.bundle_path / 'checkpoint.json'
        envelope = json.loads(checkpoint.read_text())
        ledger = envelope['payload']['state']['ledger']
        ledger['candidates'] = ledger.pop('checks')
        encode = lambda value: (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
        envelope['sha256'] = hashlib.sha256(encode(envelope['payload'])).hexdigest()
        raw = encode(envelope)
        checkpoint.write_bytes(raw)
        (self.parent.bundle_path / 'checkpoints' / (hashlib.sha256(raw).hexdigest() + '.json')).write_bytes(raw)
        with self.assertRaises(RunError) as raised:
            edit_run(self.parent.bundle_path, self.write(value))
        self.assertEqual(raised.exception.code, 'checkpoint_incompatible')

    def test_edit_compiled_python_runs_only_in_container_without_another_llm_call(self):
        value = export_edit(self.parent.bundle_path, operation='code')
        value['reason'] = 'Bound the two Python variables by one for a manual code experiment.'
        source = value['code']['source']
        self.assertIn('"upper_bound": null', source)
        value['code']['source'] = source.replace('"upper_bound": null', '"upper_bound": 1')
        child = edit_run(self.parent.bundle_path, self.write(value))
        self.assertEqual(self.objective(child), 5)
        bundle = json.loads((child.bundle_path / 'bundle.json').read_text())
        execution = json.loads((child.bundle_path / bundle['execution_result_ref']['relative_path']).read_text())
        self.assertEqual(execution['mode'], 'container')
        code = json.loads((child.bundle_path / json.loads((child.bundle_path / bundle['model_artifact_ref']['relative_path']).read_text())['code_ref']['relative_path']).read_text())
        self.assertEqual(code['provenance']['generation']['origin'], 'user_edited')

    def test_native_factory_and_script_edits_use_actual_gurobi_without_model_requests(self):
        problem = json.loads((self.root / 'input/problem.json').read_text())
        base = yaml.safe_load((self.root / 'input/gurobi.yaml').read_text())
        base['model_backend']['plugin_id'] = 'llm4om.model_backends.gurobipy'
        base['budget'].update(max_checks=3, max_solver_calls=8)
        base['llm'] = {'provider_plugin_id': 'llm4om.providers.mock', 'model': 'no-model-human-fixture',
                       'config': {'response_artifact': 'script-edits.json'}}
        representation = json.loads((self.root / 'input/formulation.json').read_text())
        body = """import gurobipy as gp
from gurobipy import GRB
m = gp.Model()
a = m.addVar(lb=0, vtype=GRB.INTEGER, name='x_A')
b = m.addVar(lb=0, vtype=GRB.INTEGER, name='x_B')
m.setObjective(3*a + 2*b, GRB.MAXIMIZE)
m.addConstr(2*a + b <= 8)
m.addConstr(a + 2*b <= 8)
"""
        for variant in ('native_code', 'native_script', 'native_script_formulation'):
            kind = 'native_script' if variant.startswith('native_script') else variant
            with self.subTest(kind=variant):
                if kind == 'native_code':
                    source = 'from llm4om.backends import ModelHandle\ndef build_model(data):\n' + ''.join('    ' + line + '\n' for line in body.splitlines()) + "    return ModelHandle(m, {'x_A': a, 'x_B': b})\n"
                    formulation = representation
                else:
                    source = body + 'm.optimize()\n'
                    formulation = None
                    if variant == 'native_script_formulation':
                        formulation = {'schema_version': '0.3.0', 'formulation_id': 'public-native-edit',
                            'problem_id': problem['problem_id'], 'problem_revision': problem['revision'],
                            'representation_kind': 'native_formulation', 'representation': {'schema': 'public-native-state/0.1.0',
                                'state': {'decisions': ['x_A', 'x_B']}}, 'data_bindings': [], 'provenance': {}, 'structured_ir_ref': None}
                document = {'schema_version': '0.1.0', 'operation': 'code', 'reason': 'Public native editing fixture.',
                    'budget': base['budget'], 'problem': problem, 'formulation': formulation, 'structured_ir': None,
                    'model_metadata': {'assumptions': [], 'requirement_traces': [], 'warnings': []},
                    'code': {'representation_kind': kind, 'source': source, 'data_json': {} if kind == 'native_script' else None}}
                (self.root / 'input/script-edits.json').write_text(json.dumps(document))
                config = deepcopy(base)
                config['method'] = {'plugin_id': 'llm4om.methods.assisted', 'config': {'code_kind': kind,
                    'formulation_kind': formulation['representation_kind'] if formulation else 'not_available', 'edits': document}}
                config_path = self.root / ('input/native-' + variant + '.json')
                config_path.write_text(json.dumps(config))
                parent = run_problem(self.root / 'input/problem.json', config_path, output_root=self.root / ('runs-' + variant))
                bundle = json.loads((parent.bundle_path / 'bundle.json').read_text())
                self.assertEqual(parent.status, 'completed', bundle['error'])
                edit = export_edit(parent.bundle_path, operation='code')
                edit['reason'] = 'Manually cap native quantities at one.'
                edit['code']['source'] = edit['code']['source'].replace('lb=0, vtype=', 'lb=0, ub=1, vtype=')
                child = edit_run(parent.bundle_path, self.write(edit))
                bundle = json.loads((child.bundle_path / 'bundle.json').read_text())
                self.assertEqual(child.status, 'completed', bundle['error'])
                solve = json.loads((child.bundle_path / bundle['solve_result_ref']['relative_path']).read_text())
                self.assertEqual(solve['objective_value'], 5)
                ledger = json.loads((child.bundle_path / 'budget-ledger.json').read_text())
                self.assertEqual(ledger['llm_attempts'], 0)
                self.assertEqual(ledger['solver_calls'], 4 if kind == 'native_script' else 2)

    def test_cli_template_and_edits_reject_changed_source_or_exhausted_budget(self):
        command = subprocess.run([sys.executable, '-m', 'llm4om', 'edit', '--run-id', self.parent.run_id,
            '--output', str(self.root / 'runs'), '--operation', 'formulation'], capture_output=True, text=True)
        self.assertEqual(command.returncode, 0, command.stderr)
        value = json.loads(command.stdout)
        self.assertEqual(value['operation'], 'formulation')
        value['reason'] = 'Preserve the original artifact but explicitly test admission.'
        value['budget']['max_checks'] = 1
        with self.assertRaises(RunError) as exhausted:
            edit_run(self.parent.bundle_path, self.write(value))
        self.assertEqual(exhausted.exception.code, 'budget_exhausted')
        value = export_edit(self.parent.bundle_path, operation='code')
        value['reason'] = 'Change only Code.'
        value['problem']['description'] += ' Changed problem.'
        with self.assertRaises(RunError) as changed:
            edit_run(self.parent.bundle_path, self.write(value))
        self.assertEqual(changed.exception.code, 'invalid_edit')
        self.assertEqual(len(list((self.root / 'runs').glob('*/bundle.json'))), 1)
