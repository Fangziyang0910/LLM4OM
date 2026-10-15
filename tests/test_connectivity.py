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
from urllib.parse import urlsplit

from llm4om.contracts import read_config
from llm4om.providers import provider_factory
from llm4om.workbench import llm_presets


class ConnectivityTests(unittest.TestCase):
    def test_preset_directories_use_their_protocol_and_keep_api_ids(self):
        requests = []
        reply = {}
        credential = 'synthetic-directory-private-key'

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, dict(self.headers)))
                self.send_response(404 if self.path.startswith('/compatible-mode/') else 200)
                self.end_headers()
                self.wfile.write(json.dumps(reply).encode())

            def do_POST(self):
                requests.append(('UNEXPECTED_GENERATION', {}))
                self.send_response(500)
                self.end_headers()

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for preset in llm_presets():
            with self.subTest(preset=preset['id']):
                path = urlsplit(preset['base_url']).path or '/v1'
                reply.clear()
                if preset['id'] == 'bailian':
                    reply.update(success=True, output={'total': 3, 'page_no': 1, 'page_size': 2,
                        'models': [{'model': 'directory-choice', 'name': 'Directory Choice'}, {'model': 'other-choice'}]})
                    expected_path = '/api/v1/models?capabilities=TG&page_no=1&page_size=100'
                else:
                    name_field = 'display_name' if preset['id'] == 'anthropic' else 'name'
                    reply.update(data=[{'id': 'directory-choice', name_field: 'Directory Choice'}, {'id': 'other-choice'}])
                    if preset['id'] == 'openrouter':
                        reply['data'][0]['description'] = 'x' * (1024 * 1024)
                    expected_path = path + '/models'
                provider = provider_factory(preset['provider_plugin_id']).create(
                    {'base_url': f'http://127.0.0.1:{server.server_port}' + path + '/',
                     'credential_env': 'DIRECTORY_TEST_KEY'}, 'directory-choice',
                    environment={'DIRECTORY_TEST_KEY': credential})
                result = provider.check_connectivity(10)
                self.assertEqual(result, {'status': 'reachable', 'model_listed': True,
                    'models': [{'id': 'directory-choice', 'name': 'Directory Choice'},
                        {'id': 'other-choice', 'name': 'other-choice'}], 'has_more': preset['id'] == 'bailian'})
                self.assertEqual(requests[-1][0], expected_path)
                headers = requests[-1][1]
                if preset['id'] == 'anthropic':
                    self.assertEqual(headers['X-Api-Key'], credential)
                    self.assertEqual(headers['Anthropic-Version'], '2023-06-01')
                    self.assertNotIn('Authorization', headers)
                else:
                    self.assertEqual(headers['Authorization'], 'Bearer ' + credential)
                    self.assertNotIn('X-Api-Key', headers)
                self.assertNotIn(credential, json.dumps(result))
        self.assertEqual(len(requests), len(llm_presets()))

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
