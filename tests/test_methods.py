"""Every method runs end to end with scripted LLM replies and real local solving."""

import asyncio
import json
import subprocess
import sys
import time
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from llm4om.graph import run
from llm4om.languages import LANGUAGES, CodeTarget
from llm4om.llm import LLMSettings
from llm4om.model_code import ModelCode
from llm4om.runtime import Limits
from tests.conftest import (
    FORMULATION,
    PRODUCTION_CODE,
    PRODUCTION_PROBLEM,
    TWO_PART_REPLY,
    ScriptedChat,
    tool_call,
)

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


CP_SAT_REPLY = """### Formulation
$$\\max 3x_A + 2x_B$$

```python
from ortools.sat.python import cp_model

def build_model(data):
    m = cp_model.CpModel()
    x = [m.new_int_var(0, 10, f"x[{i}]") for i in range(2)]
    m.add(2 * x[0] + x[1] <= 8)
    m.add(x[0] + 2 * x[1] <= 8)
    m.maximize(3 * x[0] + 2 * x[1])
    return m
```"""


def test_direct_writes_ortools_cp_sat(run_method: Any) -> None:
    prompts: list[str] = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        prompts.append(messages[0].text)
        return CP_SAT_REPLY

    record = run_method("direct", script, language="ortools")
    assert not record.get("failure"), record.get("failure")
    assert record["solve"]["objective"] == 13
    assert "OR-Tools" in prompts[0] and "CpModel" in prompts[0]


def test_builtin_methods_do_not_restrict_modeling_libraries() -> None:
    from llm4om.methods import methods

    assert len(methods()) == 9
    assert all(method.languages is None for method in methods().values() if not method.builtin_solver)
    assert methods()["autoco"].builtin_solver and methods()["autoco"].languages == frozenset()
    assert {method.id for method in methods().values() if method.linear_only} == {
        "optimus", "coe", "optitree", "or_llm_agent",
    }


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
    assert "self-correction" in record["failure"] and "12 re-solves" in record["failure"]


def test_mathematical_presentation_keeps_method_protocol_and_solving(run_method: Any) -> None:
    formulation = ("## Sets:\n$P=\\{A,B\\}$\n\n## Parameters:\n$p_A=3, p_B=2$\n\n"
                   "## Variables:\n$x_A,x_B\\in\\mathbb{Z}_{\\ge0}$\n\n## Objective:\n$$\\max 3x_A+2x_B$$\n\n"
                   "## Constraints:\n$2x_A+x_B\\le8$, $x_A+2x_B\\le8$.")
    calls: list[str] = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        calls.append(role)
        if role == "five_element":
            prompt = messages[-1].text
            assert "Markdown lists" in prompt and "$...$" in prompt and "$$...$$" in prompt
            assert "continuous, integer or binary" in prompt
            assert all(section in prompt for section in ("## Sets", "## Parameters", "## Variables", "## Objective", "## Constraints"))
            return f"```text\n{formulation}\n```"
        return CODE_BLOCK if role == "code" else JUDGED.format(five="True", code="True")

    record = run_method("llmopt", script)
    assert_solved(record)
    assert record["formulation"] == formulation
    assert calls == ["five_element", "code", "self_correction"]
    assert record["usage"]["solves"] == 1


@pytest.mark.parametrize("language", LANGUAGES)
def test_domain_contract_preserves_required_domains_and_constraint_senses(language: str) -> None:
    prompt = CodeTarget(language).prompt
    assert "Do not relax integer or binary domains" in prompt
    assert "equalities with inequalities" in prompt
    assert "incompatibility" in prompt


@pytest.mark.parametrize("locale,output_language", [("zh", "Simplified Chinese"), ("en", "English")])
def test_method_output_locale_survives_code_repair(make_resources: Any, locale: str, output_language: str) -> None:
    formulation = ("## Sets:\n$P=\\{A,B\\}$\n\n## Parameters:\n$p_A=3, p_B=2$\n\n"
                   "## Variables:\n$x_A,x_B\\in\\mathbb{Z}_{\\ge0}$\n\n## Objective:\n$$\\max 3x_A+2x_B$$\n\n"
                   "## Constraints:\n$2x_A+x_B\\le8$, $x_A+2x_B\\le8$.")
    calls: list[str] = []

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        prompt = messages[-1].text
        assert f"Write explanatory prose in {output_language}" in prompt
        assert "Do not translate required section headings" in prompt
        calls.append(role)
        if role == "five_element":
            assert "## Sets" in prompt and "## Constraints" in prompt
            return f"```text\n{formulation}\n```"
        if role == "code":
            return f"```python\n{BROKEN_CODE if calls.count('code') == 1 else PRODUCTION_CODE}```"
        assert role == "self_correction"
        return JUDGED.format(five="True", code="False" if calls.count(role) == 1 else "True")

    record = asyncio.run(run(PRODUCTION_PROBLEM,
                             method="llmopt", resources=make_resources(script), locale=locale))
    assert_solved(record)
    assert record["spec"]["locale"] == locale
    assert record["formulation"] == formulation
    assert record["usage"]["solves"] == 2
    assert calls == ["five_element", "code", "self_correction", "code", "self_correction"]


