"""Public HTTP data previews preserve values and identify display limits."""

import base64
import csv
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
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
from urllib.error import URLError
from urllib.request import Request, ProxyHandler, build_opener


class WebDataPreviewTests(unittest.TestCase):
    def test_saved_csv_and_json_are_readable_bounded_and_linked_to_sources(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples/specs'
        stream = StringIO()
        writer = csv.writer(stream)
        writer.writerow(['label', 'note', 'amount'])
        writer.writerow(['A, special', 'first\nsecond', '003'])
        for index in range(24):
            writer.writerow([f'item{index}', '<img src=x onerror=alert(1)>', str(index)])
        uploads = [('products', 'csv', (fixture / 'data/products.csv').read_bytes()),
            ('capacities', 'csv', (fixture / 'data/capacities.csv').read_bytes()),
            ('notes', 'csv', stream.getvalue().encode()),
            ('settings', 'json', b'{"capacity":8,"costs":[3,2],"enabled":false,"unknown":null}')]
        formulation = json.loads((fixture / 'formulation.json').read_text())['representation']
        ir = json.loads((fixture / 'model-ir.json').read_text())
        compact = {'representation': formulation, 'structured_ir': {key: ir[key] for key in
            ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}}
        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                raw = json.dumps({'choices': [{'message': {'content': json.dumps(compact)}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}}).encode()
                self.send_response(200); self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
            def log_message(self, *args): pass
        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        threading.Thread(target=provider.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as root, socket.socket() as allocation:
            allocation.bind(('127.0.0.1', 0)); port = allocation.getsockname()[1]; allocation.close()
            process = subprocess.Popen([sys.executable, '-m', 'llm4om', 'serve', '--port', str(port), '--workspace', root],
                env={**os.environ, 'DATA_PREVIEW_TEST_KEY': 'synthetic-data-key'}, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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
                preview = api('/api/data-preview', {'format': 'csv', 'base64': base64.b64encode(uploads[2][2]).decode()})
                self.assertEqual(preview['rows'][0], ['A, special', 'first\nsecond', '003'])
                self.assertEqual(preview['total_items'], 25)
                self.assertTrue(preview['display_truncated'])
                self.assertEqual(api('/api/jobs')['jobs'], [])
                config['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'data-preview-fixture',
                    'config': {'base_url': f'http://127.0.0.1:{provider.server_port}/v1', 'credential_env': 'DATA_PREVIEW_TEST_KEY',
                        'max_retries': 0, 'max_output_tokens': 8192, 'timeout_s': 10}}
                job = api('/api/jobs', {'description': 'Maximize production profit with the supplied products and capacities.',
                    'config': config, 'data': [{'data_id': name, 'format': format_name, 'base64': base64.b64encode(raw).decode()}
                        for name, format_name, raw in uploads]})['job_id']
                for _ in range(300):
                    result = api('/api/jobs/' + job)
                    if result['job']['status'] in {'completed', 'failed'}: break
                    time.sleep(0.05)
                self.assertEqual(result['job']['status'], 'completed', result.get('bundle', {}).get('error'))
                previews = result['data_previews']
                notes = previews['notes']
                self.assertEqual(notes['columns'], ['label', 'note', 'amount'])
                self.assertEqual(notes['rows'][0], ['A, special', 'first\nsecond', '003'])
                self.assertEqual(len(notes['rows']), 20)
                self.assertEqual(notes['metadata']['total_rows'], 25)
                self.assertTrue(notes['metadata']['complete'])
                self.assertEqual(notes['rows'][1][1], '<img src=x onerror=alert(1)>')
                self.assertEqual(previews['settings']['rows'], [['capacity', '8'], ['costs', '[3, 2]'],
                    ['enabled', 'false'], ['unknown', 'null']])
                refs = {ref['data_id']: ref for ref in result['contents']['public-problem.json']['data_refs']}
                self.assertEqual(notes['metadata']['source_sha256'], refs['notes']['sha256'])
                self.assertEqual(result['contents']['checks/001/solve-result.json']['objective_value'], 13)
                self.assertFalse(any('private' in ref['relative_path'] for ref in result['artifacts']))
            finally:
                process.send_signal(signal.SIGTERM)
                process.communicate(timeout=10)
                provider.shutdown()
                provider.server_close()
