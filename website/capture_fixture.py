"""Scripted modeling replies for website captures; the real workbench and solver run normally."""

import importlib.util
import json
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

source = Path(__file__).resolve().parents[1] / "frontend/e2e/mock_llm.py"
spec = importlib.util.spec_from_file_location("workbench_fixture", source)
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
original_reply = fixture.reply


def reply(messages: list[dict], tools: list[dict]) -> str | dict:
    system = messages[0]["content"]
    if "Explain a computed optimization solution" in system:
        english = "in English" in system
        facts = json.loads(messages[-1]["content"])
        return json.dumps({
            "summary": "Produce the quantities below to maximize profit within the available resources." if english else "在现有切割与加工资源内，按下列数量安排生产，使总利润最大。",
            "objective_label": "Total profit" if english else "总利润", "objective_unit": "CNY" if english else "元",
            "decisions": [{"variable": name, "label": f"Product {name[2:-1]}" if english else f"产品 {name[2:-1]} 的生产数量", "unit": "units" if english else "件"}
                          for name in facts["variables"]],
            "notes": ["Production quantities are nonnegative integers." if english else "两种产品的产量均为非负整数。"],
        }, ensure_ascii=False)
    if "Revise an optimization problem" in system:
        request = json.loads(messages[-1]["content"])
        return request["original_problem"] + "\n" + request["change_request"]
    if "Explain an infeasible optimization model" in system:
        return original_reply(messages, tools)
    text = json.dumps(messages, ensure_ascii=False)
    if "Explain" not in system:
        code = fixture.FEASIBLE
        minimum = 4 if "at least 4" in text or "至少生产 4" in text else 3 if "at least 3" in text or "至少生产 3" in text else 0
        if minimum:
            code = code.replace("    return m", f'    m.minimum_b = pyo.Constraint(expr=m.x["B"] >= {minimum})\n    return m')
        formulation = fixture.FORMULATION + (f" $x_B \\ge {minimum}$." if minimum else "")
        return f"### Formulation\n{formulation}\n\n```python\n{code}```"
    return original_reply(messages, tools)


fixture.reply = reply
if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), fixture.Handler).serve_forever()
