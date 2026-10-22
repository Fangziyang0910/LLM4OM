"""Extract anchors, generate components, backtranslate constraints and selectively repair mismatches.

This is an independent implementation of SAC-Opt's published algorithm, not a copy of its unlicensed prompts.
llm4om adaptations (batching, attachments and bounded final validation) are detailed in README.md.
"""

import json
import textwrap
from dataclasses import asdict
from typing import Annotated, TypeVar

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import AfterValidator, BaseModel, Field

from llm4om.methods import Method, presets
from llm4om.methods.common import TWO_PARTS, split_formulation_and_code
from llm4om.runtime import Context, ModelingState


class Elements(BaseModel):
    items: list[str]


class Objective(BaseModel):
    text: str = Field(min_length=1)


class Confidence(BaseModel):
    score: int = Field(ge=1, le=5)
    reason: str


def code_fragment(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        _, text = split_formulation_and_code(text)
    return textwrap.dedent(text).strip()


Code = Annotated[str, AfterValidator(code_fragment), Field(min_length=1)]


class Component(BaseModel):
    formulation: str = Field(min_length=1, description="Markdown with LaTeX enclosed in $...$ or $$...$$.")
    code: Code


class Components(BaseModel):
    setup: Code
    objective: Component
    constraints: list[Component]


class Replacements(BaseModel):
    constraints: list[Component]


class Comparison(BaseModel):
    equivalent: bool
    reason: str


class Comparisons(BaseModel):
    items: list[Comparison]


class State(ModelingState, total=False):
    parameters: list[str]
    variables: list[str]
    objective: str
    constraints: list[str]
    components: dict
    reconstructed: list[str]
    comparisons: list[dict]
    accepted: list[bool]
    semantic_rounds: int
    executions: int
    _pending: list[int]
    _semantic_failure: str | None


T = TypeVar("T", bound=BaseModel)


async def structured(context: Context, role: str, instruction: str, payload: dict, schema: type[T],
                     *, length: tuple[str, int] | None = None) -> T:
    if length:
        instruction += f"\nThe {length[0]} list must contain exactly {length[1]} entries, one per supplied anchor, in order."
    messages = [SystemMessage(instruction + "\nReturn only JSON matching this schema:\n" + json.dumps(schema.model_json_schema())),
                HumanMessage(json.dumps(payload, ensure_ascii=False))]
    for attempt in range(presets.SAC_OPT.max_parse_attempts):
        reply = await context.llm(role).bind(temperature=presets.SAC_OPT.temperature).ainvoke(messages)
        try:
            parsed = schema.model_validate_json(reply.text.strip().removeprefix("```json").removesuffix("```").strip())
            if length and len(getattr(parsed, length[0])) != length[1]:
                raise ValueError(f"{length[0]} must have exactly {length[1]} entries, covering every constraint in order.")
            return parsed
        except ValueError as error:
            if attempt + 1 == presets.SAC_OPT.max_parse_attempts:
                raise
            messages += [AIMessage(reply.text), HumanMessage("Correct the JSON response: " + str(error))]
    raise AssertionError("SAC-Opt requires at least one parse attempt.")


async def extract_elements(state: State, context: Context, kind: str, instruction: str) -> list[str]:
    result = await structured(context, "sac_" + kind, instruction, {"problem": state["problem"],
                              "parameters": state.get("parameters", []), "variables": state.get("variables", []),
                              "objective": state.get("objective", "")}, Elements)
    kept = []
    criteria = {
        "parameters": "It must be fixed input data with a known value or an attached-file source. "
                      "An unknown production quantity is a decision variable, not a parameter. "
                      "An objective expression is not a parameter. Score these invalid cases 1.",
        "variables": "It must be an unknown decision to be optimized. A known cost, capacity, or coefficient is not a variable.",
        "constraints": "It must restrict feasible decisions, not restate data or an optimization goal; "
                       "it must be required by the problem and expressible in a (mixed integer) linear model.",
    }
    for item in result.items:
        confidence = await structured(context, "sac_check_" + kind,
                                      "Score from 1 to 5 whether this is a valid " + kind + " anchor for the problem. "
                                      + criteria[kind],
                                      {"problem": state["problem"], "anchor": item}, Confidence)
        if confidence.score > 3:
            kept.append(item)
        elif kind == "constraints":
            revised = await structured(context, "sac_revise_constraint",
                                       "Check this doubtful constraint against the problem. Return its corrected description; "
                                       "return an empty list only if it is not required. Do not drop a required constraint "
                                       "merely because it needs auxiliary variables or a linear reformulation.",
                                       {"problem": state["problem"], "constraint": item, "feedback": confidence.reason}, Elements)
            kept.extend(revised.items)
    return kept


async def parameters(state: State, runtime: Runtime[Context]) -> dict:
    items = await extract_elements(state, runtime.context, "parameters",
                                   "Extract only known input data parameters, each with a distinct symbol, meaning, units, "
                                   "shape and fixed value or attached-file field. Include dimensions and index sets. "
                                   "Exclude unknown decision quantities, objective expressions and constraints.")
    return {"parameters": items}


async def variables(state: State, runtime: Runtime[Context]) -> dict:
    items = await extract_elements(state, runtime.context, "variables",
                                   "Extract decision variables. Each anchor must give its symbol, meaning, shape, "
                                   "continuous/integer/binary type and bounds supported by the problem.")
    return {"variables": items}


async def objective(state: State, runtime: Runtime[Context]) -> dict:
    result = await structured(runtime.context, "sac_objective", "Describe the objective, including direction, units and terms.",
                              {"problem": state["problem"], "parameters": state["parameters"], "variables": state["variables"]}, Objective)
    return {"objective": result.text}


async def constraints(state: State, runtime: Runtime[Context]) -> dict:
    items = await extract_elements(state, runtime.context, "constraints",
                                   "Extract restrictions on feasible decisions, one complete condition or indexed family per anchor. "
                                   "Combine resource usage coefficients and available capacity into a single capacity constraint. "
                                   "Do not list parameter facts, objective terms or the optimization goal as constraints. "
                                   "Variable domains/bounds already in the variable anchors need not be repeated. "
                                   "Remove duplicates without losing restrictions, exceptions or index scopes.")
    return {"constraints": items}


def anchors(state: State) -> dict:
    return {key: state[key] for key in ("problem", "parameters", "variables", "objective", "constraints")}


COMPONENT_RULES = """Use gurobipy with gp, GRB, json, csv, io, itertools and numpy as np available. A model named \
`model` already exists inside build_model(data). The setup and code fields contain plain Python function-body \
fragments without Markdown fences, not build_model or another model. \
The setup declares parameters and all variables; the objective calls model.setObjective; each constraint component \
adds exactly its anchor's condition/family to model. Do not optimize or return. `data` maps attached FILE NAMES to \
raw CSV/JSON TEXT, not parameter names to values. Parse attachments when present. If data_files is empty, data is \
empty: assign the numeric values from the problem description directly. Never invent or truncate values. \
Use explicit variable domains and bounds. Include a Markdown formulation with $...$ or $$...$$ math delimiters \
for the objective and each constraint. Keep the component list in the same order as the supplied anchors."""


async def generate(state: State, runtime: Runtime[Context]) -> dict:
    result = await structured(runtime.context, "sac_generate", COMPONENT_RULES,
                              {**anchors(state), "data_files": list(runtime.context.data)}, Components,
                              length=("constraints", len(state["constraints"])))
    return {"components": result.model_dump(), "accepted": [False] * len(result.constraints), "semantic_rounds": 0}


async def backtranslate(state: State, runtime: Runtime[Context]) -> dict:
    pending = [i for i, accepted in enumerate(state["accepted"]) if not accepted]
    components = state["components"]
    # The decoder sees code and declarations, not the source constraint it is supposed to reconstruct.
    result = await structured(runtime.context, "sac_backtranslate",
                              "Translate each code fragment into a precise natural-language constraint. Include its indices, "
                              "signs, quantifiers, bounds and exceptions. Return one description per fragment in order.",
                              {"parameters": state["parameters"], "variables": state["variables"], "setup": components["setup"],
                               "code": [components["constraints"][i]["code"] for i in pending]}, Elements,
                              length=("items", len(pending)))
    return {"reconstructed": result.items, "_pending": pending, "semantic_rounds": state["semantic_rounds"] + 1}


async def compare(state: State, runtime: Runtime[Context]) -> dict:
    result = await structured(runtime.context, "sac_compare",
                              "Compare each original constraint with its reconstruction. Equivalent means neither missing "
                              "nor extra restrictions, with the same index scope, units and direction. Judge each pair separately.",
                              {"pairs": [{"original": state["constraints"][i], "reconstructed": text}
                                         for i, text in zip(state["_pending"], state["reconstructed"], strict=True)]}, Comparisons,
                              length=("items", len(state["_pending"])))
    accepted = list(state["accepted"])
    for i, decision in zip(state["_pending"], result.items, strict=True):
        accepted[i] = decision.equivalent
    return {"accepted": accepted, "comparisons": [item.model_dump() for item in result.items]}


async def repair(state: State, runtime: Runtime[Context]) -> dict:
    pending = [i for i in state["_pending"] if not state["accepted"][i]]
    feedback = {i: {"reconstructed": text, **decision} for i, text, decision in
                zip(state["_pending"], state["reconstructed"], state["comparisons"], strict=True)}
    components = state["components"]
    result = await structured(runtime.context, "sac_repair", COMPONENT_RULES +
                              "\nReplace only the mismatched constraint components below. Keep setup, symbols and other constraints fixed.",
                              {"problem": state["problem"], "data_files": list(runtime.context.data),
                               "setup": components["setup"], "constraints": [
                                  {"anchor": state["constraints"][i], "previous": components["constraints"][i],
                                   "feedback": feedback[i]} for i in pending]}, Replacements,
                              length=("constraints", len(pending)))
    updated = list(components["constraints"])
    for i, component in zip(pending, result.constraints, strict=True):
        updated[i] = component.model_dump()
    return {"components": {**components, "constraints": updated}}


def assemble(state: State) -> dict:
    components = state["components"]
    pieces = [components["objective"], *components["constraints"]]
    body = "\n\n".join(["model = gp.Model('sac_opt')", components["setup"], *[p["code"] for p in pieces], "return model"])
    code = ("import csv\nimport io\nimport itertools\nimport json\nimport numpy as np\n"
            "import gurobipy as gp\nfrom gurobipy import GRB\n\ndef build_model(data):\n" + textwrap.indent(body, "    ") + "\n")
    formulation = ("## Parameters\n" + "\n".join(state["parameters"]) + "\n\n## Variables\n" + "\n".join(state["variables"])
                   + "\n\n## Objective and constraints\n" + "\n\n".join(p["formulation"] for p in pieces))
    failure = None if all(state["accepted"]) else "SAC-Opt exhausted semantic checks with unresolved constraint mismatches."
    return {"code": code, "formulation": formulation, "executions": 0, "_semantic_failure": failure, "failure": failure}


async def solve(state: State, runtime: Runtime[Context]) -> dict:
    result = await runtime.context.solve(state["code"], title=f"SAC-Opt 求解 {state['executions'] + 1}")
    return {"solve": result, "executions": state["executions"] + 1,
            "failure": state.get("_semantic_failure") or (None if result.executed else result.error or result.status)}


async def debug(state: State, runtime: Runtime[Context]) -> dict:
    system = "Fix execution errors without changing the intended mathematical model. " + TWO_PARTS + "\n\n" + runtime.context.target.prompt
    user = (state["problem"] + "\n\n" + state["formulation"] + "\n```python\n" + state["code"] + "```\n"
            + state["solve"].feedback())
    reply = await runtime.context.llm("sac_debug").bind(temperature=presets.SAC_OPT.temperature).ainvoke([
        SystemMessage(system), HumanMessage(user)])
    formulation, code = split_formulation_and_code(reply.text)
    if not formulation or not code.strip():
        raise ValueError("SAC-Opt debugging must return a formulation and nonempty code.")
    return {"formulation": formulation, "code": code, "solve": None}


def graph():
    builder = StateGraph(State, context_schema=Context)
    nodes = [("parameters", parameters), ("variables", variables), ("objective", objective), ("constraints", constraints),
             ("generate", generate), ("backtranslate", backtranslate), ("compare", compare), ("repair", repair),
             ("assemble", assemble), ("solve", solve), ("debug", debug)]
    for name, node in nodes:
        builder.add_node(name, node)
    path = [START, "parameters", "variables", "objective", "constraints", "generate"]
    for before, after in zip(path, path[1:]):
        builder.add_edge(before, after)
    builder.add_conditional_edges("generate", lambda s: "backtranslate" if s["constraints"] else "assemble", ["backtranslate", "assemble"])
    builder.add_edge("backtranslate", "compare")
    builder.add_conditional_edges("compare", lambda s: "assemble" if all(s["accepted"]) or
                                  s["semantic_rounds"] >= presets.SAC_OPT.max_semantic_rounds else "repair", ["assemble", "repair"])
    builder.add_edge("repair", "backtranslate")
    builder.add_edge("assemble", "solve")
    builder.add_conditional_edges("solve", lambda s: END if s["solve"].executed or s["executions"] >= presets.SAC_OPT.max_executions else "debug",
                                  ["debug", END])
    builder.add_edge("debug", "solve")
    return builder.compile(name="sac_opt")


SAC_OPT = Method(
    id="sac_opt", name="SAC-Opt", description="提取语义锚点，将约束代码回译并比较，逐项修正语义偏差。",
    graph=graph, source="https://github.com/Forrest-Stone/SAC-Opt/tree/ec0ddb544ae6b70714181740ebbba16027df50e4",
    titles={"parameters": "参数锚点", "variables": "变量锚点", "objective": "目标锚点", "constraints": "约束锚点",
            "generate": "分项建模", "backtranslate": "约束回译", "compare": "语义比较", "repair": "修正约束",
            "assemble": "组装模型", "debug": "修正执行错误"},
    languages=frozenset({"gurobipy"}), parameters=lambda: asdict(presets.SAC_OPT),
)
