"""Explicit doctor checks use public CLI/HTTP and never submit generation."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llm4om.contracts import read_config


class ConnectivityTests(unittest.TestCase):
    def test_doctor_opt_in_protocols_and_unsupported_directory(self):
        requests = []
        response = {"status": 200}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, dict(self.headers)))
                self.send_response(response["status"])
                self.end_headers()
                self.wfile.write(json.dumps({"data": [{"id": "fixture-model"}]}).encode())

            def do_POST(self):
                requests.append(("UNEXPECTED_GENERATION", {}))
                self.send_response(500)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = read_config(Path(__file__).resolve().parents[1] / 'examples/specs/run.yaml')
            settings['executor'] = {'plugin_id': 'llm4om.executors.trusted_local', 'config': {}}
            settings['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'fixture-model',
                'config': {'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'credential_env': 'CONNECTIVITY_TEST_KEY', 'timeout_s': 5}}
            config = root / 'config.json'
            environment = {**os.environ, 'CONNECTIVITY_TEST_KEY': 'synthetic-connectivity-secret'}

            def doctor(*arguments):
                config.write_text(json.dumps(settings))
                result = subprocess.run([sys.executable, '-m', 'llm4om', 'doctor', '--config', str(config), *arguments],
                    env=environment, capture_output=True, text=True, timeout=30)
                self.assertNotIn('synthetic-connectivity-secret', result.stdout + result.stderr)
                return result.returncode, json.loads(result.stdout)

            code, report = doctor()
            self.assertEqual(code, 0)
            self.assertEqual(report['connectivity_checks']['status'], 'not_requested')
            self.assertEqual(requests, [])
            for plugin, header in [('openai_compatible', 'Authorization'), ('anthropic', 'X-Api-Key')]:
                settings['llm']['provider_plugin_id'] = 'llm4om.providers.' + plugin
                code, report = doctor('--check-connectivity')
                self.assertEqual(code, 0)
                self.assertTrue(report['preflight_ok'])
                self.assertEqual(report['connectivity_checks']['status'], 'passed')
                self.assertTrue(report['connectivity_checks']['checks'][0]['model_listed'])
                self.assertEqual(report['connectivity_checks']['generation_requests'], 0)
                self.assertEqual(requests[-1][0], '/v1/models')
                self.assertIn('synthetic-connectivity-secret', requests[-1][1][header])
            response['status'] = 404
            code, report = doctor('--check-connectivity')
            self.assertEqual(code, 1)
            self.assertTrue(report['preflight_ok'])
            self.assertEqual(report['connectivity_checks']['checks'][0]['status'], 'not_supported')
            self.assertEqual(len(requests), 3)
            self.assertTrue(all(path == '/v1/models' for path, _ in requests))


if __name__ == '__main__':
    unittest.main()
