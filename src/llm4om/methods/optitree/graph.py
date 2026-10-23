"""OptiTree: `Reasoner.reason_run` of https://github.com/MIRALab-USTC/OptiTree at 2e70ecf as a graph.

Walk the modeling tree from the root: at each level an interpreter decides whether the problem belongs to one of the
child types (`TemplateMatcher.final_template`). The deepest matched node's thought template, the whole tree entry,
guides a reasoner that writes the code; while the code fails to run, an inspector edits it, at most four times.
Prompts (prompts.py) and the tree (source/) are the upstream text and data; the problem keeps test.py's MILP prefix.

Adaptations:
- Library. "gurobi code" in the reasoner prompt names the selected language's library, and the reasoner and inspector
  prompts end with the platform code contract, which replaces the template's solve-and-print code.
- Execution. Code runs in the platform sandbox. Upstream inspects while the printed output is an error, empty or
  "None"; here while the code does not run, and the inspector reads the sandbox feedback.
- Conversation. Upstream's Agent stores its own replies with the role "system"; they are assistant messages here,
  because several providers reject system messages after the first.
- Error avoidance. Upstream fails when the matched type is not in the tree or the reply lacks the decision field;
  the walk stops at the current node instead. It also stops if a match would revisit a node on the path.
"""

import json
from dataclasses import asdict
from functools import cache
from importlib.resources import files
from typing import Any

import json_repair
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.methods import Method, presets
from llm4om.methods.common import TWO_PARTS
from llm4om.methods.optitree.prompts import CLASSIFY_PROMPT, INSPECTOR_PROMPT, MILP, REASON_PROMPT
from llm4om.runtime import Context, ModelingState

ROOT_TYPE = "Mixed Integer Programming"
CODE_MARKERS = ["```python", "```Python", "```"]


@cache
def _tree() -> tuple[dict[int, dict[str, Any]], dict[str, list[int]]]:
    """Upstream load_template (each entry without its id) and load_tree."""
    root = files("llm4om.methods.optitree").joinpath("source")
    templates = {}
    for line in root.joinpath("thoughts.jsonl").read_text("utf-8").splitlines():
        entry = json.loads(line)
        templates[entry.pop("id")] = entry
    return templates, json_repair.loads(root.joinpath("tree.json").read_text("utf-8"))


def get_template_id(problem_type: str) -> int | None:
    return next((key for key, template in _tree()[0].items() if template["problem_type"] == problem_type), None)


def extract_code(text: str) -> str | None:
    """Upstream extract_and_execute_code, without the execution: the first fenced block, or None."""
    start, used = -1, ""
    for marker in CODE_MARKERS:
        start = text.lower().find(marker.lower())
        if start != -1:
            used = marker
            break
    if start == -1:
        return None
    end = text.find("```", start + len(used))
    code = text[start + len(used): end if end != -1 else len(text)].strip()
    for marker in CODE_MARKERS:
        code = code.replace(marker, "")
    return code.replace("```", "").strip() + "\n"


class State(ModelingState, total=False):
    node: int  # the current tree node
    path: list[str]  # matched problem types from the root
    belongs: bool  # the last classification matched a child
    thought_template: dict[str, Any]
    reply: str
    inspections: int
    _inspector: list[BaseMessage]  # the inspector's conversation


async def _reply(context: Context, role: str, system: str, user: str) -> str:
    return (await context.llm(role).bind(temperature=presets.OPTITREE.temperature).ainvoke([SystemMessage(system), HumanMessage(user)])).text


