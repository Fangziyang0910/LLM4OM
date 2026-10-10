"""Installed Reporter selection through CLI/SDK with actual HiGHS and saved results."""

import csv
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

import test_experiments as experiment_fixtures


ROOT = Path(__file__).resolve().parents[1]


class ReporterPluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        shutil.copytree(ROOT / 'examples/specs', self.inputs)
        target = self.root / 'plugins'
        built = subprocess.run(['uv', 'build', str(ROOT / 'examples/plugins/fixture_reporter'), '--wheel',
            '--out-dir', str(self.root / 'wheel')], capture_output=True, text=True)
        self.assertEqual(built.returncode, 0, built.stderr)
        wheel = next((self.root / 'wheel').glob('*.whl'))
        installed = subprocess.run(['uv', 'pip', 'install', '--no-deps', '--target', str(target), str(wheel)],
            capture_output=True, text=True)
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.environment = {**os.environ, 'PYTHONPATH': os.pathsep.join((str(ROOT / 'src'), str(target)))}

    def cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'llm4om', *args], env=self.environment,
                              capture_output=True, text=True, cwd=self.root)

    def config(self, selections):
        value = yaml.safe_load((self.inputs / 'solve.yaml').read_text())
        value['reporters'] = selections
        (self.inputs / 'run.json').write_text(json.dumps(value))
        return self.inputs / 'run.json'

    def cli_run(self):
        return self.cli('run', '--problem', str(self.inputs / 'problem.json'),
                        '--config', str(self.inputs / 'run.json'), '--output', str(self.root / 'runs'))

    def test_installed_reporter_and_four_formats_keep_solve_and_render_without_new_calls(self):
        self.config([{'plugin_id': 'llm4om.examples.public_report', 'config': {'label': 'research'}},
            *[{'plugin_id': 'llm4om.reporters.' + name} for name in ('jsonl', 'csv', 'markdown', 'html')]])
        listing = self.cli('plugins', 'list')
        fixture = next(item for item in json.loads(listing.stdout)['plugins']
            if item['manifest']['plugin_id'] == 'llm4om.examples.public_report')
        self.assertEqual(fixture['origin']['kind'], 'installed')
        completed = self.cli_run()
        self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
        path = Path(json.loads(completed.stdout)['bundle_path'])
        bundle = json.loads((path / 'bundle.json').read_text())
        self.assertEqual(bundle['status'], 'completed')
        self.assertEqual(bundle['report_errors'], [])
        self.assertEqual(len(bundle['report_refs']), 5)
        for ref in bundle['report_refs']:
            raw = (path / ref['relative_path']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), ref['sha256'])
            self.assertEqual(len(raw), ref['size_bytes'])
            self.assertEqual(ref['namespace'], 'run_public')
        observed = json.loads((path / 'reports/fixture-report.json').read_text())
        self.assertEqual(observed['statuses'], ['completed'])
        self.assertEqual(observed['label'], 'research')
        solve_before = (path / bundle['solve_result_ref']['relative_path']).read_bytes()
        self.assertEqual(json.loads(solve_before)['objective_value'], 13)
        ledger_before = (path / 'budget-ledger.json').read_bytes()
        rendered = self.cli('report', '--run', str(path))
        self.assertEqual(rendered.returncode, 0, rendered.stderr + rendered.stdout)
        self.assertEqual((path / 'budget-ledger.json').read_bytes(), ledger_before)
        self.assertEqual((path / bundle['solve_result_ref']['relative_path']).read_bytes(), solve_before)
        resumed = self.cli('resume', '--run-id', path.name, '--output', str(path.parent))
        self.assertEqual(json.loads(resumed.stdout)['status'], 'completed')
        self.assertEqual((path / 'budget-ledger.json').read_bytes(), ledger_before)

    def test_bad_report_output_retains_completed_evidence_and_public_errors(self):
        for mode in ('error', 'path', 'ref'):
            with self.subTest(mode=mode):
                self.config([{'plugin_id': 'llm4om.examples.public_report', 'config': {'mode': mode}},
                             {'plugin_id': 'llm4om.reporters.markdown'}])
                completed = self.cli_run()
                self.assertEqual(completed.returncode, 0, completed.stderr + completed.stdout)
                path = Path(json.loads(completed.stdout)['bundle_path'])
                bundle = json.loads((path / 'bundle.json').read_text())
                self.assertEqual(bundle['status'], 'completed')
                self.assertEqual(len(bundle['report_errors']), 1)
                self.assertFalse((path / 'reports/fixture-report.json').exists())
                self.assertEqual(len(bundle['report_refs']), 1)
                public = ''.join(p.read_text() for p in (path / 'diagnostics').glob('*.json'))
                self.assertNotIn('PRIVATE-REPORTER-SENTINEL', public)
                self.assertFalse((path / 'escape.txt').exists())
                self.assertEqual(json.loads((path / 'budget-ledger.json').read_text())['solver_calls'], 1)

    def test_unknown_duplicate_and_invalid_reporters_fail_before_model(self):
        for selection in (
            [{'plugin_id': 'llm4om.reporters.unknown'}],
            [{'plugin_id': 'llm4om.reporters.csv'}, {'plugin_id': 'llm4om.reporters.csv'}],
            [{'plugin_id': 'llm4om.examples.public_report', 'config': {'unknown': True}}],
        ):
            with self.subTest(selection=selection):
                path = self.config(selection)
                doctor = self.cli('doctor', '--config', str(path))
                self.assertEqual(doctor.returncode, 1)
                completed = self.cli_run()
                bundle_path = Path(json.loads(completed.stdout)['bundle_path'])
                self.assertEqual(json.loads((bundle_path / 'budget-ledger.json').read_text())['llm_attempts'], 0)

    def test_experiment_renderer_selection_failure_denominators_and_escaping(self):
        baseline = experiment_fixtures.ExperimentTests('test_total_budget_keeps_unstarted_case_in_frozen_denominator')
        baseline.setUp()
        try:
            baseline.spec['reporters'] = [{'plugin_id': 'llm4om.examples.public_report'},
                *[{'plugin_id': 'llm4om.reporters.' + name} for name in ('jsonl', 'csv', 'markdown', 'html')]]
            baseline.spec['budget']['max_llm_attempts'] = 1
            baseline.write(baseline.path, baseline.spec)
            output = baseline.root / 'batch'
            result = self.cli('benchmark', '--config', str(baseline.path), '--output', str(output), '--offline')
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            summary = json.loads(result.stdout)
            self.assertEqual([group['N_selected'] for group in summary['groups']], [1, 1])
            self.assertEqual(summary['report_errors'], [])
            self.assertEqual(len(summary['report_refs']), 5)
            rows = [json.loads(line) for line in (output / 'reports/results.jsonl').read_text().splitlines()]
            self.assertEqual([row['status'] for row in rows], ['artifact_ready', 'budget_exhausted'])
            before = sorted(str(path) for path in output.glob('runs/*/*/bundle.json'))
            rendered = self.cli('report', '--experiment', str(output))
            self.assertEqual(rendered.returncode, 0, rendered.stdout + rendered.stderr)
            self.assertEqual(before, sorted(str(path) for path in output.glob('runs/*/*/bundle.json')))
            public = ''.join(path.read_text() for path in (output / 'reports').glob('*'))
            self.assertNotIn('oracle_ref', public)
            from llm4om import resolve_reporters, ReportDestination, ReportContext
            result_view = {'id': 'public-comparison', 'rows': [{'task_id': '=unsafe'}],
                'summary': {'policy': 'Public reference', 'groups': [{**summary['groups'][0],
                    'task_id': '=unsafe', 'configuration_id': '<script>alert(1)</script>'}]}}
            for selection in ('csv', 'html'):
                reporter = resolve_reporters([{'plugin_id': 'llm4om.reporters.' + selection}], 'experiment')[0]
                # The independent caller observes emitted public bytes through the public put contract.
                class ObservedDestination(ReportDestination):
                    def put(self, name, content, media_type):
                        self.content = content
                        return super().put(name, content, media_type)
                observed = ObservedDestination(reporter.binding['manifest']['capabilities']['report_filenames'], 'experiment_public')
                reporter.instance.render(result_view, observed, ReportContext('experiment'))
                if selection == 'html':
                    self.assertNotIn('<script>alert(1)</script>', observed.content.decode())
                    self.assertIn('&lt;script&gt;', observed.content.decode())
                else:
                    from io import StringIO
                    self.assertEqual(next(csv.DictReader(StringIO(observed.content.decode())))['task_id'], "'=unsafe")
        finally:
            baseline.doCleanups()
