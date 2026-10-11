"""Frozen batch execution and public, denominator-preserving reports."""

import fcntl
import hashlib
import json
import platform
import re
import time
import sys
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4
from typing import Any, Iterator

from llm4om.application import _sdk_sha256
from llm4om.contracts import (RunError, parse_json, parse_reference_json, read_config,
                              public_path, validate_problem, validate_data)
from llm4om.control import CancellationToken
from llm4om.executors import run_owned_process
from llm4om.preflight import prepare_run
from llm4om.task_plugins import load_registered_case
from llm4om.evaluation import _verify_ref
from llm4om.storage import cancel_run
from llm4om.reporters import DEFAULT_REPORTERS, resolve_reporters, render_reports, publish_report


LIMITS = ('max_llm_attempts', 'max_total_tokens', 'max_solver_calls')
METRICS = ('independent_feasibility', 'objective_match', 'verified_solution')


def _write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    temporary.chmod(0o600)
    temporary.replace(path)


@contextmanager
def _lock(output: Path) -> Iterator[None]:
    output.mkdir(parents=True, exist_ok=True)
    with (output / '.experiment.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RunError('experiment_active', 'control', 'Another process owns this experiment.') from error
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def _id(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}', value) is None:
        raise RunError('invalid_experiment', 'admission', 'Experiment, task and configuration IDs must be safe stable names.')
    return value


def _positive(value: Any, name: str, maximum: int = 1000000, minimum: int = 1) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise RunError('invalid_experiment', 'admission', f'{name} must be an integer between {minimum} and {maximum}.')
    return value


def _prepare(config: Path, offline: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    settings = read_config(config)
    required = {'schema_version', 'experiment_id', 'tasks', 'configurations', 'repeats', 'budget', 'exclusions'}
    if not required <= set(settings) or set(settings) - required - {'reporters'} or settings['schema_version'] != '0.1.0':
        raise RunError('invalid_experiment', 'admission', 'Expected an explicit ExperimentSpec 0.1.0.')
    selections = settings.get('reporters', DEFAULT_REPORTERS)
    reporters = resolve_reporters(selections, 'experiment')
    experiment_id = _id(settings['experiment_id'])
    repeats = _positive(settings['repeats'], 'repeats', 1000)
    budget = settings['budget']
    if not isinstance(budget, dict) or set(budget) != {*LIMITS, 'max_concurrency', 'wall_time_s'}:
        raise RunError('invalid_experiment', 'admission', 'Declare concurrency, wall time and experiment-wide attempt/token/Solver caps.')
    for key in budget:
        _positive(budget[key], key, 32 if key == 'max_concurrency' else 1000000000, 0 if key in LIMITS else 1)
    exclusions: dict[tuple[str, str], str] = {}
    if not isinstance(settings['exclusions'], list):
        raise RunError('invalid_experiment', 'admission', 'Exclusions must be an explicit list.')
    for item in settings['exclusions']:
        if not isinstance(item, dict) or set(item) != {'task_id', 'configuration_id', 'reason'} or not isinstance(item['reason'], str) or not item['reason'].strip():
            raise RunError('invalid_experiment', 'admission', 'Each excluded task/configuration cell needs a reason.')
        key = (_id(item['task_id']), _id(item['configuration_id']))
        if key in exclusions:
            raise RunError('invalid_experiment', 'admission', 'Duplicate excluded cell.')
        exclusions[key] = item['reason']
    sources: dict[str, str] = {str(config.resolve()): hashlib.sha256(config.read_bytes()).hexdigest()}
    tasks: dict[str, tuple[Path, dict[str, Any], list[dict[str, Any]]]] = {}
    configurations: dict[str, tuple[Path, dict[str, Any]]] = {}
    for name, target, path_field in (('tasks', tasks, 'manifest'), ('configurations', configurations, 'run_config')):
        entries = settings[name]
        if not isinstance(entries, list) or not entries:
            raise RunError('invalid_experiment', 'admission', f'{name} must contain explicit selections.')
        for item in entries:
            if not isinstance(item, dict) or not {'id', path_field} <= set(item) or set(item) - {'id', path_field, *({'case_ids'} if name == 'tasks' else set())}:
                raise RunError('invalid_experiment', 'admission', 'Selections require exactly id and their input path.')
            identifier = _id(item['id'])
            if identifier in target:
                raise RunError('invalid_experiment', 'admission', 'Selection IDs must be unique.')
            path = (config.parent / item[path_field]).resolve()
            sources[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
            if name == 'configurations':
                run_settings = read_config(path)
                configurations[identifier] = (path, run_settings)
                llm_settings = run_settings.get('llm')
                llm_config = llm_settings.get('config') if isinstance(llm_settings, dict) else None
                response = llm_config.get('response_artifact') if isinstance(llm_config, dict) else None
                if response is not None:
                    artifact_path = public_path(path.parent, response)
                    sources[str(artifact_path)] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
            else:
                manifest = parse_reference_json(path.read_bytes())
                requested = item.get('case_ids')
                if requested is not None and (not isinstance(requested, list) or not requested or any(not isinstance(value, str) for value in requested) or len(set(requested)) != len(requested)):
                    raise RunError('invalid_experiment', 'admission', 'case_ids must be an explicit nonempty unique selection.')
                entries_for_task = []
                seen = set()
                for entry in manifest['cases']:
                    if entry.get('selected') is not True or requested is not None and entry['case_id'] not in requested:
                        continue
                    if entry['case_id'] in seen:
                        raise RunError('invalid_manifest', 'admission', 'Duplicate selected case.')
                    seen.add(entry['case_id'])
                    evaluator, _, frozen_case, _ = load_registered_case(path, entry['case_id'])
                    for field, material in (('public_ref', frozen_case.public_problem), ('oracle_ref', frozen_case.oracle_ref)):
                        raw = material.read_bytes()
                        if hashlib.sha256(raw).hexdigest() != entry[field]['sha256'] or len(raw) != entry[field]['size_bytes']:
                            raise RunError('snapshot_hash_mismatch', 'admission', 'Selected frozen case bytes changed.')
                    problem = parse_json(frozen_case.public_problem.read_bytes())
                    validate_problem(problem)
                    for ref in problem['data_refs']:
                        data_path = public_path(frozen_case.public_problem.parent, ref['path'])
                        validate_data(data_path.read_bytes(), ref)
                        sources[str(data_path)] = hashlib.sha256(data_path.read_bytes()).hexdigest()
                    entries_for_task.append({'case_id': frozen_case.case_id, 'problem_path': str(frozen_case.public_problem),
                        'public_sha256': hashlib.sha256(frozen_case.public_problem.read_bytes()).hexdigest(),
                        'eligible': entry['eligible'], 'verified_eligible': entry.get('verified_eligible', False),
                        'metric_eligibility': {metric: bool(entry.get('verified_eligible' if metric == 'verified_solution' else 'eligible', False)
                            and metric in evaluator.manifest['capabilities']['evidence_levels']
                            and (metric != 'objective_match' or entry.get('reference_quality') != 'not_available')) for metric in METRICS}})
                if requested is not None and set(requested) != seen:
                    raise RunError('invalid_manifest', 'admission', 'Every requested case must be selected in the frozen task manifest.')
                if not entries_for_task:
                    raise RunError('invalid_manifest', 'admission', 'A selected task must contain selected cases.')
                tasks[identifier] = (path, manifest, entries_for_task)
    if any(task not in tasks or selection not in configurations for task, selection in exclusions):
        raise RunError('invalid_experiment', 'admission', 'Exclusions refer to an absent matrix cell.')
    cells = []
    jobs = []
    for task_id, (manifest_path, manifest, cases) in tasks.items():
        for configuration_id, (run_config, run_settings) in configurations.items():
            cell: dict[str, Any] = {'task_id': task_id, 'configuration_id': configuration_id,
                'manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                'protocol_id': manifest['protocol_id'], 'source': manifest['source'],
                'config_sha256': hashlib.sha256(run_config.read_bytes()).hexdigest(),
                'configuration': run_settings, 'N_selected': len(cases), 'N_manifest_selected': manifest['N_selected'],
                'cases': [{k: v for k, v in case.items() if k != 'problem_path'} for case in cases]}
            if (task_id, configuration_id) in exclusions:
                cell.update(status='excluded', reason=exclusions[(task_id, configuration_id)], execution_plan=None)
                cells.append(cell)
                continue
            try:
                plan = prepare_run(run_settings, offline=offline, config_dir=run_config.parent)
                for case in cases:
                    problem = parse_json(Path(case['problem_path']).read_bytes())
                    if plan.data_loader is None:
                        raise RunError('capability_mismatch', 'admission', 'No admitted public DataLoader.')
                    for ref in problem['data_refs']:
                        raw = public_path(Path(case['problem_path']).parent, ref['path']).read_bytes()
                        view = plan.data_loader.load(raw, ref)
                        if plan.method.manifest['capabilities'].get('data_access', 'full') == 'full' and not view.complete:
                            raise RunError('capability_mismatch', 'admission', 'Selected method requires full public data.')
                    method_config = run_settings['method']['config']
                    for key in ('params_data_id', 'labels_data_id', 'public_contract_data_id'):
                        if method_config.get(key) is not None and method_config[key] not in {ref['data_id'] for ref in problem['data_refs']}:
                            raise RunError('capability_mismatch', 'admission', 'Selected method requires public data absent from this task.')
                cell.update(status='ready', reason=None, execution_plan=plan.snapshot)
            except RunError as error:
                raise RunError('experiment_incompatible', 'admission', 'A matrix cell failed preflight; explicitly exclude it or fix its configuration.',
                    details={'task_id': task_id, 'configuration_id': configuration_id, 'error_code': error.code}) from error
            cells.append(cell)
            for repeat in range(1, repeats + 1):
                for case in cases:
                    job_id = hashlib.sha256(json.dumps([task_id, configuration_id, repeat, case['case_id']]).encode()).hexdigest()[:24]
                    jobs.append({**case, 'job_id': job_id, 'task_id': task_id, 'configuration_id': configuration_id,
                        'repeat': repeat, 'manifest_path': str(manifest_path), 'run_config': str(run_config),
                        'budget': {key: run_settings['budget'][key] for key in LIMITS}, 'status': 'pending', 'started': False})
    if not jobs:
        raise RunError('invalid_experiment', 'admission', 'The matrix has no included jobs.')
    snapshot = {'schema_version': '0.1.0', 'experiment_id': experiment_id, 'offline': offline, 'repeats': repeats,
        'budget': budget, 'sdk': version('llm4om'), 'sdk_sha256': _sdk_sha256(), 'python': platform.python_version(), 'cells': cells, 'reporters': selections, 'reporter_bindings': [reporter.binding for reporter in reporters]}
    return {**snapshot, '_input_sources': sources}, jobs


def _empty(job: dict[str, Any], status: str) -> dict[str, Any]:
    result = {key: job[key] for key in ('job_id', 'task_id', 'configuration_id', 'case_id', 'repeat', 'eligible', 'verified_eligible')}
    result.update(status=status, run_id=None, evidence_origin='not_run', total_tokens=None, cost=None,
                  llm_attempts=None, solver_calls=None, elapsed_s=None, checker_error=None)
    for metric in METRICS:
        denominator = int(job['metric_eligibility'][metric])
        result.update({metric + '_numerator': 0, metric + '_denominator': denominator,
                       metric + '_rate': 0 if denominator else None})
    return result


def _execute(job: dict[str, Any], output: Path, offline: bool, cancellation: CancellationToken, deadline: float) -> dict[str, Any]:
    started = time.monotonic()
    result = _empty(job, 'failed')
    run_root = output / 'runs' / job['job_id']
    try:
        previous = list(run_root.glob('*/checkpoint.json'))
        bundles = list(run_root.glob('*/bundle.json'))
        if len(previous) > 1 or len(bundles) > 1:
            raise RunError('checkpoint_incompatible', 'control', 'A batch job must own only one persisted run.')
        if bundles and parse_json(bundles[0].read_bytes())['status'] != 'cancelled':
            run_path = bundles[0].parent
            bundle = parse_json(bundles[0].read_bytes())
        else:
            if previous:
                command = ['resume', '--run-id', previous[0].parent.name, '--output', str(run_root)]
            else:
                command = ['run', '--problem', job['problem_path'], '--config', job['run_config'], '--output', str(run_root)]
                if offline:
                    command.append('--offline')
            # Plugin output capture is process-global; each concurrent run owns a process.
            raw, _, _ = run_owned_process([sys.executable, '-m', 'llm4om', *command], b'', deadline=deadline + 3, cancellation=cancellation)
            run_record = parse_json(raw)
            if 'bundle_path' not in run_record:
                raise RunError('experiment_job_error', 'execution', 'Application did not persist a batch outcome.')
            run_path = Path(run_record['bundle_path'])
            bundle = parse_json((run_path / 'bundle.json').read_bytes())
        bundle_digest = hashlib.sha256((run_path / 'bundle.json').read_bytes()).hexdigest()[:16]
        evaluation_path = output / 'evaluations' / (job['job_id'] + '-' + bundle_digest + '.json')
        evaluation = None
        if evaluation_path.exists():
            try:
                evaluation = parse_reference_json(evaluation_path.read_bytes())
            except (ValueError, OSError):
                evaluation = None  # Truncated evaluation bytes are re-evaluated offline, never recorded as a checker error.
        if evaluation is None:
            raw, _, code = run_owned_process([sys.executable, '-m', 'llm4om', 'evaluate', '--manifest', job['manifest_path'],
                '--case-id', job['case_id'], '--run', str(run_path), '--output', str(evaluation_path)], b'',
                deadline=deadline, cancellation=cancellation)
            if not evaluation_path.exists():
                raise RunError('experiment_evaluation_error', 'evaluation', 'Evaluator did not persist public evidence.')
            evaluation = parse_reference_json(evaluation_path.read_bytes())
        ledger = parse_json((run_path / 'budget-ledger.json').read_bytes())
        result.update(status=bundle['status'], run_id=bundle['run_id'], evidence_origin=ledger['evidence_origin'],
                      evaluation=evaluation, checker_error=evaluation['checker_error'], run_error=bundle['error'])
        if bundle['status'] == 'cancelled':
            result['interrupted'] = True
        for key in ('total_tokens', 'cost', 'llm_attempts', 'solver_calls', 'known_total_tokens', 'reserved_tokens', 'external_llm_requests'):
            result[key] = ledger.get(key)
        for metric in METRICS:
            numerator = int(result[metric + '_denominator'] == 1 and evaluation.get(metric, {}).get('status') == 'pass')
            result[metric + '_numerator'] = numerator
            result[metric + '_rate'] = numerator if result[metric + '_denominator'] else None
            for suffix in ('numerator', 'denominator', 'rate'):
                key = metric + '_' + suffix
                if key in evaluation:
                    result[key] = evaluation[key]
        job['evidence'] = {str(path): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (run_path / 'bundle.json', run_path / 'budget-ledger.json', evaluation_path)}
    except (RunError, OSError, KeyError, TypeError, ValueError) as error:
        if isinstance(error, RunError) and error.code in {'run_cancelled', 'deadline_exhausted'}:
            result.update(status='cancelled' if error.code == 'run_cancelled' else 'deadline_exhausted', interrupted=True)
        result['checker_error'] = {'code': error.code if isinstance(error, RunError) else 'experiment_job_error',
                                  'message': 'Cannot complete or evaluate this frozen job; its denominator is retained.'}
    result['elapsed_s'] = time.monotonic() - started
    return result


def run_experiment(config: Path, output: Path, *, offline: bool = False, resume: bool = False,
                   cancellation: CancellationToken | None = None) -> dict[str, Any]:
    """Run a frozen matrix; resume keeps completed jobs and all prior reservations."""
    cancellation = cancellation or CancellationToken()
    output = output.resolve()
    with _lock(output):
        snapshot, jobs = _prepare(config.resolve(), offline)
        sources = snapshot.pop('_input_sources')
        state_path = output / '.private' / 'experiment-state.json'
        if state_path.exists():
            if not resume:
                raise RunError('experiment_exists', 'control', 'Use --resume to continue this saved experiment.')
            state = parse_reference_json(state_path.read_bytes())
            if state['snapshot'] != snapshot or state['input_sources'] != sources or [job['job_id'] for job in state['jobs']] != [job['job_id'] for job in jobs]:
                raise RunError('checkpoint_incompatible', 'control', 'Frozen inputs, config, package or runtime identity changed.')
            jobs = state['jobs']
            for job in jobs:
                for path, digest in job.get('evidence', {}).items():
                    if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
                        raise RunError('checkpoint_incompatible', 'control', 'Saved public batch evidence changed.')
                for path in (output / 'runs' / job['job_id']).glob('*/bundle.json'):
                    bundle = parse_json(path.read_bytes())
                    for ref in bundle['artifacts']:
                        _verify_ref(path.parent, ref)
        else:
            if resume:
                raise RunError('experiment_missing', 'control', 'No saved experiment exists.')
            state = {'snapshot': snapshot, 'input_sources': sources, 'jobs': jobs, 'results': {}, 'reserved': {key: 0 for key in LIMITS}}
            state_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            state_path.parent.chmod(0o700)
        _write(output / 'experiment.json', snapshot)
        _write(state_path, state)
        state_path.chmod(0o600)
        deadline = state.setdefault('deadline', time.time() + snapshot['budget']['wall_time_s'])
        identity = {'schema_version': '0.1.0', 'experiment_id': snapshot['experiment_id'], 'invocation_id': uuid4().hex}
        (output / 'cancel-request.json').unlink(missing_ok=True)
        _write(output / 'experiment-control.json', identity)
        cancellation.bind(output / 'cancel-request.json', identity)
        session_start = time.monotonic()
        active: dict[Any, tuple[dict[str, Any], CancellationToken]] = {}
        with ThreadPoolExecutor(max_workers=snapshot['budget']['max_concurrency']) as pool:
            for job in jobs:
                if job['job_id'] in state['results'] and not state['results'][job['job_id']].get('interrupted'):
                    state['results'][job['job_id']]['result_reused'] = True
                    continue
                while len(active) >= snapshot['budget']['max_concurrency']:
                    _collect(active, state, state_path, cancellation, deadline)
                if cancellation.cancelled or time.time() >= deadline:
                    job['status'] = 'cancelled' if cancellation.cancelled else 'deadline_exhausted'
                    continue
                if not job['started']:
                    if any(state['reserved'][key] + job['budget'][key] > snapshot['budget'][key] for key in LIMITS):
                        job['status'] = 'budget_exhausted'
                        continue
                    # Reserve a full run cap before dispatch; never hide unknown/paid usage on resume.
                    for key in LIMITS:
                        state['reserved'][key] += job['budget'][key]
                    job['started'] = True
                job['status'] = 'running'
                job.pop('cancel_requested_at', None)
                if job['job_id'] in state['results']:
                    state.setdefault('continuation_history', {}).setdefault(job['job_id'], []).append(state['results'][job['job_id']])
                    job.pop('evidence', None)
                _write(state_path, state)
                token = CancellationToken()
                active[pool.submit(_execute, job, output, offline, token, deadline)] = (job, token)
            while active:
                _collect(active, state, state_path, cancellation, deadline)
        state['elapsed_s'] = state.get('elapsed_s', 0) + time.monotonic() - session_start
        _write(state_path, state)
        return report_experiment(output)


def _collect(active: dict[Any, tuple[dict[str, Any], CancellationToken]], state: dict[str, Any], path: Path,
             cancellation: CancellationToken, deadline: float) -> None:
    if cancellation.cancelled or time.time() >= deadline:
        for job, token in active.values():
            roots = list((path.parent.parent / 'runs' / job['job_id']).glob('*/checkpoint.json'))
            if roots and 'cancel_requested_at' not in job:
                try:
                    cancel_run(roots[0].parent)
                except (RunError, OSError):
                    pass
                job['cancel_requested_at'] = time.time()
            if not roots or time.time() - job.get('cancel_requested_at', 0) >= 2:
                token.cancel()
    done, _ = wait(active, timeout=0.1, return_when=FIRST_COMPLETED)
    for future in done:
        job, _ = active.pop(future)
        result = future.result()
        state['results'][job['job_id']] = result
        job['status'] = result['status']
        _write(path, state)


def cancel_experiment(output: Path) -> dict[str, Any]:
    """Request cancellation of the current experiment invocation, including its owned runs."""
    identity = parse_json((output / 'experiment-control.json').read_bytes())
    if set(identity) != {'schema_version', 'experiment_id', 'invocation_id'} or identity['schema_version'] != '0.1.0':
        raise RunError('control_incompatible', 'control', 'Saved experiment control identity is invalid.')
    _write(output / 'cancel-request.json', identity)
    return {'experiment_id': identity['experiment_id'], 'status': 'cancel_requested'}


def report_experiment(output: Path) -> dict[str, Any]:
    """Export public JSONL/CSV and per-protocol/config/repeat Markdown/HTML summaries."""
    state = parse_reference_json((output / '.private/experiment-state.json').read_bytes())
    snapshot = state['snapshot']
    if (snapshot.get('sdk') != version('llm4om') or snapshot.get('sdk_sha256') != _sdk_sha256()
            or 'reporters' not in snapshot or 'reporter_bindings' not in snapshot):
        raise RunError('checkpoint_incompatible', 'reporting', 'Saved experiment has no compatible SDK/Reporter identities.')
    rows = [state['results'].get(job['job_id'], _empty(job, job['status'])) for job in state['jobs']]
    groups = []
    for cell in snapshot['cells']:
        if cell['status'] == 'excluded':
            continue
        for repeat in range(1, snapshot['repeats'] + 1):
            selected = [row for row in rows if row['task_id'] == cell['task_id'] and row['configuration_id'] == cell['configuration_id'] and row['repeat'] == repeat]
            group: dict[str, Any] = {'task_id': cell['task_id'], 'configuration_id': cell['configuration_id'],
                'repeat': repeat, 'protocol_id': cell['protocol_id'], 'source': cell['source'],
                'N_selected': len(selected), 'N_completed': sum(row['status'] == 'completed' for row in selected),
                'N_reused': sum(row.get('result_reused', False) for row in selected),
                'N_assisted': sum(row.get('evidence_origin') == 'assisted' for row in selected),
                'statuses': {status: sum(row['status'] == status for row in selected) for status in sorted({row['status'] for row in selected})},
                'evidence_origins': sorted({row['evidence_origin'] for row in selected})}
            for metric in METRICS:
                numerator = sum(row[metric + '_numerator'] for row in selected)
                denominator = sum(row[metric + '_denominator'] for row in selected)
                group.update({metric + '_numerator': numerator, metric + '_denominator': denominator,
                              metric + '_rate': numerator / denominator if denominator else None})
            for field in ('total_tokens', 'cost', 'llm_attempts', 'solver_calls'):
                values = [row.get(field) for row in selected]
                group[field] = sum(values) if all(value is not None for value in values) else None
                group[field + '_known_sum'] = sum(value for value in values if value is not None)
                group[field + '_unknown_count'] = sum(value is None for value in values)
            for field in ('formulation_validation', 'code_validation', 'execution', 'candidate_primal', 'semantic_validation'):
                group[field] = {status: sum(row.get('evaluation', {}).get(field, {}).get('status', 'not_available') == status for row in selected)
                    for status in sorted({row.get('evaluation', {}).get(field, {}).get('status', 'not_available') for row in selected})}
            groups.append(group)
    summary = {'schema_version': '0.1.0', 'experiment_id': snapshot['experiment_id'], 'groups': groups,
               'excluded_cells': [cell for cell in snapshot['cells'] if cell['status'] == 'excluded'],
               'budget': snapshot['budget'], 'reserved_run_caps': state['reserved'], 'elapsed_s': state.get('elapsed_s'),
               'policy': 'Groups keep protocol/source/config/repeat separate. Mock is engineering evidence; assisted results require a separate human-assisted comparison. Unknown costs/tokens are null. Unfinished and failed jobs retain frozen denominators.'}
    reporters = resolve_reporters(snapshot['reporters'], 'experiment', expected=snapshot['reporter_bindings'])
    refs, errors = render_reports(reporters, {'id': snapshot['experiment_id'], 'rows': rows, 'summary': summary},
        'experiment', lambda name, raw, ref: publish_report(output, name, raw, ref))
    summary.update(report_refs=refs, report_errors=errors)
    _write(output / 'reports/summary.json', summary)
    return summary
