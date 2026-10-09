"""External HTTP fixtures exercise the public Provider/Gateway seam."""
import asyncio
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from llm4om.providers import OpenAICompatibleFactory, Gateway


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.requests = []
        self.responses = [(200, {"id": "reply-1", "model": "deepseek-v4-pro-0813", "choices": [
            {"message": {"content": "hello"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15,
                      "prompt_tokens_details": {"cached_tokens": 2},
                      "completion_tokens_details": {"reasoning_tokens": 1}}})]
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                owner.requests.append((dict(self.headers), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                status, body = owner.responses.pop(0)
                import time
                time.sleep(body.pop('fixture_delay', 0))
                drip = body.pop('fixture_drip', 0)
                self.send_response(status)
                self.end_headers()
                try:
                    raw = json.dumps(body).encode()
                    if drip:
                        for byte in raw:
                            self.wfile.write(bytes([byte]))
                            self.wfile.flush()
                            time.sleep(drip)
                    else:
                        self.wfile.write(raw)
                except BrokenPipeError:
                    pass
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.config = {"base_url": f"http://127.0.0.1:{self.server.server_port}/v1", "credential_env": "S05_TEST_KEY",
                       "max_output_tokens": 20, "max_retries": 2, "timeout_s": 1}
        self.budget = {"max_llm_attempts": 3, "max_total_tokens": 10000, "wall_time_s": 10, "max_concurrency": 1}

    def gateway(self):
        provider = OpenAICompatibleFactory().create(self.config, 'deepseek-v4-pro-0813',
                                                    environment={'S05_TEST_KEY': 'synthetic-secret'})
        return Gateway(provider, self.budget, self.root / 'private')

    def test_slow_drip_obeys_request_and_run_deadlines(self):
        for run_limit in [False, True]:
            with self.subTest(run_limit=run_limit):
                self.config['timeout_s'] = 5 if run_limit else 1
                self.budget['wall_time_s'] = 1 if run_limit else 10
                # Leave time for a cold Python process, then keep the body dripping past the limit.
                self.responses = [(200, {'fixture_drip': 0.02, 'choices': [], 'padding': 'x' * 1000})]
                provider = OpenAICompatibleFactory().create(self.config, 'deepseek-v4-pro-0813',
                                                            environment={'S05_TEST_KEY': 'synthetic-secret'})
                gateway = Gateway(provider, self.budget, self.root / str(run_limit))
                started = time.monotonic()
                with self.assertRaises(ValueError) as caught:
                    asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'drip'}]}))
                self.assertEqual(caught.exception.code, 'provider_timeout')
                self.assertEqual(len(self.requests), 1 + int(run_limit))
                self.assertLess(time.monotonic() - started, 2)
                self.assertGreater(gateway.ledger['reserved_tokens'], 0)

    def test_cancellation_reaps_transport_and_preserves_unknown_reservation(self):
        self.config['timeout_s'] = 30
        self.responses[0][1]['fixture_delay'] = 2
        gateway = self.gateway()
        request = {'request_id': 'cancelled', 'messages': [{'role': 'user', 'content': 'cancel'}]}
        children_path = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children')
        before = set(children_path.read_text().split())
        threads_before = {thread.ident for thread in threading.enumerate()}

        async def cancel():
            task = asyncio.create_task(gateway.complete(request))
            limit = time.monotonic() + 2
            while not self.requests:
                self.assertLess(time.monotonic(), limit)
                await asyncio.sleep(0.01)
            children = set(children_path.read_text().split()) - before
            self.assertEqual(len(children), 1)
            for child in children:
                self.assertNotIn(b'synthetic-secret', Path(f'/proc/{child}/cmdline').read_bytes())
                self.assertNotIn(b'synthetic-secret', Path(f'/proc/{child}/environ').read_bytes())
            started = time.monotonic()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertLess(time.monotonic() - started, 0.5)
            for child in children:
                self.assertFalse(Path(f'/proc/{child}').exists())

        asyncio.run(cancel())
        # HTTP fixture threads belong to the server; Gateway must create no transport threads.
        self.assertFalse([thread for thread in threading.enumerate()
                          if thread.ident not in threads_before and 'process_request_thread' not in thread.name])
        reserved = gateway.ledger['reserved_tokens']
        restored = self.gateway()
        self.assertGreater(reserved, 0)
        self.assertEqual(restored.ledger['reserved_tokens'], reserved)
        self.assertIsNone(restored.ledger['total_tokens'])
        self.assertEqual(restored.trace[0]['status'], 'unknown')
        self.assertNotIn('synthetic-secret', json.dumps(restored.trace))
        with self.assertRaises(ValueError) as caught:
            asyncio.run(restored.complete(request))
        self.assertEqual(caught.exception.code, 'provider_outcome_unknown')
        self.assertEqual(len(self.requests), 1)

    def test_identical_default_calls_are_independent_samples(self):
        self.responses.append((200, json.loads(json.dumps(self.responses[0][1]))))
        request = {'messages': [{'role': 'user', 'content': 'same prompt'}]}
        gateway = self.gateway()
        first = asyncio.run(gateway.complete(request))
        second = asyncio.run(self.gateway().complete(request))
        self.assertNotEqual(first, second)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(len({item['request_id'] for item in gateway.trace}), 2)
        self.assertEqual(gateway.ledger['known_total_tokens'], 30)
        self.assertEqual(gateway.ledger['reserved_tokens'], 0)

    def test_provider_direct_slow_drip_deadline(self):
        self.responses = [(200, {'fixture_drip': 0.02, 'choices': []})]
        provider = self.gateway().provider
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            provider.complete([{'role': 'user', 'content': 'direct drip'}], 0.3)
        self.assertLess(time.monotonic() - started, 0.8)
        self.assertEqual(len(self.requests), 1)

    def test_success_usage_and_saved_response_replay(self):
        request = {'request_id': 'saved-success', 'messages': [{'role': 'user', 'content': 'public problem'}]}
        gateway = self.gateway()
        first = asyncio.run(gateway.complete(request))
        restored = self.gateway()
        second = asyncio.run(restored.complete(request))
        self.assertEqual(first, second)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][1]['model'], 'deepseek-v4-pro-0813')
        self.assertEqual(restored.ledger['total_tokens'], 15)
        self.assertIsNone(restored.ledger['cost'])
        self.assertEqual(restored.trace[0]['usage']['cached_tokens'], 2)
        self.assertNotIn('synthetic-secret', json.dumps(restored.trace))
        self.assertNotIn('public problem', json.dumps(restored.trace))
        self.assertEqual(os.stat(self.root / 'private').st_mode & 0o777, 0o700)

    def test_retry_has_independent_attempts_and_auth_is_not_retried(self):
        success = self.responses[0]
        self.responses = [(429, {'error': 'synthetic-secret'}), (503, {}), success]
        gateway = self.gateway()
        asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'retry'}]}))
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(len({item['attempt_id'] for item in gateway.trace}), 3)
        self.assertIsNone(gateway.ledger['total_tokens'])
        self.assertGreater(gateway.ledger['reserved_tokens'], 0)
        self.responses = [(401, {'error': 'synthetic-secret'})]
        with self.assertRaises(ValueError) as caught:
            asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'auth'}]}))
        self.assertEqual(caught.exception.code, 'budget_exhausted')
        self.assertEqual(len(self.requests), 3)

    def test_auth_body_is_private_and_auth_does_not_retry(self):
        self.responses = [(401, {'error': 'synthetic-secret'})]
        gateway = self.gateway()
        with self.assertRaises(ValueError) as caught:
            asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'auth'}]}))
        self.assertEqual(caught.exception.code, 'auth_error')
        self.assertNotIn('synthetic-secret', str(caught.exception))
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn('synthetic-secret', json.dumps(gateway.trace))

    def test_missing_usage_holds_reservation_and_unpriced_cost_is_null(self):
        self.responses[0][1].pop('usage')
        gateway = self.gateway()
        asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'unknown usage'}]}))
        self.assertIsNone(gateway.ledger['total_tokens'])
        self.assertIsNone(gateway.ledger['cost'])
        self.assertGreater(gateway.ledger['reserved_tokens'], 0)

    def test_budget_and_unsupported_request_do_not_send_http(self):
        from llm4om.contracts import RunError
        self.budget['max_total_tokens'] = 1
        gateway = self.gateway()
        for request, code in [({'messages': [{'role': 'user', 'content': 'budget'}]}, 'budget_exhausted'),
                              ({'messages': [], 'tools': []}, 'capability_mismatch')]:
            with self.assertRaises(RunError) as caught:
                asyncio.run(gateway.complete(request))
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.requests, [])


    def test_retry_bound_and_invalid_request_not_retried(self):
        self.config['max_retries'] = 1
        self.responses = [(503, {}), (503, {})]
        gateway = self.gateway()
        with self.assertRaises(ValueError) as caught:
            asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'failure'}]}))
        self.assertEqual(caught.exception.code, 'provider_error')
        self.assertEqual(len(self.requests), 2)
        self.responses = [(400, {'error': 'synthetic-secret'})]
        with self.assertRaises(ValueError) as caught:
            asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'invalid'}]}))
        self.assertEqual(caught.exception.code, 'invalid_provider_request')
        self.assertEqual(len(self.requests), 3)

    def test_timeout_restore_retains_unknown_and_does_not_resend(self):
        self.config['timeout_s'] = 0.3
        self.responses[0][1]['fixture_delay'] = 1
        gateway = self.gateway()
        request = {'request_id': 'saved-timeout', 'messages': [{'role': 'user', 'content': 'timeout'}]}
        with self.assertRaises(ValueError) as caught:
            asyncio.run(gateway.complete(request))
        self.assertEqual(caught.exception.code, 'provider_timeout')
        reserved = gateway.ledger['reserved_tokens']
        self.assertGreater(reserved, 0)
        restored = self.gateway()
        with self.assertRaises(ValueError) as caught:
            asyncio.run(restored.complete(request))
        self.assertEqual(caught.exception.code, 'provider_outcome_unknown')
        self.assertEqual(restored.ledger['reserved_tokens'], reserved)
        self.assertEqual(len(self.requests), 1)

    def test_last_call_overrun_is_saved_but_does_not_reissue(self):
        self.responses[0][1]['usage']['total_tokens'] = 10001
        gateway = self.gateway()
        request = {'request_id': 'saved-overrun', 'messages': [{'role': 'user', 'content': 'overrun'}]}
        for instance in [gateway, self.gateway()]:
            with self.assertRaises(ValueError) as caught:
                asyncio.run(instance.complete(request))
            self.assertEqual(caught.exception.code, 'token_budget_overrun')
        self.assertEqual(len(self.requests), 1)

    def test_settlement_counts_unknown_attempt_reservations(self):
        success = self.responses[0]
        success[1]['usage']['total_tokens'] = 9900
        self.responses = [(503, {}), success]
        gateway = self.gateway()
        request = {'request_id': 'saved-reserved-overrun', 'messages': [{'role': 'user', 'content': 'retry'}]}
        with self.assertRaises(ValueError) as caught:
            asyncio.run(gateway.complete(request))
        self.assertEqual(caught.exception.code, 'token_budget_overrun')
        self.assertGreater(gateway.ledger['reserved_tokens'] + gateway.ledger['known_total_tokens'], 10000)
        with self.assertRaises(ValueError) as caught:
            asyncio.run(self.gateway().complete(request))
        self.assertEqual(caught.exception.code, 'token_budget_overrun')
        self.assertEqual(len(self.requests), 2)

    def test_connection_failure_has_bounded_attempts(self):
        self.server.shutdown()
        self.server.server_close()
        gateway = self.gateway()
        with self.assertRaises(ValueError) as caught:
            asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'connection'}]}))
        self.assertEqual(caught.exception.code, 'provider_connection_error')
        self.assertEqual(gateway.ledger['llm_attempts'], 3)
        self.assertGreater(gateway.ledger['reserved_tokens'], 0)

    def test_two_gateways_share_atomic_attempt_and_concurrency_limits(self):
        self.budget['max_llm_attempts'] = 1
        self.responses[0][1]['fixture_delay'] = 0.1
        first, second = self.gateway(), self.gateway()
        async def requests():
            return await asyncio.gather(
                first.complete({'messages': [{'role': 'user', 'content': 'one'}]}),
                second.complete({'messages': [{'role': 'user', 'content': 'two'}]}), return_exceptions=True)
        outcomes = asyncio.run(requests())
        self.assertEqual(sum(isinstance(value, ValueError) for value in outcomes), 1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(second.ledger['llm_attempts'], 1)

    def test_identical_concurrent_identity_is_not_sent_twice(self):
        self.budget['max_concurrency'] = 2
        self.responses[0][1]['fixture_delay'] = 0.1
        first, second = self.gateway(), self.gateway()
        request = {'request_id': 'same-request', 'messages': [{'role': 'user', 'content': 'one'}]}
        async def requests():
            return await asyncio.gather(first.complete(request), second.complete(request), return_exceptions=True)
        outcomes = asyncio.run(requests())
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(sum(isinstance(value, ValueError) for value in outcomes), 1)

    def test_deadline_bounds_retry_and_invalid_reply_is_not_echoed(self):
        self.budget['wall_time_s'] = 0.4
        self.responses = [(503, {'fixture_delay': 0.25})]
        gateway = self.gateway()
        started = time.monotonic()
        with self.assertRaises(ValueError) as caught:
            asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'deadline'}]}))
        # A busy host can reach the deadline during HTTP rather than retry admission.
        self.assertIn(caught.exception.code, {'deadline_exhausted', 'provider_timeout'})
        self.assertLess(time.monotonic() - started, 1)
        self.assertLessEqual(len(self.requests), 2)

    def test_invalid_reply_body_is_not_exported(self):
        self.responses = [(200, {'choices': 'synthetic-secret'})]
        gateway = self.gateway()
        with self.assertRaises(ValueError) as caught:
            asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'invalid reply'}]}))
        self.assertEqual(caught.exception.code, 'invalid_provider_response')
        self.assertNotIn('synthetic-secret', str(caught.exception) + json.dumps(gateway.trace))
        self.assertEqual(len(self.requests), 1)


