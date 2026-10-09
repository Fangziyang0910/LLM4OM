"""Role routing shares actual HTTP, budgets and durable Gateway identity."""

import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llm4om.contracts import RunError
from llm4om import CancellationToken
from llm4om.providers import Gateway, OpenAICompatibleFactory, AnthropicFactory


class RoleModelTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.requests = []
        self.delay = 0
        self.failure_status = None
        owner = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.requests.append(request)
                time.sleep(owner.delay)
                self.send_response(owner.failure_status or 200)
                self.end_headers()
                body = ({'id': 'message-1', 'type': 'message', 'role': 'assistant', 'model': request['model'],
                    'content': [{'type': 'text', 'text': request['model']}], 'stop_reason': 'end_turn',
                    'usage': {'input_tokens': 10, 'output_tokens': 5}} if self.path.endswith('/messages') else {
                    'model': request['model'], 'choices': [{'message': {'content': request['model']}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}})
                try:
                    self.wfile.write(json.dumps(body).encode())
                except BrokenPipeError:
                    pass
            def log_message(self, *args): pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.config = {'base_url': f'http://127.0.0.1:{self.server.server_port}/v1', 'credential_env': 'ROLE_TEST_KEY',
            'max_output_tokens': 20, 'max_retries': 0, 'timeout_s': 2}
        self.budget = {'max_llm_attempts': 2, 'max_total_tokens': 10000, 'max_concurrency': 1, 'wall_time_s': 20}

    def gateway(self, *, restored=False, critic_model='critic-model'):
        factory = OpenAICompatibleFactory()
        if restored:
            default = factory.restore(self.config, 'default-model', environment=lambda: {})
            critic = factory.restore({**self.config, 'max_output_tokens': 31}, critic_model, environment=lambda: {})
        else:
            default = factory.create(self.config, 'default-model', environment={'ROLE_TEST_KEY': 'synthetic'})
            critic = factory.create({**self.config, 'max_output_tokens': 31}, critic_model, environment={'ROLE_TEST_KEY': 'synthetic'})
        return Gateway(default, self.budget, self.root / 'private', role_providers={'critic': critic})

    def test_role_model_and_cap_use_one_budget_and_replay_without_credentials(self):
        gateway = self.gateway()
        request = {'request_id': 'critic-1', 'role': 'critic', 'messages': [{'role': 'user', 'content': 'check'}]}
        critic = asyncio.run(gateway.complete(request))
        default = asyncio.run(gateway.complete({'request_id': 'other-1', 'role': 'unconfigured-role', 'messages': [{'role': 'user', 'content': 'model'}]}))
        self.assertEqual((critic.text, default.text), ('critic-model', 'default-model'))
        self.assertEqual([request['max_tokens'] for request in self.requests], [31, 20])
        self.assertEqual([row['requested_model'] for row in gateway.trace], ['critic-model', 'default-model'])
        self.assertEqual(gateway.ledger['llm_attempts'], 2)
        self.assertEqual(gateway.ledger['known_total_tokens'], 30)
        with self.assertRaises(RunError) as error:
            asyncio.run(gateway.complete({'role': 'critic', 'messages': [{'role': 'user', 'content': 'third'}]}))
        self.assertEqual(error.exception.code, 'budget_exhausted')
        restored = self.gateway(restored=True)
        replay = asyncio.run(restored.complete(request))
        self.assertEqual(replay.call_id, critic.call_id)
        self.assertEqual(len(self.requests), 2)

    def test_changed_role_identity_is_rejected_before_http(self):
        self.gateway()
        with self.assertRaises(RunError) as error:
            self.gateway(restored=True, critic_model='changed-model')
        self.assertEqual(error.exception.code, 'checkpoint_incompatible')
        self.assertEqual(len(self.requests), 0)

    def test_changed_role_cap_and_endpoint_reject_saved_resource_identity(self):
        self.gateway()
        default = OpenAICompatibleFactory().restore(self.config, 'default-model', environment=lambda: {})
        for config in ({**self.config, 'max_output_tokens': 32},
                {**self.config, 'base_url': self.config['base_url'] + '/changed', 'max_output_tokens': 31}):
            with self.subTest(config=config):
                critic = OpenAICompatibleFactory().restore(config, 'critic-model', environment=lambda: {})
                with self.assertRaises(RunError) as error:
                    Gateway(default, self.budget, self.root / 'private', role_providers={'critic': critic})
                self.assertEqual(error.exception.code, 'checkpoint_incompatible')
        self.assertEqual(len(self.requests), 0)

    def test_mixed_protocol_role_replays_its_actual_decoder_and_unknown_reservation(self):
        default = OpenAICompatibleFactory().create(self.config, 'default-model', environment={'ROLE_TEST_KEY': 'synthetic'})
        critic = AnthropicFactory().create(self.config, 'messages-critic', environment={'ROLE_TEST_KEY': 'synthetic'})
        gateway = Gateway(default, self.budget, self.root / 'private', role_providers={'critic': critic})
        request = {'request_id': 'messages-1', 'role': 'critic', 'messages': [{'role': 'system', 'content': 'check'}, {'role': 'user', 'content': 'model'}]}
        reply = asyncio.run(gateway.complete(request))
        self.assertEqual(reply.text, 'messages-critic')
        self.assertEqual(self.requests[0]['system'], [{'type': 'text', 'text': 'check'}])
        self.assertEqual(gateway.trace[0]['provider'], 'llm4om.providers.anthropic')
        restored = Gateway(OpenAICompatibleFactory().restore(self.config, 'default-model', environment=lambda: {}), self.budget,
            self.root / 'private', role_providers={'critic': AnthropicFactory().restore(self.config, 'messages-critic', environment=lambda: {})})
        self.assertEqual(asyncio.run(restored.complete(request)).call_id, reply.call_id)
        self.assertEqual(len(self.requests), 1)
        self.failure_status = 401
        with self.assertRaises(RunError):
            asyncio.run(gateway.complete({'request_id': 'unknown-1', 'role': 'critic', 'messages': [{'role': 'user', 'content': 'fail'}]}))
        self.assertGreater(gateway.ledger['reserved_tokens'], 0)
        with self.assertRaises(RunError) as error:
            asyncio.run(restored.complete({'request_id': 'unknown-1', 'role': 'critic', 'messages': [{'role': 'user', 'content': 'fail'}]}))
        self.assertEqual(error.exception.code, 'provider_outcome_unknown')
        self.assertEqual(len(self.requests), 2)

    def test_roles_compete_for_one_concurrency_slot(self):
        gateway = self.gateway()
        self.delay = .4
        async def compete():
            first = asyncio.create_task(gateway.complete({'role': 'critic', 'messages': [{'role': 'user', 'content': 'one'}]}))
            for _ in range(100):
                if self.requests:
                    break
                await asyncio.sleep(.01)
            self.assertTrue(self.requests)
            with self.assertRaises(RunError) as error:
                await gateway.complete({'role': 'modeler', 'messages': [{'role': 'user', 'content': 'two'}]})
            self.assertEqual(error.exception.code, 'budget_exhausted')
            await first
        asyncio.run(compete())
        self.assertEqual(len(self.requests), 1)

    def test_cancelled_role_keeps_unknown_reservation_and_releases_the_shared_slot(self):
        from llm4om.providers import AnthropicFactory
        default = OpenAICompatibleFactory().create(self.config, 'default-model', environment={'ROLE_TEST_KEY': 'synthetic'})
        critic = AnthropicFactory().create(self.config, 'messages-critic', environment={'ROLE_TEST_KEY': 'synthetic'})
        token = CancellationToken()
        gateway = Gateway(default, self.budget, self.root / 'private', role_providers={'critic': critic}, cancellation=token)
        self.delay = .5
        async def cancel_pending():
            pending = asyncio.create_task(gateway.complete({'request_id': 'cancelled-1', 'role': 'critic', 'messages': [{'role': 'user', 'content': 'slow'}]}))
            for _ in range(100):
                if self.requests:
                    break
                await asyncio.sleep(.01)
            self.assertTrue(self.requests)
            token.cancel()
            with self.assertRaises(RunError) as error:
                await pending
            self.assertEqual(error.exception.code, 'run_cancelled')
        asyncio.run(cancel_pending())
        self.assertEqual(gateway.trace[0]['role'], 'critic')
        self.assertGreater(gateway.ledger['reserved_tokens'], 0)
        self.delay = 0
        restored = Gateway(default, self.budget, self.root / 'private', role_providers={'critic': critic})
        response = asyncio.run(restored.complete({'role': 'modeler', 'messages': [{'role': 'user', 'content': 'next'}]}))
        self.assertEqual(response.text, 'default-model')
        self.assertGreater(restored.ledger['reserved_tokens'], 0)
