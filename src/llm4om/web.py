"""Local single-user workbench over the existing application and public records."""

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import csv
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from io import BytesIO, StringIO
import json
from pathlib import Path
import secrets
import threading
import time
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4
import zipfile

from llm4om.application import run_problem, resume_run
from llm4om.contracts import RunError, parse_json, public_path, read_public_bytes, validate_config, validate_problem, validate_data
from llm4om.control import CancellationToken
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
            for plugin in discover_plugins().values()], 'jobs': self.list_jobs()}

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
            for token in self.active.values():
                token.cancel()
        self.pool.shutdown(wait=True, cancel_futures=True)


def serve_web(root: Path, *, port: int = 8765) -> None:
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
            host = self.headers.get('Host', '')
            allowed = {f'127.0.0.1:{server.server_port}', f'localhost:{server.server_port}'}
            if host not in allowed or (self.headers.get('Origin') is not None and self.headers['Origin'] not in {'http://' + item for item in allowed}):
                raise RunError('invalid_origin', 'web', 'Use this workbench from its local URL.')
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
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    print(f'LLM4OM workbench: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        workspace.close()
