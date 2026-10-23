"""A scripted OpenAI-compatible chat endpoint for the browser tests: no key, no network, the same reply every time.

Generation requests get a formulation and pyomo code; model reviews accept the result. A problem that mentions a contract
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
CP_SAT = '''from ortools.sat.python import cp_model
def build_model(data):
    m = cp_model.CpModel()
    a, b = m.new_int_var(0,8,'A'), m.new_int_var(0,8,'B')
    m.add(2*a+b<=8)
    m.add(a+2*b<=8)
    m.maximize(3*a+2*b)
    return m
'''
CVXPY = '''import cvxpy as cp
import numpy as np
def build_model(data):
    x = cp.Variable(2, name='x')
    return cp.Problem(cp.Minimize(cp.sum_squares(x-np.array([1,2]))), [x>=0,cp.sum(x)<=2])
'''


def reply(messages: list[dict]) -> str:
    text = json.dumps(messages, ensure_ascii=False)
    if "Explain an infeasible optimization model" in text:
        facts = json.loads(messages[-1]["content"])
        return json.dumps({"summary": "合同要求的最低交货量超过了切割资源能支持的数量。",
                           "conflicts": [{"constraint_ids": list(map(int, facts["constraints"])),
                                          "explanation": "两种产品各至少生产 5 件，需要 15 单位切割资源，但现有容量只有 8 单位。"}],
                           "adjustments": [{"title": "增加切割资源", "instruction": "将切割资源提高至 15 单位，其他条件保持不变。"}]}, ensure_ascii=False)
    if "Explain a computed optimization solution" in text:
        facts = json.loads(messages[-1]["content"])
        return json.dumps({"summary": "按表中数量安排生产，满足题面要求。", "objective_label": "总利润", "objective_unit": "元",
                           "decisions": [{"variable": name, "label": f"{name} 的生产数量", "unit": "件"}
                                         for name in facts["variables"]], "notes": ["数量采用非负整数。"]}, ensure_ascii=False)
    if "Revise an optimization problem according to the user's change request" in text:
        request = json.loads(messages[-1]["content"])
        if request["change_request"] == "将切割资源提高至 15 单位，其他条件保持不变。":
            return request["original_problem"].replace("切割资源共 8 单位", "切割资源共 15 单位")
        return request["original_problem"] + "\n\n" + request["change_request"]
    if "Review an optimization formulation and its code" in text:
        return json.dumps({"action": "accept", "reason": "The model matches the test problem."})
    if "E2E_PAUSE_REPAIR" in text:
        if "## Solver feedback" in text:
            time.sleep(30)
        return f"### Formulation\n{FORMULATION}\n\n```python\n{FEASIBLE.replace('return m', 'return m.missing')}```"
    if 'cp_model.CpModel' in text:
        return f"### Formulation\n{FORMULATION}\n\n```python\n{CP_SAT}```"
    if 'import cvxpy as cp' in text:
        return f"### Formulation\nMinimize squared distance to (1,2), with nonnegative x and sum(x)<=2.\n\n```python\n{CVXPY}```"
    code = INFEASIBLE if "合同" in text else FEASIBLE
    if "切割资源共 15 单位" in text:
        code = code.replace("<= 8", "<= 15")
    if "B 至少生产 3 件" in text:
        code = code.replace("    return m", '    m.minimum_b = pyo.Constraint(expr=m.x["B"] >= 3)\n    return m')
    return f"### Formulation\n{FORMULATION}\n\n```python\n{code}```"


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
