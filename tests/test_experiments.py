"""Public batch behavior: real solving, frozen denominators and safe continuation."""

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from llm4om import import_dataset, run_experiment, report_experiment, CancellationToken
from llm4om.contracts import RunError


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.fixture = Path(__file__).resolve().parents[1] / 'examples/specs'
        self.manifest = import_dataset(self.fixture / 'import-checker.json', self.root / 'task')
        entry = json.loads(self.manifest.read_text())['cases'][0]
        public = self.manifest.parent / entry['public_ref']['relative_path']
        packet = self.root / 'packet'
        packet.mkdir()
        shutil.copyfile(public, packet / 'problem.json')
        problem = json.loads(public.read_text())
        for ref in problem['data_refs']:
            target = packet / ref['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(public.parent / ref['path'], target)
        ir = json.loads((self.fixture / 'model-ir.json').read_text())
        ir.update(problem_id=problem['problem_id'], problem_revision=problem['revision'])
        self.write(packet / 'model-ir.json', ir)
        formulation = json.loads((self.fixture / 'formulation.json').read_text())
        formulation.update(problem_id=problem['problem_id'], problem_revision=problem['revision'])
        formulation['structured_ir_ref'] = self.ref(packet / 'model-ir.json', formulation['structured_ir_ref'])
        self.write(packet / 'formulation.json', formulation)
        artifact = json.loads((self.fixture / 'model-artifact.json').read_text())
        artifact['problem_ref'] = {**self.ref(packet / 'problem.json', artifact['problem_ref']), 'artifact_id': problem['problem_id']}
        artifact['formulation_ref'] = self.ref(packet / 'formulation.json', artifact['formulation_ref'])
        self.write(packet / 'model-artifact.json', artifact)
        config = yaml.safe_load((self.fixture / 'solve.yaml').read_text())
        config['llm']['config']['response_artifact'] = 'packet/model-artifact.json'
        self.write(self.root / 'run.json', config)
        self.spec = {'schema_version': '0.1.0', 'experiment_id': 'production-batch',
            'tasks': [{'id': 'production', 'manifest': str(self.manifest)}],
            'configurations': [{'id': 'direct-highs', 'run_config': 'run.json'}],
            'repeats': 2, 'budget': {'max_llm_attempts': 2, 'max_total_tokens': 8192,
                'max_solver_calls': 2, 'wall_time_s': 180, 'max_concurrency': 2}, 'exclusions': []}
        self.path = self.root / 'experiment.json'
        self.write(self.path, self.spec)

    @staticmethod
    def write(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')

    @staticmethod
    def ref(path, original):
        raw = path.read_bytes()
        return {**original, 'sha256': hashlib.sha256(raw).hexdigest(), 'size_bytes': len(raw)}

    def test_two_real_highs_runs_and_resume_do_not_repeat_completed_work(self):
        output = self.root / 'batch'
        summary = run_experiment(self.path, output)
        self.assertEqual(len(summary['groups']), 2)
        for group in summary['groups']:
            self.assertEqual(group['N_completed'], 1)
            self.assertEqual((group['verified_solution_numerator'], group['verified_solution_denominator']), (1, 1))
            self.assertEqual((group['objective_match_numerator'], group['objective_match_denominator']), (1, 1))
            self.assertEqual(group['solver_calls'], 1)
            self.assertIsNone(group['total_tokens'])
            self.assertEqual(group['evidence_origins'], ['mock_fixture'])
        before = sorted(str(path) for path in output.glob('runs/*/*/bundle.json'))
        continued = run_experiment(self.path, output, resume=True)
        self.assertEqual(before, sorted(str(path) for path in output.glob('runs/*/*/bundle.json')))
        self.assertEqual(continued['reserved_run_caps'], summary['reserved_run_caps'])
        report_experiment(output)
        for name in ('results.jsonl', 'results.csv', 'summary.json', 'report.md', 'report.html'):
            self.assertTrue((output / 'reports' / name).is_file())
        public = (output / 'experiment.json').read_text() + ''.join(path.read_text() for path in (output / 'reports').iterdir())
        self.assertNotIn('oracle_ref', public)
        self.assertNotIn('"namespace": "task_private"', public)
        self.assertNotIn('probe_points', public)

    def test_total_budget_keeps_unstarted_case_in_frozen_denominator(self):
        self.spec['budget']['max_llm_attempts'] = 1
        self.write(self.path, self.spec)
        summary = run_experiment(self.path, self.root / 'batch', offline=True)
        groups = summary['groups']
        self.assertEqual(groups[0]['statuses'], {'artifact_ready': 1})
        self.assertEqual(groups[1]['statuses'], {'budget_exhausted': 1})
        self.assertEqual(groups[1]['verified_solution_denominator'], 1)
        self.assertEqual(groups[1]['verified_solution_rate'], 0)
        self.assertIsNone(groups[1]['cost'])

    def test_preflight_requires_explicit_exclusion_before_any_run(self):
        config = json.loads((self.root / 'run.json').read_text())
        config['solver']['plugin_id'] = 'absent.solver'
        self.write(self.root / 'unsupported.json', config)
        self.spec['configurations'].append({'id': 'unsupported', 'run_config': 'unsupported.json'})
        self.write(self.path, self.spec)
        with self.assertRaises(RunError) as failure:
            run_experiment(self.path, self.root / 'batch', offline=True)
        self.assertEqual(failure.exception.code, 'experiment_incompatible')
        self.assertFalse((self.root / 'batch/runs').exists())
        self.spec['exclusions'] = [{'task_id': 'production', 'configuration_id': 'unsupported', 'reason': 'Solver not installed'}]
        self.write(self.path, self.spec)
        summary = run_experiment(self.path, self.root / 'batch', offline=True)
        self.assertEqual(len(summary['excluded_cells']), 1)
        self.assertEqual(len(summary['groups']), 2)

    def test_resume_rejects_changed_mock_input_without_more_work(self):
        output = self.root / 'batch'
        run_experiment(self.path, output, offline=True)
        artifact_path = self.root / 'packet/model-artifact.json'
        artifact_path.write_bytes(artifact_path.read_bytes() + b' ')
        with self.assertRaises(RunError) as failure:
            run_experiment(self.path, output, offline=True, resume=True)
        self.assertEqual(failure.exception.code, 'checkpoint_incompatible')

    def test_cancellation_keeps_all_selected_case_denominators(self):
        cancellation = CancellationToken()
        cancellation.cancel()
        summary = run_experiment(self.path, self.root / 'batch', offline=True, cancellation=cancellation)
        self.assertEqual([g['statuses'] for g in summary['groups']], [{'cancelled': 1}, {'cancelled': 1}])
        self.assertEqual([g['verified_solution_denominator'] for g in summary['groups']], [1, 1])
        self.assertEqual(summary['reserved_run_caps']['max_llm_attempts'], 0)
        resumed = run_experiment(self.path, self.root / 'batch', offline=True, resume=True)
        self.assertEqual([g['statuses'] for g in resumed['groups']], [{'artifact_ready': 1}, {'artifact_ready': 1}])
