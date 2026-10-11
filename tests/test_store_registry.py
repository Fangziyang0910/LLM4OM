"""An independently installed ArtifactStore participates in the actual run lifecycle."""

import json
from pathlib import Path
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class StoreRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.inputs = self.root / 'inputs'
        shutil.copytree(ROOT / 'examples/specs', self.inputs)
        target = self.root / 'plugins'
        built = subprocess.run(['uv', 'build', str(ROOT / 'examples/plugins/fixture_store'), '--wheel',
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

    def config(self, store):
        value = yaml.safe_load((self.inputs / 'solve.yaml').read_text())
        value['store'] = store
        (self.inputs / 'run.json').write_text(json.dumps(value))
        return self.inputs / 'run.json'

    def cli_run(self):
        return self.cli('run', '--problem', str(self.inputs / 'problem.json'),
            '--config', str(self.inputs / 'run.json'), '--output', str(self.root / 'runs'))

    def test_builtin_filesystem_store_is_listed_and_default_runs_still_complete(self):
        listing = self.cli('plugins', 'list')
        self.assertEqual(listing.returncode, 0, listing.stderr)
        builtin = next(item for item in json.loads(listing.stdout)['plugins']
            if item['manifest']['plugin_id'] == 'llm4om.stores.filesystem')
        self.assertEqual(builtin['manifest']['kind'], 'artifact_store')
        self.assertEqual(builtin['manifest']['capabilities']['store_profile'], 'run_store/0.1.0')
        self.assertEqual(builtin['origin']['kind'], 'builtin')
        self.config({'plugin_id': 'llm4om.stores.filesystem', 'config': {'root': 'runs'}})
        completed = self.cli_run()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        self.assertEqual(json.loads(completed.stdout)['status'], 'completed')

    def test_installed_store_opens_runs_and_records_admission_identity(self):
        receipt = self.root / 'receipt.jsonl'
        self.config({'plugin_id': 'llm4om.examples.receipt_store', 'config': {'receipt_path': str(receipt)}})
        completed = self.cli_run()
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result['status'], 'completed')
        run = Path(result['bundle_path'])
        solve = json.loads((run / json.loads((run / 'bundle.json').read_text())['solve_result_ref']['relative_path']).read_text())
        self.assertEqual(solve['objective_value'], 13)
        admission = json.loads((run / 'admission-plan.json').read_text())
        binding = admission['store']
        self.assertEqual(binding['origin']['kind'], 'installed')
        self.assertEqual(binding['manifest']['plugin_id'], 'llm4om.examples.receipt_store')
        self.assertEqual(binding['config']['receipt_path'], str(receipt))
        records = [json.loads(line) for line in receipt.read_text().splitlines()]
        self.assertTrue(any(record['root'] == str(self.root / 'runs') and record['resume'] is None for record in records))
        self.assertEqual(json.loads((run / 'public-config.json').read_text())['store']['plugin_id'],
            'llm4om.examples.receipt_store')

    def test_unknown_store_plugin_saves_a_failure_bundle_without_charging_resources(self):
        self.config({'plugin_id': 'llm4om.stores.missing', 'config': {'root': 'runs'}})
        failed = self.cli_run()
        self.assertEqual(failed.returncode, 1, failed.stdout + failed.stderr)
        result = json.loads(failed.stdout)
        run = Path(result['bundle_path'])
        bundle = json.loads((run / 'bundle.json').read_text())
        self.assertEqual(bundle['error']['code'], 'unknown_plugin')
        self.assertEqual(json.loads((run / 'budget-ledger.json').read_text())['llm_attempts'], 0)


if __name__ == '__main__':
    unittest.main()
