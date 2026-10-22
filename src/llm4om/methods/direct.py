"""Project baselines: one-shot generation, and generation with solver-feedback repair."""

from dataclasses import asdict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.methods import Method, presets
from llm4om.methods.common import ask, split_formulation_and_code
from llm4om.runtime import Context, ModelingState
from llm4om.sandbox import SolveResult

SYSTEM = """You are an expert in operations research. Model the optimization problem and implement the model.

Reply in two parts:
1. The mathematical formulation in Markdown with LaTeX ($...$ inline, $$...$$ display): sets, parameters with \
their values, decision variables with domains, the objective, and every constraint. State any assumption you make.
2. The implementation that follows the formulation exactly, in one ```python code block.

{target}"""

REPAIR = """The previous model was solved and the result shows a problem. Diagnose whether the formulation or the \
code is wrong, then reply with the complete corrected formulation and code in the same two-part format.
Do not delete or relax business requirements just to obtain a feasible solution."""


async def _generate(context: Context, role: str, user: str) -> dict[str, str]:
    formulation, code = split_formulation_and_code(await ask(context, role, SYSTEM.format(target=context.target.prompt), user))
    return {"formulation": formulation, "code": code}


async def generate(state: ModelingState, runtime: Runtime[Context]) -> dict[str, str]:
    return await _generate(runtime.context, "generate", state["problem"])


def direct_graph():
    graph = StateGraph(ModelingState, context_schema=Context)
    graph.add_node("generate", generate)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", END)
    return graph.compile(name="direct")


class RepairState(ModelingState, total=False):
    repairs: int
    _best: tuple[str, str, SolveResult] | None  # formulation, code and result of the best attempt so far


async def solve(state: RepairState, runtime: Runtime[Context]) -> dict[str, object]:
    repairs = state.get("repairs", 0)
    result = await runtime.context.solve(state["code"] or "", title="求解" if repairs == 0 else f"求解（修正 {repairs}）")
    best = state.get("_best")
    # Prefer a solution, then an executable model, then the later attempt.
    if best is None or (result.has_solution, result.executed) >= (best[2].has_solution, best[2].executed):
        best = (state["formulation"] or "", state["code"] or "", result)
    return {"_best": best, "solve": result}


def route_after_solve(state: RepairState) -> str:
    done = state["solve"] is not None and state["solve"].has_solution
    return "finish" if done or state.get("repairs", 0) >= presets.FEEDBACK_REPAIR.max_repairs else "repair"


async def repair(state: RepairState, runtime: Runtime[Context]) -> dict[str, object]:
    assert state["solve"] is not None
    feedback = (f"## Previous formulation\n{state['formulation']}\n\n## Previous code\n```python\n{state['code']}```\n\n"
                f"## Solver feedback\n{state['solve'].feedback()}\n\n{REPAIR}")
    return {**await _generate(runtime.context, "repair", state["problem"] + "\n\n" + feedback),
            "repairs": state.get("repairs", 0) + 1}


def finish(state: RepairState) -> dict[str, object]:
    assert state["_best"] is not None
    formulation, code, result = state["_best"]
    return {"formulation": formulation, "code": code, "solve": result}


def feedback_repair_graph():
    graph = StateGraph(RepairState, context_schema=Context)
    graph.add_node("generate", generate)
    graph.add_node("solve", solve)
    graph.add_node("repair", repair)
    graph.add_node("finish", finish)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", "solve")
    graph.add_conditional_edges("solve", route_after_solve, ["repair", "finish"])
    graph.add_edge("repair", "solve")
    graph.add_edge("finish", END)
    return graph.compile(name="feedback_repair")


DIRECT = Method("direct", "Direct", "一次调用生成数学模型和求解代码，然后求解。", direct_graph,
                titles={"generate": "生成数学模型和代码"})
FEEDBACK_REPAIR = Method("feedback_repair", "Feedback Repair",
                         f"生成数学模型和代码后求解；没有得到解时，把求解反馈交给模型修正，最多修正 {presets.FEEDBACK_REPAIR.max_repairs} 次。", feedback_repair_graph,
                         titles={"generate": "生成数学模型和代码", "repair": "按求解反馈修正", "finish": "选择最好的一次"},
                         parameters=lambda: asdict(presets.FEEDBACK_REPAIR))
