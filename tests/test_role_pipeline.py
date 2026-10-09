"""RunConfig role selection through the public SDK and real HiGHS."""

import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import yaml

from llm4om import run_problem, resume_run
from llm4om.preflight import prepare_run
from llm4om.contracts import RunError


class RolePipelineTests(unittest.TestCase):
    def test_role_configuration_is_checked_by_public_admission_without_http(self):
        config = yaml.safe_load((Path(__file__).parents[1] / 'examples/specs/solve.yaml').read_text())
        base = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'same-model',
            'config': {'base_url': 'https://example.com/v1', 'credential_env': 'ROLE_KEY'}}
        config['llm'] = {**base, 'role_models': {'critic': {**base,
            'config': {**base['config'], 'base_url': 'https://another.example.com/v1'}}}}
        plan = prepare_run(config, identity_only=True)
        self.assertEqual(plan.snapshot['model_comparison'], 'same_requested_model_roles')
        self.assertEqual(plan.snapshot['role_resource_comparison'], 'different_role_resources')
        for selection, code in [({'provider_plugin_id': 'llm4om.providers.mock', 'model': 'mock', 'config': {}}, 'capability_mismatch'),
                ({**base, 'config': {**base['config'], 'max_output_tokens': 0}}, 'invalid_config'),
                ({**base, 'provider_plugin_id': 'unavailable.provider'}, 'unknown_plugin')]:
            with self.subTest(selection=selection):
                config['llm']['role_models']['critic'] = selection
                with self.assertRaises(RunError) as error:
                    prepare_run(config, identity_only=True)
                self.assertEqual(error.exception.code, code)

    def test_declared_formulation_model_is_used_by_actual_application_and_saved_trace(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        repo = Path(__file__).parents[1]
        shutil.copytree(repo / 'examples/specs', root / 'input')
        requests = []
        formulation = json.loads((root / 'input/formulation.json').read_text())['representation']
        ir = json.loads((root / 'input/model-ir.json').read_text())
        for parameter, value in zip(formulation['parameters'], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
            parameter.pop('source')
            parameter['value'] = value
        compact = {'representation': formulation, 'structured_ir': {key: ir[key] for key in ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}}
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append(request)
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'model': request['model'], 'choices': [{'message': {'content': json.dumps(compact)}, 'finish_reason': 'stop'}],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}}).encode())
            def log_message(self, *args): pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        provider = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'default-model',
            'config': {'base_url': f'http://127.0.0.1:{server.server_port}/v1', 'credential_env': 'ROLE_PIPELINE_KEY', 'max_output_tokens': 3000, 'max_retries': 0}}
        config = yaml.safe_load((root / 'input/solve.yaml').read_text())
        config['llm'] = {**provider, 'role_models': {'formulation': {**provider, 'model': 'formulation-model'}}}
        config['budget']['max_total_tokens'] = 30000
        (root / 'config.yaml').write_text(yaml.safe_dump(config))
        with patch.dict(os.environ, {'ROLE_PIPELINE_KEY': 'synthetic'}):
            result = run_problem(root / 'input/problem.json', root / 'config.yaml', output_root=root / 'runs')
        bundle = json.loads((result.bundle_path / 'bundle.json').read_text())
        self.assertEqual(result.status, 'completed', bundle['error'])
        self.assertEqual([request['model'] for request in requests], ['formulation-model'])
        trace = json.loads((result.bundle_path / 'llm-trace.json').read_text())['attempts']
        self.assertEqual(trace[0]['requested_model'], 'formulation-model')
        self.assertEqual(trace[0]['model'], 'formulation-model')
        solve = json.loads((result.bundle_path / bundle['solve_result_ref']['relative_path']).read_text())
        self.assertEqual(solve['objective_value'], 13)
        plan = json.loads((result.bundle_path / 'admission-plan.json').read_text())
        self.assertEqual(plan['role_models']['formulation']['model'], 'formulation-model')
        self.assertEqual(plan['model_comparison'], 'heterogeneous_role_models')
        self.assertEqual(resume_run(result.bundle_path).status, 'completed')
        self.assertEqual(len(requests), 1)
