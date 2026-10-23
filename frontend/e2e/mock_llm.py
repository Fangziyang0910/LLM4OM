"""A scripted OpenAI-compatible chat endpoint for the browser tests: no key, no network, the same reply every time.

Generation requests get a formulation and pyomo code; model reviews accept the result. A problem that mentions a contract
(合同) gets a model whose contract bounds conflict with the cutting capacity, so the solver finds it infeasible.
Usage: python e2e/mock_llm.py PORT
"""

import json
import sys
import time
import uuid
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
REQUIREMENTS = ("工厂生产 A、B 两种产品，数量必须是非负整数。每件 A 利润为 3，每件 B 利润为 2。"
                "A 消耗 2 单位切割资源和 1 单位加工资源，B 消耗 1 单位切割资源和 2 单位加工资源。"
                "两种资源各有 8 单位。请确定生产数量，使总利润最大。")
CHAT_FAILURES: set[str] = set()


def reply(messages: list[dict], tools: list[dict]) -> str | dict:
    text = json.dumps(messages, ensure_ascii=False)
    if "Discuss an optimization plan with an ordinary user" in text:
        latest = next(message["content"] for message in reversed(messages) if message["role"] == "user")
        snapshot = json.loads(messages[0]["content"].split("Current frozen plan:\n", 1)[1])
        if snapshot.get("already_computed_scenarios"):
            return "已完成的实际目标值是 12，没有重复计算。"
        if messages[-1]["role"] == "tool":
            facts = json.loads(messages[-1]["content"])
            if isinstance(facts, list):
                if "E2E_SOLUTION_REPLY_RETRY" in latest and latest not in CHAT_FAILURES:
                    CHAT_FAILURES.add(latest)
                    return ""
                return "已实际重新建模求解：" + "；".join(f"{item['name']}，目标值 {item['objective']}" for item in facts)
            return "实际决策值：" + "，".join(f"{name} = {value}" for name, value in facts["variables"].items())
        if "E2E_SOLUTION_BATCH" in latest:
            name, args = "solve_scenarios", {"scenarios": [{"name": "B 至少 3 件", "instruction": "B 至少生产 3 件"},
                                                         {"name": "B 至少 4 件", "instruction": "B 至少生产 4 件"}]}
        elif "B 至少生产 3 件" in latest or "B 至少生产 4 件" in latest:
            number = 4 if "B 至少生产 4 件" in latest else 3
            name, args = "solve_scenarios", {"scenarios": [{"name": f"B 至少 {number} 件", "instruction": f"B 至少生产 {number} 件"}]}
        else:
            name, args = "lookup_variables", {"query": ""}
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "call_" + uuid.uuid4().hex[:8], "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}
    if "Help an ordinary user turn an idea into a business problem" in text:
        latest = next(message["content"] for message in reversed(messages) if message["role"] == "user")
        if "E2E_PAUSE_CHAT" in latest and messages[-1]["role"] == "user":
            time.sleep(3)
        if "E2E_CHAT_RETRY" in latest and latest not in CHAT_FAILURES:
            CHAT_FAILURES.add(latest)
            return ""
        complete = "各有 8" in latest or "E2E_CHAT_RETRY" in latest
        if "E2E_LOOP_DRAFT" in latest:
            if not any(tool.get("function", {}).get("name") == "update_draft" for tool in tools):
                return "已按周整理成本要求。联网搜索未开启，请开启后再查询实时价格。"
            return {"role": "assistant", "content": "", "tool_calls": [{"id": "call_" + uuid.uuid4().hex[:8], "type": "function",
                    "function": {"name": "update_draft", "arguments": json.dumps({"description": "按周计算成本。价格和来源待确认。"}, ensure_ascii=False)}}]}
        if messages[-1]["role"] == "tool" and messages[-1]["content"] == "The business draft was updated.":
            if "E2E_STREAM" in latest:
                return "这是逐字显示的回复。我们可以先确定生产目标，再补充实际资源和数量。流式回复已经完整输出。"
            if "E2E_SEARCH" in latest:
                return "查到一份[排班参考](https://example.org/shift-guide)。请确认是否把这些建议用于你的门店。"
            return "可以检查需求稿并用于建模。" if complete else "每件产品的利润和资源消耗是多少？两种资源各有多少容量？"
        name = "web_search" if "E2E_SEARCH" in latest and messages[-1]["role"] == "user" else "update_draft"
        description = REQUIREMENTS if complete else "工厂安排 A、B 两种产品的生产。希望总利润最大。\n\n待确认：每件利润、资源消耗和资源容量。"
        if "costs.csv" in text:
            description += "\n\n附数据文件 costs.csv。"
        args = {"query": "门店排班 公开参考"} if name == "web_search" else {"description": description}
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "call_" + uuid.uuid4().hex[:8], "type": "function",
                "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)}}]}
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
    if "B 至少生产 4 件" in text:
        code = code.replace('>= 3)', '>= 4)') if 'm.minimum_b' in code else code.replace("    return m", '    m.minimum_b = pyo.Constraint(expr=m.x["B"] >= 4)\n    return m')
    if "A,5" in text:
        code = code.replace('3 * m.x["A"]', '5 * m.x["A"]')
    return f"### Formulation\n{FORMULATION}\n\n```python\n{code}```"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # the model list, and the readiness check of the test runner
        self.answer(200, {"data": [{"id": "mock-model", "object": "model"}]})

    def do_POST(self) -> None:
        request = json.loads(self.rfile.read(int(self.headers["content-length"])))
        if self.path == "/v1/tools/search":
            self.answer(200, {"results": [{"title": "排班参考", "url": "https://example.org/shift-guide",
                                         "snippet": "可以参考的排班建议，仍需用户确认。", "date": "2026-10-20"}]})
            return
        content = reply(request["messages"], request.get("tools", []))
        message = content if isinstance(content, dict) else {"role": "assistant", "content": content}
        finish = "tool_calls" if message.get("tool_calls") else "stop"
        usage = {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}
        chunk = {"id": "mock", "object": "chat.completion.chunk", "created": int(time.time()), "model": request["model"]}
        if not request.get("stream"):
            self.answer(200, {**chunk, "object": "chat.completion", "usage": usage, "choices": [
                {"index": 0, "finish_reason": finish, "message": message}]})
            return
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        try:
            if message.get("tool_calls"):
                self.event({**chunk, "choices": [{"index": 0, "delta": {"role": "assistant", "tool_calls": [
                    {"index": i, **call} for i, call in enumerate(message["tool_calls"])]}, "finish_reason": None}]})
            else:
                slow = "这是逐字显示的回复。" in content
                size = 10 if slow else 200
                pieces = [content[i:i + size] for i in range(0, len(content), size)]
                for index, piece in enumerate(pieces):
                    delta = {"role": "assistant", "content": piece} if index == 0 else {"content": piece}
                    self.event({**chunk, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]})
                    if slow:
                        time.sleep(0.5)
            self.event({**chunk, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]})
            self.event({**chunk, "choices": [], "usage": usage})
            self.wfile.write(b"data: [DONE]\n\n")
        except (BrokenPipeError, ConnectionResetError):
            pass  # The browser deliberately disconnects in the cancellation test.

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