OPTIMUS_PARAMS = {"Profit": {"shape": "[2]", "definition": "profit per unit", "type": "float", "value": [3, 2]},
                  "Capacity": {"shape": "[]", "definition": "units of each resource", "type": "float", "value": 8}}
OPTIMUS_CODE = {
    language: {"constraints": [code.constraint("2 * x[0] + x[1] <= Capacity"),
                                code.constraint("x[0] + 2 * x[1] <= Capacity")],
               "objective": code.objective("quicksum(Profit[i] * x[i] for i in range(2))", "max")}
    for language in [*LANGUAGES, "pywraplp"] for code in [ModelCode(CodeTarget(language))]
}


def optimus_script(language: str, constraint_codes: list[str] | None = None, prompts: dict[str, str] | None = None) -> Any:
    codes = list(constraint_codes or OPTIMUS_CODE[language]["constraints"])

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        if prompts is not None:
            prompts[role] = messages[-1].text
        if role == "constraint_model":
            new = '{"x": {"shape": "[2]", "type": "integer", "definition": "units", "upper_bound": "Capacity"}}' if '"x"' not in messages[-1].text else "{}"
            return f'{{\n    "FORMULATION": "$a x[0] + b x[1] \\\\leq 8$",\n    "NEW VARIABLES": {new},\n    "AUXILIARY CONSTRAINTS": []\n}}'
        if role == "constraint_code":
            return f"CODE\n=====\n{codes.pop(0)}\n====="
        return {
            "parameters": json.dumps(OPTIMUS_PARAMS),
            "objective": "=====\nOBJECTIVE: Maximize the total profit\n=====",
            "constraints": '["cutting capacity", "machining capacity"]',
            "constraints_redundancy": 'No redundancy.\n["cutting capacity", "machining capacity"]',
            "constraint_check": "It is a constraint. 5 OUT OF 5",
            "objective_model": "=====\n$\\max 3 x[0] + 2 x[1]$\n=====",
            "objective_code": f"CODE\n=====\n{OPTIMUS_CODE[language]['objective']}\n=====",
            "debug": "=====\n" + PRODUCTION_CODE + "\n=====",
        }[role]
    return script


@pytest.mark.parametrize("language,library,add", [("pyomo", "Pyomo", "constraints.add"),
    ("pywraplp", "OR-Tools", "model.Add("), ("cvxpy", "CVXPY", "_constraints.append"),
    ("pyscipopt", "PySCIPOpt", "model.addCons(")])
def test_optimus_assembles_clause_code_for_each_language(run_method: Any, language: str, library: str, add: str) -> None:
    prompts: dict[str, str] = {}
    record = run_method("optimus", optimus_script(language, prompts=prompts), language=language)
    assert not record.get("failure"), (language, record.get("failure"))
    assert record["solve"]["objective"] == 13
    assert "def build_model(data)" in record["code"] and "'Profit': [3, 2]" in record["code"]
    assert "cutting capacity" in record["formulation"]
    assert library in prompts["constraint_code"] and library in prompts["objective_code"]
    assert add in prompts["constraint_code"]


def test_optimus_debugs_non_optimal_results(run_method: Any) -> None:
    record = run_method("optimus", optimus_script("pyomo", [
        "model.constraints.add(2 * x[0] + x[1] <= -Capacity)",
        "model.constraints.add(x[0] + 2 * x[1] <= Capacity)",
    ]), language="pyomo")
    statuses = [e["status"] for e in record["steps"] if e["type"] == "solve"]
    assert statuses[0].startswith("infeasible") and statuses[1:] == ["optimal"]
    assert record["code"].strip() == PRODUCTION_CODE.strip()


