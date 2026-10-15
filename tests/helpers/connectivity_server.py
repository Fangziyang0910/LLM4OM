"""Disposable Web/metadata fixture; rejects text generation."""

import argparse
import json
import os
from pathlib import Path
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from llm4om.web import serve_web


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, required=True)
    args = parser.parse_args()
    counts = {'metadata_gets': 0, 'generation_posts': 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == '/requests':
                value = counts
            else:
                counts['metadata_gets'] += 1
                value = {'data': [{'id': 'fixture-model', 'name': 'Fixture Model v2'},
                    {'id': 'alternate-model', 'display_name': 'Alternate Model'}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_POST(self):
            counts['generation_posts'] += 1
            self.send_response(500)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 8797), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ.update(LLM4OM_LLM_BASE_URL='http://127.0.0.1:8797/v1', LLM4OM_LLM_MODEL='fixture-model',
                      LLM4OM_LLM_API_KEY='synthetic-web-connectivity', LLM4OM_LLM_PROXY_URL='')
    try:
        serve_web(args.workspace, port=8796, host='127.0.0.1')
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