class CredentialAdmissionTests(unittest.TestCase):
    def test_literal_env_process_precedence_and_no_execution(self):
        from llm4om.providers import credential_environment
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.env'
            marker = Path(directory) / 'executed'
            path.write_text(f"KEY='file-value'\nOTHER=$(touch {marker})\n")
            values = credential_environment(path, {'KEY': 'process-value'})
            self.assertEqual(values['KEY'], 'process-value')
            self.assertEqual(values['OTHER'], f'$(touch {marker})')
            self.assertFalse(marker.exists())

    def test_missing_credentials_and_unsupported_config_fail_admission(self):
        from llm4om.contracts import RunError
        config = {'base_url': 'https://example.invalid/v1', 'credential_env': 'S05_TEST_KEY'}
        factory = OpenAICompatibleFactory()
        for candidate, code in [(config, 'auth_error'), ({**config, 'stream': True}, 'invalid_config'),
                                ({**config, 'base_url': 'https://example.invalid:abc/v1'}, 'invalid_config'),
                                ({**config, 'base_url': 'https://example.invalid:70000/v1'}, 'invalid_config'),
                                ({**config, 'base_url': 'https://user:secret@example.invalid'}, 'invalid_config')]:
            with self.assertRaises(RunError) as caught:
                factory.create(candidate, 'deepseek-v4-pro-0813', environment={})
            self.assertEqual(caught.exception.code, code)


