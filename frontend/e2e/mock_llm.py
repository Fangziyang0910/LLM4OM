"""A scripted OpenAI-compatible chat endpoint for the browser tests: no key, no network, the same reply every time.

Every request gets a Direct-style reply (a formulation, then pyomo code). A problem that mentions a contract
(合同) gets a model whose contract bounds conflict with the cutting capacity, so the solver finds it infeasible.
Usage: python e2e/mock_llm.py PORT
"""

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FEASIBLE = '''import pyomo.environ as pyo

def build_model(data):
    m = pyo.ConcreteModel()
    m.P = pyo.Set(initialize=["A", "B"])
    m.x = pyo.Var(m.P, domain=pyo.NonNegativeIntegers)
    m.profit = pyo.Objective(expr=3 * m.x["A"] + 2 * m.x["B"], sense=pyo.maximize)
    m.cutting = pyo.Constraint(expr=2 * m.x["A"] + m.x["B"] <= 8)
    m.machining = pyo.Constraint(expr=m.x["A"] + 2 * m.x["B"] <= 8)
    return m
'''
INFEASIBLE = '''import pyomo.environ as pyo

def build_model(data):
    m = pyo.ConcreteModel()
    m.P = pyo.Set(initialize=["A", "B"])
    m.x = pyo.Var(m.P, domain=pyo.NonNegativeReals)
    m.profit = pyo.Objective(expr=3 * m.x["A"] + 2 * m.x["B"], sense=pyo.maximize)
    m.cutting = pyo.Constraint(expr=2 * m.x["A"] + m.x["B"] <= 8)
    m.contract = pyo.Constraint(m.P, rule=lambda m, p: m.x[p] >= 5)
    return m
'''
FORMULATION = "$$\\max\\ 3x_A + 2x_B$$ subject to $2x_A + x_B \\le 8$, $x_A + 2x_B \\le 8$, $x \\in \\mathbb{Z}_+$."


def reply(messages: list[dict]) -> str:
    text = json.dumps(messages, ensure_ascii=False)
    if "E2E_PAUSE_REPAIR" in text:
        if "## Solver feedback" in text:
            time.sleep(30)
        return f"### Formulation\n{FORMULATION}\n\n```python\n{FEASIBLE.replace('return m', 'return m.missing')}```"
    return f"### Formulation\n{FORMULATION}\n\n```python\n{INFEASIBLE if '合同' in text else FEASIBLE}```"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # the model list, and the readiness check of the test runner
        self.answer(200, {"data": [{"id": "mock-model", "object": "model"}]})

    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["content-length"])))
        content = reply(request["messages"])
        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        chunk = {"id": "mock", "object": "chat.completion.chunk", "created": int(time.time()), "model": request["model"]}
        if not request.get("stream"):
            self.answer(200, {**chunk, "object": "chat.completion", "usage": usage, "choices": [
                {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}]})
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        pieces = [content[i:i + 200] for i in range(0, len(content), 200)]
        for index, piece in enumerate(pieces):
            delta = {"role": "assistant", "content": piece} if index == 0 else {"content": piece}
            self.event({**chunk, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
        self.event({**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
        self.event({**chunk, "choices": [], "usage": usage})
        self.wfile.write(b"data: [DONE]\n\n")

    def event(self, payload: dict) -> None:
        self.wfile.write(f"data: {json.dumps(payload)}\n\n".encode())
        self.wfile.flush()

    def answer(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - the name the base class uses
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
