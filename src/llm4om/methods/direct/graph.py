"""Direct one-call generation baseline."""

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.methods import Method
from llm4om.methods.common import ask, split_formulation_and_code
from llm4om.methods.direct.prompts import SYSTEM
from llm4om.runtime import Context, ModelingState


async def generate(state: ModelingState, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    reply = await ask(context, "generate", SYSTEM.format(target=context.target.prompt), state["problem"])
    try:
        formulation, code = split_formulation_and_code(reply)
        if not formulation or not code.strip():
            raise ValueError("The reply must include both a mathematical formulation and nonempty Python code.")
    except ValueError as error:
        return {"failure": str(error)}
    return {"failure": None, "formulation": formulation, "code": code, "solve": None}


def direct_graph():
    graph = StateGraph(ModelingState, context_schema=Context)
    graph.add_node("generate", generate)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", END)
    return graph.compile(name="direct")


DIRECT = Method("direct", "Direct", "一次调用生成数学模型和求解代码，检查输出格式后求解。", direct_graph,
                titles={"generate": "生成数学模型和代码"})
