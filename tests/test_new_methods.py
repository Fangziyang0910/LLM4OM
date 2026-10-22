"""New method control flow, real solving, and the data/prompt boundary."""

import json
from typing import Any

import pytest

from llm4om.methods.bind.schema import describe_data
from llm4om.methods.optimind.prompts import hint_bank
from tests.conftest import FORMULATION, PRODUCTION_CODE, TWO_PART_REPLY
from tests.test_sandbox import has_gurobi


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


@pytest.mark.parametrize("classes", [[], ["TravelingSalesman"]])
def test_optimind_selects_published_hints_and_reviews_successful_solves(run_method: Any, classes: list) -> None:
    turns = 0

    def script(role, messages, tools):
        nonlocal turns
        if role == "optimind_classify":
            assert "TravelingSalesman" in messages[0].text
            return json.dumps(classes)
        turns += 1
        assert ("Error analysis #0" in messages[1].text) == bool(classes)
        if turns == 1:
            return TWO_PART_REPLY
        assert "Status: optimal" in messages[-1].text and "Objective value: 13" in messages[-1].text
        return "#### The final model correctly solves the problem."

    result = run_method("optimind", script)
    assert not result["failure"] and result["solve"]["objective"] == 13
    assert result["code"] == PRODUCTION_CODE and result["usage"]["solves"] == 1
    assert result["usage"]["llm_calls"] == 3 and turns == 2
    assert list(hint_bank()) == ["TravelingSalesman"]


def test_optimind_does_not_finish_without_a_model(run_method: Any, preset: Any) -> None:
    preset("OPTIMIND", max_turns=2)
    result = run_method("optimind", lambda role, *_: "[]" if role == "optimind_classify" else "#### 13")
    assert result["failure"] and not result["code"]
    assert result["usage"]["llm_calls"] == 3 and result["usage"]["solves"] == 0


def test_optimind_does_not_accept_a_code_free_answer_after_execution_error(run_method: Any, preset: Any) -> None:
    preset("OPTIMIND", max_turns=2)
    calls = 0

    def script(role, *_):
        nonlocal calls
        if role == "optimind_classify":
            return "[]"
        calls += 1
        return TWO_PART_REPLY.replace("return m", "raise ValueError('bad')") if calls == 1 else "#### correct"

    result = run_method("optimind", script)
    assert result["failure"] and result["solve"]["error"] and result["usage"]["solves"] == 1


SETUP = 'x = model.addVars(["A", "B"], vtype=GRB.INTEGER, lb=0, name="x")'
PIECES = {
    "setup": SETUP,
    "objective": {"formulation": r"$\max 3x_A+2x_B$", "code": 'model.setObjective(3*x["A"]+2*x["B"], GRB.MAXIMIZE)'},
    "constraints": [
        {"formulation": r"$2x_A+x_B\le8$", "code": 'model.addConstr(2*x["A"]+x["B"]<=8, name="cutting")'},
        {"formulation": r"$x_A+2x_B\le8$", "code": 'model.addConstr(x["A"]+2*x["B"]<=8, name="machining")'},
    ],
}


def sac_reply(role: str) -> dict:
    if role.startswith("sac_check_"):
        return {"score": 5, "reason": "Required by the problem."}
    return {"sac_parameters": {"items": ["Profits (3,2); capacities (8,8)"]},
            "sac_variables": {"items": ["x[A], x[B] nonnegative integer quantities"]},
            "sac_objective": {"text": "Maximize 3 x[A] + 2 x[B]"},
            "sac_constraints": {"items": ["Cutting 2 A + B <= 8", "Machining A + 2 B <= 8"]},
            "sac_generate": PIECES}[role]


