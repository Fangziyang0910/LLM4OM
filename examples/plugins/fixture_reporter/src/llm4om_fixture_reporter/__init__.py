"""An installed Reporter that observes public results and exercises safe failures."""

import json
from typing import Any

from llm4om import ReportContext, ReportDestination


class FixtureReporter:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    def render(self, result: dict[str, Any], destination: ReportDestination,
               context: ReportContext) -> list[dict[str, Any]]:
        original_statuses = [row['status'] for row in result['rows']]
        if self.config.get('mode') == 'error':
            raise RuntimeError('PRIVATE-REPORTER-SENTINEL')
        result['rows'][0]['status'] = 'MUTATED-REPORTER-COPY'
        record = {'scope': context.scope, 'statuses': original_statuses,
            'unknown_cost_preserved': all(row.get('cost') is None for row in result['rows']),
            'public_input_keys': sorted(result), 'label': self.config.get('label', 'fixture')}
        name = '../escape.txt' if self.config.get('mode') == 'path' else 'fixture-report.json'
        ref = destination.put(name, (json.dumps(record, indent=2) + '\n').encode(), 'application/json')
        if self.config.get('mode') == 'ref':
            ref['sha256'] = '0' * 64
        return [ref]


class FixtureFactory:
    def describe(self) -> dict[str, Any]:
        return {'schema_version': '0.2.0', 'plugin_id': 'llm4om.examples.public_report', 'kind': 'reporter',
            'plugin_version': '0.1.0', 'contract_range': '>=0.2.0,<0.3.0', 'display_name': 'Public result fixture',
            'description': 'Observe finalized results without changing the core outcome.',
            'capabilities': {'problem_types': ['lp', 'milp'], 'input_artifact_kinds': ['public_results'],
                'output_artifact_kinds': ['report'], 'reporter_profile': 'public_results/0.1.0',
                'report_scopes': ['run', 'experiment'], 'report_filenames': ['fixture-report.json']},
            'config_schema': {'type': 'object', 'additionalProperties': False, 'properties': {
                'mode': {'enum': ['normal', 'error', 'path', 'ref']}, 'label': {'type': 'string'}}},
            'dependencies': {'python': []}, 'source': None}

    def create(self, config: dict[str, Any]) -> FixtureReporter:
        return FixtureReporter(config)


plugin = FixtureFactory()
