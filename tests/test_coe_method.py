"""CoE transitions through the public Method/Context response/execution seams."""

import asyncio
import hashlib
import json
import unittest

from llm4om.methods import LLMResponse, MethodContext


class Tape:
    def __init__(self, replies, exits=(0,), collector_error=None):
        self.replies, self.exits = list(replies), list(exits)
        self.requests, self.executions, self.events = [], [], []
        self.files = {}
        self.collector_error = collector_error

    async def complete(self, request):
        self.requests.append(request)
        text = self.replies.pop(0)
        return LLMResponse(text, str(len(self.requests)), 'mock_fixture', hashlib.sha256(text.encode()).hexdigest())

    async def execute(self, execution_id, code):
        self.executions.append((execution_id, code))
        return {'execution_id': execution_id, 'source': {'status': 'completed', 'exit_code': self.exits.pop(0) if self.exits else 0,
            'stdout': '', 'stderr': 'public invocation failed'}, 'collector_error': self.collector_error}

    def record(self, name, value):
        self.files[name] = value
        return {'sha256': hashlib.sha256(value).hexdigest()}

    def emit(self, event):
        self.events.append(event)


class CoEMethodTests(unittest.TestCase):
    def run_tape(self, tape, *, reflection=False, collaboration=2, trials=2, repairs=3):
        from llm4om.coe import CoEFactory
        data = {'contract': b'{"code_example":"def prob_case(capacity): pass", "entry_point":"prob_case", "input":{"capacity":4}}'}
        problem = {'problem_id': 'public', 'revision': '1', 'description': 'Maximize 3x for nonnegative integer x <= capacity.',
            'data_refs': [{'data_id': name, 'sha256': hashlib.sha256(value).hexdigest()} for name, value in data.items()]}
        context = MethodContext(tape, data, {'max_repairs': repairs, 'wall_time_s': 30}, 'a' * 64, resources=tape)
        return asyncio.run(CoEFactory().create({'public_contract_data_id': 'contract', 'max_collaborate_nums': collaboration,
            'enable_reflection': reflection, 'max_trials': trials, 'seed': 7}).run(problem, context))

    def test_dynamic_remaining_first_routing_and_native_code_without_invented_formulation(self):
        code = 'def prob_case(capacity):\n    return capacity\n'
        tape = Tape(['Programming Expert', 'first-comment', 'Modeling Expert and Programming Expert', 'second-comment', code])
        result = self.run_tape(tape)
        self.assertEqual([call['role'] for call in tape.requests], ['coe.conductor', 'coe.Programming Expert',
            'coe.conductor', 'coe.Modeling Expert', 'coe.reducer'])
        self.assertNotIn('first-comment', tape.requests[2]['messages'][0]['content'])
        self.assertNotIn('def prob_case', tape.requests[2]['messages'][0]['content'])
        self.assertIn('first-comment', tape.requests[3]['messages'][0]['content'])
        self.assertNotIn('def prob_case', tape.requests[3]['messages'][0]['content'])
        self.assertIsNone(result.proposal.formulation)
        self.assertEqual(tape.files['trial-001-code.py'].decode(), code)
        self.assertEqual(result.proposal.execution_id, 'coe-trial-001')
        self.assertEqual(len(tape.executions), 1)

    def test_reflection_reset_and_last_reducer_selection_keep_unexecuted_refinement(self):
        first = 'def prob_case(capacity):\n    raise ValueError("first")\n'
        last = 'def prob_case(capacity):\n    raise ValueError("last")\n'
        tape = Tape(['Programming Expert', 'first-comment', first, '{"input":{"capacity":4}}',
            '{"is_caused_by_you":true,"reason":"fix","refined_result":"unexecuted-repair-one"}',
            'Programming Expert', 'second-comment', last, '{"input":{"capacity":4}}',
            '{"is_caused_by_you":true,"reason":"fix","refined_result":"unexecuted-repair-two"}'], exits=(1, 1))
        result = self.run_tape(tape, reflection=True, collaboration=1)
        self.assertEqual(len(tape.requests), 10)
        self.assertNotIn('unexecuted-repair-one', tape.requests[6]['messages'][0]['content'])
        self.assertNotIn('first-comment', tape.requests[6]['messages'][0]['content'])
        self.assertEqual(tape.files['trial-002-code.py'].decode(), last)
        self.assertNotIn('unexecuted-repair-two', result.proposal.code.source)
        self.assertEqual(result.proposal.execution_id, 'coe-final-original')
        self.assertEqual(json.loads(tape.files['selection.json'])['public_check'], 'failed_trials_exhausted')

    def test_first_public_pass_stops_and_ignores_collector_feedback_for_reflection(self):
        tape = Tape(['Programming Expert', 'comment', 'def prob_case(capacity): return capacity', '[{"input":{"capacity":4}}]'],
            collector_error='capture_missing_or_unsupported')
        result = self.run_tape(tape, reflection=True, collaboration=1, trials=3)
        self.assertEqual(len(tape.requests), 4)
        self.assertEqual(result.status, 'candidate_selected')
        self.assertEqual(len(tape.executions), 2)

    def test_repeated_names_and_seeded_invalid_routing_are_not_a_fixed_chain(self):
        tape = Tape(['Programming Expert', 'first', 'Programming Expert', 'repeat', 'def prob_case(capacity): return capacity'])
        self.run_tape(tape)
        routes = json.loads(tape.files['routes.json'])['routes']
        self.assertEqual([route['expert'] for route in routes], ['Programming Expert', 'Programming Expert'])
        self.assertEqual(routes[1]['selection'], 'name_match_all')
        self.assertIn('first', tape.requests[3]['messages'][0]['content'])
        tape = Tape(['invalid-expert', 'comment', 'def prob_case(capacity): return capacity'])
        self.run_tape(tape, collaboration=1)
        route = json.loads(tape.files['routes.json'])['routes'][0]
        self.assertEqual(route['selection'], 'seeded_fallback')
        self.assertEqual(route['expert'], 'Modeling Expert')

    def test_backward_walk_is_reverse_and_parse_failure_propagates_public_feedback(self):
        tape = Tape(['Parameter Extractor', 'first', 'Programming Expert', 'second',
            'def prob_case(capacity): raise ValueError("failed")', '{"input":{"capacity":4}}',
            'unparseable public response', "{'is_caused_by_you': True, 'reason': 'root cause', 'refined_result': 'new-comment'}"], exits=(1,))
        self.run_tape(tape, reflection=True, trials=1)
        self.assertEqual([call['role'] for call in tape.requests[-2:]], ['coe.Programming Expert.backward', 'coe.Parameter Extractor.backward'])
        self.assertIn('unparseable public response', tape.requests[-1]['messages'][0]['content'])
        self.assertNotIn('new-comment', tape.executions[0][1].source)

    def test_code_extraction_retains_all_non_installation_blocks_and_malformed_public_input_aborts(self):
        from llm4om.contracts import RunError
        answer = '```python\nimport math\n```\n```sh\npip install package\n```\n```python\ndef prob_case(capacity): return capacity\n```'
        tape = Tape(['Programming Expert', 'comment', answer])
        self.run_tape(tape, collaboration=1)
        code = tape.files['trial-001-code.py'].decode()
        self.assertIn('import math', code)
        self.assertIn('def prob_case', code)
        self.assertNotIn('pip', code)
        tape = Tape(['Programming Expert', 'comment', 'def prob_case(capacity): return capacity', 'invalid-input'])
        with self.assertRaises(RunError):
            self.run_tape(tape, collaboration=1, reflection=True)
        self.assertEqual(len(tape.executions), 0)
