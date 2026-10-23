"""Every method runs end to end with scripted LLM replies and real local solving."""

import asyncio
import json
import subprocess
import sys
import time
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from llm4om.graph import run
from llm4om.runtime import Limits
from tests.conftest import ACCEPT_REVIEW, FORMULATION, PRODUCTION_CODE, TWO_PART_REPLY, ScriptedChat, tool_call

BROKEN_CODE = PRODUCTION_CODE.replace("return m", "return m.missing")
CODE_BLOCK = f"```python\n{PRODUCTION_CODE}```"


def assert_solved(record: dict[str, Any]) -> None:
    assert not record.get("failure"), record.get("failure")
    assert record["solve"]["objective"] == 13
    assert record["code"].strip() == PRODUCTION_CODE.strip()
    assert {"llm", "artifact", "solve"} <= {event["type"] for event in record["steps"]}


def by_role(replies: dict[str, Any]) -> Any:
    """Reply by role; a list is consumed one item per call."""
    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> Any:
        reply = replies[role]
        return reply.pop(0) if isinstance(reply, list) else reply
    return script


def test_direct_generates_and_solves(run_method: Any) -> None:
    record = run_method("direct", by_role({"generate": TWO_PART_REPLY}))
    assert_solved(record)
    assert FORMULATION in record["formulation"]
    llm_event = next(event for event in record["steps"] if event["type"] == "llm")
    assert (llm_event["title"], llm_event["output_tokens"]) == ("generate", 5)
    assert record["usage"]["llm_calls"] == record["usage"]["solves"] == 1


@pytest.mark.parametrize("reply", ["A model without code.", CODE_BLOCK, "Formulation\n```python\n\n```"])
def test_direct_reports_incomplete_outputs_without_solving(run_method: Any, reply: str) -> None:
    record = run_method("direct", by_role({"generate": reply}))
    assert record["failure"] and not record.get("solve")
    assert record["usage"]["llm_calls"] == 1 and record["usage"]["solves"] == 0


def test_feedback_repair_uses_the_solver_error(run_method: Any) -> None:
    seen: list[str] = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        seen.append(messages[-1].text)
        if role == "review":
            return ACCEPT_REVIEW
        return TWO_PART_REPLY.replace(PRODUCTION_CODE, BROKEN_CODE) if role == "generate" else TWO_PART_REPLY

    record = run_method("feedback_repair", script)
    assert_solved(record)
    assert "missing" in seen[1]  # the repair prompt carries the execution error
    assert [event["status"] for event in record["steps"] if event["type"] == "solve"] == ["error", "optimal"]


def test_feedback_repair_recovers_a_malformed_reply(run_method: Any) -> None:
    seen = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        seen.append((role, messages[-1].text))
        return {"generate": "The reply was cut off before the code block.", "repair": TWO_PART_REPLY,
                "review": ACCEPT_REVIEW}[role]

    record = run_method("feedback_repair", script)
    assert_solved(record)
    assert "Output format error" in seen[1][1] and "cut off" in seen[1][1]
    assert [role for role, _ in seen] == ["generate", "repair", "review"]
    assert record["usage"]["solves"] == 1


def test_feedback_repair_checks_semantics_even_after_an_optimal_solve(run_method: Any) -> None:
    wrong = TWO_PART_REPLY.replace('3 * m.x["A"]', '6 * m.x["A"]')
    reviews = iter(['{"action":"repair","reason":"The code uses profit 6 for A, but the problem states 3."}', ACCEPT_REVIEW])
    repair_prompts = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        if role == "generate":
            return wrong
        if role == "review":
            return next(reviews)
        repair_prompts.append(messages[-1].text)
        return TWO_PART_REPLY

    record = run_method("feedback_repair", script)
    assert_solved(record)
    assert [step["objective"] for step in record["steps"] if step["type"] == "solve"] == [24, 13]
    assert "profit 6" in repair_prompts[0] and "## Model review" in repair_prompts[0]


def test_feedback_repair_stops_when_output_format_cannot_be_repaired(run_method: Any, preset: Any) -> None:
    preset("FEEDBACK_REPAIR", max_repairs=1)
    record = run_method("feedback_repair", by_role({"generate": "No code.", "repair": "Still no code."}))
    assert "Output format could not be repaired" in record["failure"]
    assert not record["code"] and not record["solve"]
    assert record["usage"]["llm_calls"] == 2 and record["usage"]["solves"] == 0


