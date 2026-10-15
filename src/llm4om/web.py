"""Local single-user workbench over the existing application and public records."""

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
import hashlib
import ipaddress
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from io import BytesIO, StringIO
from itertools import islice
import json
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
import zipfile

from llm4om.contracts import RunError, parse_json, public_path, read_public_bytes, validate_config, validate_problem, validate_data, parse_reference_json
from llm4om.control import CancellationToken
from llm4om.executors import run_owned_process
from llm4om.experiments import LIMITS, cancel_experiment
from llm4om.assisted import export_edit
from llm4om.providers import credential_environment
from llm4om.run_records import read_run_ref
from llm4om.benchmarks import list_benchmarks, benchmark_detail
from llm4om.workbench import llm_presets, method_presets, validate_llm_preset
from llm4om.storage import cancel_run

MAX_REQUEST = 24 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024
WEB_KEY_ENV = 'LLM4OM_WEB_API_KEY'


def _json_file(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def _identifier(value: str) -> str:
    if len(value) != 32 or any(char not in '0123456789abcdef' for char in value):
        raise RunError('invalid_request', 'web', 'Expected a workspace job ID.')
    return value


def _data_preview(raw: bytes, format_name: str, *, total_items: int | None = None) -> dict[str, Any]:
    if len(raw) > MAX_FILE or format_name not in {'csv', 'json'}:
        raise RunError('invalid_data', 'web', 'Preview CSV or object JSON files up to8 MiB.')
    try:
        if format_name == 'csv':
            reader = csv.reader(StringIO(raw.decode('utf-8')), strict=True)
            header = next(reader)
            columns = header[:16]
            rows = [row[:16] for row in islice(reader, 20)]
            if total_items is None:
                total_items = len(rows) + sum(1 for _ in reader)
            truncated = len(header) > 16 or total_items > len(rows)
        else:
            value = parse_json(raw)
            columns = ['字段', '值']
            rows = [[key, json.dumps(item, ensure_ascii=False, allow_nan=False)] for key, item in islice(value.items(), 20)]
            total_items = len(value)
            truncated = total_items > len(rows)
    except (UnicodeDecodeError, csv.Error, StopIteration) as error:
        raise RunError('invalid_data', 'web', 'Cannot preview this file as UTF-8 CSV or object JSON.') from error
    truncated = truncated or any(len(cell) > 256 for row in rows for cell in row)
    return {'columns': columns, 'rows': [[cell[:256] + '…' if len(cell) > 256 else cell for cell in row] for row in rows],
            'total_items': total_items, 'display_truncated': truncated}


def _application(arguments: list[str], *, deadline: float,
                 cancellation: CancellationToken, environment: dict[str, str] | None = None) -> dict[str, Any]:
    raw, _, _ = run_owned_process([sys.executable, '-m', 'llm4om', *arguments], b'',
        deadline=deadline, cancellation=cancellation, cancel_grace_s=10,
        environment={**os.environ, **environment} if environment else None)
    try:
        result = parse_json(raw)
    except RunError as error:
        raise RunError('web_run_error', 'web', 'Application did not return a saved result.') from error
    if result.get('error'):
        raise RunError(result['error']['code'], 'web', result['error']['message'])
    return result


class WebWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='llm4om-web')
        self.lock = threading.Lock()
        self.active: dict[str, CancellationToken] = {}
        # shortcut: page keys live for this server session; add durable secrets only if persistent connections are needed.
        self.credentials: dict[str, dict[str, str]] = {}

    def _request_environment(self, config: dict[str, Any], api_key: str | None) -> dict[str, str]:
        selected = config['llm']
        if api_key is None:
            if selected['config'].get('credential_env') == 'LLM4OM_LLM_API_KEY':
                environment = credential_environment(Path.cwd() / '.env')
                default_url = environment.get('LLM4OM_LLM_BASE_URL', 'https://api.openai.com/v1')
                if (selected['provider_plugin_id'] != 'llm4om.providers.openai_compatible'
                        or selected['config'].get('base_url', '').rstrip('/') != default_url.rstrip('/')):
                    raise RunError('auth_error', 'web', 'Enter an API key for the selected LLM endpoint.')
            return {}
        if not isinstance(api_key, str) or not 1 <= len(api_key) <= 4096 or any(not 33 <= ord(char) <= 126 for char in api_key):
            raise RunError('auth_error', 'web', 'API key must be a nonempty printable token without spaces.')
        previous = selected['config'].get('credential_env')
        if previous is None:
            raise RunError('invalid_config', 'web', 'The selected Provider does not declare credential_env.')
        for selection in [selected, *selected.get('role_models', {}).values()]:
            if selection['config'].get('credential_env') == previous:
                selection['config']['credential_env'] = WEB_KEY_ENV
        return {WEB_KEY_ENV: api_key}

    def bootstrap(self) -> dict[str, Any]:
        environment = credential_environment(Path.cwd() / '.env')
        presets = method_presets()
        preset = presets['llm4om.methods.direct']
        config: dict[str, Any] = {'schema_version': '0.2.0',
            'method': {'plugin_id': 'llm4om.methods.direct', 'config': preset['config']},
            'llm': {'provider_plugin_id': 'llm4om.providers.openai_compatible',
                'model': environment.get('LLM4OM_LLM_MODEL', 'your-model'),
                'config': {'base_url': environment.get('LLM4OM_LLM_BASE_URL', 'https://api.openai.com/v1'),
                    'credential_env': 'LLM4OM_LLM_API_KEY', 'max_retries': 0, 'timeout_s': 90, 'max_output_tokens': 32768}},
            'compiler': preset['compiler'],
            'model_backend': preset['model_backend'],
            'solver': {**preset['solver'], 'options': {'time_limit_s': 30}},
            'executor': {'plugin_id': 'llm4om.executors.container', 'config': {'network': False, 'cpu_limit': 1,
                'memory_limit_mb': 1024, 'wall_time_s': 60}},
            'budget': {**preset['budget'], 'max_concurrency': 1},
            'store': {'plugin_id': 'llm4om.stores.filesystem', 'config': {'root': 'runs'}},
            'reporters': [{'plugin_id': 'llm4om.reporters.jsonl'}, {'plugin_id': 'llm4om.reporters.markdown'}]}
        inventory = _application(['plugins', 'list'], deadline=time.time() + 30, cancellation=CancellationToken())
        if environment.get('LLM4OM_LLM_PROXY_URL'):
            proxy = environment['LLM4OM_LLM_PROXY_URL']
            candidate = urlsplit(proxy)
            # Mirror the Provider admission rule so proxy credentials never reach the client config.
            if (candidate.scheme != 'http' or not candidate.hostname or candidate.port == 0
                    or candidate.username is not None or candidate.password is not None
                    or candidate.path not in {'', '/'} or candidate.query or candidate.fragment
                    or any(ord(char) < 33 or char.isspace() for char in proxy)):
                raise RunError('invalid_config', 'web', 'LLM4OM_LLM_PROXY_URL must be a plain http:// proxy URL without credentials.')
            config['llm']['config']['proxy_url'] = proxy
        key = environment.get('LLM4OM_LLM_API_KEY', '')
        credential = {'provider_plugin_id': config['llm']['provider_plugin_id'],
            'base_url': config['llm']['config']['base_url'], 'configured': bool(key),
            'preview': key[:4] + '••••' + key[-4:] if len(key) > 12 else '••••' if key else ''}
        return {'config': config, 'method_presets': presets, 'llm_presets': llm_presets(),
            'default_credential': credential, 'plugins': inventory['plugins'], 'jobs': self.list_jobs(), 'tasks': self.list_tasks(), 'experiments': self.list_experiments()}

    def doctor(self, config: dict[str, Any], *, check_connectivity: bool = False,
               api_key: str | None = None, llm_preset: str | None = None) -> dict[str, Any]:
        if type(check_connectivity) is not bool:
            raise RunError('invalid_request', 'web', 'Connectivity selection must be a boolean.')
        config = deepcopy(config)
        validate_config(config)
        validate_llm_preset(config, llm_preset)
        environment = self._request_environment(config, api_key) if check_connectivity or api_key is not None else {}
        with tempfile.NamedTemporaryFile(prefix='.llm4om-web-doctor-', suffix='.json', dir=Path.cwd()) as temporary:
            path = Path(temporary.name)
            path.write_text(json.dumps(config, ensure_ascii=False, allow_nan=False))
            return _application(['doctor', '--config', str(path), *(['--check-connectivity'] if check_connectivity else [])], deadline=time.time() + 45,
                                cancellation=CancellationToken(), environment=environment)

    def _tasks(self) -> dict[str, Path]:
        selected = {}
        for root in (Path.cwd() / 'runs', self.root / 'tasks'):
            if not root.is_dir():
                continue
            for path in root.rglob('manifest.json'):
                if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()) or 'private' in path.parts or '.private' in path.parts:
                    continue
                try:
                    manifest = parse_reference_json(read_public_bytes(path, max_bytes=MAX_REQUEST))
                    if 'cases' in manifest and 'protocol_id' in manifest and 'adapter_id' in manifest:
                        selected[hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:32]] = path.resolve()
                except (RunError, OSError):
                    continue
        return selected

    def list_tasks(self) -> list[dict[str, Any]]:
        result = []
        for task_id, path in self._tasks().items():
            manifest = parse_reference_json(path.read_bytes())
            result.append({'task_id': task_id, 'source': manifest['source'], 'protocol_id': manifest['protocol_id'],
                'N_selected': manifest['N_selected'], 'adapter_id': manifest['adapter_id']})
        return result

    def _experiment(self, experiment_id: str) -> Path:
        path = public_path(self.root / 'experiments', _identifier(experiment_id), require_file=False)
        if not path.is_dir():
            raise RunError('not_found', 'web', 'Experiment is not available in this workspace.')
        return path

    def list_experiments(self) -> list[dict[str, Any]]:
        result = []
        for path in (self.root / 'experiments').glob('*/job.json'):
            result.append(parse_json(path.read_bytes()))
        return sorted(result, key=lambda item: item['created_at'], reverse=True)

    def submit_experiment(self, payload: dict[str, Any]) -> dict[str, Any]:
        tasks = self._tasks()
        if not isinstance(payload.get('task_ids'), list) or not payload['task_ids'] or not set(payload['task_ids']) <= tasks.keys():
            raise RunError('invalid_request', 'web', 'Select a frozen task imported under runs/ or workspace/tasks/.')
        configurations = payload.get('configurations')
        if not isinstance(configurations, list) or not 1 <= len(configurations) <= 32:
            raise RunError('invalid_request', 'web', 'Declare one to32 explicit configuration variants.')
        validated = []
        for item in configurations:
            if not isinstance(item, dict) or set(item) != {'id', 'config'} or not isinstance(item['id'], str) or not item['id'].strip():
                raise RunError('invalid_request', 'web', 'Each configuration needs id and a full RunConfig.')
            validate_config(item['config'])
            validated.append(item)
        repeats = payload.get('repeats')
        if type(repeats) is not int or not 1 <= repeats <= 1000:
            raise RunError('invalid_request', 'web', 'repeats must be an integer between 1 and 1000.')
        budget = payload.get('budget')
        if not isinstance(budget, dict) or set(budget) != {*LIMITS, 'max_concurrency', 'wall_time_s'}:
            raise RunError('invalid_request', 'web', 'Declare concurrency, wall time and experiment-wide attempt/token/Solver caps.')
        for key in budget:
            if type(budget[key]) is not int or not 0 <= budget[key] <= (32 if key == 'max_concurrency' else 1000000000) \
                    or (key not in LIMITS and budget[key] < 1):
                raise RunError('invalid_request', 'web', f'{key} must be a positive integer within its cap.')
        exclusions = payload.get('exclusions', [])
        if not isinstance(exclusions, list) or any(not isinstance(item, dict) or set(item) != {'task_id', 'configuration_id', 'reason'}
                or not isinstance(item['reason'], str) or not item['reason'].strip() for item in exclusions):
            raise RunError('invalid_request', 'web', 'Each excluded task/configuration cell needs a reason.')
        experiment_id = uuid4().hex
        job = self.root / 'experiments' / experiment_id
        job.mkdir(parents=True)
        selections = []
        for index, item in enumerate(validated):
            name = f'configuration-{index}.json'
            _json_file(job / name, item['config'])
            selections.append({'id': item['id'], 'run_config': name})
        spec: dict[str, Any] = {'schema_version': '0.1.0', 'experiment_id': experiment_id,
            'tasks': [{'id': identifier, 'manifest': str(tasks[identifier])} for identifier in payload['task_ids']],
            'configurations': selections, 'repeats': repeats, 'budget': budget,
            'exclusions': exclusions}
        if 'reporters' in payload:
            spec['reporters'] = payload['reporters']
        _json_file(job / 'spec.json', spec)
        record = {'experiment_id': experiment_id, 'created_at': time.time(), 'status': 'queued',
                  'task_count': len(spec['tasks']), 'configuration_count': len(selections), 'repeats': spec['repeats']}
        _json_file(job / 'job.json', record)
        self._start_experiment(experiment_id)
        return record

    def _start_experiment(self, experiment_id: str, *, resume: bool = False) -> None:
        job = self._experiment(experiment_id)
        key = 'experiment:' + experiment_id
        with self.lock:
            if key in self.active or len(self.active) >= 8:
                raise RunError('experiment_active', 'web', 'Experiment is active or the queue is full.')
            token = CancellationToken()
            self.active[key] = token
        def work() -> None:
            record = parse_json((job / 'job.json').read_bytes())
            try:
                record['status'] = 'running'
                _json_file(job / 'job.json', record)
                spec = parse_json((job / 'spec.json').read_bytes())
                command = [sys.executable, '-m', 'llm4om', 'benchmark', '--config', str(job / 'spec.json'), '--output', str(job / 'batch')]
                if resume:
                    command.append('--resume')
                _, _, code = run_owned_process(command, b'', deadline=time.time() + spec['budget']['wall_time_s'] + 15,
                                               cancellation=token, cancel_grace_s=10)
                if code != 0:
                    raise RunError('experiment_failed', 'web', 'Batch preflight or execution failed; inspect the saved experiment.')
                record['status'] = 'finished'
                record.pop('error', None)
            except (Exception, SystemExit) as error:
                record.update(status='cancelled' if token.cancelled else 'failed',
                    error={'code': error.code if isinstance(error, RunError) else 'experiment_error',
                           'message': 'Cannot finish this batch. Saved samples and reservations are retained.'})
            finally:
                _json_file(job / 'job.json', record)
                with self.lock:
                    self.active.pop(key, None)
        self.pool.submit(work)

    def inspect_experiment(self, experiment_id: str) -> dict[str, Any]:
        job = self._experiment(experiment_id)
        result: dict[str, Any] = {'job': parse_json((job / 'job.json').read_bytes()), 'summary': None, 'rows': [], 'progress': None}
        state_path = job / 'batch/.private/experiment-state.json'
        if state_path.is_file():
            state = parse_reference_json(state_path.read_bytes())
            result['progress'] = {'N_selected_runs': len(state['jobs']), 'N_saved': len(state['results']),
                'statuses': {status: sum(item['status'] == status for item in state['jobs']) for status in {item['status'] for item in state['jobs']}}}
            result['rows'] = list(state['results'].values())[:200]
        summary = job / 'batch/reports/summary.json'
        if summary.is_file():
            result['summary'] = parse_json(read_public_bytes(summary, max_bytes=MAX_REQUEST))
        return result

    def control_experiment(self, experiment_id: str, *, resume: bool = False) -> dict[str, Any]:
        if resume:
            self._start_experiment(experiment_id, resume=True)
        else:
            job = self._experiment(experiment_id)
            control = job / 'batch/experiment-control.json'
            if control.is_file():
                cancel_experiment(job / 'batch')
            else:
                with self.lock:
                    token = self.active.get('experiment:' + experiment_id)
                    if token is not None:
                        token.cancel()
        return {'experiment_id': experiment_id, 'status': 'queued' if resume else 'cancel_requested'}

    def export_experiment(self, experiment_id: str) -> bytes:
        job = self._experiment(experiment_id)
        summary = parse_json(read_public_bytes(job / 'batch/reports/summary.json', max_bytes=MAX_REQUEST))
        refs = summary.get('report_refs')
        names = ['experiment.json', 'reports/summary.json']
        if refs is None:
            names.extend(['reports/results.jsonl', 'reports/results.csv', 'reports/report.md', 'reports/report.html'])
        else:
            for ref in refs:
                if ref['namespace'] != 'experiment_public' or not ref['relative_path'].startswith('reports/'):
                    raise RunError('private_reference', 'web', 'Only public report references can be exported.')
                names.append(ref['relative_path'])
        output = BytesIO()
        size = 0
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                path = public_path(job / 'batch', name)
                if not path.is_file():
                    raise RunError('not_found', 'web', 'This experiment has not saved its public report yet.')
                raw = read_public_bytes(path, max_bytes=MAX_REQUEST)
                if refs is not None and name not in {'experiment.json', 'reports/summary.json'}:
                    ref = next(item for item in refs if item['relative_path'] == name)
                    if len(raw) != ref['size_bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
                        raise RunError('artifact_hash_mismatch', 'web', 'Public report differs from its saved reference.')
                size += len(raw)
                if size > 64 * 1024 * 1024:
                    raise RunError('export_limit', 'web', 'Public experiment export exceeds64 MiB.')
                archive.writestr(name, raw)
        return output.getvalue()

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs = []
        for path in self.root.glob('*/job.json'):
            try:
                job = parse_json(path.read_bytes())
                run = self._run_path(job['job_id'])
                if run is not None:
                    job['run_id'] = run.name
                    if (run / 'bundle.json').is_file():
                        job['status'] = job['status'] if job['job_id'] in self.active or job.get('error') else parse_json((run / 'bundle.json').read_bytes())['status']
                jobs.append(job)
            except (RunError, OSError, KeyError):
                continue
        return sorted(jobs, key=lambda job: job['created_at'], reverse=True)

    def _job(self, job_id: str) -> Path:
        path = public_path(self.root, _identifier(job_id), require_file=False)
        if not path.is_dir():
            raise RunError('not_found', 'web', 'Workspace job is not available.')
        return path

    def _run_path(self, job_id: str) -> Path | None:
        job = self._job(job_id)
        record = parse_json((job / 'job.json').read_bytes())
        candidates = [path for path in (job / 'runs').glob('*') if path.is_dir()
            and len(path.name) == 32 and all(char in '0123456789abcdef' for char in path.name)]
        if job_id in self.active and record.get('prior_runs') is not None:
            candidates = [path for path in candidates if path.name not in record['prior_runs']]
        elif record.get('run_id'):
            saved = job / 'runs' / _identifier(record['run_id'])
            if saved.is_dir():
                return saved
        return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None

    def _selected_run(self, job_id: str, run_id: str | None = None) -> Path | None:
        if run_id is None:
            return self._run_path(job_id)
        run = public_path(self._job(job_id) / 'runs', _identifier(run_id), require_file=False)
        if not run.is_dir():
            raise RunError('not_found', 'web', 'Selected run is not stored in this workspace job.')
        return run

    def versions(self, job_id: str) -> list[dict[str, Any]]:
        versions = []
        for path in (self._job(job_id) / 'runs').glob('*'):
            if path.is_symlink() or not path.is_dir() or len(path.name) != 32 or any(char not in '0123456789abcdef' for char in path.name):
                continue
            if not (path / 'bundle.json').is_file():
                continue
            bundle_path = public_path(path, 'bundle.json')
            bundle = parse_json(read_public_bytes(bundle_path, max_bytes=MAX_REQUEST))
            if bundle.get('run_id') != path.name:
                raise RunError('artifact_hash_mismatch', 'web', 'Saved version identity differs from its directory.')
            lineage = parse_json(self.read_ref(path, bundle['lineage_ref'])) if bundle.get('lineage_ref') else {}
            versions.append({'run_id': path.name, 'status': bundle['status'],
                'parent_run_id': lineage.get('parent_run_id'), 'operation': lineage.get('operation'),
                'assisted': bundle.get('assisted', False), 'saved_at': bundle_path.stat().st_mtime})
        return sorted(versions, key=lambda item: item['saved_at'], reverse=True)

    def edit_template(self, job_id: str, operation: str, run_id: str | None = None) -> dict[str, Any]:
        run = self._selected_run(job_id, run_id)
        if run is None:
            raise RunError('not_found', 'web', 'No saved run is available to edit.')
        return export_edit(run, operation=operation)

    def submit_edit(self, job_id: str, payload: dict[str, Any], *, api_key: str | None = None) -> dict[str, Any]:
        job = self._job(job_id)
        run = self._selected_run(job_id, payload.get('parent_run_id'))
        if run is None:
            raise RunError('not_found', 'web', 'No saved run is available to edit.')
        if not isinstance(payload.get('edits'), dict):
            raise RunError('invalid_edit', 'web', 'Submit a public edit document.')
        self._start(job_id, 'edit', options={'edits': payload['edits'], 'parent_run_id': run.name}, api_key=api_key)
        return {'job_id': job_id, 'parent_run_id': run.name, 'status': 'queued'}

    def submit(self, payload: dict[str, Any], *, api_key: str | None = None) -> dict[str, Any]:
        config = deepcopy(payload['config'])
        validate_config(config)
        validate_llm_preset(config, payload.get('llm_preset'))
        environment = self._request_environment(config, api_key)
        job_id = uuid4().hex
        job = self.root / job_id
        job.mkdir()
        inputs = job / 'input'
        inputs.mkdir()
        problem = deepcopy(payload.get('problem')) or {'schema_version': '0.3.0', 'problem_id': 'web-' + job_id,
            'revision': '1', 'description': payload['description'], 'language': 'zh-CN', 'problem_type_hint': 'unknown',
            'requirements': [], 'data_refs': [], 'assumptions': [], 'source': {'kind': 'web_input'}}
        uploads = payload.get('data', [])
        existing = {ref['data_id']: ref for ref in problem.get('data_refs', [])}
        admitted = []
        for index, item in enumerate(uploads):
            data_id = item['data_id']
            if not isinstance(data_id, str) or not data_id.strip() or len(data_id) > 128:
                raise RunError('invalid_data', 'web', 'Data IDs must be nonempty public labels.')
            raw = base64.b64decode(item['base64'], validate=True)
            if len(raw) > MAX_FILE:
                raise RunError('invalid_data', 'web', 'Each public upload is limited to8 MiB.')
            format_name = item['format']
            if format_name not in {'csv', 'json'}:
                raise RunError('invalid_data', 'web', 'Upload CSV or object JSON.')
            schema = item.get('schema') or existing.get(data_id, {}).get('schema')
            if schema is None:
                if format_name == 'json':
                    schema = {'type': 'object'}
                else:
                    names = next(csv.reader(StringIO(raw.decode('utf-8')), strict=True))
                    schema = {'columns': [{'name': name, 'type': 'string', 'nullable': True} for name in names], 'unique_by': []}
            ref = {'data_id': data_id, 'path': f'data/{index}.{format_name}', 'format': format_name,
                'sha256': hashlib.sha256(raw).hexdigest(), 'schema': schema}
            if existing.get(data_id, {}).get('sha256') and existing[data_id]['sha256'] != ref['sha256']:
                raise RunError('data_hash_mismatch', 'web', 'Upload does not match its imported original data hash.')
            validate_data(raw, ref)
            (inputs / 'data').mkdir(exist_ok=True)
            (inputs / ref['path']).write_bytes(raw)
            admitted.append(ref)
        if set(existing) - {ref['data_id'] for ref in admitted}:
            raise RunError('invalid_data', 'web', 'Upload all data referenced by the imported problem.')
        problem['data_refs'] = admitted
        validate_problem(problem)
        _json_file(inputs / 'problem.json', problem)
        _json_file(inputs / 'config.json', config)
        record = {'job_id': job_id, 'created_at': time.time(), 'status': 'queued', 'run_id': None,
            'description': problem['description'], 'method': config['method']['plugin_id'], 'model': config['llm']['model']}
        _json_file(job / 'job.json', record)
        with self.lock:
            self.credentials[job_id] = environment
        self._start(job_id)
        return record

    def _start(self, job_id: str, action: str = 'run', *, options: dict[str, Any] | None = None,
               api_key: str | None = None) -> None:
        job = self._job(job_id)
        with self.lock:
            if job_id in self.active:
                raise RunError('run_active', 'web', 'This workspace job is already active.')
            if len(self.active) >= 8:
                raise RunError('budget_exhausted', 'web', 'At most8 local jobs can be queued.')
            if api_key is not None:
                config = parse_json((job / 'input/config.json').read_bytes())
                if config['llm']['config'].get('credential_env') != WEB_KEY_ENV:
                    raise RunError('invalid_config', 'web', 'This run uses credentials configured on the server.')
                self.credentials[job_id] = self._request_environment(config, api_key)
            token = CancellationToken()
            self.active[job_id] = token
            environment = dict(self.credentials.get(job_id, {}))
        def work() -> None:
            record = parse_json((job / 'job.json').read_bytes())
            try:
                record['status'] = 'running'
                if action == 'edit':
                    record['prior_runs'] = [path.name for path in (job / 'runs').glob('*') if path.is_dir()]
                    record['parent_run_id'] = (options or {})['parent_run_id']
                _json_file(job / 'job.json', record)
                config = parse_json((job / 'input/config.json').read_bytes())
                deadline = time.time() + config['budget']['wall_time_s'] + 15
                if action == 'edit':
                    opts = options or {}
                    edits_path = job / ('edits-' + uuid4().hex + '.json')
                    _json_file(edits_path, opts['edits'])
                    arguments = ['edit', '--run-id', _identifier(opts['parent_run_id']), '--output', str(job / 'runs'),
                                 '--edits', str(edits_path)]
                    deadline = time.time() + opts['edits']['budget']['wall_time_s'] + 15
                    record['description'] = opts['edits']['problem']['description']
                elif action == 'run':
                    arguments = ['run', '--problem', str(job / 'input/problem.json'), '--config', str(job / 'input/config.json'),
                                 '--output', str(job / 'runs'), '--interactive']
                else:
                    run = self._run_path(job_id)
                    if run is None:
                        raise RunError('not_found', 'web', 'No saved run is available to resume.')
                    saved_config = parse_json((run / 'requested-config.json').read_bytes())
                    deadline = time.time() + saved_config['budget']['wall_time_s'] + 15
                    opts = options or {}
                    answers = None
                    revised = None
                    if opts.get('answers') is not None:
                        answers = job / 'answers.json'
                        _json_file(answers, opts['answers'])
                    if opts.get('revised_problem') is not None:
                        revised = job / 'input/revised-problem.json'
                        _json_file(revised, opts['revised_problem'])
                    arguments = ['resume', '--run-id', run.name, '--output', str(job / 'runs'),
                                 '--strategy', opts.get('strategy', 'continue')]
                    if answers is not None:
                        arguments.extend(['--answers', str(answers)])
                    if revised is not None:
                        arguments.extend(['--revised-problem', str(revised)])
                result = _application(arguments, deadline=deadline, cancellation=token, environment=environment)
                record.update(status=result['status'], run_id=result['run_id'])
                record.pop('prior_runs', None)
                record.pop('error', None)
            except (Exception, SystemExit) as error:
                record.update(status='cancelled' if token.cancelled else 'failed', error={'code': error.code if isinstance(error, RunError) else 'web_run_error',
                    'message': str(error) if isinstance(error, RunError) else 'Cannot finish the local application request.'})
            finally:
                record.pop('prior_runs', None)
                _json_file(job / 'job.json', record)
                with self.lock:
                    self.active.pop(job_id, None)
        self.pool.submit(work)

    def cancel(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        with self.lock:
            token = self.active.get(job_id)
            if token is not None:
                token.cancel()
        run = self._run_path(job_id)
        status = cancel_run(run) if run is not None else 'cancel_requested'
        return {'job_id': job.name, 'status': status}

    def resume(self, job_id: str, options: dict[str, Any], *, api_key: str | None = None) -> dict[str, Any]:
        if options.get('strategy', 'continue') not in {'continue', 'rerun'}:
            raise RunError('invalid_request', 'web', 'Select continue or explicit rerun.')
        self._start(job_id, 'resume', options=options, api_key=api_key)
        return {'job_id': job_id, 'status': 'queued'}

    def read_ref(self, run: Path, ref: dict[str, Any]) -> bytes:
        return read_run_ref(run, ref, max_bytes=MAX_FILE)

    def inspect(self, job_id: str, run_id: str | None = None) -> dict[str, Any]:
        job = self._job(job_id)
        record = parse_json((job / 'job.json').read_bytes())
        latest = self._run_path(job_id)
        run = self._selected_run(job_id, run_id)
        if run is None:
            return {'job': record, 'bundle': None, 'events': [], 'artifacts': [], 'contents': {},
                    'versions': [], 'latest_run_id': None, 'historical': False, 'data_previews': {}}
        bundle = parse_json((run / 'bundle.json').read_bytes()) if (run / 'bundle.json').is_file() else None
        events = []
        if (run / 'events.jsonl').is_file():
            lines = (run / 'events.jsonl').read_bytes().splitlines()
            for line in lines[-200:]:
                try:
                    events.append(parse_json(line))
                except RunError:
                    continue
        projections = bundle.get('public_projections', {}) if bundle else {}
        if not bundle and (run / 'checkpoint.json').is_file():
            envelope = parse_json(read_public_bytes(run / 'checkpoint.json', max_bytes=MAX_REQUEST))
            payload = envelope['payload']
            raw = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
            if envelope.get('sha256') != hashlib.sha256(raw).hexdigest() or payload.get('run_id') != run.name:
                raise RunError('checkpoint_incompatible', 'web', 'Public progress checkpoint identity changed.')
            projections = payload.get('projections', {})
        refs = bundle.get('artifacts', []) if bundle else list(projections.values())
        contents = {}
        if projections:
            for key, ref in projections.items():
                if ref['media_type'] == 'application/json' or key.endswith(('.py', '.md', '.txt')):
                    raw = self.read_ref(run, ref)
                    contents[key] = parse_json(raw) if ref['media_type'] == 'application/json' else raw.decode('utf-8', errors='replace')
        record.update(run_id=run.name, status=bundle['status'] if bundle and job_id not in self.active and not record.get('error') else record['status'])
        historical = latest is None or latest.name != run.name
        if historical:
            problem = contents.get('public-problem.json')
            record.pop('error', None)
            record.update(status=bundle['status'] if bundle else 'running',
                          description=problem.get('description', record['description']) if isinstance(problem, dict) else record['description'])
        previews = {}
        data_views = contents.get('data-views.json')
        if isinstance(data_views, dict):
            for data_id, view in data_views.get('views', {}).items():
                raw = self.read_ref(run, view['content_ref'])
                previews[data_id] = {'metadata': view, **_data_preview(raw, view['format'], total_items=view['rows'])}
        return {'job': record, 'bundle': bundle, 'events': events, 'artifacts': refs, 'contents': contents,
                'versions': self.versions(job_id), 'latest_run_id': latest.name if latest else None, 'historical': historical,
                'data_previews': previews}

    def export(self, job_id: str, run_id: str | None = None) -> bytes:
        run = self._selected_run(job_id, run_id)
        if run is None or not (run / 'bundle.json').is_file():
            raise RunError('not_found', 'web', 'No public bundle has been saved.')
        bundle = parse_json((run / 'bundle.json').read_bytes())
        output = BytesIO()
        size = 0
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('bundle.json', json.dumps(bundle, ensure_ascii=False, indent=2))
            seen = set()
            for ref in bundle['artifacts']:
                name = ref['relative_path']
                if name in seen:
                    continue
                raw = self.read_ref(run, ref)
                size += len(raw)
                if size > 64 * 1024 * 1024:
                    raise RunError('export_limit', 'web', 'Public export exceeds64 MiB.')
                archive.writestr(name, raw)
                seen.add(name)
        return output.getvalue()

    def close(self) -> None:
        with self.lock:
            active = list(self.active.items())
        for identifier, token in active:
            if identifier.startswith('experiment:'):
                try:
                    self.control_experiment(identifier.split(':', 1)[1])
                except (RunError, OSError):
                    token.cancel()
            else:
                token.cancel()
        self.pool.shutdown(wait=False, cancel_futures=True)
        for pattern in ('*/job.json', 'experiments/*/job.json'):
            for path in self.root.glob(pattern):
                try:
                    record = parse_json(path.read_bytes())
                except (OSError, ValueError):
                    continue
                if record.get('status') == 'queued':
                    record['status'] = 'cancelled'
                    record['shutdown'] = True
                    _json_file(path, record)


def serve_web(root: Path, *, port: int = 8765, host: str = '127.0.0.1') -> None:
    try:
        binding = ipaddress.IPv4Address(host)
    except ipaddress.AddressValueError as error:
        raise RunError('invalid_config', 'web', 'Use an IPv4 bind address, such as 127.0.0.1 or 0.0.0.0.') from error
    workspace = WebWorkspace(root)
    token = secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def send(self, status: int, raw: bytes, media: str = 'application/json') -> None:
            self.send_response(status)
            self.send_header('Content-Type', media)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(raw)

        def check_origin(self, *, mutation: bool = False) -> None:
            authority = self.headers.get('Host', '')
            allowed = {f'127.0.0.1:{server.server_port}', f'localhost:{server.server_port}'}
            if not binding.is_loopback:
                address = urlsplit('http://' + authority)
                try:
                    remote = ipaddress.IPv4Address(address.hostname or '')
                    if address.port == server.server_port and address.username is None and address.password is None and not address.path:
                        if binding.is_unspecified or remote == binding:
                            allowed.add(authority)
                except (ipaddress.AddressValueError, ValueError):
                    pass
            if authority not in allowed or (self.headers.get('Origin') is not None and self.headers['Origin'] != 'http://' + authority):
                raise RunError('invalid_origin', 'web', 'Use this workbench from its bound server URL.')
            if mutation and not secrets.compare_digest(self.headers.get('X-LLM4OM-Token', ''), token):
                raise RunError('invalid_origin', 'web', 'Reload the local workbench before submitting changes.')

        def dispatch(self, *, mutation: bool = False) -> None:
            try:
                self.check_origin(mutation=mutation)
                address = urlsplit(self.path)
                parts = address.path.strip('/').split('/')
                payload: dict[str, Any] = {}
                if mutation:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= MAX_REQUEST or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                        raise RunError('invalid_request', 'web', 'Send a bounded JSON request.')
                    payload = parse_json(self.rfile.read(size))
                    api_key = self.headers.get('X-LLM4OM-Provider-Key')
                    if api_key and json.dumps(api_key)[1:-1] in json.dumps(payload, ensure_ascii=False):
                        raise RunError('private_input', 'web', 'API key must be separate from public inputs.')
                if not mutation and address.path in {'/', '/app.js', '/visuals.js', '/style.css'}:
                    name = {'/': 'index.html', '/app.js': 'app.js', '/visuals.js': 'visuals.js', '/style.css': 'style.css'}[address.path]
                    media = {'/': 'text/html; charset=utf-8', '/app.js': 'text/javascript; charset=utf-8', '/visuals.js': 'text/javascript; charset=utf-8', '/style.css': 'text/css; charset=utf-8'}[address.path]
                    self.send(200, files('llm4om').joinpath('web_assets', name).read_bytes(), media)
                    return
                if address.path == '/api/bootstrap' and not mutation:
                    result = {**workspace.bootstrap(), 'token': token}
                elif address.path == '/api/tasks' and not mutation:
                    result = {'tasks': workspace.list_tasks()}
                elif address.path == '/api/datasets' and not mutation:
                    result = {'datasets': list_benchmarks()}
                elif len(parts) == 3 and parts[:2] == ['api', 'datasets'] and not mutation:
                    query = parse_qs(address.query)
                    try:
                        offset = max(0, int(query.get('offset', ['0'])[0]))
                        limit = min(200, max(1, int(query.get('limit', ['100'])[0])))
                    except ValueError:
                        raise RunError('invalid_request', 'web', 'Dataset paging needs integer offset and limit.')
                    result = benchmark_detail(_identifier(parts[2]), offset, limit)
                elif address.path == '/api/experiments' and not mutation:
                    result = {'experiments': workspace.list_experiments()}
                elif address.path == '/api/experiments' and mutation:
                    result = workspace.submit_experiment(payload)
                elif len(parts) >= 3 and parts[:2] == ['api', 'experiments']:
                    experiment_id = _identifier(parts[2])
                    if len(parts) == 3 and not mutation:
                        result = workspace.inspect_experiment(experiment_id)
                    elif len(parts) == 4 and parts[3] in {'cancel', 'resume'} and mutation:
                        result = workspace.control_experiment(experiment_id, resume=parts[3] == 'resume')
                    elif len(parts) == 4 and parts[3] == 'export' and not mutation:
                        self.send(200, workspace.export_experiment(experiment_id), 'application/zip')
                        return
                    else:
                        raise RunError('not_found', 'web', 'Unknown experiment action.')
                elif address.path == '/api/jobs' and not mutation:
                    result = {'jobs': workspace.list_jobs()}
                elif address.path == '/api/doctor' and mutation:
                    result = workspace.doctor(payload['config'], check_connectivity=payload.get('check_connectivity', False),
                        api_key=self.headers.get('X-LLM4OM-Provider-Key'), llm_preset=payload.get('llm_preset'))
                elif address.path == '/api/data-preview' and mutation:
                    raw = base64.b64decode(payload['base64'], validate=True)
                    result = _data_preview(raw, payload['format'])
                    result.update(source_sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
                elif address.path == '/api/jobs' and mutation:
                    result = workspace.submit(payload, api_key=self.headers.get('X-LLM4OM-Provider-Key'))
                elif len(parts) >= 3 and parts[:2] == ['api', 'jobs']:
                    job_id = _identifier(parts[2])
                    query = parse_qs(address.query)
                    selected_run = query.get('run_id', [None])[0]
                    if len(parts) == 3 and not mutation:
                        result = workspace.inspect(job_id, selected_run)
                    elif len(parts) == 4 and parts[3] == 'edit-template' and not mutation:
                        operation = query.get('operation', ['code'])[0]
                        result = workspace.edit_template(job_id, operation, selected_run)
                    elif len(parts) == 4 and parts[3] == 'edit' and mutation:
                        result = workspace.submit_edit(job_id, payload, api_key=self.headers.get('X-LLM4OM-Provider-Key'))
                    elif len(parts) == 4 and parts[3] == 'cancel' and mutation:
                        result = workspace.cancel(job_id)
                    elif len(parts) == 4 and parts[3] == 'resume' and mutation:
                        result = workspace.resume(job_id, payload, api_key=self.headers.get('X-LLM4OM-Provider-Key'))
                    elif len(parts) == 4 and parts[3] == 'export' and not mutation:
                        self.send(200, workspace.export(job_id, selected_run), 'application/zip')
                        return
                    else:
                        raise RunError('not_found', 'web', 'Unknown workbench action.')
                else:
                    raise RunError('not_found', 'web', 'Unknown workbench resource.')
                self.send(200, json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
            except (Exception, SystemExit) as error:
                code = error.code if isinstance(error, RunError) else 'invalid_request'
                message = str(error) if isinstance(error, RunError) else 'Cannot process this local workbench request.'
                self.send(404 if code == 'not_found' else 400, json.dumps({'error': {'code': code, 'message': message}}).encode())

        def do_GET(self) -> None:
            self.dispatch()

        def do_POST(self) -> None:
            self.dispatch(mutation=True)
    server = ThreadingHTTPServer((host, port), Handler)
    print(f'LLM4OM workbench: http://{host}:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        workspace.close()
        # Workspace state is fully checkpointed; a wedged job thread must never keep
        # this restartable local workbench process alive after shutdown.
        os._exit(0)
