"""An independently installed Executor participates in actual CLI/HiGHS execution."""

import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

from llm4om.contracts import read_config


class ExecutorRegistryTests(unittest.TestCase):
    def test_installed_executors_run_both_process_profiles(self):
        repository = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = root / 'public'
            shutil.copytree(repository / 'examples/specs', packet)
            target = root / 'plugins'
            built = subprocess.run(['uv', 'build', '--offline', str(repository / 'examples/plugins/fixture_executor'),
                '--wheel', '--out-dir', str(root / 'wheel')], capture_output=True, text=True)
            self.assertEqual(built.returncode, 0, built.stderr)
            wheel = next((root / 'wheel').glob('*.whl'))
            installed = subprocess.run(['uv', 'pip', 'install', '--offline', '--no-deps', '--target', str(target), str(wheel)],
                capture_output=True, text=True)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            environment = {**os.environ, 'PYTHONPATH': os.pathsep.join((str(repository / 'src'), str(target)))}
            for mode, plugin in [('container', 'container_executor'), ('trusted_local', 'local_executor')]:
                settings = read_config(repository / 'examples/specs/run.yaml')
                receipt = root / (mode + '.jsonl')
                settings['executor']['plugin_id'] = 'llm4om.fixtures.' + plugin
                if mode == 'trusted_local':
                    settings['executor']['config'] = {}
                settings['executor']['config']['receipt_path'] = str(receipt)
                config = packet / (mode + '.json')
                config.write_text(json.dumps(settings))
                process = subprocess.run([sys.executable, '-m', 'llm4om', 'run', '--problem',
                    str(packet / 'problem.json'), '--config', str(config), '--output', str(root / mode)],
                    env=environment, capture_output=True, text=True, timeout=40)
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                result = json.loads(process.stdout)
                self.assertEqual(result['status'], 'completed')
                run = Path(result['bundle_path'])
                bundle = json.loads((run / 'bundle.json').read_text())
                solve = json.loads((run / bundle['solve_result_ref']['relative_path']).read_text())
                self.assertEqual(solve['objective_value'], 13)
                execution = json.loads((run / bundle['execution_result_ref']['relative_path']).read_text())
                self.assertEqual(execution['mode'], mode)
                admission = json.loads((run / bundle['admission_plan_ref']['relative_path']).read_text())
                binding = admission['executor']
                self.assertEqual(binding['origin']['kind'], 'installed')
                self.assertEqual(binding['manifest']['plugin_id'], settings['executor']['plugin_id'])
                records = [json.loads(line) for line in receipt.read_text().splitlines()]
                self.assertTrue(any('--runtime' in record['command'] for record in records))
                self.assertTrue(any('--solve' in record['command'] or '--solve-stdin' in record['command'] for record in records))


if __name__ == '__main__':
    unittest.main()