def test_feedback_repair_accepts_a_faithful_infeasible_model(run_method: Any) -> None:
    infeasible = TWO_PART_REPLY.replace("<= 8)", "<= -8)", 1)
    record = run_method("feedback_repair", by_role({"generate": infeasible, "review": ACCEPT_REVIEW}),
                        problem="Use the same production model, but cutting capacity is -8, so it is infeasible.")
    assert not record["failure"] and record["solve"]["status"] == "infeasible"
    assert record["usage"]["llm_calls"] == 2 and record["usage"]["solves"] == 1
    assert record["code"] in infeasible


@pytest.mark.parametrize("status,objective", [("time_limit", None), ("time_limit", 12), ("unbounded", None), ("feasible", None)])
def test_feedback_repair_does_not_rewrite_for_solver_status_alone(make_resources: Any, status: str, objective: Any) -> None:
    from llm4om.sandbox import Sandbox, SolveResult

    class StatusSandbox(Sandbox):
        async def solve(self, *args: Any, **kwargs: Any) -> SolveResult:
            return SolveResult(status, objective, {"x": 1} if status == "feasible" or objective else {})

    resources = make_resources(by_role({"generate": TWO_PART_REPLY, "review": ACCEPT_REVIEW}))
    resources.sandbox = StatusSandbox("local")
    record = asyncio.run(run("test", method="feedback_repair", resources=resources))
    assert not record["failure"] and record["solve"]["status"] == status
    assert record["usage"]["llm_calls"] == 2 and record["usage"]["solves"] == 1


def test_feedback_repair_keeps_unresolved_review_as_a_failure(run_method: Any, preset: Any) -> None:
    preset("FEEDBACK_REPAIR", max_repairs=1)
    wrong = TWO_PART_REPLY.replace('3 * m.x["A"]', '6 * m.x["A"]')
    record = run_method("feedback_repair", by_role({"generate": wrong, "repair": wrong,
                         "review": '{"action":"repair","reason":"Wrong profit coefficient for A."}'}))
    assert "Wrong profit" in record["failure"]
    assert record["solve"]["objective"] == 24 and record["code"] in wrong
    assert record["usage"]["llm_calls"] == 4 and record["usage"]["solves"] == 2


def test_feedback_repair_keeps_the_last_evaluated_attempt_when_repair_is_malformed(run_method: Any, preset: Any) -> None:
    preset("FEEDBACK_REPAIR", max_repairs=1)
    record = run_method("feedback_repair", by_role({"generate": TWO_PART_REPLY.replace(PRODUCTION_CODE, BROKEN_CODE),
                                                   "repair": "An incomplete response without code."}))
    assert "Output format could not be repaired" in record["failure"]
    assert record["code"].strip() == BROKEN_CODE.strip() and record["solve"]["status"] == "error"
    assert record["usage"]["llm_calls"] == 2 and record["usage"]["solves"] == 1


@pytest.mark.parametrize("reply", ["Not JSON", '{"action":"maybe","reason":"Unknown"}', '{"action":"accept"}'])
def test_feedback_repair_does_not_accept_an_invalid_review(run_method: Any, reply: str) -> None:
    record = run_method("feedback_repair", by_role({"generate": TWO_PART_REPLY, "review": reply}))
    assert "Could not read the model review" in record["failure"]
    assert record["solve"]["objective"] == 13 and record["usage"]["solves"] == 1


def test_feedback_repair_can_read_a_fenced_json_review(run_method: Any) -> None:
    record = run_method("feedback_repair", by_role({"generate": TWO_PART_REPLY,
                                                   "review": f"```json\n{ACCEPT_REVIEW}\n```"}))
    assert_solved(record)


def test_feedback_repair_keeps_solved_artifacts_when_review_call_fails(run_method: Any) -> None:
    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        if role == "review":
            raise RuntimeError("Review provider unavailable")
        return TWO_PART_REPLY

    record = run_method("feedback_repair", script)
    assert "Review provider unavailable" in record["failure"]
    assert record["solve"]["objective"] == 13 and record["code"].strip() == PRODUCTION_CODE.strip()
    assert record["usage"]["solves"] == 1


CPMPY_REPLY = """### Formulation
$$\\max 3x_A + 2x_B$$

```python
import cpmpy as cp

def build_model(data):
    x = cp.intvar(0, 10, shape=2, name="x")
    m = cp.Model(2 * x[0] + x[1] <= 8, x[0] + 2 * x[1] <= 8)
    m.maximize(3 * x[0] + 2 * x[1])
    return m
```"""


def test_direct_writes_cpmpy_for_cp_sat(run_method: Any) -> None:
    prompts: list[str] = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        prompts.append(messages[0].text)
        return CPMPY_REPLY

    record = run_method("direct", script, language="cpmpy")
    assert not record.get("failure"), record.get("failure")
    assert record["solve"]["objective"] == 13
    assert "CPMpy reference" in prompts[0] and "CP-SAT" in prompts[0]


