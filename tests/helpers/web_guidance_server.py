"""Local deterministic clarification responder and Web server for browser acceptance."""

import argparse
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
import time

from llm4om.web import serve_web


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True, help='An empty disposable directory.')
    parser.add_argument('--port', type=int, default=8774)
    parser.add_argument('--provider-port', type=int, default=8775)
    parser.add_argument('--response-delay', type=float, default=0, help='Delay local replies to observe live modeling.')
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        parser.error('Use an empty disposable workspace; existing records are not overwritten.')
    workspace.mkdir(parents=True, exist_ok=True)
    fixtures = Path(__file__).resolve().parents[2] / 'examples/specs'
    representation = json.loads((fixtures / 'formulation.json').read_text())['representation']
    for parameter, value in zip(representation['parameters'], [[3, 2], [[2, 1], [1, 2]], [8, 8]]):
        parameter.pop('source')
        parameter['value'] = value
    ir = json.loads((fixtures / 'model-ir.json').read_text())
    compact = {'representation': representation, 'structured_ir': {key: ir[key] for key in
        ('problem_type', 'variables', 'objective', 'constraints', 'assumptions')}}

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            time.sleep(max(0, args.response_delay))
            request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            payload = json.loads(request['messages'][-1]['content'])
            revised = [item['id'] for item in payload['problem']['requirements'] if item['id'].startswith('CLARIFY-')]
            if not payload.get('clarifications') and not revised:
                if 'need-new-rule' in payload['problem']['description']:
                    question = {'question_id': 'capacity', 'kind': 'new_information',
                        'question': '产品 A 的产量上限是多少？', 'statement_ref': None}
                else:
                    question = {'question_id': 'domain', 'kind': 'confirm_existing',
                        'question': '请确认产品数量必须是非负整数。',
                        'statement_ref': {'kind': 'requirement', 'id': 'R-DOMAIN'}}
                result = {'clarification': {'questions': [question]}}
            else:
                result = deepcopy(compact)
                if 'need-repair' in payload['problem']['description']:
                    if 'feedback' in payload:
                        result.update(repair_stage='formulation', change_reason='修正变量引用 qty_X → qty_A。')
                    else:
                        result['structured_ir']['objective']['expression']['terms'][0]['variable_id'] = 'qty_X'
                if revised:
                    result['representation']['constraints'].append({'id': 'limit_A',
                        'expression_text': 'qty[A] <= 2', 'requirement_ids': revised})
                    result['structured_ir']['constraints'].append({'id': 'limit_A', 'expression': {
                        'constant': 0, 'terms': [{'variable_id': 'qty_A', 'coefficient': 1}]},
                        'sense': 'le', 'rhs': 2, 'requirement_ids': revised})
            raw = json.dumps({'choices': [{'message': {'content': json.dumps(result)}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 100, 'completion_tokens': 100, 'total_tokens': 200}}).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args: object) -> None:
            pass

    provider = ThreadingHTTPServer(('127.0.0.1', args.provider_port), Provider)
    threading.Thread(target=provider.serve_forever, daemon=True).start()
    os.environ.update(LLM4OM_LLM_BASE_URL=f'http://127.0.0.1:{provider.server_port}/v1',
        LLM4OM_LLM_MODEL='synthetic-web-guidance', LLM4OM_LLM_API_KEY='synthetic-guidance-key',
        LLM4OM_UI_GUIDANCE_TEST_KEY='synthetic-guidance-key')
    (workspace / '.env').write_text('LLM4OM_LLM_API_KEY=synthetic-guidance-key\n')
    os.chdir(workspace)
    try:
        serve_web(workspace / 'jobs', host='127.0.0.1', port=args.port)
    finally:
        provider.shutdown()
        provider.server_close()


if __name__ == '__main__':
    main()
