"""S05 CLI admission and HTTP-to-HiGHS pipeline, without collaborator mocks."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


class ProviderAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = yaml.safe_load((ROOT / 'examples/specs/run.yaml').read_text())
        self.settings['executor'] = {'plugin_id': 'llm4om.executors.trusted_local', 'config': {}}
        self.settings['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible',
                                'model': 'deepseek-v4-pro-0813',
                                'config': {'base_url': 'https://example.invalid/v1', 'credential_env': 'S05_PIPELINE_KEY'}}
        self.config = self.root / 'run.yaml'

    def cli(self, *args, credential=None):
        self.config.write_text(yaml.safe_dump(self.settings))
        env = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        env.pop('S05_PIPELINE_KEY', None)
        if credential is not None:
            env['S05_PIPELINE_KEY'] = credential
        return subprocess.run([sys.executable, '-m', 'llm4om', *args, '--config', str(self.config)],
                              cwd=self.root, env=env, capture_output=True, text=True)

    def test_missing_credential_rejected_before_method(self):
        result = self.cli('doctor')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'auth_error')

    def test_doctor_is_unpaid_and_literal_env_is_not_exported(self):
        (self.root / '.env').write_text('S05_PIPELINE_KEY=file-synthetic\nUNUSED=$(touch executed)\n')
        result = self.cli('doctor', credential='process-synthetic')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('synthetic', result.stdout)
        self.assertFalse((self.root / 'executed').exists())
        self.assertEqual(json.loads(result.stdout)['connectivity_checks']['status'], 'not_requested')

    def test_external_provider_cannot_be_offline_mock(self):
        result = self.cli('doctor', '--offline', credential='process-synthetic')
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['error']['code'], 'capability_mismatch')

    def test_project_env_works_with_a_nested_config(self):
        (self.root / '.env').write_text('S05_PIPELINE_KEY=project-synthetic\n')
        nested = self.root / 'configs'
        nested.mkdir()
        self.config = nested / 'run.yaml'
        result = self.cli('doctor')
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn('project-synthetic', result.stdout)

    def test_headers_and_url_credentials_are_rejected_without_export(self):
        for config in [{'headers': {'X-secret': 'S05-PRIVATE-SENTINEL'}},
                       {'base_url': 'https://user:S05-PRIVATE-SENTINEL@example.invalid/v1'}]:
            self.settings['llm']['config'].update(config)
            result = self.cli('run', '--problem', str(ROOT / 'examples/specs/problem.json'),
                              '--output', str(self.root / 'runs'), credential='synthetic-key')
            self.assertEqual(result.returncode, 1)
            path = Path(json.loads(result.stdout)['bundle_path'])
            self.assertEqual(json.loads((path / 'bundle.json').read_text())['error']['code'], 'private_input')
            self.assertNotIn('S05-PRIVATE-SENTINEL', '\n'.join(file.read_text() for file in path.rglob('*') if file.is_file()))
            self.settings['llm']['config'].pop('headers', None)


class HTTPPipelineTests(unittest.TestCase):
    def test_public_cli_lp13_full_problem_csv_and_private_reply(self):
        self.run_pipeline()

    def test_public_cli_no_data_continuous_problem(self):
        self.run_pipeline(no_data=True)

    def test_truncated_generation_preserves_usage_without_a_formulation(self):
        self.run_pipeline(truncated=True)

    def run_pipeline(self, no_data=False, truncated=False):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading
        public = json.loads((ROOT / 'examples/specs/problem.json').read_text())
        formulation = json.loads((ROOT / 'examples/specs/formulation.json').read_text())
        ir = json.loads((ROOT / 'examples/specs/model-ir.json').read_text())
        compact = {'representation': formulation['representation'],
                   'structured_ir': {key: ir[key] for key in ['problem_type', 'variables', 'objective', 'constraints', 'assumptions']}}
        if no_data:
            public['data_refs'] = []
            public['description'] = 'Choose nonnegative real A,B. Maximize 3*A+2*B with 2*A+B<=8 and A+2*B<=8.'
            public['problem_type_hint'] = 'lp'
            public['requirements'][1]['text'] = 'A and B are nonnegative real numbers.'
            for parameter, value in zip(compact['representation']['parameters'], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
                parameter.pop('source')
                parameter['value'] = value
            compact['representation']['variables'][0]['domain'] = 'continuous'
            compact['structured_ir']['problem_type'] = 'lp'
            for variable in compact['structured_ir']['variables']:
                variable['domain'] = 'continuous'
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append((dict(self.headers), json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'id': 'local-hand-fixture', 'model': 'deepseek-v4-pro-0813',
                    'choices': [{'message': {'content': '' if truncated else json.dumps(compact)}, 'finish_reason': 'length' if truncated else 'stop'}],
                    'usage': {'prompt_tokens': 200, 'completion_tokens': 300, 'total_tokens': 500}}).encode())
            def log_message(self, *args):
                pass
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'examples/specs', root / 'input')
            (root / 'input/problem.json').write_text(json.dumps(public))
            settings = yaml.safe_load((root / 'input/run.yaml').read_text())
            settings['executor'] = {'plugin_id': 'llm4om.executors.trusted_local', 'config': {}}
            settings['budget']['max_total_tokens'] = 30000
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            settings['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'deepseek-v4-pro-0813',
                               'config': {'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                                          'credential_env': 'S05_PIPELINE_KEY', 'max_output_tokens': 2048}}
            config = root / 'input/run.yaml'
            config.write_text(yaml.safe_dump(settings))
            result = subprocess.run([sys.executable, '-m', 'llm4om', 'run', '--problem', str(root / 'input/problem.json'),
                                     '--config', str(config), '--output', str(root / 'runs')],
                                    cwd=root, env={**os.environ, 'S05_PIPELINE_KEY': 'synthetic-key'}, capture_output=True, text=True)
            path = Path(json.loads(result.stdout)['bundle_path'])
            if truncated:
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                bundle = json.loads((path / 'bundle.json').read_text())
                self.assertEqual(bundle['error']['code'], 'llm_output_truncated')
                self.assertIsNone(bundle['model_artifact_ref'])
                trace = json.loads((path / 'llm-trace.json').read_text())
                self.assertEqual(trace['attempts'][0]['usage']['total_tokens'], 500)
                return
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            solve = json.loads((path / 'checks/001/solve-result.json').read_text())
            self.assertAlmostEqual(solve['objective_value'], 40 / 3 if no_data else 13)
            self.assertEqual(solve['termination'], 'optimal')
            self.assertEqual(len(requests), 1)
            prompt = requests[0][1]['messages'][1]['content']
            sent = json.loads(prompt)
            self.assertEqual(sent['problem']['description'], public['description'])
            self.assertEqual(sent['problem']['requirements'], public['requirements'])
            if no_data:
                self.assertEqual(sent['data'], {})
            else:
                self.assertIn('A,3,2,1', sent['data']['products'])
            exported = '\n'.join(file.read_text() for file in path.rglob('*') if file.is_file())
            self.assertNotIn('synthetic-key', exported)
            trace = json.loads((path / 'llm-trace.json').read_text())
            self.assertNotIn('representation', json.dumps(trace))
            self.assertEqual(trace['attempts'][0]['model'], 'deepseek-v4-pro-0813')
            self.assertTrue((path.parent / '.private' / path.name / 'state.json').exists())
            bundle = json.loads((path / 'bundle.json').read_text())
            self.assertFalse(any('.private' in ref['relative_path'] for ref in bundle['artifacts']))
            artifact = json.loads((path / 'checks/001/artifact.json').read_text())
            self.assertEqual(artifact['provenance']['origin'], 'external_provider')
            self.assertNotIn('hand_authored_design_fixture', json.dumps(artifact))
