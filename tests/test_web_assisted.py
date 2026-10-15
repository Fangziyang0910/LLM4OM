"""HTTP problem revision and Code editing reuse paid responses and preserve parents."""

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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, build_opener, ProxyHandler

import yaml


class WebAssistedTests(unittest.TestCase):
    def test_http_concurrent_runs_control_and_assisted_edits(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples/specs'
        problem = json.loads((fixture / 'problem.json').read_text())
        representation = json.loads((fixture / 'formulation.json').read_text())['representation']
        for parameter, value in zip(representation['parameters'], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
            parameter.pop('source')
            parameter['value'] = value
        ir = json.loads((fixture / 'model-ir.json').read_text())
        compact = {'representation': representation, 'structured_ir': {key: ir[key] for key in ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}}
        requests = []
        overlap = threading.Barrier(2)
        slow_started = threading.Event()
        release_slow = threading.Event()
        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                if len(requests) <= 2:
                    overlap.wait(timeout=10)
                elif 'cancel-this-public-request' in json.dumps(requests[-1]):
                    slow_started.set()
                    release_slow.wait(timeout=10)
                raw = json.dumps({'choices': [{'message': {'content': json.dumps(compact)}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *args): pass
        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory() as directory:
            with socket.socket() as allocation:
                allocation.bind(('127.0.0.1', 0)); port = allocation.getsockname()[1]
            environment = {**os.environ, 'LLM4OM_WEB_EDIT_TEST_KEY': 'synthetic-edit-key'}
            server = subprocess.Popen([sys.executable, '-m', 'llm4om', 'serve', '--workspace', directory, '--port', str(port)],
                env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                opener = build_opener(ProxyHandler({})); url = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        with opener.open(url + '/api/bootstrap', timeout=2) as response: bootstrap = json.load(response)
                        break
                    except URLError: time.sleep(0.05)
                else: self.fail('Web did not start.')
                def api(path, payload=None):
                    raw = json.dumps(payload).encode() if payload is not None else None
                    headers = {'Origin': url, 'Content-Type': 'application/json', 'X-LLM4OM-Token': bootstrap['token']}
                    with opener.open(Request(url + path, data=raw, headers=headers), timeout=5) as response: return json.load(response)
                config = yaml.safe_load((fixture / 'solve.yaml').read_text())
                config['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic-edit',
                    'config': {'base_url': f'http://127.0.0.1:{provider.server_port}/v1', 'credential_env': 'LLM4OM_WEB_EDIT_TEST_KEY',
                               'max_retries': 0, 'max_output_tokens': 8192, 'timeout_s': 10}}
                config['budget'].update(max_llm_attempts=4, max_total_tokens=100000, max_solver_calls=4, max_checks=4)
                import base64
                data = [{'data_id': ref['data_id'], 'format': ref['format'], 'schema': ref['schema'],
                         'base64': base64.b64encode((fixture / ref['path']).read_bytes()).decode()} for ref in problem['data_refs']]
                payload = {'problem': problem, 'description': problem['description'], 'config': config, 'data': data}
                job = api('/api/jobs', payload)
                identifier = job['job_id']
                second = api('/api/jobs', payload)['job_id']
                self.assertTrue(api('/api/doctor', {'config': config})['preflight_ok'])
                self.assertTrue(api('/api/bootstrap')['plugins'])
                def completed(previous=None, selected=None):
                    for _ in range(400):
                        record = api('/api/jobs/' + (selected or identifier))
                        if record['job']['status'] in {'completed', 'failed', 'cancelled'} and record['job']['run_id'] != previous:
                            return record
                        time.sleep(0.05)
                    self.fail('Assisted request did not finish.')
                original = completed(); self.assertEqual(original['job']['status'], 'completed', original)
                concurrent = completed(selected=second)
                self.assertEqual(concurrent['job']['status'], 'completed', concurrent)
                self.assertNotEqual(original['job']['run_id'], concurrent['job']['run_id'])
                self.assertEqual(len(requests), 2)
                api('/api/jobs/' + second + '/resume', {})
                self.assertEqual(completed(selected=second)['job']['status'], 'completed')
                self.assertEqual(len(requests), 2)
                original_id = original['job']['run_id']
                parent_bytes = (Path(directory) / identifier / 'runs' / original_id / 'bundle.json').read_bytes()
                value = api('/api/jobs/' + identifier + '/edit-template?operation=problem')
                value['reason'] = 'Explicitly revalidate this public problem as revision two.'
                value['problem']['revision'] = '2'
                value['problem']['description'] += ' 本次为显式修订验证。'
                api('/api/jobs/' + identifier + '/edit', {'edits': value})
                revised = completed(original_id); self.assertEqual(revised['job']['status'], 'completed', revised)
                self.assertTrue(revised['bundle']['assisted'])
                self.assertEqual(len(requests), 3)
                revised_id = revised['job']['run_id']
                value = api('/api/jobs/' + identifier + '/edit-template?operation=code')
                value['reason'] = 'Explore a manual Code bound without another LLM request.'
                value['code']['source'] = value['code']['source'].replace('"upper_bound": null', '"upper_bound": 1')
                api('/api/jobs/' + identifier + '/edit', {'edits': value})
                edited = completed(revised_id); self.assertEqual(edited['job']['status'], 'completed', edited)
                self.assertTrue(edited['bundle']['assisted'])
                self.assertEqual(len(requests), 3)
                run = Path(directory) / identifier / 'runs' / edited['job']['run_id']
                solve = json.loads((run / edited['bundle']['solve_result_ref']['relative_path']).read_text())
                self.assertEqual(solve['objective_value'], 5)
                self.assertEqual((Path(directory) / identifier / 'runs' / original_id / 'bundle.json').read_bytes(), parent_bytes)
                ledger = json.loads((run / 'budget-ledger.json').read_text())
                self.assertEqual(ledger['llm_attempts'], 2)
                self.assertEqual(ledger['solver_calls'], 3)
                self.assertEqual(ledger['checks'], 3)
                self.assertEqual(ledger['evidence_origin'], 'assisted')
                slow_problem = {**problem, 'description': problem['description'] + ' cancel-this-public-request'}
                cancelled_id = api('/api/jobs', {**payload, 'problem': slow_problem})['job_id']
                self.assertTrue(slow_started.wait(timeout=10))
                api('/api/jobs/' + cancelled_id + '/cancel', {})
                cancelled = completed(selected=cancelled_id)
                self.assertEqual(cancelled['job']['status'], 'cancelled', cancelled)
                self.assertEqual(cancelled['bundle']['status'], 'cancelled')
                self.assertEqual(api('/api/jobs/' + second)['job']['status'], 'completed')
                release_slow.set()
            finally:
                release_slow.set()
                server.send_signal(signal.SIGINT); server.communicate(timeout=15)
                provider.shutdown(); provider.server_close(); thread.join(timeout=2)