def test_milp_methods_reject_cpmpy(run_method: Any) -> None:
    for method in ("optimus", "coe", "optitree", "or_llm_agent", "autoformulation"):
        record = run_method(method, by_role({}), language="cpmpy")
        assert "does not support cpmpy" in record["failure"] and not record.get("steps")


def test_or_llm_agent_fixes_code_in_the_conversation(run_method: Any) -> None:
    seen: list[list[BaseMessage]] = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        seen.append(messages)
        return {"math_model": FORMULATION, "code": f"```python\n{BROKEN_CODE}```", "debug": CODE_BLOCK}[role]

    record = run_method("or_llm_agent", script)
    assert_solved(record)
    assert "missing" in seen[-1][-1].text  # the fix request carries the execution error
    assert "Gurobi" not in seen[1][-1].text and "build_model" in seen[1][-1].text  # the code request names the contract


def test_or_llm_agent_rechecks_infeasible_models(run_method: Any) -> None:
    infeasible = PRODUCTION_CODE.replace("<= 8)", "<= -8)", 1)
    record = run_method("or_llm_agent", by_role(
        {"math_model": FORMULATION, "code": [f"```python\n{infeasible}```", CODE_BLOCK]}))
    assert_solved(record)
    assert [e["status"] for e in record["steps"] if e["type"] == "solve"] == ["infeasible", "optimal"]


FIVE_ELEMENT = "```text\n## Sets:\nP = {A, B}\n\n## Variables:\nx_p integer\n```"
JUDGED = "```\nThe five-element is {five}.\n\nThe code is {code}.\n\nAnalysis:\n-\n```"


def test_llmopt_returns_to_the_step_its_self_correction_rejects(run_method: Any) -> None:
    seen: dict[str, list[str]] = {}

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        seen.setdefault(role, []).append(messages[-1].text)
        replies = {"five_element": [FIVE_ELEMENT] * 2, "code": [f"```python\n{BROKEN_CODE}```", CODE_BLOCK, CODE_BLOCK],
                   "self_correction": [JUDGED.format(five="True", code="False"), JUDGED.format(five="False", code="True"),
                                       JUDGED.format(five="True", code="True")]}
        return replies[role][len(seen[role]) - 1]

    record = run_method("llmopt", script)
    assert_solved(record)
    assert record["formulation"].startswith("## Sets:")
    assert [len(seen[role]) for role in ("five_element", "code", "self_correction")] == [2, 3, 3]
    assert "five-element" in seen["five_element"][0] and FIVE_ELEMENT[8:30] in seen["code"][0]
    assert "build_model" in seen["code"][0] and "main function" not in seen["code"][0]  # the contract replaces upstream's suffix
    assert "missing" in seen["self_correction"][0]  # the judge reads the execution error
    assert "returns the model without solving it" in seen["self_correction"][0]


def test_llmopt_reads_a_five_element_split_over_several_blocks() -> None:
    from llm4om.methods.llmopt.graph import _five_element

    split = "## Sets:\n```text\nP = {A, B}\n```\n## Parameters:\n```\np = 3\n```\n## Variables:\nx\n## Objective:\nmax\n## Constraints:\nc"
    assert _five_element(split).startswith("## Sets:\nP = {A, B}\n## Parameters:") and "```" not in _five_element(split)
    whole = "## Sets:\nP\n## Parameters:\np\n## Variables:\nx\n## Objective:\nmax\n## Constraints:\nc"
    assert _five_element(f"Model:\n```text\n{whole}\n```\nDone.") == whole  # one block with every section: upstream's case


def test_llmopt_stops_after_twelve_re_solves(run_method: Any) -> None:
    record = run_method("llmopt", by_role({"five_element": FIVE_ELEMENT, "code": CODE_BLOCK,
                                           "self_correction": JUDGED.format(five="True", code="False")}))
    assert [e["status"] for e in record["steps"] if e["type"] == "solve"] == ["optimal"] * 13
    assert record["usage"]["llm_calls"] == 1 + 13 + 12


ORTHOUGHT_REPLY = ("## 1. Solution Path\n<solution_path>\nMaximize profit.\n</solution_path>\n\n## 2. Summary\n"
                   f"```model\n{FORMULATION}\n```\n\n## 3. Code\n```python\n{BROKEN_CODE}```")


def test_orthought_debugs_code_that_does_not_run(run_method: Any) -> None:
    seen: list[str] = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        seen.append(messages[-1].text)
        return ORTHOUGHT_REPLY if role == "model" else f"Fixed the attribute.\n<code>\n{PRODUCTION_CODE}</code>"

    record = run_method("orthought", script)
    assert not record.get("failure") and record["formulation"] == FORMULATION
    assert any("Maximize profit." in step["content"] for step in record["steps"] if step["type"] == "artifact")
    assert "Pyomo" in seen[0] and "Gurobipy" not in seen[0] and "build_model" in seen[0]
    assert "missing" in seen[1] and FORMULATION in seen[1]  # the debug prompt carries the model and the error
    assert [e["status"] for e in record["steps"] if e["type"] == "solve"] == ["error", "optimal"]


