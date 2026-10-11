"""Render finalized public results through admitted, bounded Reporter plugins."""

import csv
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import html
from io import StringIO
import json
from pathlib import Path
from typing import Any, Protocol, Callable

from llm4om.contracts import RunError, public_path
from llm4om.plugins import Plugin, resolve_configured_plugin, _quiet, _exception_details

METRICS = ('independent_feasibility', 'objective_match', 'verified_solution')
DEFAULT_REPORTERS = [{'plugin_id': 'llm4om.reporters.' + name} for name in ('jsonl', 'csv', 'markdown', 'html')]
MAX_REPORT_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class ReportContext:
    scope: str


class ReportDestination:
    """Collect only declared report files before the caller publishes any bytes."""

    def __init__(self, filenames: list[str], namespace: str) -> None:
        self._filenames = frozenset(filenames)
        self._namespace = namespace
        self._files: dict[str, tuple[bytes, dict[str, Any]]] = {}

    def put(self, name: str, content: bytes, media_type: str) -> dict[str, Any]:
        if name not in self._filenames or name in self._files or not isinstance(content, bytes):
            raise RunError('invalid_report', 'reporting', 'Report output must use a unique declared filename and bytes.')
        if media_type not in {'application/json', 'application/x-ndjson', 'text/csv', 'text/markdown', 'text/html', 'text/plain'}:
            raise RunError('invalid_report', 'reporting', 'Unsupported public report media type.')
        if sum(len(item[0]) for item in self._files.values()) + len(content) > MAX_REPORT_BYTES:
            raise RunError('report_limit', 'reporting', 'Reporter output exceeds64 MiB.')
        ref = {'artifact_id': 'report-' + name, 'media_type': media_type, 'sha256': hashlib.sha256(content).hexdigest(),
            'size_bytes': len(content), 'namespace': self._namespace, 'relative_path': 'reports/' + name, 'schema_version': None}
        self._files[name] = (content, ref)
        return deepcopy(ref)


class Reporter(Protocol):
    def render(self, result: dict[str, Any], destination: ReportDestination,
               context: ReportContext) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class ResolvedReporter:
    instance: Reporter
    binding: dict[str, Any]


def resolve_reporters(selections: list[dict[str, Any]], scope: str, *,
                      inventory: dict[tuple[str, str], Plugin] | None = None,
                      expected: list[dict[str, Any]] | None = None) -> list[ResolvedReporter]:
    if (not isinstance(selections, list) or len(selections) > 32 or any(not isinstance(item, dict)
            or not isinstance(item.get('plugin_id'), str) or not item['plugin_id']
            or set(item) - {'plugin_id', 'config'} or not isinstance(item.get('config', {}), dict) for item in selections)):
        raise RunError('invalid_config', 'admission', 'Declare at most32 valid Reporter selections.')
    if expected is not None and len(expected) != len(selections):
        raise RunError('checkpoint_incompatible', 'admission', 'Saved Reporter selections changed.')
    result: list[ResolvedReporter] = []
    filenames: set[str] = set()
    for index, selection in enumerate(selections):
        instance, binding = resolve_configured_plugin('reporter', selection, inventory=inventory,
            expected=expected[index] if expected is not None else None)
        caps = binding['manifest']['capabilities']
        if scope not in caps['report_scopes']:
            raise RunError('capability_mismatch', 'admission', 'Reporter does not accept this result scope.')
        declared = caps['report_filenames']
        if sum(len(item.binding['manifest']['capabilities']['report_filenames']) for item in result) + len(declared) > 128:
            raise RunError('invalid_config', 'admission', 'At most128 report files may be declared.')
        if filenames.intersection(declared):
            raise RunError('invalid_config', 'admission', 'Selected Reporter output filenames collide.')
        filenames.update(declared)
        if not callable(getattr(instance, 'render', None)):
            raise RunError('invalid_plugin_manifest', 'admission', 'Reporter must implement render.')
        result.append(ResolvedReporter(instance, binding))
    return result