async def classify(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """One step of final_template: template_reduce on the current node's children, then move to the match."""
    templates, tree = _tree()
    node = state.get("node", 0)
    current_type = templates[node]["problem_type"]
    children = tree[str(node)]
    problem = MILP + state["problem"]
    if current_type == ROOT_TYPE:
        prompt = CLASSIFY_PROMPT[2].format(specific_problem=problem,
                                           list_of_problem_types=[templates[i]["problem_type"] for i in children])
        keys = ("belongs_to_problem_types", "matching_problem_type")
    else:
        info = [{"problem_type": templates[i]["problem_type"], "description": templates[i]["description"]} for i in children]
        prompt = CLASSIFY_PROMPT[1].format(basic_type=current_type, template_info=info, input_problem=problem)
        keys = ("belongs_to_subtypes", "matching_subtype")
    answer = json_repair.loads(await _reply(runtime.context, "interpreter", CLASSIFY_PROMPT[0], prompt))
    belongs = isinstance(answer, dict) and bool(answer.get(keys[0]))
    index = get_template_id(answer.get(keys[1], "")) if belongs else None
    path = state.get("path") or [current_type]
    if index is None or templates[index]["problem_type"] in path:
        return {"node": node, "path": path, "belongs": False}
    return {"node": index, "path": path + [templates[index]["problem_type"]], "belongs": bool(tree[str(index)])}


def retrieve(state: State) -> dict[str, Any]:
    return {"thought_template": _tree()[0][state.get("node", 0)]}


async def reason(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    prompt = REASON_PROMPT[1].replace("gurobi code", f"{context.target.library.lower()} code").format(
        user_input=MILP + state["problem"], thought_template=state["thought_template"])
    reply = await _reply(context, "reasoner", REASON_PROMPT[0], prompt + "\n\n" + context.target.prompt + "\n" + TWO_PARTS)
    return {"reply": reply, "formulation": reply.split("```", 1)[0].strip() or None,
            "code": extract_code(reply), "inspections": 0, "_inspector": []}


async def execute(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    result = await runtime.context.solve(state["code"] or "", title=f"执行代码（第 {state['inspections'] + 1} 次）")
    return {"solve": result}


async def inspect(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    assert state["solve"] is not None
    request = f"""
            User_input:{MILP + state["problem"]}
            {state["code"]}
            {state["solve"].feedback()}
            """
    messages = state["_inspector"] + [HumanMessage(request)]
    reply = (await context.llm("inspector").bind(temperature=presets.OPTITREE.temperature).ainvoke(
        [SystemMessage(INSPECTOR_PROMPT + "\n" + context.target.prompt), *messages])).text
    return {"reply": reply, "code": extract_code(reply), "inspections": state["inspections"] + 1,
            "_inspector": messages + [AIMessage(reply)]}


def after_classify(state: State) -> str:
    return "classify" if state["belongs"] else "retrieve"


def after_code(state: State) -> str:
    return "execute" if state.get("code") else END  # upstream stops when the reply has no code


def after_execute(state: State) -> str:
    assert state["solve"] is not None
    return END if state["solve"].executed or state["inspections"] >= presets.OPTITREE.max_inspections else "inspect"


def optitree_graph():
    graph = StateGraph(State, context_schema=Context)
    for node in (classify, retrieve, reason, execute, inspect):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "classify")
    graph.add_conditional_edges("classify", after_classify, ["classify", "retrieve"])
    graph.add_edge("retrieve", "reason")
    graph.add_conditional_edges("reason", after_code, ["execute", END])
    graph.add_conditional_edges("execute", after_execute, ["inspect", END])
    graph.add_conditional_edges("inspect", after_code, ["execute", END])
    return graph.compile(name="optitree")


OPTITREE = Method("optitree", "OptiTree",
                  "在问题类型树中逐层匹配，取出最深匹配节点的建模思路模板，据此写出代码；代码无法运行时由检查员修改。",
                  optitree_graph, "https://github.com/MIRALab-USTC/OptiTree/tree/2e70ecfd0a3c8e9c0c16d36d7d498a7344cfdec9",
                  titles={"classify": "匹配问题类型", "retrieve": "建模思路模板", "reason": "按模板生成代码",
                          "inspect": "检查并修改代码"}, hidden=frozenset({"belongs", "node", "inspections"}),
                  linear_only=True,
                  parameters=lambda: asdict(presets.OPTITREE))
