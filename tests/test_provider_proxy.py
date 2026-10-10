"""Explicit routing uses the public Provider interface without an upstream DNS lookup."""

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import unittest
from unittest.mock import patch

from llm4om.contracts import RunError, parse_json
from llm4om.providers import OpenAICompatibleFactory, AnthropicFactory


class ProviderProxyTests(unittest.TestCase):
    def test_both_protocols_use_explicit_proxy_even_with_no_proxy(self):
        requests = []
        class Proxy(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((self.path, self.headers, json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                if self.path.endswith('/messages'):
                    value = {'type': 'message', 'role': 'assistant', 'content': [{'type': 'text', 'text': 'proxied'}],
                        'stop_reason': 'end_turn', 'usage': {'input_tokens': 1, 'output_tokens': 1}}
                else:
                    value = {'choices': [{'message': {'content': 'proxied'}, 'finish_reason': 'stop'}],
                        'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}}
                raw = json.dumps(value).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Proxy)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for factory in [OpenAICompatibleFactory(), AnthropicFactory()]:
                config = {'base_url': 'http://localhost:1/v1', 'credential_env': 'PROXY_TEST_KEY',
                    'proxy_url': f'http://127.0.0.1:{server.server_port}', 'max_retries': 0}
                provider = factory.create(config, 'fixture', environment={'PROXY_TEST_KEY': 'synthetic-proxy-key'})
                with patch.dict(os.environ, {'NO_PROXY': '*', 'no_proxy': '*'}):
                    result = asyncio.run(provider.acomplete([{'role': 'user', 'content': 'hello'}], 10))
                self.assertEqual(result['text'], 'proxied')
            self.assertEqual([request[0] for request in requests], ['http://localhost:1/v1/chat/completions', 'http://localhost:1/v1/messages'])
            self.assertEqual(requests[0][1]['Authorization'], 'Bearer synthetic-proxy-key')
            self.assertEqual(requests[1][1]['x-api-key'], 'synthetic-proxy-key')
        finally:
            server.shutdown()
            server.server_close()

    def test_invalid_or_credentialed_proxy_rejected_before_transport(self):
        for url in ['socks5://localhost:7890', 'http://localhost:0', 'http://localhost:70000',
                    'http://user:secret@localhost:7890', 'http://localhost:7890/path', 'http://localhost:7890?token=secret']:
            with self.subTest(url=url):
                with self.assertRaises(RunError) as caught:
                    OpenAICompatibleFactory().create({'base_url': 'https://example.invalid/v1',
                        'credential_env': 'PROXY_TEST_KEY', 'proxy_url': url}, 'fixture',
                        environment={'PROXY_TEST_KEY': 'synthetic-proxy-key'})
                self.assertEqual(caught.exception.code, 'invalid_config')

    def test_proxy_credentials_rejected_at_public_config_boundary(self):
        import yaml
        from pathlib import Path
        config = yaml.safe_load((Path(__file__).resolve().parents[1] / 'examples/specs/run.yaml').read_text())
        config['llm']['config']['proxy_url'] = 'http://user:synthetic-secret@localhost:7890'
        with self.assertRaises(RunError) as caught:
            parse_json(json.dumps(config).encode())
        self.assertEqual(caught.exception.code, 'private_input')
