"""Explanation references are checked against solver evidence, not its prompt-sized subset."""

import asyncio
import json
from copy import deepcopy
from typing import Any

import pytest

from llm4om.followups import explain_result
from llm4om.languages import CodeTarget
from llm4om.runtime import Context, Limits, Recorder
from llm4om.sandbox import Sandbox
from tests.conftest import ScriptedChat


@pytest.mark.parametrize("variables, names, accepted", [
    ({"x[A]": 3, "x[B]": 2, "x[C]": 0}, ["x[A]", "x[B]", "x[C]"], True),
    ({**{f"x[{i}]": 1 for i in range(99)}, "x[99]": 0}, ["x[99]"], True),
    ({**{f"x[{i}]": 1 for i in range(100)}, "x[100]": 0}, ["x[100]"], True),
    ({"x[A]": 0, "x[B]": 0}, ["x[A]", "x[B]"], True),
    ({"x[A]": 3, "x[B]": 2}, ["x[invented]"], False),
    ({"x[A]": 3, "x[B]": 2}, ["x[A]", "x[A]"], False),
], ids=["mixed-zero", "100-variables", "real-zero-outside-prompt", "all-zero", "invented", "duplicate"])
def test_explanation_variable_evidence(variables: dict[str, int], names: list[str], accepted: bool) -> None:
    solve = {"status": "optimal", "objective": sum(variables.values()), "variables": variables}
    original = deepcopy(solve)
    calls = []

    def reply(role: str, messages: Any, tools: Any) -> str:
        calls.append(role)
        facts = json.loads(messages[-1].text)
        assert facts["total_variables"] == len(variables)
        assert len(facts["variables"]) == min(len(variables), 100)
        if len(variables) <= 100:
            assert facts["variables"] == variables
        else:
            assert "x[100]" not in facts["variables"]
        return json.dumps({"summary": "按实际结果安排。", "objective_label": "目标值",
                           "decisions": [{"variable": name, "label": name} for name in names]})

    model = ScriptedChat(script=reply)
    context = Context(Recorder(Limits()), Sandbox("local"), lambda role: model, CodeTarget("pyomo"), {})
    task = explain_result(context, "解释已保存的求解结果。", None, None, solve, "zh")
    if accepted:
        result = asyncio.run(task)
        assert [item["variable"] for item in result["decisions"]] == names
        assert result["total_variables"] == len(variables)
    else:
        with pytest.raises(ValueError, match="actual solution"):
            asyncio.run(task)
    assert len(calls) == 1
    assert solve == original
