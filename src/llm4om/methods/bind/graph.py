"""BIND's default agentic path, adapted from Text2Opt-Bench at the commit below.

llm4om: original attachments replace benchmark instance_data; no reference optimum or gold model is available.
"""

from dataclasses import asdict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.methods import Method, presets
from llm4om.methods.bind.schema import describe_data
from llm4om.methods.common import TWO_PARTS, split_formulation_and_code
from llm4om.runtime import Context, ModelingState


class State(ModelingState, total=False):
    messages: list[BaseMessage]
    rounds: int
    data_schema: str
    _format_error: str | None


def prepare(state: State, runtime: Runtime[Context]) -> dict:
    context = runtime.context
    description = state.get("description", state["problem"])
    data_schema = describe_data(context.data)
    system = (
        "Build an optimization model from the problem description and the attached data schema. "
        "The schema gives field names, types and dimensions, not numeric array contents. "
        "Read the full attachments from data in build_model(data); never hardcode or invent their values. "
        "Preserve indices, units, domains, objective direction and all stated constraints. "
        "Do not relax the problem to obtain a feasible answer. " + TWO_PARTS + "\n\n" + context.target.prompt
    )
    return {"data_schema": data_schema, "rounds": 0,
            "messages": [SystemMessage(system), HumanMessage(description + "\n\nData schema:\n" + data_schema)]}


async def generate(state: State, runtime: Runtime[Context]) -> dict:
    reply = await runtime.context.llm("bind_generate").bind(
        temperature=presets.BIND.temperature, top_p=presets.BIND.top_p).ainvoke(state["messages"])
    update = {"messages": [*state["messages"], AIMessage(reply.text)], "rounds": state["rounds"] + 1}
    try:
        formulation, code = split_formulation_and_code(reply.text)
        if not formulation or not code.strip():
            raise ValueError("Return a formulation and nonempty Python code.")
    except ValueError as error:
        return {**update, "_format_error": str(error), "failure": str(error)}
    return {**update, "formulation": formulation, "code": code, "solve": None,
            "_format_error": None, "failure": None}


async def solve(state: State, runtime: Runtime[Context]) -> dict:
    result = await runtime.context.solve(state["code"], title=f"BIND 求解 {state['rounds']}")
    return {"solve": result, "failure": None if result.executed else result.error or result.status}


def retry(state: State) -> str:
    if not state.get("failure") or state["rounds"] >= presets.BIND.max_rounds:
        return END
    return "feedback"


def feedback(state: State) -> dict:
    # llm4om: real execution feedback replaces reference-optimum/model-count comparisons.
    result = state.get("solve")
    text = state.get("_format_error") or (result.feedback() if result else state["failure"])
    return {"messages": [*state["messages"], HumanMessage(
        "The previous attempt failed:\n" + text + "\nRepair the model using the original description and schema. "
        "Read all data from the attachments. " + TWO_PARTS)]}


def graph():
    builder = StateGraph(State, context_schema=Context)
    for name, node in [("prepare", prepare), ("generate", generate), ("solve", solve), ("feedback", feedback)]:
        builder.add_node(name, node)
    builder.add_edge(START, "prepare")
    builder.add_edge("prepare", "generate")
    builder.add_conditional_edges("generate", lambda s: retry(s) if s.get("_format_error") else "solve",
                                  ["solve", "feedback", END])
    builder.add_conditional_edges("solve", retry, ["feedback", END])
    builder.add_edge("feedback", "generate")
    return builder.compile(name="bind")


BIND = Method(
    id="bind", name="BIND", description="数据留在求解环境，以结构描述建模，再用执行反馈修正代码。",
    graph=graph, source="https://github.com/SprocketLab/Text2Opt-Bench/tree/1dac06be656c41d827ef20987cf8af0b48d382a2",
    titles={"prepare": "数据结构", "generate": "BIND 建模"},
    parameters=lambda: asdict(presets.BIND),
)