GUROBIPY_PARAMS = {"Profit": {"shape": "[2]", "definition": "profit per unit", "type": "float", "value": [3, 2]},
                   "Capacity": {"shape": "[]", "definition": "units of each resource", "type": "float", "value": 8}}
OPTIMUS_CODE = {
    "gurobipy": {"constraints": ["model.addConstr(2 * x[0] + x[1] <= Capacity)", "model.addConstr(x[0] + 2 * x[1] <= Capacity)"],
               "objective": "model.setObjective(quicksum(Profit[i] * x[i] for i in range(2)), GRB.MAXIMIZE)"},
    "pyomo": {"constraints": ["model.constraints.add(2 * x[0] + x[1] <= Capacity)",
                              "model.constraints.add(x[0] + 2 * x[1] <= Capacity)"],
              "objective": "model.objective = Objective(expr=quicksum(Profit[i] * x[i] for i in range(2)), sense=maximize)"},
    "pywraplp": {"constraints": ["model.Add(2 * x[0] + x[1] <= Capacity)", "model.Add(x[0] + 2 * x[1] <= Capacity)"],
                "objective": "model.Maximize(sum(Profit[i] * x[i] for i in range(2)))"},
    "pulp": {"constraints": ["model += 2 * x[0] + x[1] <= Capacity", "model += x[0] + 2 * x[1] <= Capacity"],
             "objective": "model.sense = pulp.LpMaximize\nmodel.setObjective(pulp.lpSum(Profit[i] * x[i] for i in range(2)))"},
}
GUROBIPY_CODE = """from gurobipy import Model, GRB, quicksum

def build_model(data):
    model = Model("fixed")
    x = model.addVars(2, vtype=GRB.INTEGER, name="x")
    model.addConstr(2 * x[0] + x[1] <= 8)
    model.addConstr(x[0] + 2 * x[1] <= 8)
    model.setObjective(3 * x[0] + 2 * x[1], GRB.MAXIMIZE)
    return model"""


def optimus_script(language: str, constraint_codes: list[str] | None = None, prompts: dict[str, str] | None = None) -> Any:
    codes = list(constraint_codes or OPTIMUS_CODE[language]["constraints"])

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        if prompts is not None:
            prompts[role] = messages[-1].text
        if role == "constraint_model":
            new = '{"x": {"shape": "[2]", "type": "integer", "definition": "units"}}' if '"x"' not in messages[-1].text else "{}"
            return f'{{\n    "FORMULATION": "$a x[0] + b x[1] \\\\leq 8$",\n    "NEW VARIABLES": {new},\n    "AUXILIARY CONSTRAINTS": []\n}}'
        if role == "constraint_code":
            return f"CODE\n=====\n{codes.pop(0)}\n====="
        return {
            "parameters": json.dumps(GUROBIPY_PARAMS),
            "objective": "=====\nOBJECTIVE: Maximize the total profit\n=====",
            "constraints": '["cutting capacity", "machining capacity"]',
            "constraints_redundancy": 'No redundancy.\n["cutting capacity", "machining capacity"]',
            "constraint_check": "It is a constraint. 5 OUT OF 5",
            "objective_model": "=====\n$\\max 3 x[0] + 2 x[1]$\n=====",
            "objective_code": f"CODE\n=====\n{OPTIMUS_CODE[language]['objective']}\n=====",
            "debug": "=====\n" + GUROBIPY_CODE + "\n=====",
        }[role]
    return script


@pytest.mark.parametrize("language,library,add", [("pyomo", "Pyomo", "constraints.add"),
    ("gurobipy", "gurobipy", "addConstr"), ("pywraplp", "OR-Tools", "model.Add("), ("pulp", "PuLP", "model +=")])
def test_optimus_assembles_clause_code_for_each_language(run_method: Any, language: str, library: str, add: str) -> None:
    if language == "gurobipy":
        pytest.importorskip("gurobipy")
    prompts: dict[str, str] = {}
    record = run_method("optimus", optimus_script(language, prompts=prompts), language=language)
    assert not record.get("failure"), (language, record.get("failure"))
    assert record["solve"]["objective"] == 13
    assert "def build_model(files)" in record["code"] and "'Profit': [3, 2]" in record["code"]
    assert "cutting capacity" in record["formulation"]
    assert library in prompts["constraint_code"] and library in prompts["objective_code"]
    assert add in prompts["constraint_code"]


