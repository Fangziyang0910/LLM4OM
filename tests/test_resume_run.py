"""S04-B behavior through the approved SDK/CLI, HTTP and Executor seams."""

import json
from pathlib import Path
import shutil
import tempfile
import unittest

from llm4om import run_problem

ROOT = Path(__file__).resolve().parents[1]


class ResumeRunTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        shutil.copytree(ROOT / 'examples/specs', self.inputs)

    def test_sdk_precancel_is_terminal_without_a_model_call(self):
        from llm4om import CancellationToken
        token = CancellationToken()
        token.cancel()
        result = run_problem(self.inputs / 'problem.json', self.inputs / 'run.yaml',
                             offline=True, output_root=self.root / 'runs', cancellation=token)
        bundle = json.loads((result.bundle_path / 'bundle.json').read_text())
        self.assertEqual(result.status, 'cancelled')
        self.assertIsNone(bundle['solve_result_ref'])
        self.assertEqual(json.loads((result.bundle_path / 'budget-ledger.json').read_text())['llm_attempts'], 0)

    def test_completed_offline_resume_is_idempotent_and_checks_public_bytes(self):
        from llm4om import resume_run
        from llm4om.contracts import RunError
        result = run_problem(self.inputs / 'problem.json', self.inputs / 'run.yaml',
                             offline=True, output_root=self.root / 'runs')
        before = (result.bundle_path / 'events.jsonl').read_bytes()
        restored = resume_run(result.bundle_path)
        self.assertEqual(restored, result)
        self.assertEqual((result.bundle_path / 'events.jsonl').read_bytes(), before)
        (result.bundle_path / 'candidates/001/formulation.json').write_text('{}')
        with self.assertRaises(RunError) as caught:
            resume_run(result.bundle_path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')

    def test_sdk_cancels_http_and_resume_keeps_unknown_reservation(self):
        from concurrent.futures import ThreadPoolExecutor
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from threading import Event, Thread
        import os
        import yaml
        from llm4om import CancellationToken, resume_run
        entered, release = Event(), Event()
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.rfile.read(int(self.headers['Content-Length'])))
                entered.set()
                release.wait(10)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(release.set)
        Thread(target=server.serve_forever, daemon=True).start()
        settings = yaml.safe_load((self.inputs / 'run.yaml').read_text())
        settings['executor'] = {'plugin_id': 'llm4om.executors.trusted_local', 'config': {}}
        settings['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic',
                           'config': {'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                                      'credential_env': 'S04B_TEST_KEY', 'max_retries': 0}}
        settings['budget']['max_total_tokens'] = 30000
        config = self.inputs / 'http.yaml'
        config.write_text(yaml.safe_dump(settings))
        os.environ['S04B_TEST_KEY'] = 'synthetic-public-fixture'
        self.addCleanup(os.environ.pop, 'S04B_TEST_KEY', None)
        token = CancellationToken()
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(run_problem, self.inputs / 'problem.json', config,
                                  output_root=self.root / 'runs', cancellation=token)
            self.assertTrue(entered.wait(5))
            token.cancel()
            result = pending.result(timeout=3)
        self.assertEqual(result.status, 'cancelled')
        bundle = json.loads((result.bundle_path / 'bundle.json').read_text())
        ledger = json.loads((result.bundle_path / 'budget-ledger.json').read_text())
        self.assertGreater(ledger['reserved_tokens'], 0)
        self.assertIsNone(bundle['solve_result_ref'])
        restored = resume_run(result.bundle_path)
        bundle = json.loads((restored.bundle_path / 'bundle.json').read_text())
        self.assertEqual(bundle['error']['code'], 'provider_outcome_unknown')
        self.assertEqual(len(requests), 1)

    def test_executor_cancellation_removes_actual_container(self):
        from concurrent.futures import ThreadPoolExecutor
        import subprocess
        import time
        from llm4om import CancellationToken
        from llm4om.executors import run_container
        token = CancellationToken()
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(run_container, ['python', '-u', '-c',
                "import time; print('started', flush=True); time.sleep(30)"], {},
                {'network': False, 'cpu_limit': 1, 'memory_limit_mb': 128, 'wall_time_s': 40},
                cancellation=token)
            time.sleep(0.6)
            token.cancel()
            result = pending.result(timeout=6)
        self.assertEqual(result.status, 'cancelled')
        self.assertTrue(result.container_id)
        remaining = subprocess.run(['docker', 'inspect', result.container_id], capture_output=True)
        self.assertNotEqual(remaining.returncode, 0)

    def test_cli_resume_completed_and_cancel_inactive(self):
        import subprocess
        import sys
        result = run_problem(self.inputs / 'problem.json', self.inputs / 'run.yaml',
                             offline=True, output_root=self.root / 'runs')
        command = [sys.executable, '-m', 'llm4om']
        restored = subprocess.run([*command, 'resume', '--run-id', result.run_id,
                                   '--output', str(self.root / 'runs')], capture_output=True, text=True)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        self.assertEqual(json.loads(restored.stdout)['run_id'], result.run_id)
        cancelled = subprocess.run([*command, 'cancel', '--run-id', result.run_id,
                                    '--output', str(self.root / 'runs')], capture_output=True, text=True)
        self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
        self.assertEqual(json.loads(cancelled.stdout)['status'], 'inactive')

    def test_cancel_after_actual_solve_resumes_without_redundant_solve(self):
        import os
        from unittest.mock import patch
        from llm4om import CancellationToken, resume_run
        token = CancellationToken()
        replace = os.replace
        def stop_after_execution(source, target, *args, **kwargs):
            result = replace(source, target, *args, **kwargs)
            if Path(target).name == 'execution.json':
                token.cancel()
            return result
        with patch('os.replace', side_effect=stop_after_execution):
            result = run_problem(self.inputs / 'problem.json', self.inputs / 'solve.yaml',
                                 output_root=self.root / 'runs', cancellation=token)
        self.assertEqual(result.status, 'cancelled')
        before = json.loads((result.bundle_path / 'bundle.json').read_text())
        restored = resume_run(result.bundle_path)
        self.assertEqual(restored.status, 'completed')
        bundle = json.loads((restored.bundle_path / 'bundle.json').read_text())
        self.assertEqual(bundle['solve_result_ref'], before['solve_result_ref'])
        solve = json.loads((restored.bundle_path / bundle['solve_result_ref']['relative_path']).read_text())
        self.assertEqual(solve['objective_value'], 13)
        budget_refs = [ref for ref in bundle['artifacts'] if ref['artifact_id'] == 'budget']
        ledger = json.loads((restored.bundle_path / budget_refs[-1]['relative_path']).read_text())
        self.assertEqual(ledger['solver_calls'], 1)
        self.assertEqual(ledger['llm_attempts'], 1)

    def test_saved_http_success_is_replayed_from_method_checkpoint(self):
        import os
        import threading
        import yaml
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from unittest.mock import patch
        from llm4om import CancellationToken, resume_run
        formulation = json.loads((self.inputs / 'formulation.json').read_text())
        ir = json.loads((self.inputs / 'model-ir.json').read_text())
        compact = {'representation': formulation['representation'], 'structured_ir': {
            key: ir[key] for key in ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}}
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'choices': [{'message': {'content': json.dumps(compact)},
                    'finish_reason': 'stop'}], 'usage': {'total_tokens': 500}}).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        settings = yaml.safe_load((self.inputs / 'solve.yaml').read_text())
        settings['budget']['max_total_tokens'] = 30000
        settings['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic',
                           'config': {'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                                      'credential_env': 'S04B_TEST_KEY', 'max_retries': 0}}
        config = self.inputs / 'http.yaml'
        config.write_text(yaml.safe_dump(settings))
        os.environ['S04B_TEST_KEY'] = 'synthetic-fixture'
        self.addCleanup(os.environ.pop, 'S04B_TEST_KEY', None)
        token = CancellationToken()
        replace = os.replace
        def cancel_after_saved_reply(source, target, *args, **kwargs):
            result = replace(source, target, *args, **kwargs)
            if Path(target).name == 'state.json':
                value = json.loads(Path(target).read_text())
                if any(attempt.get('status') == 'success' for attempt in value['attempts']):
                    token.cancel()
            return result
        with patch('os.replace', side_effect=cancel_after_saved_reply):
            result = run_problem(self.inputs / 'problem.json', config, output_root=self.root / 'runs', cancellation=token)
        bundle = json.loads((result.bundle_path / 'bundle.json').read_text())
        self.assertEqual(result.status, 'cancelled')
        self.assertIsNone(bundle['model_artifact_ref'])
        restored = resume_run(result.bundle_path)
        self.assertEqual(restored.status, 'completed')
        self.assertEqual(len(requests), 1)
        ledger = json.loads((restored.bundle_path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['external_llm_requests'], 1)
        self.assertEqual(ledger['total_tokens'], 500)
        # Reading a completed result needs no valid Provider credential.
        os.environ['S04B_TEST_KEY'] = 'invalid\ncredential'
        self.assertEqual(resume_run(restored.bundle_path), restored)


    def staged_cancel(self, *, config_name='solve.yaml'):
        import os
        from unittest.mock import patch
        from llm4om import CancellationToken
        token = CancellationToken()
        replace = os.replace
        def stop_after_code(source, target, *args, **kwargs):
            result = replace(source, target, *args, **kwargs)
            if Path(target).name == 'build.json':
                token.cancel()
            return result
        with patch('os.replace', side_effect=stop_after_code):
            result = run_problem(self.inputs / 'problem.json', self.inputs / config_name,
                                 output_root=self.root / 'runs', cancellation=token)
        self.assertEqual(result.status, 'cancelled')
        return result

    def test_code_checkpoint_resumes_without_method_call_and_keeps_deadline(self):
        from llm4om import resume_run
        result = self.staged_cancel()
        checkpoint = json.loads((result.bundle_path / 'checkpoint.json').read_text())['payload']['state']
        restored = resume_run(result.bundle_path)
        self.assertEqual(restored.status, 'completed')
        state = json.loads((restored.bundle_path / 'checkpoint.json').read_text())['payload']['state']
        self.assertEqual(state['deadline'], checkpoint['deadline'])
        self.assertEqual(state['ledger']['llm_attempts'], 1)
        self.assertEqual(state['ledger']['solver_calls'], 1)
        self.assertEqual(state['artifact_ref'], checkpoint['artifact_ref'])

    def test_expired_resume_refuses_without_resetting_history_or_budget(self):
        import time
        from unittest.mock import patch
        from llm4om import resume_run
        from llm4om.contracts import RunError
        result = self.staged_cancel()
        checkpoint = (result.bundle_path / 'checkpoint.json').read_bytes()
        events = (result.bundle_path / 'events.jsonl').read_bytes()
        with patch('time.time', return_value=time.time() + 1000):
            with self.assertRaises(RunError) as caught:
                resume_run(result.bundle_path)
        self.assertEqual(caught.exception.code, 'deadline_exhausted')
        self.assertEqual((result.bundle_path / 'checkpoint.json').read_bytes(), checkpoint)
        self.assertEqual((result.bundle_path / 'events.jsonl').read_bytes(), events)

    def test_corrupted_checkpoint_and_changed_source_are_rejected(self):
        from llm4om import resume_run
        from llm4om.contracts import RunError
        result = self.staged_cancel()
        path = result.bundle_path / 'checkpoint.json'
        original = path.read_bytes()
        value = json.loads(original)
        value['payload']['state']['ledger']['llm_attempts'] = 0
        path.write_text(json.dumps(value))
        with self.assertRaises(RunError) as caught:
            resume_run(result.bundle_path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')
        path.write_bytes(original)
        (self.inputs / 'data/capacities.csv').write_text('mutated public data')
        with self.assertRaises(RunError) as caught:
            resume_run(result.bundle_path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')

    def test_cli_live_cancel_and_sigint_reap_only_owned_http_child(self):
        import os
        import signal
        import subprocess
        import sys
        import threading
        import time
        import yaml
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from llm4om import resume_run
        from llm4om.contracts import RunError
        entered, release = threading.Event(), threading.Event()
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                entered.set()
                release.wait(15)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(release.set)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        settings = yaml.safe_load((self.inputs / 'solve.yaml').read_text())
        settings['budget']['max_total_tokens'] = 30000
        settings['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic',
                           'config': {'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                                      'credential_env': 'S04B_TEST_KEY', 'max_retries': 0}}
        config = self.inputs / 'http.yaml'
        config.write_text(yaml.safe_dump(settings))
        env = {**os.environ, 'S04B_TEST_KEY': 'synthetic-fixture'}
        unrelated = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        self.addCleanup(unrelated.wait)
        self.addCleanup(unrelated.kill)
        for mode in ('command', 'sigint'):
            with self.subTest(mode=mode):
                entered.clear()
                output = self.root / mode
                process = subprocess.Popen([sys.executable, '-m', 'llm4om', 'run', '--problem',
                    str(self.inputs / 'problem.json'), '--config', str(config), '--output', str(output)],
                    env=env, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    self.assertTrue(entered.wait(6))
                    path = next(path for path in output.iterdir() if len(path.name) == 32)
                    with self.assertRaises(RunError) as caught:
                        resume_run(path)
                    self.assertEqual(caught.exception.code, 'run_busy')
                    children = subprocess.check_output(['ps', '-o', 'pid=', '--ppid', str(process.pid)], text=True).split()
                    self.assertTrue(children)
                    started = time.monotonic()
                    if mode == 'command':
                        cancelled = subprocess.run([sys.executable, '-m', 'llm4om', 'cancel', '--run-id',
                            path.name, '--output', str(output)], capture_output=True, text=True, timeout=3)
                        self.assertEqual(cancelled.returncode, 0, cancelled.stderr)
                        self.assertEqual(json.loads(cancelled.stdout)['status'], 'cancellation_requested')
                    else:
                        process.send_signal(signal.SIGINT)
                    stdout, stderr = process.communicate(timeout=4)
                    self.assertLess(time.monotonic() - started, 4)
                    self.assertEqual(json.loads(stdout)['status'], 'cancelled', stderr)
                    self.assertTrue(all(not Path('/proc', child).exists() for child in children))
                    self.assertIsNone(unrelated.poll())
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=2)

    def test_owned_trusted_resource_cancellation_is_bounded_and_keeps_partial_output(self):
        from concurrent.futures import ThreadPoolExecutor
        import sys
        import time
        from llm4om import CancellationToken
        from llm4om.contracts import RunError
        from llm4om.executors import run_owned_process
        token = CancellationToken()
        with ThreadPoolExecutor(1) as pool:
            pending = pool.submit(run_owned_process, [sys.executable, '-u', '-c',
                "import time; print('partial-resource-output'); time.sleep(20)"], b'',
                deadline=time.time() + 30, cancellation=token)
            time.sleep(0.2)
            token.cancel()
            with self.assertRaises(RunError) as caught:
                pending.result(timeout=2)
        self.assertEqual(caught.exception.code, 'run_cancelled')
        self.assertIn('partial-resource-output', caught.exception.details['stdout'])

    def test_factory_and_native_completed_candidates_resume_without_reexecution(self):
        import os
        import yaml
        from unittest.mock import patch
        from llm4om import CancellationToken, resume_run
        from test_factory_run import FactoryRunTests
        for mode, source, expected in (
            ('python_factory', (ROOT / 'examples/factories/production.py').read_text().replace(
                'pyo.NonNegativeIntegers', 'pyo.NonNegativeReals'), 40 / 3),
            ('native_gurobipy', (ROOT / 'examples/factories/production_gurobi.py').read_text().replace(
                'model.setObjective(gp.quicksum', 'model.setObjective(-10 + gp.quicksum'), 3),
        ):
            with self.subTest(mode=mode):
                self.config = yaml.safe_load((self.inputs / 'run.yaml').read_text())
                self.config['method']['config']['output_mode'] = mode
                if mode == 'native_gurobipy':
                    self.config['model_backend']['plugin_id'] = 'llm4om.model_backends.gurobipy'
                    self.config['solver']['plugin_id'] = 'llm4om.solvers.gurobi'
                FactoryRunTests.start_provider(self, source)
                if mode == 'native_gurobipy':
                    self.reply[mode] = self.reply.pop('python_factory')
                    self.reply['representation']['objective']['expression_text'] += ' - 10'
                else:
                    self.reply['representation']['variables'][0]['domain'] = 'continuous'
                config = self.inputs / (mode + '.yaml')
                config.write_text(yaml.safe_dump(self.config))
                os.environ['S02B_FIXTURE_KEY'] = 'synthetic-fixture'
                self.addCleanup(os.environ.pop, 'S02B_FIXTURE_KEY', None)
                token = CancellationToken()
                replace = os.replace
                def stop_after_execution(source, target, *args, **kwargs):
                    result = replace(source, target, *args, **kwargs)
                    if Path(target).name == 'execution.json':
                        token.cancel()
                    return result
                with patch('os.replace', side_effect=stop_after_execution):
                    result = run_problem(self.inputs / 'problem.json', config,
                                         output_root=self.root / 'runs', cancellation=token)
                self.assertEqual(result.status, 'cancelled')
                before = json.loads((result.bundle_path / 'bundle.json').read_text())
                restored = resume_run(result.bundle_path)
                self.assertEqual(restored.status, 'completed')
                bundle = json.loads((restored.bundle_path / 'bundle.json').read_text())
                self.assertEqual(bundle['solve_result_ref'], before['solve_result_ref'])
                self.assertEqual(bundle['execution_result_ref'], before['execution_result_ref'])
                solved = json.loads((restored.bundle_path / bundle['solve_result_ref']['relative_path']).read_text())
                self.assertAlmostEqual(solved['objective_value'], expected)
                self.assertEqual(len(self.requests), 1)
                ledger = json.loads((restored.bundle_path / 'budget-ledger.json').read_text())
                self.assertEqual(ledger['solver_calls'], 1)
                self.assertEqual(ledger['external_llm_requests'], 1)


if __name__ == '__main__':
    unittest.main()
