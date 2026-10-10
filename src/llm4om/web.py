"""Local single-user workbench over the existing application and public records."""

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
import hashlib
import ipaddress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from io import BytesIO, StringIO
import json
from pathlib import Path
import secrets
import sys
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4
import zipfile

from llm4om.application import run_problem, resume_run
from llm4om.contracts import RunError, parse_json, public_path, read_public_bytes, validate_config, validate_problem, validate_data, parse_reference_json
from llm4om.control import CancellationToken
from llm4om.executors import run_owned_process
from llm4om.experiments import cancel_experiment
from llm4om.plugins import discover_plugins
from llm4om.preflight import prepare_run
from llm4om.providers import credential_environment
from llm4om.storage import cancel_run

MAX_REQUEST = 24 * 1024 * 1024
MAX_FILE = 8 * 1024 * 1024


def _json_file(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def _identifier(value: str) -> str:
    if len(value) != 32 or any(char not in '0123456789abcdef' for char in value):
        raise RunError('invalid_request', 'web', 'Expected a workspace job ID.')
    return value


class WebWorkspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='llm4om-web')
        self.lock = threading.Lock()
        self.active: dict[str, CancellationToken] = {}

    def bootstrap(self) -> dict[str, Any]:
        environment = credential_environment(Path.cwd() / '.env') if (Path.cwd() / '.env').exists() else {}
        config: dict[str, Any] = {'schema_version': '0.2.0',
            'method': {'plugin_id': 'llm4om.methods.direct', 'config': {'formulation_mode': 'five_element', 'output_mode': 'lp_ir'}},
            'llm': {'provider_plugin_id': 'llm4om.providers.openai_compatible',
                'model': environment.get('LLM4OM_LLM_MODEL', 'your-model'),
                'config': {'base_url': environment.get('LLM4OM_LLM_BASE_URL', 'https://api.openai.com/v1'),
                    'credential_env': 'LLM4OM_LLM_API_KEY', 'max_retries': 1, 'max_output_tokens': 8192}},
            'compiler': {'plugin_id': 'llm4om.compilers.lp_ir_to_pyomo'},
            'model_backend': {'plugin_id': 'llm4om.model_backends.pyomo_factory'},
            'solver': {'plugin_id': 'llm4om.solvers.highs', 'options': {'time_limit_s': 30}},
            'executor': {'plugin_id': 'llm4om.executors.container', 'config': {'network': False, 'cpu_limit': 1,
                'memory_limit_mb': 1024, 'wall_time_s': 60}},
            'budget': {'max_llm_attempts': 4, 'max_total_tokens': 100000, 'max_candidates': 4, 'max_repairs': 2,
                'max_solver_calls': 4, 'wall_time_s': 180, 'max_concurrency': 1},
            'store': {'plugin_id': 'llm4om.stores.filesystem', 'config': {'root': 'runs'}},
            'reporters': [{'plugin_id': 'llm4om.reporters.jsonl'}, {'plugin_id': 'llm4om.reporters.markdown'}]}
        return {'config': config, 'plugins': [{'manifest': plugin.manifest, 'origin': plugin.origin}
            for plugin in discover_plugins().values()], 'jobs': self.list_jobs(), 'tasks': self.list_tasks(), 'experiments': self.list_experiments()}

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
            if not isinstance(item, dict) or set(item) != {'id', 'config'}:
                raise RunError('invalid_request', 'web', 'Each configuration needs id and a full RunConfig.')
            validate_config(item['config'])
            validated.append(item)
        experiment_id = uuid4().hex
        job = self.root / 'experiments' / experiment_id
        job.mkdir(parents=True)
        selections = []
        for index, item in enumerate(validated):
            name = f'configuration-{index}.json'
            _json_file(job / name, item['config'])
            selections.append({'id': item['id'], 'run_config': name})
        spec = {'schema_version': '0.1.0', 'experiment_id': experiment_id,
            'tasks': [{'id': identifier, 'manifest': str(tasks[identifier])} for identifier in payload['task_ids']],
            'configurations': selections, 'repeats': payload['repeats'], 'budget': payload['budget'],
            'exclusions': payload.get('exclusions', [])}
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
                _, _, code = run_owned_process(command, b'', deadline=time.time() + spec['budget']['wall_time_s'] + 15, cancellation=token)
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
        output = BytesIO()
        size = 0
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('experiment.json', 'reports/results.jsonl', 'reports/results.csv', 'reports/summary.json', 'reports/report.md', 'reports/report.html'):
                path = job / 'batch' / name
                if not path.is_file():
                    raise RunError('not_found', 'web', 'This experiment has not saved its public report yet.')
                raw = read_public_bytes(path, max_bytes=MAX_REQUEST)
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
                        job['status'] = parse_json((run / 'bundle.json').read_bytes())['status']
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
        candidates = [path for path in (job / 'runs').glob('*') if path.is_dir()
            and len(path.name) == 32 and all(char in '0123456789abcdef' for char in path.name)]
        return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = deepcopy(payload['config'])
        validate_config(config)
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
        self._start(job_id)
        return record

    def _start(self, job_id: str, action: str = 'run', *, options: dict[str, Any] | None = None) -> None:
        job = self._job(job_id)
        with self.lock:
            if job_id in self.active:
                raise RunError('run_active', 'web', 'This workspace job is already active.')
            if len(self.active) >= 8:
                raise RunError('budget_exhausted', 'web', 'At most8 local jobs can be queued.')
            token = CancellationToken()
            self.active[job_id] = token
        def work() -> None:
            record = parse_json((job / 'job.json').read_bytes())
            try:
                record['status'] = 'running'
                _json_file(job / 'job.json', record)
                if action == 'run':
                    result = run_problem(job / 'input/problem.json', job / 'input/config.json', output_root=job / 'runs',
                        cancellation=token, interactive=True)
                else:
                    run = self._run_path(job_id)
                    if run is None:
                        raise RunError('not_found', 'web', 'No saved run is available to resume.')
                    opts = options or {}
                    answers = None
                    revised = None
                    if opts.get('answers') is not None:
                        answers = job / 'answers.json'
                        _json_file(answers, opts['answers'])
                    if opts.get('revised_problem') is not None:
                        revised = job / 'input/revised-problem.json'
                        _json_file(revised, opts['revised_problem'])
                    result = resume_run(run, cancellation=token, strategy=opts.get('strategy', 'continue'),
                        answers=answers, revised_problem=revised)
                record.update(status=result.status, run_id=result.run_id)
                record.pop('error', None)
            except (Exception, SystemExit) as error:
                record.update(status='failed', error={'code': error.code if isinstance(error, RunError) else 'web_run_error',
                    'message': str(error) if isinstance(error, RunError) else 'Cannot finish the local application request.'})
            finally:
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

    def resume(self, job_id: str, options: dict[str, Any]) -> dict[str, Any]:
        if options.get('strategy', 'continue') not in {'continue', 'rerun'}:
            raise RunError('invalid_request', 'web', 'Select continue or explicit rerun.')
        self._start(job_id, 'resume', options=options)
        return {'job_id': job_id, 'status': 'queued'}

    def read_ref(self, run: Path, ref: dict[str, Any]) -> bytes:
        if ref.get('namespace') != 'run_public':
            raise RunError('private_reference', 'web', 'Only admitted public run references are readable.')
        raw = read_public_bytes(public_path(run, ref['relative_path']), max_bytes=MAX_FILE)
        if len(raw) != ref['size_bytes'] or hashlib.sha256(raw).hexdigest() != ref['sha256']:
            raise RunError('artifact_hash_mismatch', 'web', 'Public artifact differs from its immutable reference.')
        return raw

    def inspect(self, job_id: str) -> dict[str, Any]:
        job = self._job(job_id)
        record = parse_json((job / 'job.json').read_bytes())
        run = self._run_path(job_id)
        if run is None:
            return {'job': record, 'bundle': None, 'events': [], 'artifacts': []}
        bundle = parse_json((run / 'bundle.json').read_bytes()) if (run / 'bundle.json').is_file() else None
        events = []
        if (run / 'events.jsonl').is_file():
            lines = (run / 'events.jsonl').read_bytes().splitlines()
            for line in lines[-200:]:
                try:
                    events.append(parse_json(line))
                except RunError:
                    continue
        refs = bundle.get('artifacts', []) if bundle else []
        contents = {}
        if bundle:
            for key, ref in bundle.get('public_projections', {}).items():
                if ref['media_type'] == 'application/json' or key.endswith('.py') or key.endswith('.md'):
                    raw = self.read_ref(run, ref)
                    contents[key] = parse_json(raw) if ref['media_type'] == 'application/json' else raw.decode('utf-8', errors='replace')
        record.update(run_id=run.name, status=bundle['status'] if bundle else record['status'])
        return {'job': record, 'bundle': bundle, 'events': events, 'artifacts': refs, 'contents': contents}

    def export(self, job_id: str) -> bytes:
        run = self._run_path(job_id)
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
        self.pool.shutdown(wait=True, cancel_futures=True)


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
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'")
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
                if not mutation and address.path in {'/', '/app.js', '/style.css'}:
                    name = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}[address.path]
                    media = {'/': 'text/html; charset=utf-8', '/app.js': 'text/javascript; charset=utf-8', '/style.css': 'text/css; charset=utf-8'}[address.path]
                    self.send(200, files('llm4om').joinpath('web_assets', name).read_bytes(), media)
                    return
                if address.path == '/api/bootstrap' and not mutation:
                    result = {**workspace.bootstrap(), 'token': token}
                elif address.path == '/api/tasks' and not mutation:
                    result = {'tasks': workspace.list_tasks()}
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
                    result = {'preflight_ok': True, 'execution_plan': prepare_run(payload['config'], config_dir=Path.cwd()).snapshot}
                elif address.path == '/api/jobs' and mutation:
                    result = workspace.submit(payload)
                elif len(parts) >= 3 and parts[:2] == ['api', 'jobs']:
                    job_id = _identifier(parts[2])
                    if len(parts) == 3 and not mutation:
                        result = workspace.inspect(job_id)
                    elif len(parts) == 4 and parts[3] == 'cancel' and mutation:
                        result = workspace.cancel(job_id)
                    elif len(parts) == 4 and parts[3] == 'resume' and mutation:
                        result = workspace.resume(job_id, payload)
                    elif len(parts) == 4 and parts[3] == 'export' and not mutation:
                        self.send(200, workspace.export(job_id), 'application/zip')
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