def test_optimus_recovers_missing_fences_optional_fields_and_missing_var_type(run_method: Any) -> None:
    from llm4om.methods.optimus.parsing import (
        extract_formulation_from_end,
        extract_objective,
        extract_objective_formulation,
    )

    assert extract_objective("Reasoning...\nOBJECTIVE: Maximize profit") == "Maximize profit"
    assert extract_objective_formulation("Therefore the objective is $$\\max 3x_0 + 2x_1$$") == "$$\\max 3x_0 + 2x_1$$"
    # Unescaped LaTeX backslashes, alternate casing, and omitted optional keys.
    form, new_vars, aux = extract_formulation_from_end(
        '{"formulation": "$2 x_0 + x_1 \\leq 8$", "new_variables": {"x": {"type": "integer"}}}'
    )
    assert form == "$2 x_0 + x_1 \\leq 8$" and new_vars == {"x": {"type": "integer"}} and aux == []

    # Missing required variable type triggers a format retry instead of relaxing to continuous.
    base = optimus_script("pyomo")
    model_calls = 0

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> str:
        nonlocal model_calls
        if role == "objective":
            return "OBJECTIVE: Maximize total profit"  # omitted ===== fences
        if role == "objective_model":
            return "Objective: $\\max 3x[0] + 2x[1]$"  # omitted ===== fences
        if role == "constraint_model":
            model_calls += 1
            if model_calls == 1:
                return '{"FORMULATION": "$2x[0]+x[1] \\leq 8$", "NEW VARIABLES": {"x": {"shape": "[2]"}}}'
            if model_calls == 2:
                assert "missing required field 'type'" in messages[-1].text
                return '{"FORMULATION": "$2x[0]+x[1] \\leq 8$", "NEW VARIABLES": {"x": {"shape": "[2]", "type": "integer"}}}'
            # Re-declaring an existing variable and omitting AUXILIARY CONSTRAINTS must not crash.
            return '{"FORMULATION": "$x[0]+2x[1] \\leq 8$", "NEW VARIABLES": {"x": {"shape": "[2]", "type": "integer"}}}'
        return base(role, messages, tools)

    record = run_method("optimus", script, language="pyomo")
    assert not record.get("failure"), record.get("failure")
    assert record["solve"]["objective"] == 13
    assert all(value == round(value) for value in record["solve"]["variables"].values())
    assert model_calls == 3


def test_optimus_reads_long_fences() -> None:
    from llm4om.methods.optimus.parsing import extract_code_from_end
    reply = "Final code:\n\n=======\nmodel.setObjective(a * x, GRB.MAXIMIZE)\n=======\n"  # seen from DeepSeek
    assert extract_code_from_end(reply) == "model.setObjective(a * x, GRB.MAXIMIZE)"


def test_optimus_takes_the_last_markdown_code_block() -> None:
    from llm4om.methods.optimus.parsing import extract_code_from_end
    reply = ("The expression is:\n\n```python\nquicksum(c[i] * x[i] for i in I)\n```\n\nFinal code:\n\n"
             "```python\nmodel.setObjective(quicksum(c[i] * x[i] for i in I), GRB.MINIMIZE)\n```\n")  # seen from GPT
    assert extract_code_from_end(reply) == "model.setObjective(quicksum(c[i] * x[i] for i in I), GRB.MINIMIZE)"


@pytest.mark.parametrize("fence", ["=====", "```python\n", "```\n"])
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
    assert "ConcreteModel" in prompts["Programming Expert"] and "ConcreteModel" in prompts["reducer"]
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


def trival_script(code_reviews: list[dict[str, Any]], formulation_reviews: list[dict[str, Any]],
                  code: str = PRODUCTION_CODE) -> Any:
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
            return tool_call("write_code", code=code)
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


@pytest.mark.parametrize("stage", ["semantic", "formulation", "code"])
def test_trival_reports_exhausted_validation_even_when_the_code_runs(run_method: Any, preset: Any, stage: str) -> None:
    preset("TRIVAL", max_validations=1)
    feedback = "The model still omits a required restriction."
    base = trival_script([{"code_validation_passed": stage != "code", "code_validation_feedback": feedback}],
        [{"formulation_validation_passed": stage != "formulation", "formulation_validation_feedback": feedback,
          "formulation_revision_action": "partial_revise" if stage == "formulation" else None}])

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> Any:
        if stage == "semantic" and role == "trival.semantic_validator" and not isinstance(messages[-1], ToolMessage):
            return tool_call("SemanticValidationOutput", facts_faithful=False, ambiguities_relevant=True,
                             resolutions_consistent=True, feedback=feedback)
        return base(role, messages, tools)

    record = run_method("trival", script)
    assert record["failure"] and stage in record["failure"] and feedback in record["failure"]
    assert record["solve"]["objective"] == 13 and record["code"].strip() == PRODUCTION_CODE.strip()
    assert record["usage"]["solves"] == 1


