"""Direct generation, and bounded repair with execution feedback and semantic review."""

import json
import re
from dataclasses import asdict
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from llm4om.methods import Method, presets
from llm4om.methods.common import ask, split_formulation_and_code
from llm4om.methods.direct.prompts import REPAIR, REVIEW, SYSTEM
from llm4om.runtime import Context, ModelingState
from llm4om.sandbox import SolveResult


class State(ModelingState, total=False):
    repairs: int
    review: dict[str, str] | None
    _reply: str
    _format_error: str | None
    _last: tuple[str, str, SolveResult]  # latest evaluated attempt, retained if a later reply cannot be parsed


class Review(BaseModel):
    action: Literal["accept", "repair"]
    reason: str = Field(min_length=1)


async def _generate(context: Context, role: str, user: str) -> dict[str, Any]:
    reply = await ask(context, role, SYSTEM.format(target=context.target.prompt), user)
    try:
        formulation, code = split_formulation_and_code(reply)
        if not formulation or not code.strip():
            raise ValueError("The reply must include both a mathematical formulation and nonempty Python code.")
    except ValueError as error:
        return {"_reply": reply, "_format_error": str(error), "failure": str(error), "review": None,
                "formulation": None, "code": None, "solve": None}
    return {"_reply": reply, "_format_error": None, "failure": None, "review": None,
            "formulation": formulation, "code": code, "solve": None}


async def generate(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    return await _generate(runtime.context, "generate", state["problem"])


def direct_graph():
    graph = StateGraph(State, context_schema=Context)
    graph.add_node("generate", generate)
    graph.add_edge(START, "generate")
    graph.add_edge("generate", END)
    return graph.compile(name="direct")


def retry_or_finish(state: State) -> str:
    return "repair" if state.get("repairs", 0) < presets.FEEDBACK_REPAIR.max_repairs else "finish"


def after_generate(state: State) -> str:
    return retry_or_finish(state) if state.get("_format_error") else "solve"


async def solve(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    repairs = state.get("repairs", 0)
    result = await runtime.context.solve(state["code"] or "", title="求解" if repairs == 0 else f"求解（修正 {repairs}）")
    return {"solve": result, "_last": (state["formulation"] or "", state["code"] or "", result)}


def after_solve(state: State) -> str:
    assert state["solve"] is not None
    return "review" if state["solve"].executed else retry_or_finish(state)


def attempt_feedback(state: State) -> str:
    assert state["solve"] is not None
    result = state["solve"]
    feedback = (f"## Previous formulation\n{state['formulation']}\n\n"
                f"## Previous code\n```python\n{state['code']}```\n\n## Solver feedback\n{result.feedback()}")
    # Only this project's repair method uses diagnostics; published methods keep their original feedback.
    if result.diagnosis:
        feedback += "\n\n## Solver conflict diagnosis\n" + json.dumps(result.diagnosis, ensure_ascii=False)
    return feedback


async def review(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    reply = await ask(runtime.context, "review", REVIEW.format(target=runtime.context.target.prompt),
                      state["problem"] + "\n\n" + attempt_feedback(state))
    fenced = re.fullmatch(r"```(?:json)?[ \t]*\n(.*?)\n?```", reply.strip(), re.S | re.I)
    try:
        verdict = Review.model_validate_json(fenced[1] if fenced else reply)
    except ValueError as error:
        return {"failure": f"Could not read the model review: {error}"}
    return {"review": verdict.model_dump()}


def after_review(state: State) -> str:
    return "finish" if state.get("failure") or state["review"]["action"] == "accept" else retry_or_finish(state)


async def repair(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    if state.get("_format_error"):
        feedback = f"## Output format error\n{state['_format_error']}\n\n## Previous reply\n{state['_reply']}"
    else:
        feedback = attempt_feedback(state)
        if state.get("review"):
            feedback += "\n\n## Model review\n" + state["review"]["reason"]
    return {**await _generate(runtime.context, "repair", state["problem"] + "\n\n" + feedback + "\n\n" + REPAIR),
            "repairs": state.get("repairs", 0) + 1}


def finish(state: State) -> dict[str, Any]:
    if state.get("_format_error"):
        result: dict[str, Any] = {"failure": "Output format could not be repaired: " + state["_format_error"]}
        if state.get("_last"):
            formulation, code, solved = state["_last"]
            result.update(formulation=formulation, code=code, solve=solved)
        return result
    if state.get("failure"):
        return {"failure": state["failure"]}
    if state.get("review") and state["review"]["action"] == "repair":
        return {"failure": "Model review still found a problem after the repair limit: " + state["review"]["reason"]}
    return {"failure": None}


def feedback_repair_graph():
    graph = StateGraph(State, context_schema=Context)
    for name, node in (("generate", generate), ("solve", solve), ("review", review), ("repair", repair), ("finish", finish)):
        graph.add_node(name, node)
    graph.add_edge(START, "generate")
    graph.add_conditional_edges("generate", after_generate, ["solve", "repair", "finish"])
    graph.add_conditional_edges("solve", after_solve, ["review", "repair", "finish"])
    graph.add_conditional_edges("review", after_review, ["repair", "finish"])
    graph.add_conditional_edges("repair", after_generate, ["solve", "repair", "finish"])
    graph.add_edge("finish", END)
    return graph.compile(name="feedback_repair")


DIRECT = Method("direct", "Direct", "一次调用生成数学模型和求解代码，检查输出格式后求解。", direct_graph,
                titles={"generate": "生成数学模型和代码"})
FEEDBACK_REPAIR = Method("feedback_repair", "Feedback Repair",
                         f"生成、求解并复核模型；根据格式、执行或建模问题修正，最多修正 {presets.FEEDBACK_REPAIR.max_repairs} 次。",
                         feedback_repair_graph,
                         titles={"generate": "生成数学模型和代码", "repair": "按反馈修正模型和代码", "review": "复核模型与求解结果"},
                         parameters=lambda: asdict(presets.FEEDBACK_REPAIR))