def test_optimus_debugs_non_optimal_results(run_method: Any) -> None:
    pytest.importorskip("gurobipy")
    record = run_method("optimus", optimus_script("gurobipy", ["model.addConstr(2 * x[0] + x[1] <= -Capacity)",
                                                       "model.addConstr(x[0] + 2 * x[1] <= Capacity)"]), language="gurobipy")
    statuses = [e["status"] for e in record["steps"] if e["type"] == "solve"]
    assert statuses[0].startswith("infeasible") and statuses[1:] == ["optimal"]
    assert record["code"].strip() == GUROBIPY_CODE.strip()


def test_optimus_reads_long_fences() -> None:
    from llm4om.methods.optimus.parsing import extract_code_from_end
    reply = "Final code:\n\n=======\nmodel.setObjective(a * x, GRB.MAXIMIZE)\n=======\n"  # seen from DeepSeek
    assert extract_code_from_end(reply) == "model.setObjective(a * x, GRB.MAXIMIZE)"


def test_optimus_takes_the_last_markdown_code_block() -> None:
    from llm4om.methods.optimus.parsing import extract_code_from_end
    reply = ("The expression is:\n\n```python\nquicksum(c[i] * x[i] for i in I)\n```\n\nFinal code:\n\n"
             "```python\nmodel.setObjective(quicksum(c[i] * x[i] for i in I), GRB.MINIMIZE)\n```\n")  # seen from GPT
    assert extract_code_from_end(reply) == "model.setObjective(quicksum(c[i] * x[i] for i in I), GRB.MINIMIZE)"


@pytest.mark.parametrize("fence", ["=====", "```python\n"])
def test_optimus_preserves_python_in_code(fence: str) -> None:
    from llm4om.methods.optimus.parsing import extract_code_from_end
    code = 'python_count = 1\nlabel = "python"'
    end = "=====" if fence == "=====" else "```"
    assert extract_code_from_end(fence + code + end) == code


def test_optimus_fences_need_no_newline_but_must_be_complete() -> None:
    from llm4om.methods.optimus.parsing import extract_code_from_end, extract_equal_sign_closed, extract_objective
    assert extract_equal_sign_closed("=====x + y=====") == "x + y"
    assert extract_objective("=====OBJECTIVE: maximize x=====") == "maximize x"
    for incomplete in ("unfenced", "=====x", "```python\nx"):
        with pytest.raises(ValueError):
            extract_code_from_end(incomplete)


COE_REPLIES = {"conductor": ["Modeling Expert", "Programming Expert", "Code Reviewer"],
               "Modeling Expert": FORMULATION, "Programming Expert": CODE_BLOCK, "Code Reviewer": "Looks fine."}


def test_coe_reduces_expert_comments(run_method: Any) -> None:
    prompts: dict[str, str] = {}

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        prompts[role] = messages[-1].text
        return CODE_BLOCK if role == "reducer" else by_role(COE_REPLIES)(role, messages, tools)

    record = run_method("coe", script)
    assert_solved(record)
    assert "def build_model(data):" in prompts["Programming Expert"]  # the starter code
    assert "Modeling Expert: ```" in prompts["reducer"]
    assert not any(role.endswith("(backward)") for role in prompts)  # reflection is off by default


def test_coe_reflection_asks_experts_backwards(run_method: Any, preset: Any) -> None:
    roles: list[str] = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        roles.append(role)
        if role == "reducer":
            return f"```python\n{BROKEN_CODE}```" if roles.count("reducer") == 1 else CODE_BLOCK
        if role.endswith("(backward)"):
            caused = role.startswith("Programming Expert")
            return json.dumps({"is_caused_by_you": caused, "reason": "" if caused else "not me", "refined_result": CODE_BLOCK})
        replies = dict(COE_REPLIES, conductor=["Modeling Expert", "Programming Expert", "Code Reviewer"])
        return replies[role] if role != "conductor" else replies["conductor"][roles.count("conductor") % 3 - 1]

    preset("COE", enable_reflection=True)
    record = run_method("coe", script)
    assert_solved(record)
    assert [r for r in roles if r.endswith("(backward)")] == ["Code Reviewer (backward)", "Programming Expert (backward)"]
    assert roles.count("reducer") == 2


def test_optitree_stops_at_the_root_type(run_method: Any) -> None:
    record = run_method("optitree", by_role({
        "interpreter": json.dumps({"matching_problem_type": "", "belongs_to_problem_types": False}),
        "reasoner": TWO_PART_REPLY}))
    assert_solved(record)


