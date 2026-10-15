"""A running user request exposes only verified public progress and solves with HiGHS."""

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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import URLError


class WebProgressTests(unittest.TestCase):
    def test_live_steps_public_inputs_and_final_solution(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples/specs'
        representation = json.loads((fixture / 'formulation.json').read_text())['representation']
        for parameter, value in zip(representation['parameters'], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
            parameter.pop('source')
            parameter['value'] = value
        ir = json.loads((fixture / 'model-ir.json').read_text())
        compact = {'representation': representation, 'structured_ir': {key: ir[key] for key in
            ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}}
        started, release = threading.Event(), threading.Event()

        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                started.set()
                release.wait(timeout=20)
                raw = json.dumps({'choices': [{'message': {'content': json.dumps(compact)}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}}).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *args):
                pass

        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory() as root, socket.socket() as allocation:
            allocation.bind(('127.0.0.1', 0))
            port = allocation.getsockname()[1]
            allocation.close()
            process = subprocess.Popen([sys.executable, '-m', 'llm4om', 'serve', '--workspace', root, '--port', str(port)],
                env={**os.environ, 'LLM4OM_PROGRESS_TEST_KEY': 'synthetic-progress-key'},
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                opener = build_opener(ProxyHandler({}))
                url = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        bootstrap = json.load(opener.open(url + '/api/bootstrap', timeout=2))
                        break
                    except URLError:
                        time.sleep(0.05)
                else:
                    self.fail('Web did not start.')
                with opener.open(url + '/app.js') as asset:
                    self.assertIn(b'window.UI', asset.read())
                with opener.open(url + '/style.css') as asset:
                    styles = asset.read()
                    self.assertIn(b'katex', styles)
                    self.assertIn(b'data:font/woff2', styles)
                with opener.open(url + '/style.css') as asset:
                    self.assertIn("font-src 'self' data:", asset.headers.get('Content-Security-Policy', ''))
                config = bootstrap['config']
                config['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic-progress',
                    'config': {'base_url': f'http://127.0.0.1:{provider.server_port}/v1',
                        'credential_env': 'LLM4OM_PROGRESS_TEST_KEY', 'max_retries': 0, 'max_output_tokens': 8192, 'timeout_s': 30}}
                config['executor'] = {'plugin_id': 'llm4om.executors.trusted_local', 'config': {}}
                def api(path, payload=None):
                    raw = json.dumps(payload).encode() if payload is not None else None
                    headers = {'Origin': url, 'Content-Type': 'application/json', 'X-LLM4OM-Token': bootstrap['token']}
                    with opener.open(Request(url + path, data=raw, headers=headers), timeout=5) as response:
                        return json.load(response)
                job = api('/api/jobs', {'description': 'Production A and B: maximize 3*A+2*B; 2*A+B<=8; A+2*B<=8; nonnegative integers.', 'config': config})
                self.assertTrue(started.wait(timeout=10))
                live = api('/api/jobs/' + job['job_id'])
                self.assertIsNone(live['bundle'])
                self.assertEqual(live['job']['status'], 'running')
                self.assertIn('public-problem.json', live['contents'])
                step = next(event['method_event'] for event in live['events'] if event.get('method_event', {}).get('type') == 'modeling_step')
                self.assertEqual((step['phase'], step['status']), ('formulation', 'running'))
                self.assertIsInstance(step['timestamp'], float)
                self.assertNotIn('synthetic-progress-key', json.dumps(live))
                self.assertFalse(any('private' in key for key in live['contents']))
                release.set()
                for _ in range(200):
                    final = api('/api/jobs/' + job['job_id'])
                    if final['job']['status'] in {'completed', 'failed'}:
                        break
                    time.sleep(0.05)
                self.assertEqual(final['job']['status'], 'completed', final.get('bundle', {}).get('error'))
                solve = final['contents']['checks/001/solve-result.json']
                self.assertEqual(solve['objective_value'], 13)
                self.assertEqual(final['contents']['checks/001/solution.json']['variables'], {'qty_A': 3.0, 'qty_B': 2.0})
                self.assertTrue(any(event.get('method_event', {}).get('status') == 'completed' for event in final['events']))
            finally:
                release.set()
                process.send_signal(signal.SIGINT)
                process.communicate(timeout=15)
                provider.shutdown()
                provider.server_close()
                thread.join(timeout=2)
