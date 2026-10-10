"""HTTP entry point for explicitly authorized IPv4 remote access."""

import json
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, ProxyHandler


class WebBindTests(unittest.TestCase):
    def test_remote_host_same_origin_and_existing_submission_token(self):
        with tempfile.TemporaryDirectory() as root, socket.socket() as allocation:
            allocation.bind(('127.0.0.1', 0))
            port = allocation.getsockname()[1]
            allocation.close()
            process = subprocess.Popen([sys.executable, '-m', 'llm4om', 'serve', '--host', '0.0.0.0', '--port', str(port),
                                        '--workspace', root], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                opener = build_opener(ProxyHandler({}))
                url = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        opener.open(url, timeout=1).close()
                        break
                    except URLError:
                        time.sleep(0.05)
                else:
                    self.fail('Web server did not start.')
                remote = f'192.0.2.10:{port}'
                request = Request(url + '/api/bootstrap', headers={'Host': remote, 'Origin': 'http://' + remote})
                with opener.open(request, timeout=3) as response:
                    bootstrap = json.load(response)
                self.assertTrue(bootstrap['token'])
                for headers in ({'Host': remote, 'Origin': 'http://other.example'}, {'Host': f'rebind.example:{port}'}):
                    with self.assertRaises(HTTPError) as denied:
                        opener.open(Request(url + '/api/bootstrap', headers=headers), timeout=3)
                    self.assertEqual(json.load(denied.exception)['error']['code'], 'invalid_origin')
                payload = b'{"config": {}}'
                with self.assertRaises(HTTPError) as missing_token:
                    opener.open(Request(url + '/api/doctor', data=payload, headers={'Host': remote,
                        'Origin': 'http://' + remote, 'Content-Type': 'application/json'}), timeout=3)
                self.assertEqual(json.load(missing_token.exception)['error']['code'], 'invalid_origin')
                with self.assertRaises(HTTPError) as admitted:
                    opener.open(Request(url + '/api/doctor', data=payload, headers={'Host': remote,
                        'Origin': 'http://' + remote, 'Content-Type': 'application/json',
                        'X-LLM4OM-Token': bootstrap['token']}), timeout=3)
                self.assertEqual(json.load(admitted.exception)['error']['code'], 'invalid_config')
            finally:
                process.send_signal(signal.SIGINT)
                process.communicate(timeout=10)