def test_optitree_follows_the_tree_and_inspects_failing_code(run_method: Any) -> None:
    prompts: dict[str, list[str]] = {}

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        prompts.setdefault(role, []).append(messages[-1].text)
        if role == "interpreter":  # root -> Transportation Problem, which then matches none of its subtypes
            return json.dumps({"matching_problem_type": "Transportation Problem", "belongs_to_problem_types": True}) \
                if len(prompts[role]) == 1 else json.dumps({"belongs_to_subtypes": False, "matching_subtype": ""})
        return {"reasoner": f"```python\n{BROKEN_CODE}```", "inspector": CODE_BLOCK}[role]

    record = run_method("optitree", script)
    assert_solved(record)
    assert len(prompts["interpreter"]) == 2 and "Transportation Problem" in prompts["interpreter"][1]
    assert "'problem_type': 'Transportation Problem'" in prompts["reasoner"][0]
    assert "pyomo code" in prompts["reasoner"][0] and "build_model" in prompts["reasoner"][0]
    assert "missing" in prompts["inspector"][0]
    assert [e["status"] for e in record["steps"] if e["type"] == "solve"] == ["error", "optimal"]


AF_PARAMETERS = "formalization_dict['parameters'] = {\n    # profit per unit\n    'profit': [3, 2],\n    'cut': [2, 1],\n" \
                "    'mach': [1, 2],\n    # capacity of each resource\n    'cap': 8\n}"
AF_OBJECTIVES = ["formalization_dict['objective'] = {'max': 'sum(profit[i] * x[i] for i in range(2))'}",
                 "formalization_dict['objective'] = {'max': 'profit[0] * x[0] + profit[1] * x[1]'}"]
AF_INEQUALITIES = ["formalization_dict['inequality_constraints'] = {'cutting': 'sum(cut[i] * x[i] for i in range(2)) <= cap', "
                   "'machining': 'sum(mach[i] * x[i] for i in range(2)) <= cap'}",
                   "formalization_dict['inequality_constraints'] = {'cutting': 'sum(cut[i] * x[i] for i in range(2)) <= cap'}"]


def autoformulation_script(vtype: str, calls: list[tuple[str, str]]) -> Any:
    """Two samples per step: equal parameters, equal variables, equivalent objectives, two different constraint sets."""
    counters: dict[str, int] = {}

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        prompt = messages[-1].text
        calls.append((role, prompt))
        count = counters[role] = counters.get(role, 0) + 1
        if role == "generate.parameters":
            return AF_PARAMETERS
        if role == "generate.decision_variables":
            return ("formalization_dict['decision_variables'] = {'x': {'description': 'units of each product', "
                    f"'type': '{vtype}', 'iteration_space': '[i for i in range(2)]'}}}}")
        if role == "generate.objective":
            return AF_OBJECTIVES[count % 2]
        if role == "generate.equality_constraints":
            return "formalization_dict['equality_constraints'] = {None: None}"
        if role == "generate.inequality_constraints":
            return AF_INEQUALITIES[count % 2]
        if role == "group_decision_variables":
            return "groups = {1: ['decision_variables_0', 'decision_variables_1']}"
        if role == "rank.inequality_constraints":  # the candidate with both constraints first
            first = "inequality_constraints_0" if "machining" in prompt.split("inequality_constraints_1")[0] else "inequality_constraints_1"
            other = "inequality_constraints_1" if first.endswith("0") else "inequality_constraints_0"
            return f"rank = {{1: '{first}', 2: '{other}'}}"
        if role == "compare":  # prefer the formulation with both constraints
            solution_a = prompt.split("solution_A =")[1].split("solution_B =")[0]
            return "best_solution = {1: 'solution_A'}" if "machining" in solution_a else "best_solution = {1: 'solution_B'}"
        raise AssertionError(f"unexpected role {role}")
    return script


def test_autoformulation_searches_the_tree_and_ranks_leaves(run_method: Any, preset: Any) -> None:
    calls: list[tuple[str, str]] = []
    preset("AUTOFORMULATION", n_used_gpt=2, n_top=2, n_reward=1, total_rollouts=2)
    record = run_method("autoformulation", autoformulation_script("pyo.NonNegativeIntegers", calls))
    assert not record.get("failure"), record.get("failure")
    assert record["solve"]["objective"] == 13  # the preferred leaf, not the looser one (objective 16)
    assert "def build_model(data):" in record["code"] and "pyo.Var(pyo.Any" in record["code"]
    roles = [role for role, _ in calls]
    assert roles.count("group_decision_variables") == 8 and roles.count("rank.objective") == 0  # equivalent objectives
    assert roles.count("compare") == 2 * 5  # the second leaf against the first, in both orders
    generate_dv = next(prompt for role, prompt in calls if role == "generate.decision_variables")
    assert "Pyomo variable domain" in generate_dv and "GRB.INTEGER" not in generate_dv
    assert "using Pyomo" in next(prompt for role, prompt in calls if role == "compare")
    objectives = sorted(e["objective"] for e in record["steps"] if e["type"] == "solve")
    assert objectives == [13, 16]
    steps = [e["title"] for e in record["steps"] if e["type"] == "artifact"]
    assert steps.count("扩展建模树") == 5 and steps.count("MCTS rollout") == 2 and "选中的数学模型" in steps


