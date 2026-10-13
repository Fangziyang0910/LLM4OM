"""数据集浏览 API:本地所有者可逐条查看冻结快照的公开输入与参考答案。"""
import json
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, ProxyHandler

from llm4om.tasks import import_dataset

REPO = Path(__file__).resolve().parents[1]


class WebDatasetTests(unittest.TestCase):
    def test_dataset_listing_and_case_reference_browsing(self):
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            (workspace / 'tasks').mkdir()
            manifest = import_dataset(REPO / 'examples/specs/import-checker.json', workspace / 'tasks' / 'micro')
            self.assertTrue(manifest.is_file())
            with socket.socket() as allocation:
                allocation.bind(('127.0.0.1', 0))
                port = allocation.getsockname()[1]
                allocation.close()
            process = subprocess.Popen([sys.executable, '-m', 'llm4om', 'serve', '--host', '127.0.0.1', '--port', str(port),
                                        '--workspace', str(workspace)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                opener = build_opener(ProxyHandler({}))
                url = f'http://127.0.0.1:{port}'
                for _ in range(100):
                    try:
                        with opener.open(url + '/api/bootstrap', timeout=1) as response:
                            self.assertTrue(json.load(response)['token'])
                        break
                    except Exception:
                        time.sleep(0.05)
                else:
                    self.fail('Web server did not start.')
                headers = {'Origin': url}
                with opener.open(Request(url + '/api/datasets', headers=headers), timeout=3) as response:
                    listing = json.load(response)
                datasets = {item['dataset_id']: item for item in listing['datasets']}
                self.assertIn('original-production-micro-fixture', datasets)
                entry = datasets['original-production-micro-fixture']
                self.assertEqual(entry['source_version'], 'v1')
                self.assertEqual(entry['protocol_id'], 'llm4om.eval.checker-v0.1')
                self.assertEqual(entry['adapter_id'], 'llm4om.tasks.checker_fixture')
                self.assertEqual(entry['N_selected'], 1)
                self.assertEqual(entry['N_cases'], 1)
                task_id = entry['task_id']
                with opener.open(Request(f'{url}/api/datasets/{task_id}', headers=headers), timeout=3) as response:
                    detail = json.load(response)
                self.assertEqual(detail['dataset']['dataset_id'], 'original-production-micro-fixture')
                self.assertEqual(detail['total'], 1)
                case = detail['cases'][0]
                self.assertEqual(case['case_id'], 'fixture-production-milp-001')
                self.assertTrue(case['selected'])
                self.assertTrue(case['eligible'])
                self.assertIn('生产数量', case['problem']['description'])
                self.assertEqual(case['problem']['requirements'][0]['id'], 'R-PROFIT')
                reference = case['reference']
                self.assertEqual(reference['reference_objective']['value'], 13)
                self.assertEqual(reference['decision_mapping'], {'A': 'qty_A', 'B': 'qty_B'})
                # 分页:offset 越界返回空窗口,total 不变
                with opener.open(Request(f'{url}/api/datasets/{task_id}?offset=5&limit=10', headers=headers), timeout=3) as response:
                    beyond = json.load(response)
                self.assertEqual(beyond['cases'], [])
                self.assertEqual(beyond['total'], 1)
                # 单条参考答案字节被改动:只降级该条,数据集整体仍可浏览
                oracle = workspace / 'tasks' / 'micro' / 'private' / '0.json'
                original = oracle.read_bytes()
                oracle.write_bytes(original[:-1] + b' ')
                try:
                    with opener.open(Request(f'{url}/api/datasets/{task_id}', headers=headers), timeout=3) as response:
                        degraded = json.load(response)
                    self.assertEqual(degraded['total'], 1)
                    self.assertEqual(degraded['cases'][0]['error'], 'snapshot_hash_mismatch')
                    self.assertIsNone(degraded['cases'][0]['reference'])
                finally:
                    oracle.write_bytes(original)
                # 未知数据集与跨源访问按既有错误语义拒绝
                with self.assertRaises(HTTPError) as unknown:
                    opener.open(Request(f'{url}/api/datasets/{("0" * 32)}', headers=headers), timeout=3)
                self.assertEqual(json.load(unknown.exception)['error']['code'], 'not_found')
                with self.assertRaises(HTTPError) as foreign:
                    opener.open(Request(url + '/api/datasets', headers={'Host': f'192.0.2.10:{port}',
                        'Origin': f'http://192.0.2.10:{port}'}), timeout=3)
                self.assertEqual(json.load(foreign.exception)['error']['code'], 'invalid_origin')
            finally:
                process.send_signal(signal.SIGINT)
                process.communicate(timeout=10)


if __name__ == '__main__':
    unittest.main()
