"""Public Web batch submission, actual HiGHS evidence, export and reuse."""

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, build_opener, ProxyHandler

import yaml

from llm4om import import_dataset
from llm4om.contracts import RunError
from llm4om.web import WebWorkspace


class WebExperimentTests(unittest.TestCase):
    def test_submit_experiment_rejects_malformed_repeats_budget_exclusions(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples/specs'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            import_dataset(fixture / 'import-checker.json', root / 'tasks/production')
            workspace = WebWorkspace(root)
            try:
                config = yaml.safe_load((fixture / 'solve.yaml').read_text())
                task_id = next(iter(workspace._tasks()))
                budget = {'max_llm_attempts': 2, 'max_total_tokens': 60000, 'max_solver_calls': 2,
                          'wall_time_s': 180, 'max_concurrency': 2}
                base = {'task_ids': [task_id], 'configurations': [{'id': 'direct', 'config': config}]}
                cases = (
                    ({**base, 'repeats': 0, 'budget': budget, 'exclusions': []}, 'repeats must be an integer'),
                    ({**base, 'repeats': '2', 'budget': budget, 'exclusions': []}, 'repeats must be an integer'),
                    ({**base, 'repeats': 1, 'budget': {'max_llm_attempts': 2}, 'exclusions': []}, 'attempt/token/Solver caps'),
                    ({**base, 'repeats': 1, 'budget': {**budget, 'max_concurrency': 0}, 'exclusions': []}, 'within its cap'),
                    ({**base, 'repeats': 1, 'budget': budget, 'exclusions': [{'task_id': 't'}]}, 'needs a reason'),
                    ({**base, 'repeats': 1, 'budget': budget, 'exclusions': ['cell']}, 'needs a reason'))
                for payload, fragment in cases:
                    with self.assertRaises(RunError) as raised:
                        workspace.submit_experiment(payload)
                    self.assertIn(fragment, str(raised.exception))
                self.assertEqual(list((root / 'experiments').glob('*/job.json')), [])
            finally:
                workspace.close()

    def test_http_batch_real_solver_reports_and_completed_continue(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples/specs'
        ir = json.loads((fixture / 'model-ir.json').read_text())
        representation = json.loads((fixture / 'formulation.json').read_text())['representation']
        for parameter, value in zip(representation['parameters'], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
            parameter.pop('source')
            parameter['value'] = value
        compact = {'representation': representation, 'structured_ir': {key: ir[key] for key in ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}}
        requests = []
        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                raw = json.dumps({'choices': [{'message': {'content': json.dumps(compact)}, 'finish_reason': 'stop'}],
                                  'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def log_message(self, *args): pass
        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            import_dataset(fixture / 'import-checker.json', root / 'tasks/production')
            with socket.socket() as allocation:
                allocation.bind(('127.0.0.1', 0))
                port = allocation.getsockname()[1]
            environment = {**os.environ, 'LLM4OM_WEB_BATCH_TEST_KEY': 'synthetic-web-batch-key'}
            process = subprocess.Popen([sys.executable, '-m', 'llm4om', 'serve', '--workspace', str(root), '--port', str(port)],
                                       env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                opener = build_opener(ProxyHandler({}))
                url = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        with opener.open(url + '/api/bootstrap', timeout=2) as response:
                            bootstrap = json.load(response)
                        break
                    except URLError:
                        time.sleep(0.05)
                else:
                    self.fail('Web did not start.')
                def api(path, payload=None):
                    headers = {'Origin': url}
                    raw = None
                    if payload is not None:
                        raw = json.dumps(payload).encode()
                        headers.update({'Content-Type': 'application/json', 'X-LLM4OM-Token': bootstrap['token']})
                    with opener.open(Request(url + path, data=raw, headers=headers), timeout=5) as response:
                        return json.load(response)
                task = next(task for task in bootstrap['tasks'] if task['source']['dataset_id'] == 'original-production-micro-fixture')
                self.assertNotIn('oracle_ref', json.dumps(task))
                config = yaml.safe_load((fixture / 'solve.yaml').read_text())
                config['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic-web-batch',
                    'config': {'base_url': f'http://127.0.0.1:{provider.server_port}/v1', 'credential_env': 'LLM4OM_WEB_BATCH_TEST_KEY',
                               'max_retries': 0, 'timeout_s': 10, 'max_output_tokens': 8192}}
                config['budget']['max_total_tokens'] = 30000
                payload = {'task_ids': [task['task_id']], 'configurations': [{'id': 'direct-test-highs', 'config': config}],
                    'repeats': 2, 'budget': {'max_llm_attempts': 2, 'max_total_tokens': 60000, 'max_solver_calls': 2,
                    'wall_time_s': 180, 'max_concurrency': 2}, 'exclusions': []}
                job = api('/api/experiments', payload)
                identifier = job['experiment_id']
                def finished():
                    for _ in range(300):
                        result = api('/api/experiments/' + identifier)
                        if result['job']['status'] in {'finished', 'failed', 'cancelled'}:
                            return result
                        time.sleep(0.05)
                    self.fail('Batch did not finish.')
                result = finished()
                self.assertEqual(result['job']['status'], 'finished', result)
                self.assertEqual(result['progress']['N_saved'], 2)
                self.assertEqual(len(requests), 2)
                self.assertTrue(all(group['verified_solution_rate'] == 1 for group in result['summary']['groups']))
                run_ids = [row['run_id'] for row in result['rows']]
                with opener.open(url + '/api/experiments/' + identifier + '/export', timeout=5) as response:
                    archive_bytes = response.read()
                with zipfile.ZipFile(BytesIO(archive_bytes)) as archive:
                    self.assertEqual(len(archive.namelist()), 6)
                    self.assertFalse(any('private' in name for name in archive.namelist()))
                    self.assertFalse(any(b'synthetic-web-batch-key' in archive.read(name) or b'"oracle_ref"' in archive.read(name) for name in archive.namelist()))
                api('/api/experiments/' + identifier + '/resume', {})
                resumed = finished()
                self.assertEqual(resumed['job']['status'], 'finished')
                self.assertEqual([row['run_id'] for row in resumed['rows']], run_ids)
                self.assertEqual(len(requests), 2)
                self.assertTrue(all(group['N_reused'] == 1 for group in resumed['summary']['groups']))
                slow = (fixture.parent / 'factories/production.py').read_text().replace('def build_model(data):', 'def build_model(data):\n    import time\n    time.sleep(5)')
                compact.clear()
                compact.update({'representation': representation, 'python_factory': slow})
                config['method']['config']['output_mode'] = 'python_factory'
                config['budget']['max_solver_calls'] = 2
                config['executor'] = {'plugin_id': 'llm4om.executors.container', 'config': {'network': False,
                    'cpu_limit': 1, 'memory_limit_mb': 512, 'wall_time_s': 30}}
                payload['repeats'] = 1
                active = api('/api/experiments', payload)
                active_id = active['experiment_id']
                for _ in range(200):
                    bundles = list((root / 'experiments' / active_id).glob('batch/runs/*/*/events.jsonl'))
                    if bundles and 'code_saved' in bundles[0].read_text():
                        break
                    time.sleep(0.05)
                else:
                    self.fail('Factory did not reach the execution stage.')
                started = time.monotonic()
                api('/api/experiments/' + active_id + '/cancel', {})
                for _ in range(150):
                    cancelled = api('/api/experiments/' + active_id)
                    if cancelled['job']['status'] in {'finished', 'cancelled', 'failed'}:
                        break
                    time.sleep(0.05)
                self.assertLess(time.monotonic() - started, 5)
                self.assertEqual(cancelled['progress']['N_saved'], 1)
                self.assertEqual(cancelled['rows'][0]['status'], 'cancelled')
                self.assertEqual(cancelled['summary']['groups'][0]['verified_solution_denominator'], 1)
                calls_before = len(requests)
                api('/api/experiments/' + active_id + '/resume', {})
                for _ in range(300):
                    continued = api('/api/experiments/' + active_id)
                    if continued['job']['status'] in {'finished', 'cancelled', 'failed'}:
                        break
                    time.sleep(0.05)
                self.assertEqual(continued['job']['status'], 'finished', continued)
                self.assertEqual(continued['rows'][0]['status'], 'completed', continued)
                self.assertEqual(len(requests), calls_before)
                self.assertEqual(continued['summary']['groups'][0]['N_selected'], 1)


            finally:
                process.send_signal(signal.SIGINT)
                process.communicate(timeout=15)
                provider.shutdown()
                provider.server_close()
                thread.join(timeout=2)