@pytest.mark.parametrize("language,vtype,expected", [("gurobipy", "GRB.INTEGER", "gpy_model.addVar(vtype=GRB.INTEGER"),
    ("pywraplp", "integer", "_new_var('integer'"), ("pulp", "Integer", "_new_var('Integer'")])
def test_autoformulation_writes_each_languages_code(run_method: Any, preset: Any, language: str, vtype: str,
                                                   expected: str) -> None:
    if language == "gurobipy":
        pytest.importorskip("gurobipy")
    calls: list[tuple[str, str]] = []
    preset("AUTOFORMULATION", n_used_gpt=1, n_top=1, n_reward=1, total_rollouts=1)
    record = run_method("autoformulation", autoformulation_script(vtype, calls), language=language)
    assert not record.get("failure"), (language, record.get("failure"))
    assert expected in record["code"]
    assert record["solve"]["objective"] in (13, 16)
    prompt = next(prompt for role, prompt in calls if role == "generate.decision_variables")
    assert ("GRB.INTEGER" in prompt) == (language == "gurobipy") and ("IntVar" in prompt) == (language == "pywraplp")


def trival_script(code_reviews: list[dict[str, Any]], formulation_reviews: list[dict[str, Any]]) -> Any:
    """Scripted TriVAL nodes; validators consume the given review lists in order."""
    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> Any:
        node = role.removeprefix("trival.")
        if isinstance(messages[-1], ToolMessage):
            return "Done."
        if node == "semantic_fact_extractor":
            return tool_call("write_semantic_facts", semantic_facts="- Two products, two resources.") if isinstance(
                messages[-1], HumanMessage) else "Done."
        if node == "semantic_validator":
            return tool_call("SemanticValidationOutput", facts_faithful=True, ambiguities_relevant=True,
                             resolutions_consistent=True)
        if node.endswith("_expert"):
            return f"{FORMULATION} ({node})"
        if node == "formulation_selector":
            return tool_call("select_formulation", expert_name="constraint_expert")
        if node == "formulation_validator":
            return tool_call("FormulationValidationOutput", **formulation_reviews.pop(0))
        if node == "revise_formulation":
            return tool_call("write_formulation", formulation=FORMULATION + " (revised)")
        if node == "code_agent":
            return tool_call("write_code", code=PRODUCTION_CODE)
        if node == "code_validator":
            return tool_call("CodeValidationOutput", **code_reviews.pop(0))
        raise AssertionError(f"unexpected role {role}")
    return script


PASS_FORMULATION = {"formulation_validation_feedback": "ok", "formulation_validation_passed": True}


def test_trival_runs_all_three_validation_stages(run_method: Any) -> None:
    script = trival_script([{"code_validation_passed": True, "code_validation_feedback": "faithful"}], [PASS_FORMULATION])
    record = run_method("trival", script)
    assert_solved(record)
    assert record["formulation"] == f"{FORMULATION} (constraint_expert)"
    titles = [event["title"] for event in record["steps"] if event["type"] == "artifact"]
    for title in ("语义事实与歧义", "语义验证", "候选模型：约束专家", "选择候选模型", "数学模型验证", "代码验证"):
        assert title in titles
    # Each node's update is recorded before the next node's calls: the code comes before its solve.
    order = [(event["type"], event["title"]) for event in record["steps"]]
    assert order.index(("artifact", "生成或修订代码")) < order.index(("solve", "执行代码（第 1 次）"))
    assert order.index(("artifact", "语义事实与歧义")) < order.index(("llm", "trival.semantic_validator"))


def test_trival_routes_formulation_defects_back(run_method: Any) -> None:
    script = trival_script(
        [{"code_validation_passed": False, "code_validation_feedback": "missing logic", "error_attribution": "formulation"},
         {"code_validation_passed": True, "code_validation_feedback": "faithful"}],
        [PASS_FORMULATION, PASS_FORMULATION])
    record = run_method("trival", script)
    assert_solved(record)
    assert record["formulation"].endswith("(revised)")
    roles = [event["title"] for event in record["steps"] if event["type"] == "llm"]
    assert "trival.revise_formulation" in roles


