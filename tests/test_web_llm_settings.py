"""Local LLM settings survive restart while public runs and exports exclude keys."""

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
from urllib.request import Request, build_opener, ProxyHandler


class WebLLMSettingsTests(unittest.TestCase):
    def test_two_protocols_use_selected_models_and_isolated_private_keys(self):
        fixtures = Path(__file__).resolve().parents[1] / 'examples/specs'
        representation = json.loads((fixtures / 'formulation.json').read_text())['representation']
        for parameter, value in zip(representation['parameters'], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
            parameter.pop('source')
            parameter['value'] = value
        ir = json.loads((fixtures / 'model-ir.json').read_text())
        answer = json.dumps({'representation': representation, 'structured_ir': {key: ir[key] for key in
            ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}})
        requests = []
        keys = ['synthetic-private-chat-key', 'synthetic-private-messages-key']

        class Provider(BaseHTTPRequestHandler):
            def send_json(self, value):
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                requests.append(('GET', self.path, self.headers.get('Authorization'), self.headers.get('x-api-key')))
                self.send_json({'data': [{'id': 'chosen-chat'}, {'id': 'chosen-messages'}]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(('POST', self.path, self.headers.get('Authorization'), self.headers.get('x-api-key'), body['model']))
                if self.path == '/v1/messages':
                    self.send_json({'id': 'fixture-messages', 'model': body['model'], 'stop_reason': 'end_turn',
                        'type': 'message', 'role': 'assistant',
                        'content': [{'type': 'text', 'text': answer}],
                        'usage': {'input_tokens': 100, 'output_tokens': 100, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}})
                else:
                    self.send_json({'choices': [{'message': {'content': answer}, 'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}})

            def log_message(self, *args):
                pass

        provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        thread = threading.Thread(target=provider.serve_forever, daemon=True)
        thread.start()
        with tempfile.TemporaryDirectory() as temporary, socket.socket() as allocation:
            root = Path(temporary)
            allocation.bind(('127.0.0.1', 0))
            port = allocation.getsockname()[1]
            allocation.close()
            environment = {key: value for key, value in os.environ.items() if key not in {'UNSET_WEB_TEST_KEY', 'LLM4OM_WEB_API_KEY'}}
            environment.update(LLM4OM_LLM_BASE_URL='http://127.0.0.1:9/v1', LLM4OM_LLM_API_KEY='synthetic-server-default-key')
            process = subprocess.Popen([sys.executable, '-m', 'llm4om', 'serve', '--workspace', str(root), '--port', str(port)],
                cwd=temporary, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            opener = build_opener(ProxyHandler({}))
            url = f'http://127.0.0.1:{port}'
            try:
                for _ in range(100):
                    try:
                        bootstrap = json.load(opener.open(url + '/api/bootstrap', timeout=2))
                        break
                    except URLError:
                        time.sleep(.05)
                else:
                    self.fail('Web did not start.')

                def api(path, payload=None, key=None):
                    headers = {'Origin': url, 'Content-Type': 'application/json', 'X-LLM4OM-Token': bootstrap['token']}
                    if key is not None:
                        headers['X-LLM4OM-Provider-Key'] = key
                    raw = json.dumps(payload).encode() if payload is not None else None
                    with opener.open(Request(url + path, data=raw, headers=headers), timeout=10) as response:
                        return json.load(response)

                presets = {item['id']: item for item in bootstrap['llm_presets']}
                self.assertEqual(set(presets), {'openai', 'google', 'kimi', 'glm', 'openrouter',
                    'bailian', 'deepseek', 'anthropic', 'openai_compatible'})
                credential = bootstrap['default_credential']
                self.assertTrue(credential['configured'])
                self.assertEqual(credential['preview'], 'synt••••-key')
                self.assertNotIn('synthetic-server-default-key', json.dumps(bootstrap))
                for preset_id, preset in presets.items():
                    if preset_id == 'openai_compatible':
                        continue
                    config = deepcopy(bootstrap['config'])
                    config['llm']['provider_plugin_id'] = preset['provider_plugin_id']
                    config['llm']['config']['base_url'] = preset['base_url']
                    self.assertEqual(api('/api/doctor', {'config': config, 'llm_preset': preset_id})
                        ['connectivity_checks']['status'], 'not_requested')
                    config['llm']['config']['base_url'] = 'https://rewritten.invalid/v1'
                    for endpoint in ('/api/doctor', '/api/jobs'):
                        with self.assertRaises(HTTPError) as fixed_url:
                            api(endpoint, {'config': config, 'llm_preset': preset_id, 'description': 'Public input'})
                        self.assertEqual(fixed_url.exception.code, 400)

                configs = []
                for index, protocol in enumerate(('openai_compatible', 'anthropic')):
                    config = deepcopy(bootstrap['config'])
                    config['llm'] = {'provider_plugin_id': 'llm4om.providers.' + protocol,
                        'model': ('chosen-chat', 'chosen-messages')[index], 'config': {
                            'base_url': f'http://127.0.0.1:{provider.server_port}/v1',
                            'credential_env': 'UNSET_WEB_TEST_KEY', 'max_retries': 0, 'timeout_s': 10, 'max_output_tokens': 4096}}
                    config['executor'] = {'plugin_id': 'llm4om.executors.trusted_local', 'config': {}}
                    configs.append(config)
                    doctor = api('/api/doctor', {'config': config, 'check_connectivity': True}, keys[index])
                    self.assertEqual(doctor['connectivity_checks']['status'], 'passed', doctor)
                    self.assertEqual(doctor['connectivity_checks']['checks'][0]['status'], 'reachable')
                    self.assertNotIn(keys[index], json.dumps(doctor))
                google = deepcopy(configs[0])
                google['llm']['config']['base_url'] = presets['google']['base_url']
                google['llm']['model'] = 'saved-google-model'
                api('/api/llm-settings', {'config': google, 'llm_preset': 'google'}, 'synthetic-google-private-key')
                saved = api('/api/llm-settings', {'config': configs[0], 'llm_preset': 'openai_compatible'}, keys[0])
                self.assertEqual(saved['llm_profiles']['google']['model'], 'saved-google-model')
                self.assertEqual(len(saved['llm_credentials']), 2)
                settings_path = root / '.private/llm-settings.local.json'
                self.assertEqual(settings_path.stat().st_mode & 0o777, 0o600)
                before = settings_path.read_bytes()
                tampered = deepcopy(google)
                tampered['llm']['config']['base_url'] = configs[0]['llm']['config']['base_url']
                with self.assertRaises(HTTPError):
                    api('/api/llm-settings', {'config': tampered, 'llm_preset': 'google'}, keys[0])
                self.assertEqual(settings_path.read_bytes(), before)
                public_settings = api('/api/bootstrap')
                for key in [*keys, 'synthetic-google-private-key']:
                    self.assertNotIn(key, json.dumps(public_settings))
                self.assertEqual(public_settings['config']['llm'], configs[0]['llm'])
                jobs = [api('/api/jobs', {'description': 'Maximize production A and B within capacities.', 'config': config}, keys[index] if index else None)
                    for index, config in enumerate(configs)]
                for job in jobs:
                    for _ in range(200):
                        result = api('/api/jobs/' + job['job_id'])
                        if result['job']['status'] in {'completed', 'failed'}:
                            break
                        time.sleep(.05)
                    self.assertEqual(result['job']['status'], 'completed', (result.get('bundle') or {}).get('error'))
                    self.assertEqual(result['contents']['candidates/001/solve-result.json']['objective_value'], 13)
                    for key in keys:
                        self.assertNotIn(key, json.dumps(result))
                    with opener.open(url + '/api/jobs/' + job['job_id'] + '/export') as response:
                        exported = response.read()
                        for key in keys:
                            self.assertNotIn(key.encode(), exported)
                self.assertIn(('POST', '/v1/chat/completions', 'Bearer ' + keys[0], None, 'chosen-chat'), requests)
                self.assertIn(('POST', '/v1/messages', None, keys[1], 'chosen-messages'), requests)
                process.send_signal(signal.SIGINT)
                process.communicate(timeout=15)
                environment['LLM4OM_LLM_API_KEY'] = ''
                process = subprocess.Popen([sys.executable, '-m', 'llm4om', 'serve', '--workspace', str(root), '--port', str(port)],
                    cwd=temporary, env=environment, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                for _ in range(100):
                    try:
                        bootstrap = json.load(opener.open(url + '/api/bootstrap', timeout=2))
                        break
                    except URLError:
                        time.sleep(.05)
                else:
                    self.fail('Web did not restart.')
                self.assertFalse(bootstrap['default_credential']['configured'])
                self.assertEqual(bootstrap['default_credential']['preview'], '')
                self.assertEqual(bootstrap['selected_llm_preset'], 'openai_compatible')
                self.assertEqual(bootstrap['config']['llm'], configs[0]['llm'])
                self.assertEqual(bootstrap['llm_profiles']['google']['model'], 'saved-google-model')
                self.assertEqual(len(bootstrap['llm_credentials']), 2)
                api('/api/doctor', {'config': configs[0], 'check_connectivity': True})
                api('/api/jobs/' + jobs[0]['job_id'] + '/resume', {'strategy': 'rerun'})
                for _ in range(200):
                    result = api('/api/jobs/' + jobs[0]['job_id'])
                    if result['job']['status'] in {'completed', 'failed'} and len(result['versions']) == 2:
                        break
                    time.sleep(.05)
                self.assertEqual(result['job']['status'], 'completed', (result.get('bundle') or {}).get('error'))
                self.assertEqual(len(result['versions']), 2)
                self.assertEqual(result['contents']['candidates/001/solve-result.json']['objective_value'], 13)
                for path in root.rglob('*'):
                    if path.is_file() and path != settings_path:
                        for key in keys:
                            self.assertNotIn(key.encode(), path.read_bytes(), str(path))
                with self.assertRaises(HTTPError) as invalid_key:
                    api('/api/doctor', {'config': configs[0]}, 'bad key')
                self.assertEqual(invalid_key.exception.code, 400)
                wrong_default = deepcopy(configs[0])
                wrong_default['llm']['config']['credential_env'] = 'LLM4OM_LLM_API_KEY'
                wrong_default['llm']['config']['base_url'] = 'http://127.0.0.1:1/v1'
                before = len(requests)
                with self.assertRaises(HTTPError):
                    api('/api/doctor', {'config': wrong_default, 'check_connectivity': True})
                self.assertEqual(len(requests), before)
                private = deepcopy(configs[0])
                private['llm']['config']['api_key'] = keys[0]
                with self.assertRaises(HTTPError):
                    api('/api/jobs', {'description': 'Public input', 'config': private}, keys[0])
                exposed = deepcopy(configs[0])
                exposed['llm']['model'] = keys[0]
                with self.assertRaises(HTTPError):
                    api('/api/jobs', {'description': 'Public input', 'config': exposed}, keys[0])
            finally:
                process.send_signal(signal.SIGINT)
                process.communicate(timeout=15)
                provider.shutdown()
                provider.server_close()
                thread.join(timeout=2)