class GatewayAdmissionTests(unittest.TestCase):
    def test_invalid_requests_budget_and_deadline_never_reach_http(self):
        from llm4om.contracts import RunError
        import time
        provider = OpenAICompatibleFactory().create(
            {'base_url': 'https://example.invalid/v1', 'credential_env': 'KEY'},
            'deepseek-v4-pro-0813', environment={'KEY': 'synthetic-key'})
        budget = {'max_llm_attempts': 1, 'max_total_tokens': 1, 'wall_time_s': 10, 'max_concurrency': 1}
        with tempfile.TemporaryDirectory() as directory:
            gateway = Gateway(provider, budget, Path(directory) / 'budget')
            for request, code in [({'messages': [], 'tools': []}, 'capability_mismatch'),
                                  ({'messages': []}, 'invalid_llm_request'),
                                  ({'messages': [{'role': 'user', 'content': 'public'}]}, 'budget_exhausted')]:
                with self.assertRaises(RunError) as caught:
                    asyncio.run(gateway.complete(request))
                self.assertEqual(caught.exception.code, code)
            self.assertEqual(gateway.ledger['external_llm_requests'], 0)
            expired = Gateway(provider, {**budget, 'max_total_tokens': 10000}, Path(directory) / 'expired', deadline=time.time() - 1)
            with self.assertRaises(RunError) as caught:
                asyncio.run(expired.complete({'messages': [{'role': 'user', 'content': 'public'}]}))
            self.assertEqual(caught.exception.code, 'deadline_exhausted')