def render_reports(reporters: list[ResolvedReporter], result: dict[str, Any], scope: str,
                   publish: Callable[[str, bytes, dict[str, Any]], dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    refs: list[dict[str, Any]] = []
    errors = []
    total_bytes = 0
    for reporter in reporters:
        plugin_id = reporter.binding['manifest']['plugin_id']
        destination = ReportDestination(reporter.binding['manifest']['capabilities']['report_filenames'],
            'run_public' if scope == 'run' else 'experiment_public')
        try:
            with _quiet():
                produced = reporter.instance.render(deepcopy(result), destination, ReportContext(scope))
            stored = [ref for _, ref in destination._files.values()]
            produced_set = produced if isinstance(produced, list) else []
            if (set(destination._files) != destination._filenames or len(produced_set) != len(stored)
                    or not all(any(candidate == ref for ref in stored) for candidate in produced_set)):
                raise RunError('invalid_report', 'reporting', 'Returned report references differ from the produced bytes.')
            outputs = [(ref['relative_path'], raw, deepcopy(ref)) for raw, ref in destination._files.values()]
            if total_bytes + sum(len(raw) for _, raw, _ in outputs) > MAX_REPORT_BYTES:
                raise RunError('report_limit', 'reporting', 'Combined report output exceeds64 MiB.')
        except (Exception, SystemExit) as error:
            errors.append({'plugin_id': plugin_id, 'code': error.code if isinstance(error, RunError) else 'reporter_error',
                'message': 'Reporter could not render this saved public result.', **_exception_details(error)})
            continue
        for name, raw, ref in outputs:
            refs.append(publish(name, raw, ref))
            total_bytes += len(raw)
    return refs, errors


def publish_report(root: Path, name: str, content: bytes, ref: dict[str, Any]) -> dict[str, Any]:
    from llm4om.storage import _atomic, _mkdir
    destination = public_path(root, name, require_file=False)
    _mkdir(destination.parent)
    _atomic(destination, content)
    return ref


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def _table(result: dict[str, Any], scope: str) -> tuple[list[str], list[list[str]]]:
    if scope == 'run':
        row = result['rows'][0]
        return ['Stage', 'Status'], [[name, stage['status']] for name, stage in row['stages'].items()]
    headers = ['Task', 'Configuration', 'Repeat', 'Completed/selected', 'Independent feasible',
               'Objective match', 'Verified solution', 'Tokens', 'Cost']
    table = []
    for group in result['summary']['groups']:
        table.append([group['task_id'], group['configuration_id'], str(group['repeat']),
            f"{group['N_completed']}/{group['N_selected']}",
            *[f"{group[metric + '_numerator']}/{group[metric + '_denominator']}"
              if group[metric + '_denominator'] else 'not_available' for metric in METRICS],
            str(group['total_tokens']) if group['total_tokens'] is not None else 'unknown',
            str(group['cost']) if group['cost'] is not None else 'unknown'])
    return headers, table


class PublicResultReporter:
    def __init__(self, format_name: str) -> None:
        self.format_name = format_name

    def render(self, result: dict[str, Any], destination: ReportDestination,
               context: ReportContext) -> list[dict[str, Any]]:
        if self.format_name == 'jsonl':
            return [destination.put('results.jsonl', ''.join(_json(row) + '\n' for row in result['rows']).encode(),
                                    'application/x-ndjson')]
        if self.format_name == 'csv':
            if context.scope == 'experiment':
                columns = ['task_id', 'configuration_id', 'case_id', 'repeat', 'status', 'run_id', 'evidence_origin',
                    'eligible', 'verified_eligible', *[metric + '_' + suffix for metric in METRICS
                    for suffix in ('numerator', 'denominator', 'rate')],
                    'llm_attempts', 'solver_calls', 'total_tokens', 'cost', 'elapsed_s']
            else:
                columns = ['run_id', 'status', 'mode', 'method_id', 'provider_id', 'model',
                           'external_llm_requests', 'total_tokens', 'cost']
            stream = StringIO(newline='')
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            for row in result['rows']:
                writer.writerow({key: "'" + value if isinstance(value, str) and value.startswith(
                    ('=', '+', '-', '@', '\t', '\r')) else value for key, value in row.items()})
            return [destination.put('results.csv', stream.getvalue().encode(), 'text/csv')]
        headers, rows = _table(result, context.scope)
        title = 'LLM4OM ' + context.scope + ' ' + result['id']
        policy = result['summary']['policy']
        if self.format_name == 'markdown':
            def escape(value: str) -> str:
                return value.replace('|', '\\|').replace('\n', ' ')
            report = '# ' + title + '\n\n' + policy + '\n\n'
            report += '| ' + ' | '.join(headers) + ' |\n|' + '|'.join(['---'] * len(headers)) + '|\n'
            report += ''.join('| ' + ' | '.join(escape(value) for value in row) + ' |\n' for row in rows)
            if context.scope == 'run':
                row = result['rows'][0]
                report += (f"\nMode: {row['mode']}. Status: {row['status']}.\n\n"
                    f"Method: {html.escape(row['method_id'])}. Provider: {html.escape(row['provider_id'])}.\n\n"
                    f"External LLM requests: {row['external_llm_requests']}. "
                    f"Tokens: {row['total_tokens'] if row['total_tokens'] is not None else 'unknown'}. "
                    f"Cost: {row['cost'] if row['cost'] is not None else 'unknown'}.\n")
                if row['solve']:
                    report += f"\nCandidate termination: {row['solve']['termination']}. Objective: {row['solve']['objective_value']}.\n"
                if row['error']:
                    report += f"\nError: {row['error']['code']} ({row['error']['stage']}).\n"
            report += '\nFull public results and diagnostics remain in the saved machine-readable records.\n'
            return [destination.put('report.md', report.encode(), 'text/markdown')]
        rendered = '<!doctype html><html lang="en"><meta charset="utf-8"><title>' + html.escape(title) + '</title>'
        rendered += '<h1>' + html.escape(title) + '</h1><p>' + html.escape(policy) + '</p><table>'
        rendered += '<caption>Public ' + context.scope + ' results</caption><thead><tr>'
        rendered += ''.join('<th scope="col">' + html.escape(header) + '</th>' for header in headers) + '</tr></thead><tbody>'
        rendered += ''.join('<tr>' + ''.join('<td>' + html.escape(value) + '</td>' for value in row) + '</tr>' for row in rows)
        rendered += '</tbody></table><p>Full public results and diagnostics remain in the saved machine-readable records.</p></html>\n'
        return [destination.put('report.html', rendered.encode(), 'text/html')]


class PublicReporterFactory:
    def __init__(self, format_name: str) -> None:
        self.format_name = format_name

    def describe(self) -> dict[str, Any]:
        filename = {'jsonl': 'results.jsonl', 'csv': 'results.csv', 'markdown': 'report.md', 'html': 'report.html'}[self.format_name]
        return {'schema_version': '0.2.0', 'plugin_id': 'llm4om.reporters.' + self.format_name, 'kind': 'reporter',
            'plugin_version': '0.1.0', 'contract_range': '>=0.2.0,<0.3.0', 'display_name': self.format_name.upper(),
            'description': 'Render finalized public results; never recompute evaluation.',
            'capabilities': {'problem_types': ['lp', 'milp'], 'input_artifact_kinds': ['public_results'],
                'output_artifact_kinds': ['report'], 'reporter_profile': 'public_results/0.1.0',
                'report_scopes': ['run', 'experiment'], 'report_filenames': [filename]},
            'config_schema': {'type': 'object', 'additionalProperties': False}, 'dependencies': {'python': []}, 'source': None}

    def create(self, config: dict[str, Any]) -> Reporter:
        return PublicResultReporter(self.format_name)


def builtin_reporters() -> tuple[PublicReporterFactory, ...]:
    return tuple(PublicReporterFactory(name) for name in ('jsonl', 'csv', 'markdown', 'html'))
