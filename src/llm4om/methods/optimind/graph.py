"""OptiMind: select published hints, generate, execute and reflect (one trajectory, up to five turns)."""

import json
from dataclasses import asdict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.languages import MILP_LANGUAGES
from llm4om.methods import Method, presets
from llm4om.methods.common import ask, split_formulation_and_code
from llm4om.methods.optimind.prompts import FEEDBACK, SYSTEM, hint_bank, hints
from llm4om.runtime import Context, ModelingState


class State(ModelingState, total=False):
    classes: list[str]
    messages: list[BaseMessage]
    turns: int
    reflection: str
    _done: bool
    _format_error: str | None


async def classify(state: State, runtime: Runtime[Context]) -> dict:
    # llm4om: upstream datasets supply class labels; arbitrary user input needs classification.
    reply = await ask(runtime.context, "optimind_classify",
                      'Choose applicable problem classes. Reply only with a JSON array of exact class names, '
                      'or [] if none applies. Available classes: ' + ", ".join(hint_bank()), state["problem"])
    classes = json.loads(reply.strip().removeprefix("```json").removesuffix("```").strip())
    if not isinstance(classes, list) or any(not isinstance(name, str) or name not in hint_bank() for name in classes):
        raise ValueError("OptiMind classification must be an array of published hint class names.")
    classes = list(dict.fromkeys(classes))
    context = runtime.context
    return {"classes": classes, "turns": 0, "messages": [SystemMessage(SYSTEM.format(
        library=context.target.library, target=context.target.prompt)), HumanMessage(state["problem"] + "\n\n" + hints(classes))]}


async def generate(state: State, runtime: Runtime[Context]) -> dict:
    settings = presets.OPTIMIND
    reply = await runtime.context.llm("optimind_generate").bind(
        temperature=settings.temperature, top_p=settings.top_p).ainvoke(state["messages"])
    update = {"turns": state["turns"] + 1, "messages": [*state["messages"], AIMessage(reply.text)],
              "reflection": reply.text, "_done": False, "_format_error": None}
    try:
        formulation, code = split_formulation_and_code(reply.text)
        if not formulation or not code.strip():
            raise ValueError("Provide a formulation and nonempty Python code.")
    except ValueError as error:
        # A code-free final answer ends a trajectory only after a successfully executed model.
        result = state.get("solve")
        if "```" not in reply.text and reply.text.strip() and result and result.executed:
            return {**update, "_done": True, "failure": None}
        return {**update, "_format_error": str(error), "failure": str(error)}
    return {**update, "formulation": formulation, "code": code, "solve": None, "failure": None}


async def solve(state: State, runtime: Runtime[Context]) -> dict:
    result = await runtime.context.solve(state["code"], title=f"OptiMind 求解 {state['turns']}")
    return {"solve": result, "failure": None if result.executed else result.error or result.status}


def reflect_or_finish(state: State) -> str:
    return END if state.get("_done") or state["turns"] >= presets.OPTIMIND.max_turns else "feedback"


def feedback(state: State) -> dict:
    text = state.get("_format_error") or state["solve"].feedback()
    return {"messages": [*state["messages"], HumanMessage(FEEDBACK.format(result=text))]}


def graph():
    builder = StateGraph(State, context_schema=Context)
    for name, node in [("classify", classify), ("generate", generate), ("solve", solve), ("feedback", feedback)]:
        builder.add_node(name, node)
    builder.add_edge(START, "classify")
    builder.add_edge("classify", "generate")
    builder.add_conditional_edges("generate", lambda s: reflect_or_finish(s) if s.get("_done") or s.get("_format_error") else "solve",
                                  ["solve", "feedback", END])
    builder.add_conditional_edges("solve", reflect_or_finish, ["feedback", END])
    builder.add_edge("feedback", "generate")
    return builder.compile(name="optimind")


OPTIMIND = Method(
    id="optimind", name="OptiMind", description="按问题类型选用公开建模提示，并结合求解结果迭代检查模型。",
    graph=graph, source="https://github.com/microsoft/OptiGuide/tree/419cf7b9eee20b6af036abf15152fa775b20c951/optimind",
    titles={"classify": "匹配建模提示", "generate": "OptiMind 建模与检查"}, hidden=frozenset({"reflection"}),
    languages=MILP_LANGUAGES | {"pyscipopt", "coptpy", "cvxpy"},
    parameters=lambda: asdict(presets.OPTIMIND),
)
