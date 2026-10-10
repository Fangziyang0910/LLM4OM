"""Historical HTTP views and explicit edit parents preserve completed versions."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, build_opener
from zipfile import ZipFile


class WebVersionTests(unittest.TestCase):
    def test_historical_read_export_and_branch_from_original_parent(self):
        fixtures = Path(__file__).resolve().parents[1] / 'examples/specs'
        representation = json.loads((fixtures / 'formulation.json').read_text())['representation']
        for parameter, value in zip(representation['parameters'], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
            parameter.pop('source')
            parameter['value'] = value
        ir = json.loads((fixtures / 'model-ir.json').read_text())
        compact = {'representation': representation, 'structured_ir': {key: ir[key] for key in
            ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}}
        requests = []
        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                raw = json.dumps({'choices': [{'message': {'content': json.dumps(compact)}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}}).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def log_message(self, *args): pass
        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as root, socket.socket() as allocation:
            allocation.bind(('127.0.0.1', 0)); port = allocation.getsockname()[1]; allocation.close()
            process = subprocess.Popen([sys.executable, '-m', 'llm4om', 'serve', '--port', str(port), '--workspace', root],
                env={**os.environ, 'VERSION_TEST_KEY': 'synthetic-version-key'}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                opener = build_opener(ProxyHandler({})); url = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        bootstrap = json.load(opener.open(url + '/api/bootstrap', timeout=2)); break
                    except URLError: time.sleep(0.05)
                else: self.fail('Web did not start.')
                def api(path, payload=None):
                    data = json.dumps(payload).encode() if payload is not None else None
                    with opener.open(Request(url + path, data=data, headers={'Origin': url,
                        'Content-Type': 'application/json', 'X-LLM4OM-Token': bootstrap['token']}), timeout=10) as response:
                        return json.load(response)
                config = bootstrap['config']
                config['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic-version',
                    'config': {'base_url': f'http://127.0.0.1:{provider.server_port}/v1', 'credential_env': 'VERSION_TEST_KEY',
                        'max_retries': 0, 'max_output_tokens': 8192, 'timeout_s': 10}}
                config['executor'] = {'plugin_id': 'llm4om.executors.trusted_local', 'config': {}}
                job = api('/api/jobs', {'description': 'Maximize 3A+2B, 2A+B<=8, A+2B<=8, nonnegative integer A/B.', 'config': config})['job_id']
                base = '/api/jobs/' + job
                def complete(previous=None):
                    for _ in range(400):
                        result = api(base)
                        if result['job']['status'] in {'completed', 'failed'} and result['job']['run_id'] != previous:
                            self.assertEqual(result['job']['status'], 'completed', result['bundle'].get('error')); return result
                        time.sleep(0.05)
                    self.fail('Version did not finish.')
                original = complete(); parent = original['job']['run_id']
                bundle_path = Path(root) / job / 'runs' / parent / 'bundle.json'
                parent_bytes = bundle_path.read_bytes()
                edits = api(base + '/edit-template?operation=code&run_id=' + parent)
                edits['reason'] = 'Set both variable upper bounds to1.'
                edits['code']['source'] = edits['code']['source'].replace('"upper_bound": null', '"upper_bound": 1')
                api(base + '/edit', {'parent_run_id': parent, 'edits': edits})
                child = complete(parent); child_id = child['job']['run_id']
                old = api(base + '?run_id=' + parent)
                self.assertTrue(old['historical']); self.assertEqual(old['latest_run_id'], child_id)
                self.assertEqual(old['contents']['candidates/001/solve-result.json']['objective_value'], 13)
                self.assertEqual(child['contents']['candidates/001/solve-result.json']['objective_value'], 5)
                self.assertEqual({v['run_id'] for v in old['versions']}, {parent, child_id})
                self.assertEqual(next(v for v in old['versions'] if v['run_id'] == child_id)['parent_run_id'], parent)
                with opener.open(url + base + '/export?run_id=' + parent) as response:
                    with ZipFile(BytesIO(response.read())) as archive:
                        self.assertEqual(json.loads(archive.read('bundle.json'))['run_id'], parent)
                for invalid in ['../.private', 'f' * 32]:
                    with self.assertRaises(HTTPError): api(base + '?run_id=' + invalid)
                problem = api(base + '/edit-template?operation=problem&run_id=' + parent)
                problem['problem']['revision'] = '2'; problem['problem']['description'] += ' Explicitly reviewed second version.'
                problem['reason'] = 'Regenerate from the original model Provider after a manual branch.'
                api(base + '/edit', {'parent_run_id': parent, 'edits': problem})
                branch = complete(child_id)
                self.assertEqual(branch['contents']['lineage.json']['parent_run_id'], parent)
                self.assertEqual(branch['contents']['public-problem.json']['revision'], '2')
                self.assertEqual(branch['contents']['candidates/001/solve-result.json']['objective_value'], 13)
                self.assertEqual(len(requests), 2); self.assertEqual(bundle_path.read_bytes(), parent_bytes)
            finally:
                process.send_signal(signal.SIGINT); process.communicate(timeout=15)
                provider.shutdown(); provider.server_close()
