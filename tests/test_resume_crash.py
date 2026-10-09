"""Hard exits at the documented atomic filesystem publication boundary, via CLI."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from llm4om import resume_run
from llm4om.contracts import RunError

ROOT = Path(__file__).resolve().parents[1]

# The OS rename is the actual durability boundary. Inspect published records, not
# private orchestration functions; os._exit prevents cooperative final saving.
CRASH = '''
import json, os, sys
from pathlib import Path
from llm4om.cli import main
replace = os.replace
def crash(source, target, *args, **kwargs):
    result = replace(source, target, *args, **kwargs)
    try:
        lines = Path(target).read_text().splitlines()
        record = json.loads(lines[-1])
    except (OSError, ValueError, UnicodeError, IndexError):
        return result
    if "history" not in Path(target).parts and isinstance(record, dict) and record.get("kind") == "formulation_saved":
        os._exit(91)
    return result
os.replace = crash
sys.exit(main())
'''

class CrashResumeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.inputs = self.root / 'inputs'
        shutil.copytree(ROOT / 'examples/specs', self.inputs)

    def crashed_run(self):
        output = self.root / 'runs'
        process = subprocess.run([sys.executable, '-c', CRASH, 'run', '--offline',
            '--problem', str(self.inputs / 'problem.json'), '--config', str(self.inputs / 'run.yaml'),
            '--output', str(output)], capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 91, process.stderr)
        return next(path for path in output.iterdir() if len(path.name) == 32)

    def test_hard_crash_after_publication_restores_last_checkpoint_and_counted_attempt(self):
        path = self.crashed_run()
        result = resume_run(path)
        self.assertEqual(result.status, 'artifact_ready')
        ledger = json.loads((path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['llm_attempts'], 1)
        self.assertEqual(ledger['external_llm_requests'], 0)
        events = [json.loads(line) for line in (path / 'events.jsonl').read_text().splitlines()]
        self.assertEqual(sum(event['kind'] == 'mock_call_started' for event in events), 1)

    def installed_stage_crash(self, condition, *, mode='grounded'):
        import yaml
        from test_plugins import PluginTests
        self.packages = self.root / 'packages'
        self.method_calls = self.root / 'method-calls'
        describe = '''manifest = json.loads(files(__package__).joinpath('manifest.json').read_text())
CAPABILITIES
return manifest'''
        capabilities = ''
        if mode != 'grounded':
            native = mode == 'native_gurobipy'
            capabilities = f'''manifest['capabilities'].update(
    method_profile={'native_single_candidate/0.1.0' if native else 'factory_single_candidate/0.1.0'!r},
    code_representations={['native_code' if native else 'python_factory']!r},
    model_backends={['llm4om.model_backends.gurobipy' if native else 'llm4om.model_backends.pyomo_factory']!r},
    solvers={['llm4om.solvers.gurobi' if native else 'llm4om.solvers.highs']!r}, execution_modes=['container'])'''
        PluginTests.install_method(self, describe_body=describe.replace('CAPABILITIES', capabilities), run_body=f"""from pathlib import Path
from hashlib import sha256
from llm4om import FactoryCodeProposal
from llm4om.contracts import RunError
if checkpoint is not None:
    raise RunError('checkpoint_unsupported', 'formulation', 'No internal checkpoint.')
with Path({str(self.method_calls)!r}).open('a') as calls:
    calls.write('called\\n')
response = await context.llm.complete({{'messages': [{{'role': 'user', 'content': problem['description']}}]}})
value = json.loads(response.text)
if 'source' in value:
    code = FactoryCodeProposal(value['source'], sha256(value['source'].encode()).hexdigest(),
        value['artifact']['data_bindings'], representation_kind={'native_code' if mode == 'native_gurobipy' else 'python_factory'!r})
    return MethodOutcome('candidate_selected', '001', ModelProposal(value['artifact'], value['formulation'], code=code))
