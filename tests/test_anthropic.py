"""Messages compatibility through the public factory/Gateway and real local HTTP."""
import asyncio
import hashlib
import json
import os
import subprocess
import sys
import time
import yaml
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from llm4om.providers import Gateway, provider_factory


class MessagesTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.requests = []
        self.credential = "synthetic-secret"
        self.statuses = [200]
        self.delay = 0
        self.header_id = "req-fixture"
        self.raw = None
        self.reply = {'type': 'message', 'role': 'assistant', 'id': 'msg-fixture',
                      'model': 'deepseek-v4-pro-0813', 'stop_reason': 'end_turn',
                      'content': [{'type': 'thinking', 'thinking': 'private thought', 'signature': 'opaque'},
                                  {'type': 'text', 'text': 'first'}, {'type': 'text', 'text': ' second'}],
                      'usage': {'input_tokens': 40, 'output_tokens': 18,
                                'cache_creation_input_tokens': 5, 'cache_read_input_tokens': 7}}
        fixture = self
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                fixture.requests.append((self.path, dict(self.headers),
                    json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                time.sleep(fixture.delay)
                self.send_response(fixture.statuses.pop(0) if len(fixture.statuses) > 1 else fixture.statuses[0])
                self.send_header('request-id', fixture.header_id)
                self.end_headers()
                try:
                    self.wfile.write(fixture.raw if fixture.raw is not None else json.dumps(fixture.reply).encode())
                except (BrokenPipeError, ConnectionResetError):
                    pass
            def log_message(self, *args):
                pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.config = {'base_url': f'http://127.0.0.1:{self.server.server_port}/v1',
                       'credential_env': 'S05B_KEY', 'max_output_tokens': 100, 'max_retries': 2, 'timeout_s': 5}
        self.budget = {'max_llm_attempts': 3, 'max_total_tokens': 30000, 'wall_time_s': 30, 'max_concurrency': 1}

    def gateway(self, name='archive'):
        provider = provider_factory('llm4om.providers.anthropic').create(
            self.config, 'deepseek-v4-pro-0813', environment={'S05B_KEY': self.credential})
        return Gateway(provider, self.budget, self.root / name)

    def test_messages_wire_order_normalization_and_saved_reply(self):
        gateway = self.gateway()
        request = {'request_id': 'saved', 'messages': [
            {'role': 'system', 'content': 'system one'},
            {'role': 'user', 'content': 'question'},
            {'role': 'assistant', 'content': 'answer'},
            {'role': 'system', 'content': 'system two'},
            {'role': 'user', 'content': 'follow up'}]}
        reply = asyncio.run(gateway.complete(request))
        self.assertEqual(reply.text, 'first second')
        self.assertEqual(reply.finish_reason, 'stop')
        self.assertEqual(self.requests, [('/v1/messages', self.requests[0][1], {
            'model': 'deepseek-v4-pro-0813', 'max_tokens': 100, 'stream': False,
            'system': [{'type': 'text', 'text': 'system one'}, {'type': 'text', 'text': 'system two'}],
            'messages': [{'role': 'user', 'content': 'question'}, {'role': 'assistant', 'content': 'answer'},
                         {'role': 'user', 'content': 'follow up'}]})])
        headers = {key.lower(): value for key, value in self.requests[0][1].items()}
        self.assertEqual(headers['anthropic-version'], '2023-06-01')
        self.assertEqual(headers['x-api-key'], 'synthetic-secret')
        self.assertNotIn('authorization', headers)
        trace = gateway.trace[0]
        self.assertEqual(trace['usage'], {'input_tokens': 52, 'output_tokens': 18, 'total_tokens': 70,
                                         'cached_tokens': 12, 'reasoning_tokens': None})
        self.assertEqual(trace['response_id'], 'msg-fixture')
        self.assertEqual(trace['provider_request_id'], 'req-fixture')
        self.assertEqual(trace['model'], 'deepseek-v4-pro-0813')
        self.assertEqual(trace['stop_reason'], 'end_turn')
        self.assertEqual(trace['response_sha256'], hashlib.sha256(json.dumps(self.reply).encode()).hexdigest())
        self.assertIsNone(gateway.ledger['cost'])
        self.assertNotIn('private thought', json.dumps(trace))
        self.assertEqual(asyncio.run(self.gateway().complete(request)), reply)
        self.assertEqual(len(self.requests), 1)

    def test_ordered_request_text_blocks_and_unsupported_features_before_http(self):
        from llm4om.contracts import RunError
        request = {'messages': [
            {'role': 'system', 'content': [{'type': 'text', 'text': 'one'}, {'type': 'text', 'text': 'two'}]},
            {'role': 'user', 'content': [{'type': 'text', 'text': 'question'}, {'type': 'text', 'text': ' detail'}]}]}
        gateway = self.gateway()
        asyncio.run(gateway.complete(request))
        body = self.requests[0][2]
        self.assertEqual(body['system'], request['messages'][0]['content'])
        self.assertEqual(body['messages'], [request['messages'][1]])
        for option in ('tools', 'response_schema', 'images', 'stream'):
            with self.subTest(option=option), self.assertRaises(RunError) as caught:
                asyncio.run(gateway.complete({**request, option: True}))
            self.assertEqual(caught.exception.code, 'capability_mismatch')
        with self.assertRaises(RunError) as caught:
            asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': [
                {'type': 'image', 'source': {'type': 'base64', 'data': 'not-an-image'}}]}]}))
        self.assertEqual(caught.exception.code, 'capability_mismatch')
        self.assertEqual(len(self.requests), 1)

    def test_doctor_rejects_unsupported_capabilities_without_http(self):
        root = Path(__file__).resolve().parents[1]
        settings = yaml.safe_load((root / 'examples/specs/solve.yaml').read_text())
        for option in ('tools', 'response_schema', 'images', 'stream'):
            settings['llm'] = {'provider_plugin_id': 'llm4om.providers.anthropic',
                               'model': 'deepseek-v4-pro-0813', 'config': {**self.config, option: True}}
            config = self.root / 'run.yaml'
            config.write_text(yaml.safe_dump(settings))
            result = subprocess.run([sys.executable, '-m', 'llm4om', 'doctor', '--config', str(config)],
                                    cwd=self.root, env={**os.environ, 'S05B_KEY': 'synthetic-secret'},
                                    capture_output=True, text=True, timeout=10)
            with self.subTest(option=option):
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout)['error']['code'], 'capability_mismatch')
                self.assertNotIn('synthetic-secret', result.stdout + result.stderr)
        self.assertEqual(self.requests, [])

    def test_credential_echo_in_decoded_metadata_fails_before_any_archive_bytes(self):
        from llm4om.contracts import RunError
        self.credential = 'synthetic-"secret'
        self.reply['metadata'] = {'nested': [self.credential]}
        gateway = self.gateway()
        with self.assertRaises(RunError) as caught:
            asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'echo'}]}))
        self.assertEqual(caught.exception.code, 'invalid_provider_response')
        self.assertEqual(len(self.requests), 1)
        for file in gateway.archive.rglob('*'):
            if file.is_file():
                self.assertNotIn('synthetic-', file.read_text())

    def test_missing_counts_remain_unknown_and_hold_reservations_on_replay(self):
        request = {'request_id': 'unknown-counts', 'messages': [{'role': 'user', 'content': 'usage'}]}
        cases = [None, {}, {'input_tokens': 40, 'output_tokens': 18},
                 {'input_tokens': 40, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0},
                 {'input_tokens': 40, 'output_tokens': 18, 'cache_creation_input_tokens': 0, 'cache_read_input_tokens': 0}]
        for index, usage in enumerate(cases):
            with self.subTest(usage=usage):
                self.reply['usage'] = usage
                gateway = self.gateway(str(index))
                response = asyncio.run(gateway.complete(request))
                fields = gateway.trace[0]['usage']
                self.assertEqual(fields['input_tokens'], 40 if index >= 3 else None)
                self.assertEqual(fields['output_tokens'], 18 if index in (2, 4) else None)
                self.assertEqual(fields['total_tokens'], 58 if index == 4 else None)
                self.assertEqual(fields['cached_tokens'], 0 if index >= 3 else None)
                self.assertIsNone(fields['reasoning_tokens'])
                self.assertIsNone(gateway.ledger['cost'])
                self.assertEqual(gateway.ledger['reserved_tokens'] == 0, index == 4)
                self.assertEqual(asyncio.run(self.gateway(str(index)).complete(request)), response)
        self.assertEqual(len(self.requests), 5)

    def test_invalid_content_and_usage_fail_once_without_exporting_response(self):
        from llm4om.contracts import RunError
        original = json.loads(json.dumps(self.reply))
        cases = [ {'content': None}, {'content': []}, {'content': [{'type': 'text', 'text': 1}]},
                  {'content': [{'type': 'tool_use', 'id': 'unsupported'}]},
                  {'content': [{'type': 'future_block', 'text': 'not admitted'}]},
                  {'content': [{'type': 'thinking', 'thinking': 'no final text'}]},
                  {'usage': []}, {'usage': {'input_tokens': True}}, {'usage': {'output_tokens': -1}},
                  {'usage': {'cache_creation_input_tokens': 1.5}}, {'usage': {'cache_read_input_tokens': '7'}},
                  {'type': 'error'}, {'role': 'user'}, {'stop_reason': []}, {'model': 17}]
        for index, change in enumerate(cases):
            self.reply = {**original, **change}
            with self.subTest(change=change):
                gateway = self.gateway(str(index))
                with self.assertRaises(RunError) as caught:
                    asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'invalid'}]}))
                self.assertEqual(caught.exception.code, 'invalid_provider_response')
                self.assertGreater(gateway.ledger['reserved_tokens'], 0)
                self.assertIsNone(gateway.ledger['total_tokens'])
                self.assertEqual(len(gateway.trace), 1)
                self.assertNotIn('raw_reply', (gateway.archive / 'state.json').read_text())
        self.assertEqual(len(self.requests), len(cases))

    def test_credential_echo_in_header_thinking_text_or_unknown_metadata_is_refused(self):
        from llm4om.contracts import RunError
        original = json.loads(json.dumps(self.reply))
        for index, location in enumerate(('header', 'thinking', 'text', 'metadata')):
            self.reply = json.loads(json.dumps(original))
            self.header_id = 'req-fixture'
            if location == 'header':
                self.header_id = self.credential
            elif location in ('thinking', 'text'):
                self.reply['content'].append({'type': location, location: self.credential})
            else:
                self.reply[self.credential] = 'echo in a JSON key'
            gateway = self.gateway(str(index))
            with self.subTest(location=location), self.assertRaises(RunError) as caught:
                asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'echo'}]}))
            self.assertEqual(caught.exception.code, 'invalid_provider_response')
            self.assertTrue(all(self.credential.encode() not in path.read_bytes()
                                for path in gateway.archive.rglob('*') if path.is_file()))

    def test_http_errors_use_bounded_shared_attempts_and_unknown_reservations(self):
        from llm4om.contracts import RunError
        self.statuses = [429, 529, 200]
        gateway = self.gateway()
        asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'retry'}]}))
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(len({item['attempt_id'] for item in gateway.trace}), 3)
        self.assertEqual(gateway.ledger['known_total_tokens'], 70)
        self.assertIsNone(gateway.ledger['total_tokens'])
        self.assertGreater(gateway.ledger['reserved_tokens'], 0)
        for status, code, attempts in ((503, 'provider_error', 3), (429, 'rate_limit', 3),
                                      (400, 'invalid_provider_request', 1), (401, 'auth_error', 1),
                                      (403, 'auth_error', 1)):
            self.statuses = [status]
            self.reply = {'error': {'message': self.credential}}
            current = self.gateway(str(status))
            with self.subTest(status=status), self.assertRaises(RunError) as caught:
                asyncio.run(current.complete({'messages': [{'role': 'user', 'content': 'error'}]}))
            self.assertEqual(caught.exception.code, code)
            self.assertEqual(current.ledger['llm_attempts'], attempts)
            self.assertIsNone(current.ledger['total_tokens'])
            self.assertNotIn(self.credential, json.dumps(current.trace))

    def test_timeout_is_not_retried_and_same_request_is_not_resubmitted(self):
        from llm4om.contracts import RunError
        self.delay = 2
        self.config['timeout_s'] = 1
        request = {'request_id': 'timeout', 'messages': [{'role': 'user', 'content': 'slow'}]}
        gateway = self.gateway()
        with self.assertRaises(RunError) as caught:
            asyncio.run(gateway.complete(request))
        self.assertEqual(caught.exception.code, 'provider_timeout')
        reserved = gateway.ledger['reserved_tokens']
        with self.assertRaises(RunError) as caught:
            asyncio.run(self.gateway().complete(request))
        self.assertEqual(caught.exception.code, 'provider_outcome_unknown')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(gateway.ledger['reserved_tokens'], reserved)
        self.assertGreater(reserved, 0)

    def test_cancellation_reaps_owned_http_child_without_losing_unknown_attempt(self):
        from llm4om import CancellationToken
        from llm4om.contracts import RunError
        self.delay = 3
        gateway = self.gateway()
        token = CancellationToken()
        gateway.cancellation = token
        children_path = Path(f'/proc/{os.getpid()}/task/{os.getpid()}/children')
        before = set(children_path.read_text().split())
        request = {'request_id': 'cancelled', 'messages': [{'role': 'user', 'content': 'cancel'}]}
        async def cancel():
            pending = asyncio.create_task(gateway.complete(request))
            deadline = time.monotonic() + 3
            while not self.requests:
                self.assertLess(time.monotonic(), deadline)
                await asyncio.sleep(0.01)
            children = set(children_path.read_text().split()) - before
            self.assertEqual(len(children), 1)
            for child in children:
                self.assertNotIn(self.credential.encode(), Path(f'/proc/{child}/cmdline').read_bytes())
                self.assertNotIn(self.credential.encode(), Path(f'/proc/{child}/environ').read_bytes())
            token.cancel()
            with self.assertRaises(RunError) as caught:
                await pending
            self.assertEqual(caught.exception.code, 'run_cancelled')
            self.assertTrue(all(not Path(f'/proc/{child}').exists() for child in children))
        asyncio.run(cancel())
        restored = self.gateway()
        self.assertEqual(restored.ledger['llm_attempts'], 1)
        self.assertGreater(restored.ledger['reserved_tokens'], 0)
        with self.assertRaises(RunError) as caught:
            asyncio.run(restored.complete(request))
        self.assertEqual(caught.exception.code, 'provider_outcome_unknown')
        self.assertEqual(len(self.requests), 1)

    def test_missing_identity_and_unknown_stop_reason_are_not_invented(self):
        self.reply.pop('id')
        self.reply.pop('model')
        self.reply.pop('stop_reason')
        self.reply['content'].insert(0, {'type': 'redacted_thinking', 'data': 'opaque-private'})
        gateway = self.gateway()
        first = asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'missing'}]}))
        self.assertIsNone(first.finish_reason)
        self.assertIsNone(gateway.trace[0]['response_id'])
        self.assertIsNone(gateway.trace[0]['model'])
        self.assertIsNone(gateway.trace[0]['stop_reason'])
        self.assertEqual(first.text, 'first second')
        self.reply['stop_reason'] = 'future_stop'
        second = asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'unknown'}]}))
        self.assertEqual(second.finish_reason, 'future_stop')
        self.assertEqual(gateway.trace[1]['stop_reason'], 'future_stop')

    def test_invalid_json_wire_bytes_are_nonretryable(self):
        from llm4om.contracts import RunError
        for index, raw in enumerate((b'{"content": [], "content": []}', b'{"usage": NaN}', b'\xff', b'[]')):
            self.raw = raw
            gateway = self.gateway(str(index))
            with self.subTest(raw=raw), self.assertRaises(RunError) as caught:
                asyncio.run(gateway.complete({'messages': [{'role': 'user', 'content': 'invalid'}]}))
            self.assertEqual(caught.exception.code, 'invalid_provider_response')
            self.assertEqual(gateway.ledger['llm_attempts'], 1)
            self.assertGreater(gateway.ledger['reserved_tokens'], 0)

    def test_shared_budget_rejects_competing_call_and_saved_overrun_never_resends(self):
        from llm4om.contracts import RunError
        self.delay = 0.2
        self.budget['max_llm_attempts'] = 1
        first, second = self.gateway(), self.gateway()
        async def competing():
            return await asyncio.gather(first.complete({'messages': [{'role': 'user', 'content': 'one'}]}),
                second.complete({'messages': [{'role': 'user', 'content': 'two'}]}), return_exceptions=True)
        outcomes = asyncio.run(competing())
        self.assertEqual(sum(isinstance(value, RunError) for value in outcomes), 1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(second.ledger['llm_attempts'], 1)
        self.reply['usage']['output_tokens'] = 30000
        request = {'request_id': 'overrun', 'messages': [{'role': 'user', 'content': 'overrun'}]}
        for gateway in (self.gateway('overrun'), self.gateway('overrun')):
            with self.assertRaises(RunError) as caught:
                asyncio.run(gateway.complete(request))
            self.assertEqual(caught.exception.code, 'token_budget_overrun')
            self.assertEqual(gateway.ledger['known_total_tokens'], 30052)
        self.assertEqual(len(self.requests), 2)


class MessagesRecoveryTests(unittest.TestCase):
    def setUp(self):
        import shutil
        MessagesTests.setUp(self)
        self.inputs = self.root / 'inputs'
        shutil.copytree(Path(__file__).resolve().parents[1] / 'examples/specs', self.inputs)
        formulation = json.loads((self.inputs / 'formulation.json').read_text())
        ir = json.loads((self.inputs / 'model-ir.json').read_text())
        self.reply['content'] = [{'type': 'text', 'text': json.dumps({
            'representation': formulation['representation'], 'structured_ir': {
                key: ir[key] for key in ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}})}]

    def http_config(self, *, max_attempts=1):
        settings = yaml.safe_load((self.inputs / 'solve.yaml').read_text())
        settings['budget']['max_total_tokens'] = 30000
        settings['budget']['max_llm_attempts'] = max_attempts
        settings['llm'] = {'provider_plugin_id': 'llm4om.providers.anthropic',
                           'model': 'deepseek-v4-pro-0813', 'config': self.config}
        config = self.inputs / 'messages.yaml'
        config.write_text(yaml.safe_dump(settings))
        os.environ['S05B_KEY'] = 'synthetic-secret'
        self.addCleanup(os.environ.pop, 'S05B_KEY', None)
        return config

    def resource_crash(self, status, **kwargs):
        from test_resume_crash import CrashResumeTests
        return CrashResumeTests.resource_crash(self, status, **kwargs)

    def test_unadmitted_checkpoint_resumes_after_local_credentials_are_restored(self):
        from llm4om import resume_run
        from unittest.mock import patch
        from test_resume_crash import CRASH
        messages_reply = self.reply
        for provider in ('anthropic', 'openai_compatible'):
            with self.subTest(provider=provider):
                config = self.http_config()
                settings = yaml.safe_load(config.read_text())
                settings['llm']['provider_plugin_id'] = 'llm4om.providers.' + provider
                config.write_text(yaml.safe_dump(settings))
                self.reply = messages_reply if provider == 'anthropic' else {
                    'choices': [{'message': {'content': messages_reply['content'][0]['text']},
                                 'finish_reason': 'stop'}], 'usage': {'total_tokens': 70}}
                fault = CRASH.replace(
                    'record = json.loads(lines[-1])', 'record = json.loads(Path(target).read_text())')
                fault = fault.replace(
                    '"history" not in Path(target).parts and isinstance(record, dict) and record.get("kind") == "formulation_saved"',
                    'Path(target).name == "checkpoint.json" and record.get("payload", {}).get("state", {}).get("method_checkpoint")')
                output = self.root / provider
                process = subprocess.run([sys.executable, '-c', fault, 'run',
                    '--problem', str(self.inputs / 'problem.json'), '--config', str(config),
                    '--output', str(output)], cwd=self.root, capture_output=True, text=True, timeout=15)
                self.assertEqual(process.returncode, 91, process.stderr)
                path = next(path for path in output.iterdir() if len(path.name) == 32)
                checkpoint = json.loads((path / 'checkpoint.json').read_text())['payload']['state']
                request_id = checkpoint['method_checkpoint']['request_id']
                archive = output / '.private' / path.name
                original = (archive / 'state.json').read_bytes()
                self.assertEqual(json.loads(original)['attempts'], [])
                before = len(self.requests)
                os.environ.pop('S05B_KEY')
                # An isolated cwd prevents fallback to any developer credential file.
                previous_cwd = Path.cwd()
                os.chdir(self.root)
                try:
                    for credential in (None, '', 'invalid\nkey', 'invalid\u00e9key'):
                        with self.subTest(credential=repr(credential)):
                            if credential is not None:
                                os.environ['S05B_KEY'] = credential
                            with patch('asyncio.create_subprocess_exec', side_effect=AssertionError('No HTTP child')):
                                result = resume_run(path)
                            self.assertEqual(result.status, 'failed')
                            self.assertEqual(json.loads((path / 'bundle.json').read_text())['error']['code'], 'auth_error')
                            ledger = json.loads((path / 'budget-ledger.json').read_text())
                            for field in ('llm_attempts', 'external_llm_requests', 'reserved_tokens'):
                                self.assertEqual(ledger[field], 0, field)
                            self.assertEqual(json.loads((path / 'llm-trace.json').read_text())['attempts'], [])
                            self.assertEqual((archive / 'state.json').read_bytes(), original)
                            self.assertEqual(len(self.requests), before)
                    os.environ['S05B_KEY'] = 'synthetic-secret'
                    result = resume_run(path)
                finally:
                    os.chdir(previous_cwd)
                self.assertEqual(result.status, 'completed')
                self.assertEqual(result.run_id, path.name)
                self.assertEqual(len(self.requests), before + 1)
                ledger = json.loads((path / 'budget-ledger.json').read_text())
                self.assertEqual(ledger['external_llm_requests'], 1)
                self.assertEqual(ledger['solver_calls'], 1)
                trace = json.loads((path / 'llm-trace.json').read_text())['attempts']
                self.assertEqual([item['request_id'] for item in trace], [request_id])
                self.assertEqual(json.loads((path / 'candidates/001/solve-result.json').read_text())['objective_value'], 13)

    def test_durable_success_replays_without_credentials_after_both_commit_windows(self):
        from llm4om import resume_run
        for journal in (False, True):
            with self.subTest(journal=journal):
                # Keep usage unknown and its reservation across both recovery windows.
                self.reply.pop('usage', None)
                path = self.resource_crash('success', journal=journal)
                os.environ.pop('S05B_KEY')
                from unittest.mock import patch
                read_text = Path.read_text
                def public_text(file, *args, **kwargs):
                    if file.name == '.env':
                        raise AssertionError('Replay must not load credential files')
                    return read_text(file, *args, **kwargs)
                with patch.object(Path, 'read_text', public_text):
                    result = resume_run(path)
                self.assertEqual(result.status, 'completed')
                solve = json.loads((path / 'candidates/001/solve-result.json').read_text())
                self.assertEqual(solve['objective_value'], 13)
                ledger = json.loads((path / 'budget-ledger.json').read_text())
                self.assertEqual(ledger['external_llm_requests'], 1)
                self.assertIsNone(ledger['total_tokens'])
                self.assertIsNone(ledger['cost'])
                self.assertGreater(ledger['reserved_tokens'], 0)
                self.assertEqual(len(self.requests), 1 + int(journal))
                before = (path / 'events.jsonl').read_bytes()
                with patch.object(Path, 'read_text', public_text):
                    self.assertEqual(resume_run(path), result)
                self.assertEqual((path / 'events.jsonl').read_bytes(), before)
                # Give the next independent crash a distinct storage root.
                self.root = self.root / 'next'
                self.root.mkdir()

    def test_unknown_admission_is_not_sent_on_restore_without_credentials(self):
        from llm4om import resume_run
        path = self.resource_crash('unknown')
        os.environ.pop('S05B_KEY')
        result = resume_run(path)
        self.assertEqual(result.status, 'failed')
        self.assertEqual(json.loads((path / 'bundle.json').read_text())['error']['code'], 'provider_outcome_unknown')
        ledger = json.loads((path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['external_llm_requests'], 1)
        self.assertIsNone(ledger['total_tokens'])
        self.assertGreater(ledger['reserved_tokens'], 0)
        self.assertEqual(self.requests, [])

    def test_corrupt_mutable_immutable_and_public_bytes_refuse_before_http(self):
        from llm4om import resume_run
        from llm4om.contracts import RunError
        path = self.resource_crash('success')
        os.environ.pop('S05B_KEY')
        archive = path.parent / '.private' / path.name
        head = archive / 'state.json'
        immutable = archive / 'journal' / (hashlib.sha256(head.read_bytes()).hexdigest() + '.json')
        for file in (head, immutable, path / 'requested-config.json'):
            with self.subTest(file=file.name):
                original = file.read_bytes()
                file.write_bytes(original + b'corruption')
                with self.assertRaises(RunError) as caught:
                    resume_run(path)
                self.assertEqual(caught.exception.code, 'checkpoint_incompatible')
                file.write_bytes(original)
                self.assertEqual(len(self.requests), 1)
        self.assertEqual(archive.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(file.stat().st_mode & 0o777 == 0o600
                            for file in archive.rglob('*') if file.is_file()))

    def test_cli_messages_solves_and_truncation_preserves_usage(self):
        config = self.http_config()
        original = json.loads(json.dumps(self.reply))
        for truncated in (False, True):
            self.reply = json.loads(json.dumps(original))
            if truncated:
                self.reply['content'] = [{'type': 'thinking', 'thinking': 'unfinished'}]
                self.reply['stop_reason'] = 'max_tokens'
            result = subprocess.run([sys.executable, '-m', 'llm4om', 'run', '--problem', str(self.inputs / 'problem.json'),
                                     '--config', str(config), '--output', str(self.root / 'runs')],
                                    cwd=self.root, capture_output=True, text=True, timeout=20)
            path = Path(json.loads(result.stdout)['bundle_path'])
            bundle = json.loads((path / 'bundle.json').read_text())
            trace = json.loads((path / 'llm-trace.json').read_text())['attempts'][0]
            self.assertEqual(trace['usage']['total_tokens'], 70)
            self.assertIsNone(trace['usage']['reasoning_tokens'])
            self.assertEqual(trace['stop_reason'], 'max_tokens' if truncated else 'end_turn')
            self.assertEqual(result.returncode, int(truncated), result.stdout + result.stderr)
            if truncated:
                self.assertEqual(bundle['error']['code'], 'llm_output_truncated')
                self.assertIsNone(bundle['model_artifact_ref'])
            else:
                solve = json.loads((path / 'candidates/001/solve-result.json').read_text())
                self.assertEqual(solve['objective_value'], 13)
                self.assertEqual(solve['termination'], 'optimal')
                sent = self.requests[-1][2]
                self.assertIn('system', sent)
                self.assertEqual([message['role'] for message in sent['messages']], ['user'])
                prompt = json.loads(sent['messages'][0]['content'])
                self.assertIn('A,3,2,1', prompt['data']['products'])
                artifact = json.loads((path / 'candidates/001/artifact.json').read_text())
                self.assertEqual(artifact['provenance']['origin'], 'external_provider')
            exported = '\n'.join(file.read_text() for file in path.rglob('*') if file.is_file())
            self.assertNotIn('synthetic-secret', exported)
            self.assertNotIn('unfinished', exported)
            self.assertNotIn('raw_reply', exported)
            self.assertTrue(all('.private' not in ref['relative_path'] for ref in bundle['artifacts']))
