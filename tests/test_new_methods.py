"""BIND control flow, real solving, and the data/prompt boundary."""

import json
from typing import Any

import pytest

from llm4om.methods.bind.schema import describe_data
from tests.conftest import FORMULATION, PRODUCTION_CODE, TWO_PART_REPLY


def test_bind_keeps_large_numeric_data_out_of_prompts_and_reads_it_all(run_method: Any) -> None:
    numbers = [0] * 21000 + [876543]
    code = PRODUCTION_CODE.replace('3 * m.x["A"]', 'max(__import__("json").loads(data["profit.json"])) * m.x["A"]')

    def script(role, messages, tools):
        prompt = "\n".join(m.text for m in messages)
        assert "876543" not in prompt and "truncated" not in prompt
        assert '"length": 21001' in prompt and '"integer"' in prompt
        return f"{FORMULATION}\n```python\n{code}```"

    result = run_method("bind", script, data={"profit.json": json.dumps(numbers)})
    assert not result["failure"] and result["solve"]["objective"] == 4 * 876543


def test_bind_repairs_in_conversation_and_accepts_genuine_infeasibility(run_method: Any) -> None:
    calls = 0

    def script(role, messages, tools):
        nonlocal calls
        calls += 1
        if calls == 1:
            return TWO_PART_REPLY.replace("return m", "raise ValueError('broken')")
        assert "broken" in messages[-1].text and messages[-2].type == "ai"
        return TWO_PART_REPLY.replace("    return m", "    m.impossible = pyo.Constraint(expr=m.x['A'] >= 9)\n    return m")

    result = run_method("bind", script, problem="The production problem also requires A >= 9.")
    assert not result["failure"] and result["solve"]["status"] == "infeasible"
    assert result["usage"]["solves"] == calls == 2


def test_bind_keeps_last_solved_attempt_after_malformed_repair(run_method: Any, preset: Any) -> None:
    preset("BIND", max_rounds=2)
    calls = 0

    def script(*_):
        nonlocal calls
        calls += 1
        return TWO_PART_REPLY.replace("return m", "raise ValueError('broken')") if calls == 1 else "no code"

    result = run_method("bind", script)
    assert result["failure"] and result["solve"]["error"] and "broken" in result["code"]
    assert result["usage"]["solves"] == 1 and calls == 2


def test_bind_describes_ragged_json_and_csv_without_values() -> None:
    described = json.loads(describe_data({"matrix.json": "[[101], [202, 303]]", "table.csv": "name,value\nAlice,567\nBob,678\n"}))
    assert {item["length"] for item in described["matrix.json"]["items"]} == {1, 2}
    assert described["table.csv"]["columns"] == ["name", "value"] and described["table.csv"]["rows"] == 2
    assert "Alice" not in json.dumps(described) and "567" not in json.dumps(described)


@pytest.mark.parametrize("data", [{"a.csv": "x,x\n1,2"}, {"a.csv": "x,y\n1,2,3"}, {"a.json": "{invalid"}])
def test_bind_rejects_unusable_data_before_calling_llm(run_method: Any, data: dict) -> None:
    result = run_method("bind", lambda *_: pytest.fail("Must not call the LLM"), data=data)
    assert result["failure"] and result["usage"]["llm_calls"] == result["usage"]["solves"] == 0