return MethodOutcome('candidate_selected', '001', ModelProposal(value['artifact'], value['formulation'], value['structured_ir']))""")
        manifest = json.loads((self.packages / 'llm4om_fixture_method/manifest.json').read_text())
        self.assertFalse(manifest['capabilities']['supports_checkpoint'])
        reply = {key: json.loads((self.inputs / filename).read_text()) for key, filename in (
            ('artifact', 'model-artifact.json'), ('formulation', 'formulation.json'), ('structured_ir', 'model-ir.json'))}
        if mode != 'grounded':
            reply.pop('structured_ir')
            reply['formulation']['structured_ir_ref'] = None
            reply['source'] = (ROOT / 'examples/factories' /
                               ('production_gurobi.py' if mode == 'native_gurobipy' else 'production.py')).read_text()
        config = self.http_config(reply=reply)
        settings = yaml.safe_load(config.read_text())
        settings['method'] = {'plugin_id': manifest['plugin_id'], 'config': {'objective_offset': 0}}
        if mode != 'grounded':
            from llm4om.executors import DEFAULT_IMAGE
            settings['executor'] = yaml.safe_load((self.inputs / 'run.yaml').read_text())['executor']
            settings['executor']['config']['image'] = os.environ.get('S04B_WORKER_IMAGE', DEFAULT_IMAGE)
            if mode == 'native_gurobipy':
                settings['model_backend']['plugin_id'] = 'llm4om.model_backends.gurobipy'
                settings['solver']['plugin_id'] = 'llm4om.solvers.gurobi'
        config.write_text(yaml.safe_dump(settings))
        fault = CRASH.replace('record = json.loads(lines[-1])', 'record = json.loads(Path(target).read_text())')
        start = fault.index('    if "history"')
        end = fault.index('    return result', start)
        fault = fault[:start] + '    if ' + condition + ':\n        os._exit(91)\n' + fault[end:]
        self.plugin_env = {**os.environ, 'PYTHONPATH': os.pathsep.join((str(ROOT / 'src'), str(self.packages)))}
        output = self.root / 'runs'
        process = subprocess.run([sys.executable, '-c', fault, 'run',
            '--problem', str(self.inputs / 'problem.json'), '--config', str(config), '--output', str(output)],
            env=self.plugin_env, capture_output=True, text=True, timeout=60)
        self.assertEqual(process.returncode, 91, process.stdout + process.stderr)
        return next(path for path in output.iterdir() if len(path.name) == 32)

    def assert_installed_stage_resume(self, path):
        process = subprocess.run([sys.executable, '-m', 'llm4om', 'resume', '--run-id', path.name,
            '--output', str(path.parent)], env=self.plugin_env, capture_output=True, text=True, timeout=60)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertEqual(self.method_calls.read_text().splitlines(), ['called'])
        bundle = json.loads((path / 'bundle.json').read_text())
        self.assertEqual(bundle['status'], 'completed')
        self.assertEqual(json.loads((path / bundle['solve_result_ref']['relative_path']).read_text())['objective_value'], 13)
        ledger = json.loads((path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['llm_attempts'], 1)
        self.assertEqual(ledger['external_llm_requests'], 1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(ledger['solver_calls'], 1)
        events = [json.loads(line) for line in (path / 'events.jsonl').read_text().splitlines()]
        for kind in ('formulation_saved', 'code_saved'):
            self.assertEqual(sum(event['kind'] == kind for event in events), 1, kind)
        import hashlib
        for ref in bundle['artifacts']:
            raw = (path / ref['relative_path']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), ref['sha256'])
            self.assertEqual(len(raw), ref['size_bytes'])
        return bundle

    def test_installed_noncheckpoint_method_resumes_committed_formulation_event(self):
        path = self.installed_stage_crash('Path(target).name == "checkpoint.json" and '
            'any(event["kind"] == "formulation_saved" for event in record["payload"]["events"])')
        saved = json.loads((path / 'candidates/001/formulation-snapshot.json').read_text())
        state = json.loads((path / 'checkpoint.json').read_text())['payload']['state']
        self.assertEqual(state['phase'], 'method_done')
        self.assertIsNotNone(state['artifact_ref'])
        self.assert_installed_stage_resume(path)
        self.assertEqual(json.loads((path / 'candidates/001/formulation-snapshot.json').read_text()), saved)

    def test_installed_noncheckpoint_method_resumes_early_formulation_publication(self):
        path = self.installed_stage_crash('"history" not in Path(target).parts and '
            'record.get("stage_status", {}).get("formulation", {}).get("status") == "available" and '
            '"artifact_id" in record and "formulation_ref" in record')
        saved = (path / 'candidates/001/formulation-snapshot.json').read_bytes()
        state = json.loads((path / 'checkpoint.json').read_text())['payload']['state']
        self.assertIsNone(state['artifact_ref'])
        self.assert_installed_stage_resume(path)
        self.assertEqual((path / 'candidates/001/formulation-snapshot.json').read_bytes(), saved)

    def test_completed_code_event_commits_phase_and_is_not_duplicated(self):
        path = self.installed_stage_crash('Path(target).name == "checkpoint.json" and '
            'any(event["kind"] == "code_saved" for event in record["payload"]["events"])')
        saved = (path / 'candidates/001/artifact.json').read_bytes()
        state = json.loads((path / 'checkpoint.json').read_text())['payload']['state']
        self.assertEqual(state['phase'], 'code_done')
        self.assertEqual(state['stages']['code']['status'], 'available')
        self.assert_installed_stage_resume(path)
        self.assertEqual((path / 'candidates/001/artifact.json').read_bytes(), saved)
        self.assertTrue((path / 'candidates/001/build.json').is_file())

    def test_installed_noncheckpoint_method_can_start_from_cold_admission(self):
        path = self.installed_stage_crash('Path(target).name == "checkpoint.json" and '
            '"admission" in record["payload"]["state"] and '
            'not record["payload"]["state"].get("method_started")')
        self.assertFalse(self.method_calls.exists())
        self.assertEqual(len(self.requests), 0)
        self.assert_installed_stage_resume(path)

    def test_completed_formulation_receipt_survives_source_rejection_and_rejects_changed_bytes(self):
        path = self.installed_stage_crash('"history" not in Path(target).parts and '
            'record.get("stage_status", {}).get("formulation", {}).get("status") == "available" and '
            '"artifact_id" in record and "formulation_ref" in record')
        artifact = json.loads((path / 'candidates/001/formulation-snapshot.json').read_text())
        problem = self.inputs / 'problem.json'
        original = problem.read_bytes()
        problem.write_bytes(original + b' ')
        for _ in range(2):
            process = subprocess.run([sys.executable, '-m', 'llm4om', 'resume', '--run-id', path.name,
                '--output', str(path.parent)], env=self.plugin_env, capture_output=True, text=True, timeout=20)
            self.assertEqual(json.loads(process.stdout)['error']['code'], 'checkpoint_incompatible')
        problem.write_bytes(original)
        immutable = path / artifact['formulation_ref']['relative_path']
        original = immutable.read_bytes()
        immutable.write_bytes(original + b' ')
        process = subprocess.run([sys.executable, '-m', 'llm4om', 'resume', '--run-id', path.name,
            '--output', str(path.parent)], env=self.plugin_env, capture_output=True, text=True, timeout=20)
        self.assertEqual(json.loads(process.stdout)['error']['code'], 'checkpoint_incompatible')
        immutable.write_bytes(original)
        self.assert_installed_stage_resume(path)

    def test_installed_factory_early_formulation_keeps_original_code_and_data(self):
        self.check_installed_factory_stage('python_factory', early=True)

    def test_installed_native_early_formulation_keeps_original_code_and_data(self):
        self.check_installed_factory_stage('native_gurobipy', early=True)

    def test_installed_factory_committed_code_event_keeps_original_code_and_data(self):
        self.check_installed_factory_stage('python_factory', early=False)

    def check_installed_factory_stage(self, mode, *, early):
        condition = ('"history" not in Path(target).parts and "artifact_id" in record and '
            'record.get("stage_status", {}).get("code", {}).get("status") == "available"') if early else (
            'Path(target).name == "checkpoint.json" and '
            'any(event["kind"] == "code_saved" for event in record["payload"]["events"])')
        path = self.installed_stage_crash(condition, mode=mode)
        saved = (path / 'candidates/001/formulation-snapshot.json').read_bytes()
        artifact = json.loads(saved)
        code = json.loads((path / artifact['code_ref']['relative_path']).read_text())
        source = (path / code['representation_ref']['relative_path']).read_bytes()
        bundle = self.assert_installed_stage_resume(path)
        restored = json.loads((path / bundle['model_artifact_ref']['relative_path']).read_text())
        self.assertEqual(restored['code_ref'], artifact['code_ref'])
        self.assertEqual(restored['formulation_ref'], artifact['formulation_ref'])
        self.assertEqual(restored['data_bindings'], artifact['data_bindings'])
        self.assertEqual((path / code['representation_ref']['relative_path']).read_bytes(), source)
        self.assertEqual((path / 'candidates/001/formulation-snapshot.json').read_bytes(), saved)

    def test_unclean_owner_does_not_allow_corrupt_committed_public_bytes(self):
        path = self.crashed_run()
        (path / 'requested-config.json').write_text('{}')
        with self.assertRaises(RunError) as caught:
            resume_run(path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')

    def http_config(self, *, max_attempts=1, reply=None):
        import threading
        import yaml
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        formulation = json.loads((self.inputs / 'formulation.json').read_text())
        ir = json.loads((self.inputs / 'model-ir.json').read_text())
        compact = {'representation': formulation['representation'], 'structured_ir': {
            key: ir[key] for key in ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}}
        if reply is not None:
            compact = reply
        self.requests = []
        requests = self.requests
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                requests.append(self.rfile.read(int(self.headers['Content-Length'])))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps({'choices': [{'message': {'content': json.dumps(compact)},
                    'finish_reason': 'stop'}], 'usage': {'total_tokens': 500}}).encode())
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        settings = yaml.safe_load((self.inputs / 'solve.yaml').read_text())
        settings['budget']['max_total_tokens'] = 30000
        settings['budget']['max_llm_attempts'] = max_attempts
        settings['llm'] = {'provider_plugin_id': 'llm4om.providers.openai_compatible', 'model': 'synthetic',
            'config': {'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                       'credential_env': 'S04B_TEST_KEY', 'max_retries': 0}}
        config = self.inputs / 'http.yaml'
        config.write_text(yaml.safe_dump(settings))
        os.environ['S04B_TEST_KEY'] = 'synthetic-fixture'
        self.addCleanup(os.environ.pop, 'S04B_TEST_KEY', None)
        return config

    def test_sdk_persists_all_new_directory_ancestors_before_record_publication(self):
        import stat
        from unittest.mock import patch
        from llm4om import run_problem
        config = self.http_config()
        output = self.root / 'new' / 'nested' / 'runs'
        mkdir, fsync, replace = os.mkdir, os.fsync, os.replace
        unsynced, created, synced = set(), set(), set()
        def observe_mkdir(path, *args, **kwargs):
            result = mkdir(path, *args, **kwargs)
            path = Path(path).resolve()
            if path.is_relative_to(self.root):
                unsynced.add(path)
                created.add(path)
            return result
        def observe_fsync(fd):
            result = fsync(fd)
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                directory = Path(os.readlink(f'/proc/self/fd/{fd}'))
                persisted = {path for path in unsynced if path.parent == directory}
                synced.update(persisted)
                unsynced.difference_update(persisted)
            return result
        def observe_replace(source, target, *args, **kwargs):
            target = Path(target).resolve()
            if target.is_relative_to(output):
                self.assertFalse(set(target.parents) & unsynced,
                                 f'Record published before ancestor entries were synced: {target}')
            return replace(source, target, *args, **kwargs)
        with patch('os.mkdir', side_effect=observe_mkdir), patch('os.fsync', side_effect=observe_fsync), \
                patch('os.replace', side_effect=observe_replace):
            result = run_problem(self.inputs / 'problem.json', config, output_root=output)
        self.assertEqual(result.status, 'completed')
        self.assertEqual(created, synced)
        self.assertTrue(any(path.name == 'history' for path in created))
        self.assertTrue(any(path.name == 'checkpoints' for path in created))
        self.assertTrue(any(path.name == 'journal' for path in created))
        archive = output / '.private' / result.run_id
        self.assertEqual(archive.stat().st_mode & 0o777, 0o700)
        self.assertEqual((archive / 'journal').stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600
                            for path in archive.rglob('*') if path.is_file()))

    def resource_crash(self, status, *, journal=False, max_attempts=1):
        config = self.http_config(max_attempts=max_attempts)
        fault = CRASH.replace('record = json.loads(lines[-1])', 'record = json.loads(Path(target).read_text())')
        start = fault.index('    if "history"')
        end = fault.index('    return result', start)
        fault = fault[:start] + (
            '    if Path(target).name == "state.json" and '
            f'any(item.get("status") == {status!r} for item in record.get("attempts", [])):\n'
            '        os._exit(91)\n') + fault[end:]
        if journal:
            fault = fault.replace('Path(target).name == "state.json"', 'Path(target).parent.name == "journal"')
            fault = fault.replace('record.get("attempts", [])', 'record.get("state", {}).get("attempts", [])')
        output = self.root / 'runs'
        process = subprocess.run([sys.executable, '-c', fault, 'run',
            '--problem', str(self.inputs / 'problem.json'), '--config', str(config),
            '--output', str(output)], capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 91, process.stderr)
        return next(path for path in output.iterdir() if len(path.name) == 32)

    def test_private_success_survives_crash_before_core_callback_without_http_resend(self):
        path = self.resource_crash('success')
        result = resume_run(path)
        self.assertEqual(result.status, 'completed')
        self.assertEqual(len(self.requests), 1)
        ledger = json.loads((path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['external_llm_requests'], 1)
        self.assertEqual(ledger['total_tokens'], 500)

    def test_private_unknown_reservation_survives_crash_without_http_send(self):
        path = self.resource_crash('unknown')
        result = resume_run(path)
        bundle = json.loads((path / 'bundle.json').read_text())
        self.assertEqual(result.status, 'failed')
        self.assertEqual(bundle['error']['code'], 'provider_outcome_unknown')
        ledger = json.loads((path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['external_llm_requests'], 1)
        self.assertGreater(ledger['reserved_tokens'], 0)
        self.assertIsNone(ledger['total_tokens'])
        self.assertEqual(len(self.requests), 0)

    def test_success_journal_commit_before_mutable_head_is_reconciled_without_resend(self):
        path = self.resource_crash('success', journal=True)
        result = resume_run(path)
        self.assertEqual(result.status, 'completed')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(json.loads((path / 'budget-ledger.json').read_text())['total_tokens'], 500)

    def test_genesis_journal_before_first_head_recovers_without_losing_admission(self):
        config = self.http_config()
        fault = CRASH.replace('record = json.loads(lines[-1])', 'record = json.loads(Path(target).read_text())')
        start = fault.index('    if "history"')
        end = fault.index('    return result', start)
        fault = fault[:start] + (
            '    if Path(target).parent.name == "journal" and not record["state"]["attempts"]:\n'
            '        os._exit(91)\n') + fault[end:]
        process = subprocess.run([sys.executable, '-c', fault, 'run',
            '--problem', str(self.inputs / 'problem.json'), '--config', str(config),
            '--output', str(self.root / 'runs')], capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 91, process.stderr)
        path = next(path for path in (self.root / 'runs').iterdir() if len(path.name) == 32)
        self.assertEqual(len(self.requests), 0)
        self.assertEqual(resume_run(path).status, 'completed')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(json.loads((path / 'budget-ledger.json').read_text())['external_llm_requests'], 1)

    def test_explicit_semantic_rerun_keeps_unknown_parent_usage_and_reservations_visible(self):
        path = self.resource_crash('unknown', max_attempts=3)
        checkpoint = (path / 'checkpoint.json').read_bytes()
        child = resume_run(path, strategy='rerun')
        self.assertNotEqual(child.run_id, path.name)
        self.assertEqual(child.status, 'completed')
        self.assertEqual((path / 'checkpoint.json').read_bytes(), checkpoint)
        ledger = json.loads((child.bundle_path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['external_llm_requests'], 2)
        self.assertEqual(ledger['known_total_tokens'], 500)
        self.assertIsNone(ledger['total_tokens'])
        self.assertGreater(ledger['reserved_tokens'], 0)
        bundle = json.loads((child.bundle_path / 'bundle.json').read_text())
        lineage = json.loads((child.bundle_path / bundle['lineage_ref']['relative_path']).read_text())
        self.assertEqual(lineage['parent_resource_records'][0]['status'], 'unknown')
        self.assertEqual(lineage['reused_records'], [])
        self.assertEqual(len(self.requests), 1)

    def test_explicit_rerun_does_not_forget_exhausted_parent_attempt_cap(self):
        path = self.resource_crash('success')
        child = resume_run(path, strategy='rerun')
        bundle = json.loads((child.bundle_path / 'bundle.json').read_text())
        self.assertEqual(child.status, 'failed')
        self.assertEqual(bundle['error']['code'], 'budget_exhausted')
        self.assertEqual(json.loads((child.bundle_path / 'budget-ledger.json').read_text())['external_llm_requests'], 1)
        self.assertEqual(len(self.requests), 1)

    def test_storage_failure_after_view_commit_is_recoverable_without_losing_attempt(self):
        from unittest.mock import patch
        from llm4om import run_problem
        replace = os.replace
        def failing_storage(source, target, *args, **kwargs):
            result = replace(source, target, *args, **kwargs)
            if 'history' not in Path(target).parts:
                try:
                    event = json.loads(Path(target).read_text().splitlines()[-1])
                except (ValueError, OSError, IndexError):
                    return result
                if isinstance(event, dict) and event.get('kind') == 'formulation_saved':
                    raise OSError('Synthetic failure after OS rename')
            return result
        with patch('os.replace', side_effect=failing_storage):
            with self.assertRaises(OSError):
                run_problem(self.inputs / 'problem.json', self.inputs / 'run.yaml',
                            offline=True, output_root=self.root / 'runs')
        path = next(path for path in (self.root / 'runs').iterdir() if len(path.name) == 32)
        self.assertEqual(resume_run(path).status, 'artifact_ready')
        self.assertEqual(json.loads((path / 'budget-ledger.json').read_text())['llm_attempts'], 1)

    def test_solver_started_attempt_is_retained_across_hard_crash(self):
        import yaml
        config = self.inputs / 'solve.yaml'
        settings = yaml.safe_load(config.read_text())
        settings['budget']['max_solver_calls'] = 2
        config.write_text(yaml.safe_dump(settings))
        process = subprocess.run([sys.executable, '-c', CRASH.replace('formulation_saved', 'solver_started'),
            'run', '--problem', str(self.inputs / 'problem.json'), '--config', str(config),
            '--output', str(self.root / 'runs')], capture_output=True, text=True, timeout=10)
        self.assertEqual(process.returncode, 91, process.stderr)
        path = next(path for path in (self.root / 'runs').iterdir() if len(path.name) == 32)
        self.assertEqual(resume_run(path).status, 'completed')
        ledger = json.loads((path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['solver_calls'], 2)
        self.assertEqual(ledger['llm_attempts'], 1)

    def test_completed_solve_hard_crash_reuses_result_with_exhausted_solver_cap(self):
        process = subprocess.run([sys.executable, '-c', CRASH.replace('formulation_saved', 'solver_finished'),
            'run', '--problem', str(self.inputs / 'problem.json'),
            '--config', str(self.inputs / 'solve.yaml'), '--output', str(self.root / 'runs')],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(process.returncode, 91, process.stderr)
        path = next(path for path in (self.root / 'runs').iterdir() if len(path.name) == 32)
        result = resume_run(path)
        self.assertEqual(result.status, 'completed', json.loads((path / 'bundle.json').read_text()).get('error'))
        ledger = json.loads((path / 'budget-ledger.json').read_text())
        self.assertEqual(ledger['solver_calls'], 1)
        self.assertEqual(json.loads((path / 'candidates/001/solve-result.json').read_text())['objective_value'], 13)
        events = [json.loads(line) for line in (path / 'events.jsonl').read_text().splitlines()]
        self.assertEqual(sum(event['kind'] == 'solver_started' for event in events), 1)
        self.assertEqual(sum(event['kind'] == 'execution_reused' for event in events), 1)

    def completed_execution_crash(self, config=None):
        fault = CRASH.replace('record = json.loads(lines[-1])', 'record = json.loads(Path(target).read_text())')
        fault = fault.replace('record.get("kind") == "formulation_saved"',
            'record.get("execution_id") == "execution-001" and record.get("status") == "completed"')
        output = self.root / 'runs' / (config.stem if config else 'grounded')
        process = subprocess.run([sys.executable, '-c', fault, 'run',
            '--problem', str(self.inputs / 'problem.json'),
            '--config', str(config or self.inputs / 'solve.yaml'), '--output', str(output)],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(process.returncode, 91, process.stderr)
        path = next(path for path in output.iterdir() if len(path.name) == 32)
        self.assertEqual(json.loads((path / 'checkpoint.json').read_text())['payload']['state']['phase'],
                         'execute_pending')
        return path

    def test_completed_execution_projection_reuses_solve_before_core_done(self):
        from unittest.mock import patch
        path = self.completed_execution_crash()
        execution = json.loads((path / 'candidates/001/execution.json').read_text())
        self.assertEqual(execution['status'], 'completed')
        with patch('subprocess.Popen', side_effect=AssertionError('Completed recovery must not launch another Solver')):
            result = resume_run(path)
        self.assertEqual(result.status, 'completed', json.loads((path / 'bundle.json').read_text()).get('error'))
        bundle = json.loads((path / 'bundle.json').read_text())
        self.assertEqual(bundle['solve_result_ref'], execution['solve_result_ref'])
        self.assertEqual(json.loads((path / bundle['solve_result_ref']['relative_path']).read_text())['objective_value'], 13)
        self.assertEqual(json.loads((path / 'budget-ledger.json').read_text())['solver_calls'], 1)
        events = [json.loads(line) for line in (path / 'events.jsonl').read_text().splitlines()]
        self.assertEqual(sum(event['kind'] == 'solver_started' for event in events), 1)
        self.assertEqual(sum(event['kind'] == 'execution_reused' for event in events), 1)

    def test_completed_execution_receipt_survives_repeated_failed_resume(self):
        path = self.completed_execution_crash()
        problem = self.inputs / 'problem.json'
        original = problem.read_bytes()
        problem.write_bytes(original + b' ')
        for _ in range(2):
            with self.assertRaises(RunError) as caught:
                resume_run(path)
            self.assertEqual(caught.exception.code, 'checkpoint_incompatible')
        problem.write_bytes(original)
        result = resume_run(path)
        self.assertEqual(result.status, 'completed')
        self.assertEqual(json.loads((path / 'budget-ledger.json').read_text())['solver_calls'], 1)
        self.assertEqual(json.loads((path / 'candidates/001/solve-result.json').read_text())['objective_value'], 13)

    def test_completed_execution_requires_actual_immutable_result_bytes(self):
        path = self.completed_execution_crash()
        execution = json.loads((path / 'candidates/001/execution.json').read_text())
        immutable = path / execution['solve_result_ref']['relative_path']
        original = immutable.read_bytes()
        immutable.write_bytes(original + b' ')
        with self.assertRaises(RunError) as caught:
            resume_run(path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')
        immutable.write_bytes(original)
        self.assertEqual(resume_run(path).status, 'completed')

    def test_completed_execution_receipt_commit_interruption_remains_recoverable(self):
        from unittest.mock import patch
        path = self.completed_execution_crash()
        replace = os.replace
        def interrupt_receipt(source, target, *args, **kwargs):
            result = replace(source, target, *args, **kwargs)
            try:
                record = json.loads(Path(target).read_text())
            except (OSError, ValueError):
                return result
            if 'checkpoints' not in Path(target).parts and record.get('payload', {}).get('interrupted_publications'):
                raise OSError('Synthetic interruption after durable receipt commit')
            return result
        with patch('os.replace', side_effect=interrupt_receipt):
            with self.assertRaises(RunError) as caught:
                resume_run(path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')
        self.assertEqual(resume_run(path).status, 'completed')
        self.assertEqual(json.loads((path / 'budget-ledger.json').read_text())['solver_calls'], 1)

    def test_unrecorded_completed_public_execution_cannot_replace_solver_evidence(self):
        path = self.completed_execution_crash()
        projection = path / 'candidates/001/execution.json'
        original = projection.read_bytes()
        execution = json.loads(original)
        execution['solve_result_ref']['sha256'] = '0' * 64
        projection.write_text(json.dumps(execution))
        with self.assertRaises(RunError) as caught:
            resume_run(path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')
        projection.write_bytes(original)
        self.assertEqual(resume_run(path).status, 'completed')

    def test_completed_execution_rejects_foreign_binding_with_consistent_publication_hashes(self):
        import hashlib
        from unittest.mock import patch
        path = self.completed_execution_crash()
        name = 'candidates/001/execution.json'
        execution = json.loads((path / name).read_text())
        checkpoint = json.loads((path / 'checkpoint.json').read_text())['payload']
        execution['input_artifact_ref'] = checkpoint['projections']['candidates/001/formulation-snapshot.json']
        raw = (json.dumps(execution, ensure_ascii=False, indent=2) + '\n').encode()
        publication = json.loads((path / 'publication.json').read_text())
        ref = publication['projections'][name][-1]
        ref.update(sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
        ref['relative_path'] = 'history/' + ref['sha256'] + '/' + name
        immutable = path / ref['relative_path']
        immutable.parent.mkdir(parents=True)
        immutable.write_bytes(raw)
        (path / name).write_bytes(raw)
        (path / 'publication.json').write_text(json.dumps(publication))
        with patch('subprocess.Popen', side_effect=AssertionError('Binding rejection must precede resources')):
            with self.assertRaises(RunError) as caught:
                resume_run(path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')

    def test_completed_execution_projection_preserves_factory_and_native_binding(self):
        import yaml
        from llm4om.executors import DEFAULT_IMAGE
        from test_factory_run import FactoryRunTests
        for mode, filename in (('python_factory', 'production.py'), ('native_gurobipy', 'production_gurobi.py')):
            with self.subTest(mode=mode):
                self.config = yaml.safe_load((self.inputs / 'run.yaml').read_text())
                self.config['method']['config']['output_mode'] = mode
                self.config['executor']['config']['image'] = os.environ.get('S04B_WORKER_IMAGE', DEFAULT_IMAGE)
                if mode == 'native_gurobipy':
                    self.config['model_backend']['plugin_id'] = 'llm4om.model_backends.gurobipy'
                    self.config['solver']['plugin_id'] = 'llm4om.solvers.gurobi'
                FactoryRunTests.start_provider(self, (ROOT / 'examples/factories' / filename).read_text())
                if mode == 'native_gurobipy':
                    self.reply[mode] = self.reply.pop('python_factory')
                config = self.inputs / (mode + '.yaml')
                config.write_text(yaml.safe_dump(self.config))
                os.environ['S02B_FIXTURE_KEY'] = 'synthetic-fixture'
                self.addCleanup(os.environ.pop, 'S02B_FIXTURE_KEY', None)
                path = self.completed_execution_crash(config)
                execution = json.loads((path / 'candidates/001/execution.json').read_text())
                process = subprocess.run([sys.executable, '-m', 'llm4om', 'resume', '--run-id', path.name,
                    '--output', str(path.parent)], capture_output=True, text=True, timeout=30)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                bundle = json.loads((path / 'bundle.json').read_text())
                self.assertEqual(bundle['model_artifact_ref'], execution['artifact_ref'])
                self.assertEqual(bundle['solve_result_ref'], execution['solve_result_ref'])
                artifact = json.loads((path / bundle['model_artifact_ref']['relative_path']).read_text())
                self.assertEqual(artifact['optional_views'][-1]['source_code_ref'], artifact['code_ref'])
                self.assertEqual(json.loads((path / bundle['solve_result_ref']['relative_path']).read_text())['objective_value'], 13)
                self.assertEqual(json.loads((path / 'budget-ledger.json').read_text())['solver_calls'], 1)
                self.assertEqual(len(self.requests), 1)
                events = [json.loads(line) for line in (path / 'events.jsonl').read_text().splitlines()]
                self.assertEqual(sum(event['kind'] == 'solver_started' for event in events), 1)
                self.assertEqual(sum(event['kind'] == 'execution_reused' for event in events), 1)

    def test_corrupt_private_head_and_immutable_response_are_refused_before_http(self):
        import hashlib
        path = self.resource_crash('success')
        archive = path.parent / '.private' / path.name
        head = archive / 'state.json'
        original = head.read_bytes()
        head.write_bytes(original + b' ')
        with self.assertRaises(RunError) as caught:
            resume_run(path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')
        head.write_bytes(original)
        head.unlink()
        with self.assertRaises(RunError) as caught:
            resume_run(path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')
        head.write_bytes(original)
        head.chmod(0o600)
        version = archive / 'journal' / (hashlib.sha256(original).hexdigest() + '.json')
        record = json.loads(version.read_text())
        record['state']['attempts'][0]['reply'] = 'corrupt response'
        version.write_text(json.dumps(record))
        with self.assertRaises(RunError) as caught:
            resume_run(path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(archive.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(item.stat().st_mode & 0o777 == 0o600
                            for item in archive.rglob('*') if item.is_file()))

    def test_committed_settlement_rejects_valid_older_genesis_head_before_resources(self):
        from llm4om import run_problem
        config = self.http_config()
        result = run_problem(self.inputs / 'problem.json', config, output_root=self.root / 'runs')
        self.assertEqual(result.status, 'completed')
        path = result.bundle_path
        archive = path.parent / '.private' / path.name
        genesis = next(json.loads(item.read_text())['state'] for item in (archive / 'journal').glob('*.json')
                       if json.loads(item.read_text())['previous_sha256'] is None)
        (archive / 'state.json').write_bytes(json.dumps(genesis, allow_nan=False).encode())
        checkpoint = (path / 'checkpoint.json').read_bytes()
        events = (path / 'events.jsonl').read_bytes()
        with self.assertRaises(RunError) as caught:
            resume_run(path)
        self.assertEqual(caught.exception.code, 'checkpoint_incompatible')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual((path / 'checkpoint.json').read_bytes(), checkpoint)
        self.assertEqual((path / 'events.jsonl').read_bytes(), events)


class DerivedRerunTests(unittest.TestCase):
    setUp = CrashResumeTests.setUp
    def test_explicit_rerun_creates_child_preserving_parent_history_and_usage(self):
        from llm4om import run_problem
        import yaml
        config = self.inputs / 'run.yaml'
        settings = yaml.safe_load(config.read_text())
        settings['budget']['max_llm_attempts'] = 2
        config.write_text(yaml.safe_dump(settings))
        parent = run_problem(self.inputs / 'problem.json', self.inputs / 'run.yaml',
                             offline=True, output_root=self.root / 'runs')
        before = (parent.bundle_path / 'events.jsonl').read_bytes()
        ledger = json.loads((parent.bundle_path / 'budget-ledger.json').read_text())
        child = resume_run(parent.bundle_path, strategy='rerun')
        self.assertNotEqual(child.run_id, parent.run_id)
        self.assertEqual(child.status, 'artifact_ready')
        self.assertEqual((parent.bundle_path / 'events.jsonl').read_bytes(), before)
        bundle = json.loads((child.bundle_path / 'bundle.json').read_text())
        lineage = json.loads((child.bundle_path / bundle['lineage_ref']['relative_path']).read_text())
        self.assertEqual(lineage['operation'], 'derived_rerun')
        self.assertEqual(lineage['parent_run_id'], parent.run_id)
        self.assertEqual(lineage['parent_budget_ledger'], ledger)
        self.assertEqual(lineage['input_hashes'], json.loads(
            (parent.bundle_path / 'checkpoint.json').read_text())['payload']['state']['sources'])
        child_ledger = json.loads((child.bundle_path / 'budget-ledger.json').read_text())
        self.assertEqual(child_ledger['llm_attempts'], 2)
        for ref in lineage['parent_artifacts']:
            self.assertTrue((child.bundle_path / ref['relative_path']).is_file())


if __name__ == '__main__':
    unittest.main()
