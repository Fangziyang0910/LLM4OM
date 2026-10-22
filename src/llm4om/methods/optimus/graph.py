"""OptiMUS: the `main.py` pipeline of https://github.com/teshnizi/OptiMUS at e182e9e as a graph, with ERROR_CORRECTION on
and RAG off.

Objective, constraints (with the redundancy check and a confidence check per constraint), constraint formulations,
objective formulation, code for every constraint and the objective, deterministic assembly, then up to three
execute-and-debug rounds. Prompts are verbatim (prompts.py); the parsing helpers are ported line by line (parsing.py).

Adaptations:
- Library. Upstream generates gurobipy code; the code prompts and the assembly take the selected language's dialect
  (dialects.py). The gurobipy dialect is the upstream text.
- Parameters. Upstream reads them with their values from `params.json`. An attached `params.json` in that format is
  used the same way; otherwise the upstream parameter-extraction prompt runs with an added `value` field.
- Assembly. The parameter values are embedded in the code and the assembled statements form `build_model`, which
  returns the model; the platform solves it, so `model.optimize()` and the result printing are left out.
- Interaction. Two upstream checks ask a human through input(): the parameter check is skipped (main.py does not
  run parameter extraction), the constraint check uses its own LLM branch (`ask_LLM = True`) as upstream does.
"""

import json
import re
from dataclasses import asdict
from pprint import pformat
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.languages import MILP_LANGUAGES
from llm4om.methods import Method, presets
from llm4om.methods.optimus import prompts as P
from llm4om.methods.optimus.dialects import DIALECTS
from llm4om.methods.optimus.parsing import (
    extract_code_from_end,
    extract_debugged_code,
    extract_equal_sign_closed,
    extract_formulation_from_end,
    extract_json_from_end,
    extract_objective,
    shape_string_to_list,
)
from llm4om.runtime import Context, ModelingState

PARAMS_PROMPT = P.PARAMETERS__PROMPT_PARAMS.replace(
    '        "type": "TYPE"\n    }}\n}}',
    '        "type": "TYPE",\n        "value": VALUE\n    }}\n}}').replace(
    'and type is one of "int", "float", or "binary".',
    'and type is one of "int", "float", or "binary". VALUE is the known value of the parameter, a number for a '
    'scalar or nested lists with the given shape.').replace(
    '"definition": "The number of items in the inventory",\n        "type": "int"',
    '"definition": "The number of items in the inventory",\n        "type": "int",\n        "value": 3').replace(
    '"definition": "The value of each item in the inventory",\n        "type": "float"',
    '"definition": "The value of each item in the inventory",\n        "type": "float",\n        "value": [2.5, 4.0, 1.5]')



class State(ModelingState, total=False):
    parameters: dict[str, Any]
    _values: dict[str, Any]  # parameter values, kept out of the prompts as upstream data.json is
    objective: dict[str, Any]
    constraints: list[Any]
    variables: dict[str, Any]
    tries: int
    fixed_code: str  # the latest debugged code


async def _ask(context: Context, role: str, prompt: str) -> str:
    """Upstream get_response: one user message."""
    return (await context.llm(role).bind(temperature=presets.OPTIMUS.temperature).ainvoke([HumanMessage(prompt)])).text


def _dump(value: Any) -> str:
    return json.dumps(value, indent=4)


