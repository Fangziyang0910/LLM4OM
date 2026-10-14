"""The public example browser uses platform benchmarks, independent of user imports."""

import base64
import hashlib
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
    def test_builtin_listing_browsing_and_copy_input_hide_workspace_fixtures(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            import_dataset(REPO / 'examples/specs/import-checker.json', workspace / 'tasks' / 'micro')
            with socket.socket() as allocation:
                allocation.bind(('127.0.0.1', 0))
                port = allocation.getsockname()[1]
            process = subprocess.Popen([sys.executable, '-m', 'llm4om', 'serve', '--host', '127.0.0.1',
                '--port', str(port), '--workspace', str(workspace)], cwd=temporary,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
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
                def get(path):
                    with opener.open(Request(url + path, headers={'Origin': url}), timeout=5) as response:
                        return json.load(response)
                datasets = {item['dataset_id']: item for item in get('/api/datasets')['datasets']}
                counts = {'nl4opt': 205, 'nl4lp': 178, 'mamo_easy': 642, 'mamo_complex': 210,
                    'industryor': 99, 'complexor': 18, 'optibench': 403, 'optmath': 128, 'nl4cop': 150}
                self.assertEqual({key: item['N_cases'] for key, item in datasets.items()}, counts)
                for dataset in datasets.values():
                    cases = []
                    for offset in range(0, dataset['N_cases'], 200):
                        sample = get('/api/datasets/' + dataset['task_id'] + f'?offset={offset}&limit=200')
                        self.assertEqual(sample['total'], dataset['N_cases'])
                        cases.extend(sample['cases'])
                    self.assertEqual(len(cases), dataset['N_cases'])
                    self.assertEqual(len({case['case_id'] for case in cases}), dataset['N_cases'])
                    for public_case in cases:
                        self.assertTrue(public_case['problem']['description'].strip())
                        self.assertEqual(public_case['copy_text'], public_case['problem']['description'])
                        self.assertEqual(public_case['input']['data'], [])
                        self.assertEqual(set(public_case['input']), {'title', 'problem', 'data'})
                        self.assertNotIn('reference', public_case)
                entry = datasets['nl4opt']
                detail = get('/api/datasets/' + entry['task_id'] + '?offset=0&limit=2')
                self.assertEqual(detail['total'], 205)
                self.assertEqual(len(detail['cases']), 2)
                case = detail['cases'][0]
                self.assertTrue(case['problem']['description'])
                self.assertEqual(case['copy_text'], case['problem']['description'])
                self.assertEqual(case['input']['problem']['source']['dataset_id'], 'nl4opt')
                self.assertNotIn('reference', case)
                self.assertNotIn('eligible', case)
                self.assertNotIn('selected', case)
                self.assertEqual(get('/api/datasets/' + entry['task_id'] + '?offset=9999')['cases'], [])
                with self.assertRaises(HTTPError):
                    get('/api/datasets/' + '0'*32)
                with self.assertRaises(HTTPError):
                    opener.open(Request(url + '/api/datasets', headers={'Host': f'192.0.2.10:{port}',
                        'Origin': f'http://192.0.2.10:{port}'}), timeout=3)
            finally:
                process.send_signal(signal.SIGINT)
                process.communicate(timeout=10)

    def test_modeling_input_retains_business_data_and_omits_reference_fields(self):
        from llm4om.benchmarks import modeling_input
        raw = b'{"Capacity":4,"Count":"5"}'
        case = {'case_id':'example:1','sample_id':'1','subset':'example','description':'Maximize production with public Capacity.',
            'solution':'PRIVATE-SOLUTION-SENTINEL','reference_objective':12345,
            'data':[{'name':'parameters.json','data_id':'parameters','format':'json','base64':base64.b64encode(raw).decode(),
                'size':len(raw),'schema':{'type':'object'}}]}
        header = {'dataset_id':'example','title':'Example','source_version':'v1','source_url':'https://example.com'}
        result = modeling_input(case, header)
        self.assertEqual(base64.b64decode(result['data'][0]['base64']), raw)
        self.assertEqual(result['problem']['data_refs'][0]['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertNotIn('PRIVATE-', json.dumps(result))
        self.assertNotIn('reference_objective', json.dumps(result))
