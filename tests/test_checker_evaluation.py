"""Frozen micro-task and original-business evaluation through the public SDK."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import subprocess
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import yaml

from llm4om import evaluate_case, import_dataset, run_problem


class CheckerEvaluationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        repo = Path(__file__).parents[1]
        shutil.copytree(repo / 'examples/specs/data', self.root / 'data')
        shutil.copyfile(repo / 'examples/specs/problem.json', self.root / 'problem.json')
        self.oracle = {'schema_version': '0.1.0', 'checker': {'plugin_id': 'llm4om.checkers.production', 'version': '0.1.0', 'config': {}},
            'decision_mapping': {'A': 'qty_A', 'B': 'qty_B'}, 'reported_objective_mapping': None,
            'reference_objective': {'value': 13, 'sense': 'max', 'quality': 'proven_optimum',
                'source': 'independent_finite_integer_enumeration', 'abs_tol': 1e-6, 'rel_tol': 1e-5},
            'probe_points': [{'A': 0, 'B': 8}, {'A': 3, 'B': 2}], 'data_perturbations': []}
        self.config = {'schema_version': '0.2.0', 'adapter_id': 'llm4om.tasks.checker_fixture',
            'dataset_id': 'original-micro-fixtures', 'source_version': 'test-v1', 'cases': [], 'selected': None}
        self.write_config()

    def write_config(self):
        (self.root / 'evaluation-material.json').write_text(json.dumps(self.oracle))
        self.config['cases'] = [{'problem_path': 'problem.json', 'problem_sha256': hashlib.sha256((self.root / 'problem.json').read_bytes()).hexdigest(),
            'evaluation_path': 'evaluation-material.json', 'evaluation_sha256': hashlib.sha256((self.root / 'evaluation-material.json').read_bytes()).hexdigest()}]
        (self.root / 'import.json').write_text(json.dumps(self.config))

    def test_frozen_checker_material_is_privileged_and_eligibility_precedes_modeling(self):
        path = import_dataset(self.root / 'import.json', self.root / 'snapshot')
        manifest = json.loads(path.read_text())
        self.assertEqual((manifest['N_selected'], manifest['N_independent_eligible'], manifest['N_verified_eligible']), (1, 1, 1))
        entry = manifest['cases'][0]
        problem = json.loads((path.parent / entry['public_ref']['relative_path']).read_text())
        self.assertEqual(problem['problem_id'], 'fixture-production-milp-001')
        self.assertNotIn('reference_objective', json.dumps(problem))
        self.assertNotIn('decision_mapping', json.dumps(problem))
        self.assertTrue(entry['checker_manifest']['coverage'])
        self.assertEqual((path.parent / 'private').stat().st_mode & 0o777, 0o700)
        self.assertEqual(json.loads((path.parent / entry['oracle_ref']['relative_path']).read_text())['reference_objective']['value'], 13)

    def run_candidate(self, transform=lambda ir: None, solver='llm4om.solvers.highs'):
        repo = Path(__file__).parents[1]
        ir = json.loads((repo / 'examples/specs/model-ir.json').read_text())
        transform(ir)
        formulation = json.loads((repo / 'examples/specs/formulation.json').read_text())['representation']
        for parameter, value in zip(formulation['parameters'], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
            parameter.pop('source')
            parameter['value'] = value
        if self.oracle['checker'] is not None and self.oracle['checker']['plugin_id'] == 'llm4om.checkers.unit_cap':
            formulation = {'sets': [], 'parameters': [], 'variables': [{'id': 'Q', 'index_sets': [],
                'domain': 'integer', 'lower_bound': 0, 'upper_bound': 2, 'description': 'Quantity Q.', 'requirement_ids': ['R-DOMAIN']}],
                'objective': {'sense': 'max', 'expression_text': '0', 'description': 'Constant zero.', 'requirement_ids': []},
                'constraints': []}
        compact = {'representation': formulation, 'structured_ir': {key: ir[key] for key in ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}}
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'choices': [{'message': {'content': json.dumps(compact)}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}}).encode())
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            self.write_config()
            manifest = import_dataset(self.root / 'import.json', self.root / 'snapshot')
            entry = json.loads(manifest.read_text())['cases'][0]
            config = yaml.safe_load((repo / 'examples/specs/solve.yaml').read_text())
            config['budget']['max_total_tokens'] = 30000
            config['solver']['plugin_id'] = solver
            config['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic-public-model',
                'config': {'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'credential_env': 'CHECKER_TEST_KEY'}}
            (self.root / 'run.yaml').write_text(yaml.safe_dump(config))
            with patch.dict(os.environ, {'CHECKER_TEST_KEY': 'synthetic'}):
                run = run_problem(manifest.parent / entry['public_ref']['relative_path'], self.root / 'run.yaml', output_root=self.root / 'runs')
            self.assertEqual(run.status, 'completed')
            score = evaluate_case(manifest, entry['case_id'], run.bundle_path, self.root / 'evaluation.json')
            return score, requests, run, manifest
        finally:
            server.shutdown()
            server.server_close()

    def test_swapped_profits_same_reported_value_fail_original_objective_quality(self):
        def swapped(ir):
            ir['objective']['expression']['terms'][0]['coefficient'] = 2
            ir['objective']['expression']['terms'][1]['coefficient'] = 3
        result, requests, _, _ = self.run_candidate(swapped)
        self.assertIsNone(result['checker_error'], result)
        self.assertEqual(result['candidate_primal']['reported_objective'], 13)
        self.assertEqual(result['reported_objective_match']['status'], 'pass')
        self.assertEqual(result['independent_feasibility']['status'], 'pass')
        self.assertEqual(result['original_objective'], 12)
        self.assertEqual(result['original_objective_quality']['status'], 'fail')
        self.assertEqual(result['verified_solution']['status'], 'fail')
        self.assertEqual(result['verified_solution_denominator'], 1)
        self.assertNotIn('reference_objective', json.dumps(requests))
        self.assertNotIn('decision_mapping', json.dumps(requests))
        self.assertNotEqual(result['semantic_validation']['status'], 'semantic_verified')

    def test_correct_original_solution_and_finite_probes(self):
        result, _, _, _ = self.run_candidate()
        self.assertEqual(result['verified_solution']['status'], 'pass')
        self.assertEqual(result['original_objective'], 13)
        self.assertEqual(result['property_checks']['status'], 'pass')
        self.assertEqual(result['property_checks']['points_evaluated'], 2)

    def test_missing_resource_produces_original_violation_and_probe_counterexample(self):
        def omitted(ir):
            ir['constraints'].pop()
        result, _, _, _ = self.run_candidate(omitted)
        self.assertEqual(result['independent_feasibility']['status'], 'fail')
        self.assertEqual(result['property_checks']['status'], 'fail')
        self.assertEqual(result['property_checks']['counterexamples'][0]['original_feasible'], False)

    def test_original_integer_domain_rejects_actual_relaxed_solution(self):
        def relaxed(ir):
            ir['problem_type'] = 'lp'
            for variable in ir['variables']:
                variable['domain'] = 'continuous'
        result, _, _, _ = self.run_candidate(relaxed)
        self.assertEqual(result['candidate_primal']['status'], 'available')
        self.assertIn('integer_domain', result['independent_feasibility']['violations'])
        self.assertEqual(result['verified_solution']['status'], 'fail')

    def test_predeclared_perturbation_observes_original_data_change(self):
        self.oracle['data_perturbations'] = [{'id': 'finishing-capacity-one', 'replacement_data': {
            'capacities': 'resource_id,capacity\ncutting,8\nfinishing,1\n'}, 'probe_points': [{'A': 3, 'B': 2}]}]
        result, requests, _, _ = self.run_candidate()
        self.assertEqual(result['verified_solution']['status'], 'pass')
        self.assertEqual(result['property_checks']['status'], 'fail')
        example = result['property_checks']['counterexamples'][0]
        self.assertEqual(example['scope'], 'fixed_candidate_under_declared_data_perturbation')
        self.assertFalse(example['original_feasible'])
        self.assertNotIn('finishing-capacity-one', json.dumps(requests))

    def test_gurobi_original_solution_is_checked_independently(self):
        result, _, _, _ = self.run_candidate(solver='llm4om.solvers.gurobi')
        self.assertEqual(result['verified_solution']['status'], 'pass')
        self.assertEqual(result['original_objective'], 13)

    def test_objective_units_require_a_predeclared_mapping(self):
        def cents(ir):
            for term in ir['objective']['expression']['terms']:
                term['coefficient'] *= 100
        result, _, run, manifest = self.run_candidate(cents)
        self.assertEqual(result['verified_solution']['status'], 'pass')
        self.assertEqual(result['reported_objective_match']['status'], 'fail')
        self.assertEqual(result['objective_consistency']['status'], 'fail')
        self.assertEqual(result['property_checks']['status'], 'fail')
        self.oracle['reported_objective_mapping'] = {'scale': .01, 'offset': 0}
        self.write_config()
        declared = import_dataset(self.root / 'import.json', self.root / 'mapped-snapshot')
        result = evaluate_case(declared, 'fixture-production-milp-001', run.bundle_path, self.root / 'mapped-result.json')
        self.assertEqual(result['objective_consistency']['status'], 'pass')
        self.assertEqual(result['property_checks']['status'], 'pass')

    def test_missing_checker_mapping_and_reference_remain_distinct(self):
        _, _, run, _ = self.run_candidate()
        policies = [('no-checker', 'checker', None, 'not_available', 0, 0),
            ('uninstalled-checker', 'checker', {'plugin_id': 'not.installed', 'version': '0.1.0', 'config': {}}, 'not_available', 0, 0),
            ('no-mapping', 'decision_mapping', None, 'unknown', 0, 0),
            ('no-reference', 'reference_objective', None, 'pass', 1, 0)]
        original = dict(self.oracle)
        for name, field, value, status, feasibility_denominator, verified_denominator in policies:
            with self.subTest(policy=name):
                self.oracle = {**original, field: value}
                self.write_config()
                manifest = import_dataset(self.root / 'import.json', self.root / name)
                result = evaluate_case(manifest, 'fixture-production-milp-001', run.bundle_path, self.root / (name + '.json'))
                self.assertEqual(result['independent_feasibility']['status'], status)
                self.assertEqual(result['independent_feasibility_denominator'], feasibility_denominator)
                self.assertEqual(result['verified_solution_denominator'], verified_denominator)
                self.assertIsNone(result['checker_error'])

    def test_missing_oracle_retains_admitted_denominators_and_saves_error(self):
        _, _, run, manifest = self.run_candidate()
        (manifest.parent / 'private/0.json').unlink()
        result = evaluate_case(manifest, 'fixture-production-milp-001', run.bundle_path, self.root / 'missing-oracle.json')
        self.assertEqual(result['checker_error']['code'], 'oracle_unavailable')
        self.assertEqual(result['verified_solution_denominator'], 1)
        self.assertEqual(result['verified_solution_rate'], 0)

    def test_actual_infeasible_candidate_has_no_primal_and_retains_failure_denominator(self):
        def impossible(ir):
            ir['constraints'][0].update(sense='ge', rhs=100)
        result, _, _, _ = self.run_candidate(impossible)
        self.assertEqual(result['candidate_primal']['termination'], 'infeasible')
        self.assertEqual(result['independent_feasibility']['status'], 'not_available')
        self.assertEqual(result['verified_solution_denominator'], 1)
        self.assertEqual(result['verified_solution_rate'], 0)

    def test_best_known_improvement_and_feasibility_without_optimum(self):
        for quality in ('best_known', 'feasible'):
            with self.subTest(quality=quality):
                self.oracle['reference_objective'].update(value=12, quality=quality)
                self.write_config()
                manifest = import_dataset(self.root / 'import.json', self.root / quality)
        result, _, run, _ = self.run_candidate()
        self.assertEqual(result['original_objective'], 13)
        self.assertEqual(result['original_objective_quality']['status'], 'pass')
        self.assertEqual(result['original_objective_quality']['level'], 'feasible_original_objective')
        result = evaluate_case(self.root / 'best_known/manifest.json', 'fixture-production-milp-001', run.bundle_path, self.root / 'best-known.json')
        self.assertEqual(result['original_objective_quality']['status'], 'pass')

    def test_constant_objective_and_multiple_optima_do_not_certify_a_wrong_bound(self):
        problem = json.loads((self.root / 'problem.json').read_text())
        problem.update(description='Choose a nonnegative integer Q no larger than one. Maximize the constant zero objective.',
            data_refs=[], requirements=[{'id': 'R-DOMAIN', 'text': 'Q is a nonnegative integer no larger than one.', 'category': 'domain', 'source_span': None}])
        problem['source']['profile'] = 'integer_unit_interval_constant_zero'
        (self.root / 'problem.json').write_text(json.dumps(problem))
        self.oracle.update(checker={'plugin_id': 'llm4om.checkers.unit_cap', 'version': '0.1.0', 'config': {}},
            decision_mapping={'Q': 'qty_A'}, probe_points=[{'Q': 0}, {'Q': 1}, {'Q': 2}])
        self.oracle['reference_objective']['value'] = 0
        def wrong_bound(ir):
            ir['variables'] = [ir['variables'][0]]
            ir['variables'][0]['upper_bound'] = 2
            ir['objective']['expression']['terms'] = []
            ir['objective']['requirement_ids'] = []
            ir['constraints'] = []
        result, _, _, _ = self.run_candidate(wrong_bound)
        self.assertEqual(result['reported_objective_match']['status'], 'pass')
        self.assertEqual(result['verified_solution']['status'], 'pass')
        self.assertEqual(result['property_checks']['status'], 'fail')
        self.assertFalse(result['property_checks']['complete_semantic_proof'])

    def test_installed_trusted_checker_errors_and_invalid_outputs_are_saved_without_private_text(self):
        _, _, run, _ = self.run_candidate()
        project = self.root / 'checker-package'
        project.mkdir()
        (project / 'pyproject.toml').write_text('''[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"
[project]
name = "llm4om-checker-test"
version = "0.1.0"
[project.entry-points."llm4om.checkers"]
"llm4om.tests.production" = "checker_test:create"
''')
        (project / 'checker_test.py').write_text('''from llm4om.checkers import ProductionChecker
from llm4om.contracts import RunError
class Checker(ProductionChecker):
    def __init__(self, config): self.mode = config["mode"]
    def describe(self):
        return {**super().describe(), "checker_id": "llm4om.tests.production"}
    def check(self, problem, data, decisions):
        print("PRIVATE-CHECKER-SENTINEL")
        if self.mode == "exception": raise RuntimeError("PRIVATE-CHECKER-SENTINEL")
        if self.mode == "exit": raise SystemExit("PRIVATE-CHECKER-SENTINEL")
        if self.mode == "runerror": raise RunError("checker_test_error", "evaluation", "PRIVATE-CHECKER-SENTINEL")
        result = super().check(problem, data, decisions)
        if self.mode == "nonfinite": result["original_objective"] = float("nan")
        if self.mode == "coverage": result["independent_feasibility"]["coverage"] = []
        if self.mode == "contradiction": result["independent_feasibility"]["violations"] = ["unit_cap"]
        return result
def create(config): return Checker(config)
''')
        subprocess.run(['uv', 'build', '--offline', '--wheel', '--out-dir', str(self.root / 'dist')], cwd=project, check=True, capture_output=True)
        wheel = next((self.root / 'dist').glob('*.whl'))
        packages = self.root / 'packages'
        subprocess.run(['uv', 'pip', 'install', '--no-deps', '--target', str(packages), str(wheel)], check=True, capture_output=True)
        repo = Path(__file__).parents[1]
        environment = {**os.environ, 'PYTHONPATH': os.pathsep.join((str(repo / 'src'), str(packages)))}
        for mode, code in [('good', None), ('exception', 'checker_error'), ('exit', 'checker_error'),
                ('runerror', 'checker_test_error'), ('nonfinite', 'invalid_checker_output'),
                ('coverage', 'invalid_checker_output'), ('contradiction', 'invalid_checker_output')]:
            with self.subTest(mode=mode):
                self.oracle['checker'] = {'plugin_id': 'llm4om.tests.production', 'version': '0.1.0', 'config': {'mode': mode}}
                self.write_config()
                snapshot = self.root / ('plugin-' + mode)
                imported = subprocess.run([sys.executable, '-m', 'llm4om', 'import', '--config', str(self.root / 'import.json'),
                    '--output', str(snapshot)], cwd=self.root, env=environment, capture_output=True, text=True)
                self.assertEqual(imported.returncode, 0, imported.stdout + imported.stderr)
                output = self.root / ('plugin-' + mode + '.json')
                evaluated = subprocess.run([sys.executable, '-m', 'llm4om', 'evaluate', '--manifest', str(snapshot / 'manifest.json'),
                    '--case-id', 'fixture-production-milp-001', '--run', str(run.bundle_path), '--output', str(output)],
                    cwd=self.root, env=environment, capture_output=True, text=True)
                self.assertEqual(evaluated.returncode, 0 if code is None else 1, evaluated.stdout + evaluated.stderr)
                result = json.loads(output.read_text())
                self.assertEqual(result['verified_solution_denominator'], 1)
                self.assertEqual(result['checker_identity']['origin']['kind'], 'installed_trusted')
                if code is None:
                    self.assertEqual(result['verified_solution']['status'], 'pass')
                else:
                    self.assertEqual(result['checker_error']['code'], code)
                    self.assertEqual(result['verified_solution_rate'], 0)
                self.assertNotIn('PRIVATE-CHECKER-SENTINEL', evaluated.stdout + evaluated.stderr + output.read_text())

    def test_invalid_probe_or_objective_policy_is_rejected_before_modeling(self):
        from llm4om.contracts import RunError
        original = dict(self.oracle)
        for field, value in [('reported_objective_mapping', {'scale': 0, 'offset': 0}),
                ('probe_points', [{'A': True, 'B': 0}]), ('decision_mapping', {'A': 'qty_A', 'B': 'qty_A'}),
                ('checker', {'plugin_id': [], 'version': '0.1.0', 'config': {}})]:
            with self.subTest(field=field):
                self.oracle = {**original, field: value}
                self.write_config()
                with self.assertRaises(RunError):
                    import_dataset(self.root / 'import.json', self.root / ('bad-' + field))
