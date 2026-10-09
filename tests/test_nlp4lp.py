"""NLP4LP public Task/CLI/SDK projection and supplied-reference evaluation."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import yaml

from llm4om import evaluate_case, import_dataset, run_problem
from llm4om.contracts import RunError


class NLP4LPTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.release = self.root / 'release'
        self.release.mkdir()
        self.records = []
        params = {'Capacity': 4, 'Profit': 3, 'Names': ['a', 'b'], 'ByName': {'a': 2}, 'Count': '5'}
        for i, solution in [('1', json.dumps({'objective': 12, 'variables': {'source_x': 4}})), ('2', None), ('3', '{broken}')]:
            self.records.append({'id': i, 'type': 'easy', 'description': f'Public case {i}: choose nonnegative integer x <= Capacity and maximize Profit*x.',
                'parameters': json.dumps(params), 'optimus_code': 'raise RuntimeError("PRIVATE-CODE-SENTINEL")',
                'problem_info': json.dumps({'variables': {'PRIVATE-VARIABLE-SENTINEL': {}}}),
                'parametrized_description': 'PRIVATE-DESCRIPTION-SENTINEL', 'keywords': ['PRIVATE-KEYWORD-SENTINEL'], 'solution': solution})
        self.config = {'schema_version': '0.2.0', 'adapter_id': 'llm4om.tasks.nlp4lp', 'dataset_id': 'fixture-nlp4lp',
            'source_kind': 'fixture', 'source_version': 'test-v1', 'release_root': 'release',
            'sha256': '', 'reviews': [], 'selected': None, 'tolerance': {'abs_tol': 1e-6, 'rel_tol': 1e-5}}
        self.write_release()

    def write_release(self):
        raw = b''.join((json.dumps(record) + '\n').encode() for record in self.records)
        (self.release / 'train.jsonl').write_bytes(raw)
        (self.release / 'README.md').write_text('Fixture source card. No official-source identity.\n')
        for record in self.records:
            folder = self.release / 'data' / record['id']
            folder.mkdir(parents=True, exist_ok=True)
            for field, name in [('description', 'description.txt'), ('parameters', 'parameters.json'),
                                ('optimus_code', 'optimus-code.py'), ('problem_info', 'problem_info.json'), ('solution', 'solution.json')]:
                if record[field] is None:
                    (folder / name).unlink(missing_ok=True)
                else:
                    (folder / name).write_text(record[field])
            (folder / 'metadata.json').write_text(json.dumps({'type': record['type']}))
        self.config['sha256'] = hashlib.sha256(raw).hexdigest()
        (self.root / 'import.json').write_text(json.dumps(self.config))

    def test_public_original_parameters_survive_bad_or_missing_private_solutions(self):
        path = import_dataset(self.root / 'import.json', self.root / 'snapshot')
        manifest = json.loads(path.read_text())
        self.assertEqual((manifest['N_imported'], manifest['N_selected'], manifest['N_eligible']), (3, 3, 0))
        self.assertEqual(manifest['reference_counts'], {'available_unverified': 1, 'missing_solution': 1, 'invalid_solution': 1})
        entry = manifest['cases'][0]
        public = json.loads((path.parent / entry['public_ref']['relative_path']).read_text())
        self.assertEqual(public['description'], self.records[0]['description'])
        data = public['data_refs'][0]
        raw = (path.parent / entry['public_ref']['relative_path']).parent.joinpath(data['path']).read_bytes()
        self.assertEqual(raw, (self.release / 'data/1/parameters.json').read_bytes())
        self.assertEqual(json.loads(raw)['Count'], '5')
        self.assertEqual(json.loads(raw)['ByName'], {'a': 2})
        self.assertEqual(data['sha256'], hashlib.sha256(raw).hexdigest())
        exported = json.dumps(public) + raw.decode()
        self.assertNotIn('PRIVATE-', exported)
        self.assertNotIn('optimus_code', exported)
        self.assertNotIn('solution', exported)
        self.assertEqual(entry['consistency']['parameters'], 'semantic_equal_directory_bytes_retained')
        self.assertTrue(all(case['reference_diagnostic'] for case in manifest['cases'][1:]))

    def test_review_freezes_public_parameter_binding_and_reference_eligibility(self):
        question = self.records[0]['description']
        self.config['selected'] = ['1', '2', '3']
        self.config['reviews'] = [{'subset': 'train', 'sample_id': '1',
            'question_sha256': hashlib.sha256(question.encode()).hexdigest(), 'classification': 'milp',
            'domain_policy': 'x is a nonnegative integer', 'rounding_policy': {'kind': 'none', 'decimal_places': None},
            'data_sha256': hashlib.sha256((self.release / 'data/1/parameters.json').read_bytes()).hexdigest(),
            'data_binding_policy': 'Capacity bounds x; Profit is its objective coefficient; remaining data are unused.',
            'evidence': [{'aspect': aspect, 'start': 0, 'end': len(question), 'text': question}
                         for aspect in ('problem_type', 'variable_domains', 'rounding', 'data_binding')],
            'reviewer': 'public-fixture-review', 'reason': None}]
        self.write_release()
        path = import_dataset(self.root / 'import.json', self.root / 'snapshot')
        manifest = json.loads(path.read_text())
        self.assertEqual((manifest['N_selected'], manifest['N_eligible']), (3, 1))
        first, missing, invalid = manifest['cases']
        self.assertTrue(first['eligible'])
        self.assertEqual(missing['exclusion_reason'], 'source_does_not_supply_solution')
        self.assertEqual(invalid['exclusion_reason'], 'invalid_solution_json_or_schema')
        problem = json.loads((path.parent / first['public_ref']['relative_path']).read_text())
        self.assertEqual(problem['problem_type_hint'], 'milp')
        self.assertNotIn('PRIVATE-', json.dumps(problem))

    def test_ambiguous_public_values_and_duplicate_or_changed_source_fail_admission(self):
        params = self.release / 'data/1/parameters.json'
        original = params.read_bytes()
        value = json.loads(original)
        value['Capacity'] = 4.0
        params.write_text(json.dumps(value))
        with self.assertRaises(RunError) as caught:
            import_dataset(self.root / 'import.json', self.root / 'ambiguous')
        self.assertEqual(caught.exception.code, 'ambiguous_source')
        self.assertFalse((self.root / 'ambiguous').exists())
        params.write_bytes(original)
        self.records.append(dict(self.records[0]))
        self.write_release()
        with self.assertRaises(RunError):
            import_dataset(self.root / 'import.json', self.root / 'duplicate')
        self.records.pop()
        self.write_release()
        train = self.release / 'train.jsonl'
        train.write_bytes(train.read_bytes().replace(b'"id": "1"', b'"id": "1", "id": "1"'))
        self.config['sha256'] = hashlib.sha256(train.read_bytes()).hexdigest()
        (self.root / 'import.json').write_text(json.dumps(self.config))
        with self.assertRaises(RunError):
            import_dataset(self.root / 'import.json', self.root / 'duplicate-key')
        self.write_release()
        train.write_bytes(train.read_bytes() + b'\n')
        with self.assertRaises(RunError) as caught:
            import_dataset(self.root / 'import.json', self.root / 'changed')
        self.assertEqual(caught.exception.code, 'source_hash_mismatch')

    def test_failed_run_and_bad_reference_remain_distinct_reported_cases(self):
        path = import_dataset(self.root / 'import.json', self.root / 'snapshot')
        entries = json.loads(path.read_text())['cases']
        for entry in entries:
            run = run_problem(path.parent / entry['public_ref']['relative_path'], self.root / 'missing.yaml',
                              output_root=self.root / 'runs')
            result = evaluate_case(path, entry['case_id'], run.bundle_path, self.root / (entry['sample_id'] + '-evaluation.json'))
            self.assertEqual(result['run_status'], 'failed')
            self.assertIsNone(result['checker_error'])
            self.assertEqual(result['reference_quality'], entry['reference_quality'])
            self.assertEqual(result['objective_match']['status'], 'not_available')
            self.assertEqual(result['N_selected'], 3)
            self.assertNotIn('PRIVATE-', json.dumps(result))

    def test_actual_solver_run_binds_original_json_data_and_matches_supplied_objective(self):
        question = self.records[0]['description']
        self.config['selected'] = ['1']
        self.config['reviews'] = [{'subset': 'train', 'sample_id': '1',
            'question_sha256': hashlib.sha256(question.encode()).hexdigest(), 'classification': 'milp',
            'domain_policy': 'x is a nonnegative integer', 'rounding_policy': {'kind': 'none', 'decimal_places': None},
            'data_sha256': hashlib.sha256((self.release / 'data/1/parameters.json').read_bytes()).hexdigest(),
            'data_binding_policy': 'Capacity bounds x; Profit is its objective coefficient; remaining data are unused.',
            'evidence': [{'aspect': aspect, 'start': 0, 'end': len(question), 'text': question}
                         for aspect in ('problem_type', 'variable_domains', 'rounding', 'data_binding')],
            'reviewer': 'public-fixture-review', 'reason': None}]
        self.write_release()
        manifest = import_dataset(self.root / 'import.json', self.root / 'snapshot')
        entry = json.loads(manifest.read_text())['cases'][0]
        compact = {'representation': {'sets': [], 'parameters': [],
            'variables': [{'id': 'x', 'index_sets': [], 'domain': 'integer', 'lower_bound': 0, 'upper_bound': 4, 'requirement_ids': []}],
            'objective': {'sense': 'max', 'expression_text': '3x', 'requirement_ids': []}, 'constraints': []},
            'structured_ir': {'problem_type': 'milp', 'variables': [{'id': 'x', 'name': 'x', 'domain': 'integer', 'lower_bound': 0, 'upper_bound': 4, 'requirement_ids': []}],
                'objective': {'sense': 'max', 'expression': {'constant': 0, 'terms': [{'variable_id': 'x', 'coefficient': 3}]}, 'requirement_ids': []}, 'constraints': [], 'assumptions': []}}
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
            config = yaml.safe_load((Path(__file__).parents[1] / 'examples/specs/solve.yaml').read_text())
            config['budget']['max_total_tokens'] = 30000
            config['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic-public-model',
                'config': {'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'credential_env': 'NLP4LP_TEST_KEY'}}
            (self.root / 'run.yaml').write_text(yaml.safe_dump(config))
            with patch.dict(os.environ, {'NLP4LP_TEST_KEY': 'synthetic'}):
                run = run_problem(manifest.parent / entry['public_ref']['relative_path'], self.root / 'run.yaml', output_root=self.root / 'runs')
            self.assertEqual(run.status, 'completed')
            result = evaluate_case(manifest, entry['case_id'], run.bundle_path, self.root / 'evaluation.json')
            self.assertIsNone(result['checker_error'], result)
            self.assertEqual(result['objective_match']['status'], 'pass')
            self.assertEqual(result['case_binding']['status'], 'pass')
            self.assertEqual(result['independent_feasibility']['status'], 'not_available')
            self.assertEqual(result['variable_mapping']['status'], 'not_available')
            self.assertNotIn('PRIVATE-', json.dumps(requests))
            data = json.loads(json.loads(requests[0]['messages'][1]['content'])['data']['parameters'])
            self.assertEqual(data['Count'], '5')
            self.assertEqual(data['ByName'], {'a': 2})
            for label, file in [('snapshot-data', manifest.parent / 'public/params-1.json'),
                                ('run-data', run.bundle_path / 'data/0.json'),
                                ('private-reference', manifest.parent / entry['oracle_ref']['relative_path'])]:
                with self.subTest(changed=label):
                    original = file.read_bytes()
                    file.write_bytes(b'{}\n')
                    try:
                        broken = evaluate_case(manifest, entry['case_id'], run.bundle_path, self.root / (label + '-error.json'))
                        self.assertIsNotNone(broken['checker_error'])
                        self.assertEqual(broken['objective_match_denominator'], 1)
                        self.assertEqual(broken['objective_match_rate'], 0)
                        self.assertNotIn('PRIVATE-', json.dumps(broken))
                    finally:
                        file.write_bytes(original)
        finally:
            server.shutdown()
            server.server_close()