def test_trival_uses_tools_even_when_a_model_advertises_native_json_schema(make_resources: Any) -> None:
    script = trival_script([{"code_validation_passed": True, "code_validation_feedback": "faithful"}], [PASS_FORMULATION])
    resources = make_resources(script)
    resources.model_factory = lambda settings, **kwargs: ScriptedChat(script=script, profile={"structured_output": True}, **kwargs)
    record = asyncio.run(run("Production planning", method="trival", resources=resources))
    assert_solved(record)


def test_trival_validator_rejects_conflicting_verdicts_in_one_reply(run_method: Any) -> None:
    from langchain_core.messages import convert_to_openai_messages

    base = trival_script([{"code_validation_passed": True, "code_validation_feedback": "faithful"}], [PASS_FORMULATION])
    attempts = 0

    def script(role: str, messages: list[BaseMessage], tools: list[str]) -> Any:
        nonlocal attempts
        if role == "trival.semantic_validator":
            attempts += 1
            if attempts == 1:
                return AIMessage("", tool_calls=[
                    {"name": "SemanticValidationOutput", "id": "v1", "args": {
                        "facts_faithful": True, "ambiguities_relevant": True, "resolutions_consistent": True}},
                    {"name": "SemanticValidationOutput", "id": "v2", "args": {
                        "facts_faithful": False, "ambiguities_relevant": True, "resolutions_consistent": True, "feedback": "conflict"}},
                ])
            if attempts == 2:
                return AIMessage(
                    content=[
                        {"type": "text", "text": "checking"},
                        {"type": "function_call", "call_id": "v3", "name": "SemanticValidationOutput", "arguments": "{}"},
                        {"type": "function_call", "call_id": "bad_resp_id", "name": "SemanticValidationOutput", "arguments": "{bad"},
                    ],
                    tool_calls=[{"name": "SemanticValidationOutput", "id": "v3", "args": {
                        "facts_faithful": True, "ambiguities_relevant": True, "resolutions_consistent": True}}],
                    invalid_tool_calls=[{"name": "SemanticValidationOutput", "id": None, "args": "{bad", "error": "bad json", "type": "invalid_tool_call"}],
                )
            if attempts == 3:
                from langchain_openai.chat_models.base import (
                    _construct_responses_api_input,
                    _convert_message_to_dict,
                )

                for serialized in (convert_to_openai_messages(messages), [_convert_message_to_dict(m) for m in messages]):
                    assistant_ids = [call["id"] for msg in serialized if msg.get("role") == "assistant" for call in msg.get("tool_calls") or []]
                    tool_ids = [msg["tool_call_id"] for msg in serialized if msg.get("role") == "tool"]
                    assert None not in assistant_ids and "" not in assistant_ids and assistant_ids == tool_ids
                responses_items = _construct_responses_api_input(messages)
                fc_ids = [item["call_id"] for item in responses_items if item.get("type") == "function_call"]
                fco_ids = [item["call_id"] for item in responses_items if item.get("type") == "function_call_output"]
                assert fc_ids == fco_ids == ["v1", "v2", "v3"]
            return tool_call("SemanticValidationOutput", facts_faithful=False if attempts == 3 else True,
                             ambiguities_relevant=True, resolutions_consistent=True, feedback="missing constraint")
        return base(role, messages, tools)

    record = run_method("trival", script)
    assert_solved(record)
    assert attempts == 4


@pytest.mark.parametrize("thinking", [True, False])
def test_trival_preserves_the_model_preset_without_forcing_tool_choice(make_resources: Any, thinking: bool) -> None:
    script = trival_script([{"code_validation_passed": True, "code_validation_feedback": "faithful"}], [PASS_FORMULATION])
    settings = LLMSettings("deepseek", "deepseek-flash", api_key="test-key",
                           extra_body={"thinking": {"type": "enabled" if thinking else "disabled"}})
    seen = []

    class UnforcedChat(ScriptedChat):
        def bind_tools(self, tools: Any, **kwargs: Any) -> ScriptedChat:
            assert kwargs.get("tool_choice") in (None, "auto")
            return super().bind_tools(tools, **kwargs)

    def factory(configured: LLMSettings, **kwargs: Any) -> ScriptedChat:
        seen.append(configured)
        return UnforcedChat(script=script, profile={"structured_output": True}, **kwargs)

    resources = make_resources(script, llm=settings)
    resources.model_factory = factory
    record = asyncio.run(run("Production planning", method="trival", resources=resources))
    assert_solved(record)
    assert len(seen) >= 3
    assert all(configured == settings for configured in seen)


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