@pytest.mark.skipif(not has_gurobi, reason="SAC-Opt uses gurobipy")
def test_sac_opt_repairs_only_mismatched_constraints_and_freezes_accepted_ones(run_method: Any) -> None:
    comparisons = 0

    def script(role, messages, tools):
        nonlocal comparisons
        if role == "sac_generate":
            wrong = json.loads(json.dumps(PIECES))
            wrong["setup"] = "```python\n" + wrong["setup"] + "\n```"
            wrong["constraints"][0]["code"] = "```python\n" + wrong["constraints"][0]["code"] + "\n```"
            wrong["constraints"][1]["code"] = wrong["constraints"][1]["code"].replace("<=8", "<=80")
            return json.dumps(wrong)
        if role == "sac_backtranslate":
            payload = json.loads(messages[-1].text)
            assert "constraints" not in payload and "problem" not in payload
            assert len(payload["code"]) == (2 if comparisons == 0 else 1)
            return json.dumps({"items": ["cutting <= 8", "machining <= 80"] if comparisons == 0 else ["machining <= 8"]})
        if role == "sac_compare":
            comparisons += 1
            return json.dumps({"items": [{"equivalent": True, "reason": "matches"},
                                         {"equivalent": False, "reason": "capacity 80 instead of 8"}] if comparisons == 1
                              else [{"equivalent": True, "reason": "matches"}]})
        if role == "sac_repair":
            payload = json.loads(messages[-1].text)
            assert len(payload["constraints"]) == 1 and "Machining" in payload["constraints"][0]["anchor"]
            return json.dumps({"constraints": [PIECES["constraints"][1]]})
        return json.dumps(sac_reply(role))

    result = run_method("sac_opt", script, language="gurobipy")
    assert not result["failure"] and result["solve"]["objective"] == 13 and comparisons == 2
    assert PIECES["constraints"][0]["code"] in result["code"]
    nodes = {step.get("node") for step in result["steps"]}
    assert {"backtranslate", "compare", "repair", "assemble"} <= nodes


@pytest.mark.skipif(not has_gurobi, reason="SAC-Opt uses gurobipy")
def test_sac_opt_does_not_claim_semantic_success_when_checks_exhausted(run_method: Any, preset: Any) -> None:
    preset("SAC_OPT", max_semantic_rounds=1)

    def script(role, *_):
        if role == "sac_backtranslate":
            return '{"items":["wrong", "wrong"]}'
        if role == "sac_compare":
            return json.dumps({"items": [{"equivalent": False, "reason": "mismatch"}] * 2})
        return json.dumps(sac_reply(role))

    result = run_method("sac_opt", script, language="gurobipy")
    assert "unresolved" in result["failure"] and result["solve"]["objective"] == 13
    assert result["usage"]["solves"] == 1


def test_sac_opt_rejects_missing_components_and_bounds_json_retries(run_method: Any, preset: Any) -> None:
    preset("SAC_OPT", max_parse_attempts=2)
    result = run_method("sac_opt", lambda *_: "invalid json", language="gurobipy")
    assert result["failure"] and result["usage"]["llm_calls"] == 2 and result["usage"]["solves"] == 0

    def script(role, *_):
        return json.dumps({**PIECES, "constraints": []} if role == "sac_generate" else sac_reply(role))

    result = run_method("sac_opt", script, language="gurobipy")
    assert "every constraint" in result["failure"] and result["usage"]["solves"] == 0


@pytest.mark.skipif(not has_gurobi, reason="SAC-Opt uses gurobipy")
def test_sac_opt_revises_uncertain_constraint_and_executes_debugged_code(run_method: Any) -> None:
    from tests.test_sandbox import GUROBIPY_CODE

    def script(role, messages, tools):
        if role == "sac_check_constraints":
            return '{"score": 3, "reason": "Check the capacity."}'
        if role == "sac_revise_constraint":
            return json.dumps({"items": [json.loads(messages[-1].text)["constraint"]]})
        if role == "sac_generate":
            assert json.loads(messages[-1].text)["data_files"] == []
            assert "not parameter names" in messages[0].text
            return json.dumps({**PIECES, "setup": "raise ValueError('broken setup')"})
        if role == "sac_backtranslate":
            return '{"items":["cutting", "machining"]}'
        if role == "sac_compare":
            return json.dumps({"items": [{"equivalent": True, "reason": "match"}] * 2})
        if role == "sac_debug":
            assert "broken setup" in messages[-1].text
            return f"{FORMULATION}\n```python\n{GUROBIPY_CODE}```"
        return json.dumps(sac_reply(role))

    result = run_method("sac_opt", script, language="gurobipy")
    assert not result["failure"] and result["solve"]["objective"] == 13
    assert result["usage"]["solves"] == 2 and result["code"] == GUROBIPY_CODE