def test_trival_applies_multiple_code_edits_in_order(run_method: Any) -> None:
    base = trival_script([{"code_validation_passed": True, "code_validation_feedback": "ok"}], [PASS_FORMULATION])

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> Any:
        if role == "trival.code_agent" and not isinstance(messages[-1], ToolMessage):
            return AIMessage("", tool_calls=[
                {"name": "write_code", "args": {"code": BROKEN_CODE}, "id": "write"},
                {"name": "edit_code", "args": {"search": "return m.missing", "replace": "return m"}, "id": "edit"},
            ])
        return base(role, messages, tools)

    assert_solved(run_method("trival", script))



def test_optimus_json_preserves_urls_escapes_and_nested_values() -> None:
    # A subprocess bounds the old parser's infinite loop.
    script = r'''
from llm4om.methods.optimus.parsing import extract_json_from_end
text = '{"example": 0}\n```json\n{\n// comment\n"url": "https://example.org", "path": "a\\\\b", "nested": {"brace": "}"}}\n```'
assert extract_json_from_end(text) == {"url": "https://example.org", "path": "a\\b", "nested": {"brace": "}"}}
assert extract_json_from_end('{"url":"https://example.org"}') == {"url": "https://example.org"}
'''
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=3)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("text", ["no JSON", "{", "// comment without a newline"])
def test_optimus_rejects_missing_json(text: str) -> None:
    from llm4om.methods.optimus.parsing import extract_json_from_end

    with pytest.raises(ValueError):
        extract_json_from_end(text)


def test_optimus_extracts_the_last_complete_array() -> None:
    from llm4om.methods.optimus.parsing import extract_json_from_end

    assert extract_json_from_end('Example: [0]. Answer: ["a[b]", [1, 2]]', list) == ["a[b]", [1, 2]]


def test_trival_timeout_stops_the_agent_loop(make_resources: Any) -> None:
    calls = []

    def script(*_: Any) -> AIMessage:
        calls.append(time.monotonic())
        time.sleep(0.06)
        return tool_call("write_semantic_facts", semantic_facts="facts")

    async def check() -> None:
        resources = make_resources(script, Limits(max_llm_calls=8, run_timeout=0.2))
        result = await run("test", method="trival", resources=resources)
        count = len(calls)
        await asyncio.sleep(0.2)
        assert "time limit" in result["failure"] and count > 0
        assert len(calls) == count, "the agent kept starting calls after its run ended"

    asyncio.run(check())


def test_autoformulation_failure_cancels_other_samples(make_resources: Any, preset: Any) -> None:
    preset("AUTOFORMULATION", n_used_gpt=3)
    started, finished, cancelled = [], [], []

    class SamplingChat(ScriptedChat):
        async def _agenerate(self, *args: Any, **kwargs: Any) -> ChatResult:
            index = len(started)
            started.append(index)
            if index == 0:
                await asyncio.sleep(0.01)
                raise RuntimeError("provider failed")
            try:
                await asyncio.sleep(0.1)
            except asyncio.CancelledError:
                cancelled.append(index)
                raise
            finished.append(index)
            return ChatResult(generations=[ChatGeneration(message=AIMessage("unused"))])

    async def check() -> None:
        resources = make_resources(lambda *_: "unused")
        resources.model_factory = lambda settings, **kwargs: SamplingChat(script=None, **kwargs)
        result = await run("test", method="autoformulation", resources=resources)
        await asyncio.sleep(0.15)
        assert "provider failed" in result["failure"]
        assert started == [0, 1, 2] and sorted(cancelled) == [1, 2] and not finished

    asyncio.run(check())


@pytest.mark.parametrize('value', ['a}b', 'a{b', 'escaped\\"quote', {'nested': '{value}'}])
def test_autoformulation_dictionary_values_keep_braces_and_quotes(value: Any) -> None:
    from llm4om.methods.autoformulation.upstream.utils_prompt import extract_dict_from_string

    expected = {'label': value}
    _, parsed = extract_dict_from_string(f"formalization_dict['parameters'] = {expected!r}", 'parameters')
    assert parsed == expected


@pytest.mark.parametrize("value", ['a"b', "a'b", "line 1\nline 2\\tail"])
def test_autoformulation_generated_literals_preserve_parameter_text(value: str) -> None:
    import ast

    from llm4om.methods.autoformulation.search import parse_dict_with_comments
    from llm4om.methods.autoformulation.upstream.utils_general import get_param_code_str

    assignment = ast.parse(get_param_code_str({"parameters": {"label": value}})).body[0]
    assert isinstance(assignment, ast.Assign) and ast.literal_eval(assignment.value) == value
    assert ast.literal_eval(parse_dict_with_comments({"label": value}, [""])) == {"label": value}
