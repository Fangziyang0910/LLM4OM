"""Actual isolated CoE native function through public SDK and HTTP seams."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
import subprocess
import sys
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import yaml

from llm4om import CancellationToken, run_problem, resume_run


CODE = '''import gurobipy as gp
def prob_case(capacity):
    model = gp.Model()
    x = model.addVar(lb=0, vtype=gp.GRB.INTEGER, name="x")
    model.addConstr(x <= capacity)
    model.setObjective(3*x, gp.GRB.MAXIMIZE)
    model.optimize()
    return model.ObjVal
'''


class CoERunTests(unittest.TestCase):
    def run_case(self, *, replies=None, reflection=False, budget=None, solver='llm4om.solvers.gurobi', trials=3,
                 natural_only=False, cancel_at_source=False, crash_after_output=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        replies = replies or ['Programming Expert', 'Use an integer x bounded by capacity.', CODE]
        requests = []
        cancellation = CancellationToken()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'choices': [{'message': {'content': replies[len(requests)-1]}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}}).encode())
                if cancel_at_source and len(requests) == len(replies):
                    threading.Timer(1, cancellation.cancel).start()
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        data = json.dumps({'code_example': 'def prob_case(capacity): pass', 'entry_point': 'prob_case', 'input': {'capacity': 4}}).encode()
        (root / 'contract.json').write_bytes(data)
        problem = {'schema_version': '0.3.0', 'problem_id': 'coe-public-integer', 'revision': '1',
            'description': 'Maximize 3x. The nonnegative quantity x must be integer and no larger than capacity.',
            'language': 'en', 'problem_type_hint': 'milp', 'requirements': [], 'assumptions': [], 'source': {'kind': 'original_fixture'},
            'data_refs': [{'data_id': 'contract', 'path': 'contract.json', 'format': 'json', 'schema': {'type': 'object'},
                'sha256': hashlib.sha256(data).hexdigest()}]}
        (root / 'problem.json').write_text(json.dumps(problem))
        if natural_only:
            problem['description'] = 'Maximize 3x. The nonnegative quantity x must be integer and no larger than four.'
            problem['data_refs'] = []
            (root / 'problem.json').write_text(json.dumps(problem))
        config = yaml.safe_load((Path(__file__).parents[1] / 'examples/specs/gurobi.yaml').read_text())
        config.pop('compiler')
        config['method'] = {'plugin_id': 'llm4om.methods.coe', 'config': {'public_contract_data_id': 'contract',
            'max_collaborate_nums': 1, 'enable_reflection': reflection, 'max_trials': trials, 'seed': 7}}
        if natural_only:
            config['method']['config']['public_contract_data_id'] = None
        config['model_backend']['plugin_id'] = 'llm4om.model_backends.gurobipy'
        config['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic-public-coe',
            'config': {'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'credential_env': 'COE_TEST_KEY',
                'max_retries': 0, 'max_output_tokens': 1024}}
        config['solver']['plugin_id'] = solver
        config['budget'].update(max_llm_attempts=30, max_total_tokens=150000, max_solver_calls=6, max_repairs=3, wall_time_s=90)
        if budget is not None:
            config['budget'].update(budget)
        (root / 'config.yaml').write_text(yaml.safe_dump(config))
        with patch.dict(os.environ, {'COE_TEST_KEY': 'synthetic-no-real-key'}):
            if crash_after_output:
                script = '''import os,sys
from pathlib import Path
from llm4om import run_problem
replace = os.replace
def crash(source,target,*args,**kwargs):
    result = replace(source,target,*args,**kwargs)
    if Path(target).name == "formulation-snapshot.json" and "history" not in Path(target).parts: os._exit(71)
    return result
os.replace = crash
run_problem(Path(sys.argv[1]),Path(sys.argv[2]),output_root=Path(sys.argv[3]))
'''
                process = subprocess.run([sys.executable, '-c', script, str(root / 'problem.json'), str(root / 'config.yaml'), str(root / 'runs')],
                    cwd=root, capture_output=True, text=True, timeout=90)
                self.assertEqual(process.returncode, 71, process.stderr)
                saved = next(path for path in (root / 'runs').iterdir() if path.is_dir() and not path.name.startswith('.'))
                result = resume_run(saved)
            else:
                result = run_problem(root / 'problem.json', root / 'config.yaml', output_root=root / 'runs', cancellation=cancellation)
        bundle = json.loads((result.bundle_path / 'bundle.json').read_text())
        return root, result, bundle, requests

    def test_native_function_has_truthful_unavailable_formulation_and_real_solver_result(self):
        root, result, bundle, requests = self.run_case()
        self.assertEqual(result.status, 'completed', bundle['error'])
        self.assertEqual(bundle['stages']['formulation']['status'], 'not_available')
        self.assertEqual(bundle['stages']['code']['status'], 'available')
        evaluation = json.loads((result.bundle_path / 'evaluation.json').read_text())
        self.assertEqual(evaluation['formulation_validation']['status'], 'not_available')
        artifact = json.loads((result.bundle_path / bundle['model_artifact_ref']['relative_path']).read_text())
        self.assertIsNone(artifact['formulation_ref'])
        solve = json.loads((result.bundle_path / bundle['solve_result_ref']['relative_path']).read_text())
        self.assertEqual(solve['objective_value'], 12)
        solution = json.loads((result.bundle_path / solve['solution_ref']['relative_path']).read_text())
        self.assertEqual(solution['variables'], {'x': 4})
        self.assertEqual((result.bundle_path / 'method/trial-001-code.py').read_text(), CODE)
        self.assertEqual(resume_run(result.bundle_path).status, 'completed')
        self.assertEqual(len(requests), 3)

    def test_failed_public_invocation_reflects_then_selects_the_next_reducer_and_reuses_execution(self):
        failed = 'def prob_case(capacity):\n    raise ValueError("public source failure")\n'
        replies = ['Programming Expert', 'first-comment', failed, '{"input":{"capacity":4}}',
            '{"is_caused_by_you":true,"reason":"fix","refined_result":"ignored-refinement"}',
            'Programming Expert', 'second-comment', CODE, '{"input":{"capacity":4}}']
        _, result, bundle, requests = self.run_case(replies=replies, reflection=True)
        self.assertEqual(result.status, 'completed', bundle['error'])
        self.assertEqual(len(requests), 9)
        self.assertNotIn('ignored-refinement', requests[6]['messages'][0]['content'])
        self.assertEqual((result.bundle_path / 'method/trial-002-code.py').read_text(), CODE)
        ledger = json.loads((result.bundle_path / 'budget-ledger.json').read_text())
        self.assertEqual((ledger['script_executions'], ledger['collector_calls'], ledger['solver_calls']), (3, 2, 5))
        self.assertEqual(resume_run(result.bundle_path).status, 'completed')
        self.assertEqual(len(requests), 9)

    def test_generated_public_test_arguments_do_not_replace_the_original_task_instance(self):
        _, result, bundle, _ = self.run_case(reflection=True, replies=[
            'Programming Expert', 'comment', CODE, '{"input":{"capacity":7}}'])
        self.assertEqual(result.status, 'completed', bundle['error'])
        trial = json.loads((result.bundle_path / 'method/executions/coe-trial-001/solve-result.json').read_text())
        final = json.loads((result.bundle_path / bundle['solve_result_ref']['relative_path']).read_text())
        self.assertEqual(trial['objective_value'], 21)
        self.assertEqual(final['objective_value'], 12)
        data = json.loads((result.bundle_path / 'method/executions/coe-final-original/data.json').read_text())
        self.assertEqual(data['arguments'], {'capacity': 4})

    def test_natural_language_only_uses_an_original_public_default_interface(self):
        code = CODE.replace('def prob_case(capacity):', 'def prob_problem():\n    capacity = 4')
        _, result, bundle, requests = self.run_case(natural_only=True, replies=['Programming Expert', 'comment', code])
        self.assertEqual(result.status, 'completed', bundle['error'])
        self.assertIn('def prob_problem', requests[1]['messages'][0]['content'])
        solve = json.loads((result.bundle_path / bundle['solve_result_ref']['relative_path']).read_text())
        self.assertEqual(solve['objective_value'], 12)

    def test_public_return_value_cannot_manufacture_a_trusted_solution(self):
        _, result, bundle, _ = self.run_case(replies=['Programming Expert', 'comment', 'def prob_case(capacity): return 12'])
        self.assertEqual(result.status, 'failed')
        self.assertEqual(bundle['error']['code'], 'collector_failed')
        self.assertIsNone(bundle['solve_result_ref'])
        self.assertEqual(bundle['stages']['code']['status'], 'available')

    def test_native_highs_fails_before_http_and_solver_budget_stops_before_execution(self):
        for options, code, calls in [({'solver': 'llm4om.solvers.highs'}, 'capability_mismatch', 0),
                ({'budget': {'max_solver_calls': 1}}, 'budget_exhausted', 3)]:
            with self.subTest(options=options):
                _, result, bundle, requests = self.run_case(**options)
                self.assertEqual(result.status, 'failed')
                self.assertEqual(bundle['error']['code'], code)
                self.assertEqual(len(requests), calls)

    def test_non_prob_reflection_function_aborts_without_blame_or_silent_renaming(self):
        code = CODE.replace('prob_case', 'aircraft_assignment')
        _, result, bundle, requests = self.run_case(reflection=True,
            replies=['Programming Expert', 'comment', code, '{"input":{"capacity":4}}'])
        self.assertEqual(result.status, 'failed')
        self.assertEqual(bundle['error']['code'], 'public_function_unavailable')
        self.assertEqual(len(requests), 4)
        self.assertIsNone(bundle['solve_result_ref'])

    def test_final_failed_trial_keeps_pre_refinement_code_and_source_failure(self):
        code = 'def prob_case(capacity): raise ValueError("last reducer")'
        _, result, bundle, requests = self.run_case(reflection=True, trials=1, replies=[
            'Programming Expert', 'comment', code, '{"input":{"capacity":4}}',
            '{"is_caused_by_you":true,"reason":"fix","refined_result":"unexecuted final code"}'])
        self.assertEqual(result.status, 'failed')
        self.assertEqual(bundle['error']['code'], 'source_execution_failed')
        self.assertEqual(bundle['stages']['code']['status'], 'available')
        self.assertEqual((result.bundle_path / 'method/trial-001-code.py').read_text(), code)
        self.assertEqual(len(requests), 5)
        self.assertEqual(json.loads((result.bundle_path / 'method/selection.json').read_text())['public_check'], 'failed_trials_exhausted')

    def test_public_code_output_recovers_without_a_formulation_or_new_external_work(self):
        _, result, bundle, requests = self.run_case(crash_after_output=True)
        self.assertEqual(result.status, 'completed', bundle['error'])
        self.assertEqual(bundle['stages']['formulation']['status'], 'not_available')
        self.assertEqual(len(requests), 3)
        ledger = json.loads((result.bundle_path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['script_executions'], 1)

    def test_native_source_cancellation_is_bounded_and_keeps_original_code(self):
        code = 'import time\ndef prob_case(capacity):\n    time.sleep(100)\n'
        _, result, bundle, requests = self.run_case(cancel_at_source=True, replies=['Programming Expert', 'comment', code])
        self.assertEqual(result.status, 'cancelled', bundle['error'])
        self.assertEqual((result.bundle_path / 'method/trial-001-code.py').read_text(), code)
        self.assertEqual(len(requests), 3)