async def parameters(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    if "params.json" in context.data:
        params = json.loads(context.data["params.json"])
    else:
        k = 5
        while True:
            try:
                params = extract_json_from_end(await _ask(context, "parameters", PARAMS_PROMPT.format(description=state["problem"])))
                break
            except Exception:
                k -= 1
                if k == 0:
                    raise Exception("Failed to extract parameters")
        for p in params:
            params[p]["shape"] = shape_string_to_list(params[p]["shape"])
    values = {key: params[key].pop("value", None) for key in params}  # utils.create_state
    return {"parameters": params, "_values": values}


async def objective(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    res = await _ask(runtime.context, "objective", P.OBJECTIVE__PROMPT_OBJECTIVE.format(
        description=state["problem"], params=_dump(state["parameters"]), rag=""))
    return {"objective": {"description": extract_objective(res), "formulation": None, "code": None}}


async def constraints(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """constraint.get_constraints up to the redundancy check (k = 5 tries)."""
    context, desc, params = runtime.context, state["problem"], state["parameters"]
    res = await _ask(context, "constraints", P.CONSTRAINT__PROMPT_CONSTRAINTS.format(description=desc, params=_dump(params), rag=""))
    found = extract_json_from_end(res, list)
    k = 5
    while True:
        try:
            x = await _ask(context, "constraints_redundancy", P.CONSTRAINT__PROMPT_CONSTRAINTS_REDUNDANT.format(
                description=desc, params=_dump(params), constraints=_dump(found)))
            found = extract_json_from_end(x, list)
            break
        except Exception:
            k -= 1
            if k == 0:
                raise Exception("Failed to extract constraints")
    return {"constraints": found}


async def _score_constraint(context: Context, desc: str, text: str, params: dict[str, Any], found: list[Any],
                            c: Any) -> tuple[bool, list[Any] | None]:
    """constraint.extract_score_constraint with ask_LLM = True."""
    match = re.search(r"\d out of 5", text.lower())
    if not match:
        return False, None
    if int(match.group()[0]) > 3:
        return True, found
    response = await _ask(context, "constraint_feedback", P.CONSTRAINT__PROMPT_CONSTRAINT_FEEDBACK.format(
        description=desc, params=_dump(params), vars=_dump({}), extracted_constraints=_dump(found),
        new_constraint=c, new_constraint_explanation=text))
    output_json = extract_json_from_end(response)
    action, updated_constraint = output_json["action"], output_json["updatedConstraint"]
    if action.lower().startswith("y"):
        return True, found
    if action.lower().startswith("n"):
        found.remove(c)
        return True, found
    if action.lower().startswith("m"):
        found.remove(c)
        # Upstream appends {"Description": ..., "Formulation": None, "Code": None}, which the next step wraps again
        # as the description of a constraint; the text is kept instead.
        found.append(updated_constraint)
        return True, found
    raise Exception("Invalid input!")


async def check_constraints(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """constraint.get_constraints: a confidence check of every constraint (k = 5 tries each)."""
    context, desc, params = runtime.context, state["problem"], state["parameters"]
    found = list(state["constraints"])
    for c in found.copy():
        k = 5
        while k > 0:
            x = await _ask(context, "constraint_check", P.CONSTRAINT__PROMPT_CONSTRAINTS_Q.format(
                description=desc, params=_dump(params), targetConstraint=c, question=P.CONSTRAINT__QS_0))
            valid, checked = await _score_constraint(context, desc, x, params, found, c)
            if valid:
                found = checked or []
                break
            k -= 1
    return {"constraints": [{"description": c, "formulation": None, "code": None} for c in found]}


async def formulate_constraints(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """constraint_model.get_constraint_formulations."""
    params = state["parameters"]
    variables: dict[str, Any] = {}
    formulated = []
    for c in state["constraints"]:
        c = dict(c)
        res = await _ask(runtime.context, "constraint_model", P.CONSTRAINT_MODEL__PROMPT_CONSTRAINTS_MODEL.format(
            description=state["problem"], params=_dump(params), vars=_dump(variables), constraint=c, rag=""))
        formulation, new_variables, aux_constraints = extract_formulation_from_end(res)
        tmp_vars = variables.copy()
        for v in new_variables:
            if v in tmp_vars:
                raise Exception(f"Variable {v} already exists")
            new_variables[v]["shape"] = shape_string_to_list(new_variables[v]["shape"])
            tmp_vars[v] = new_variables[v]
        c["formulation"] = formulation
        formulated.append(c)
        formulated += [{"description": "auxiliary constraint", "formulation": aux} for aux in aux_constraints]
        variables = tmp_vars
    # Upstream also asks qs[0] about every formulation here, but its handler is a dummy that discards the answer.
    return {"constraints": formulated, "variables": variables}


async def formulate_objective(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """objective_model.get_objective_formulation; the formulation so far becomes the method's formulation."""
    description = state["objective"]["description"]
    res = await _ask(runtime.context, "objective_model", P.OBJECTIVE_MODEL__PROMPT_OBJECTIVE_MODEL.format(
        description=state["problem"], params=_dump(state["parameters"]), vars=_dump(state["variables"]), objective=description))
    objective = {"description": description, "formulation": extract_equal_sign_closed(res), "code": None}
    return {"objective": objective, "formulation": _formulation({**state, "objective": objective})}


async def write_code(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """target_code.get_codes for the selected language's dialect."""
    context, desc, params, variables = runtime.context, state["problem"], state["parameters"], state["variables"]
    dialect = DIALECTS[context.target.language]
    coded = []
    for c in state["constraints"]:
        res = await _ask(context, "constraint_code", dialect.constraint_prompt().format(
            solver=dialect.solver, description=desc, params=_dump(params), vars=_dump(variables), constraint=_dump(c),
            directions=dialect.directions))
        coded.append({**c, "code": extract_code_from_end(res)})
    objective = state["objective"]
    res = await _ask(context, "objective_code", dialect.objective_prompt().format(
        solver=dialect.solver, description=desc, params=_dump(params), vars=_dump(variables), objective=_dump(objective),
        directions=dialect.directions))
    return {"constraints": coded, "objective": {**objective, "code": extract_code_from_end(res)}}


def _indent(code: str) -> str:
    return "".join("    " + line if line.strip() else line for line in code.splitlines(True)) + "\n"


def assemble(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """generate_code.generate_code as `build_model`; data.json is embedded as DATA."""
    dialect = DIALECTS[runtime.context.target.language]
    body = [dialect.setup + "\n", "data = DATA\n", "\n\n### Define the parameters\n"]
    for symbol, v in state["parameters"].items():
        body.append(f'{symbol} = data["{symbol}"] # shape: {v["shape"]}, definition: {v["definition"]}\n')
    body.append("\n\n### Define the variables\n")
    for symbol, v in state["variables"].items():
        body.append(dialect.var_code(symbol, v["shape"], v["type"]))
    body.append("\n\n### Define the constraints\n")
    body += [c["code"] + "\n" for c in state["constraints"]]
    body.append("\n\n### Define the objective\n")
    body.append(state["objective"]["code"] + "\n")
    body.append("\nreturn model\n")
    code = (f"import os\nimport numpy as np\nimport json\n{dialect.imports}\n\n"
            f"DATA = {pformat(state['_values'], width=110, sort_dicts=False)}\n\n\n"
            "def build_model(files):\n" + _indent("".join(body)))
    return {"code": code, "tries": 0}


async def execute(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    result = await runtime.context.solve(state["code"] or "", title=f"执行代码（第 {state['tries'] + 1} 次）")
    return {"solve": result, "tries": state["tries"] + 1}


async def debug(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """execute_code.execute_and_debug: ask for a fix after every failed run, including the last one."""
    result = state["solve"]
    assert result is not None
    response = await _ask(runtime.context, "debug", P.EXECUTE_CODE__DEBUG_TEMPLATE.format(
        description=state["problem"], code=state["code"], error=result.error or result.feedback()))
    return {"fixed_code": extract_debugged_code(response) + "\n"}


def after_execute(state: State) -> str:
    # The assembled script reads model.objVal and writes the status only when it is optimal, so any non-optimal
    # result counts as an error and is debugged.
    return END if state["solve"] is not None and state["solve"].status == "optimal" else "debug"


def after_debug(state: State) -> str:
    return "use_fix" if state["tries"] < presets.OPTIMUS.max_debug_tries else END


def use_fix(state: State) -> dict[str, Any]:
    return {"code": state["fixed_code"]}


def _formulation(state: dict[str, Any]) -> str:
    lines = ["### Parameters", "```json", _dump(state["parameters"]), "```", "", "### Decision variables"]
    lines += [f"- `{name}`: {v.get('type')}, shape {v.get('shape')}. {v.get('definition', '')}" for name, v in state["variables"].items()]
    lines += ["", "### Objective", state["objective"]["description"], "", state["objective"]["formulation"] or "",
              "", "### Constraints"]
    lines += [f"- {c['description']}: {c['formulation']}" for c in state["constraints"]]
    return "\n".join(lines)


def optimus_graph():
    graph = StateGraph(State, context_schema=Context)
    steps = [parameters, objective, constraints, check_constraints, formulate_constraints, formulate_objective,
             write_code, assemble, execute]
    for node in steps + [debug, use_fix]:
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "parameters")
    for first, second in zip(steps, steps[1:]):
        graph.add_edge(first.__name__, second.__name__)
    graph.add_conditional_edges("execute", after_execute, ["debug", END])
    graph.add_conditional_edges("debug", after_debug, ["use_fix", END])
    graph.add_edge("use_fix", "execute")
    return graph.compile(name="optimus")


OPTIMUS = Method("optimus", "OptiMUS",
                 "提取目标和约束并逐条检查，逐条建模约束和目标，为每条约束生成代码，组装后执行并调试。", optimus_graph,
                 "https://github.com/teshnizi/OptiMUS/tree/e182e9ef5841605c2a7e87467021fd83522b6484",
                 titles={"parameters": "参数", "objective": "目标", "constraints": "约束（去冗余后）",
                         "check_constraints": "约束（逐条检查后）", "formulate_constraints": "约束公式与变量",
                         "formulate_objective": "数学模型", "write_code": "逐条生成代码", "assemble": "组装代码",
                         "execute": "执行代码", "debug": "调试代码", "use_fix": "使用调试后的代码"},
                 languages=MILP_LANGUAGES,
                 parameters=lambda: asdict(presets.OPTIMUS))
