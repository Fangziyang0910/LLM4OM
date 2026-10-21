"""OR-LLM-Agent: the `or_llm_agent` pipeline of `or_llm_eval.py` at the pinned commit, as a graph.

One conversation: a modeling agent writes the mathematical model; a code agent writes code; each execution error is
sent back for a fix, up to three times. Fixes stay in a copy of the conversation and only the round's last code joins
it (upstream `generate_or_code_solver`). Then one recovery round: if the code ran but found no objective, check for
infeasibility (one attempt); if it never ran, re-check the mathematical model (two attempts).

Prompts are the upstream text. Adaptations: the code requests name the platform code contract instead of
"Python code using Gurobi ... as well as solving and result output", "Gurobi" names the selected language's library,
and code runs in the platform sandbox.
"""

import re
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.languages import MILP_LANGUAGES
from llm4om.methods import Method
from llm4om.runtime import Context, ModelingState

TEMPERATURE = 0.2  # upstream query_llm default
ATTEMPTS = {"main": 3, "infeasible": 1, "recheck": 2}

MODELING_SYSTEM = (
    "You are an operations research expert. Based on the optimization problem provided by the user, construct a mathematical model that effectively models the original problem using mathematical (linear programming) expressions."
    "Focus on obtaining a correct mathematical model expression without too much concern for explanations."
    "This model will be used later to guide the generation of Gurobi code, and this step is mainly used to generate effective linear scale expressions."
)
# Upstream: "...write complete and reliable Python code using Gurobi to solve this operations research optimization
# problem.The code should include ..., objective function settings, as well as solving and result output."
CODE_REQUEST = (
    "Based on the above mathematical model, write complete and reliable Python code that follows the code contract below to solve this operations research optimization problem."
    "The code should include necessary model construction, variable definitions, constraint additions, objective function settings."
    "Output in the format ```python\n{{code}}\n```, without code explanations.\n\n{contract}"
)
FIX_REQUEST = ("Code execution encountered an error, error message is as follows:\n{error}\n"
               "Please fix the code and provide the complete executable code again.")
# Upstream says "the Gurobi Python code" in both recovery requests.
INFEASIBLE_REQUEST = (
    "The current model resulted in *no feasible solution*. Please carefully check the mathematical model and Python code for errors that might be causing the infeasibility."
    "After checking, please reoutput the Python code."
    "Output in the format ```python\n{code}\n```, without code explanations."
)
RECHECK_REQUEST = (
    "The model code still reports errors after multiple debugging attempts. Please carefully check if there are errors in the mathematical model."
    "After checking, please rebuild the Python code."
    "Output in the format ```python\n{code}\n```, without code explanations."
)


class State(ModelingState, total=False):
    messages: list[BaseMessage]  # the main conversation
    reply: str  # the latest code reply
    _trial: list[BaseMessage]  # the conversation copy that holds this round's fixes
    stage: str  # main, infeasible or recheck
    attempts: int  # fixes asked in this round
    executed: bool  # the latest reply ran
    _error: str  # its execution error


async def _query(context: Context, role: str, messages: list[BaseMessage]) -> str:
    return (await context.llm(role).bind(temperature=TEMPERATURE).ainvoke(messages)).text


async def math_model(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    messages: list[BaseMessage] = [SystemMessage(MODELING_SYSTEM.replace("Gurobi", context.target.library)),
                                   HumanMessage(state["problem"])]
    model = await _query(context, "math_model", messages)
    request = CODE_REQUEST.format(contract=context.target.prompt)
    return {"formulation": model, "messages": messages + [AIMessage(model), HumanMessage(request)], "stage": "main"}


async def write_code(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    messages = state["messages"]
    return {"reply": await _query(runtime.context, "code", messages), "_trial": list(messages), "attempts": 0}


async def execute(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """Upstream extract_and_execute_python_code: run the first non-empty ```python block."""
    blocks = [block.strip() for block in re.findall(r"```python\s*([\s\S]*?)```", state["reply"]) if block.strip()]
    if not blocks:
        return {"executed": False, "_error": "No Python code blocks found"}
    code = blocks[0] + "\n"
    result = await runtime.context.solve(code, title=f"执行代码（第 {runtime.context.solves + 1} 次）")
    return {"code": code, "solve": result, "executed": result.executed, "_error": result.error or result.feedback()}


async def fix(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    trial = state["_trial"] + [AIMessage(state["reply"]), HumanMessage(FIX_REQUEST.format(error=state.get("_error", "")))]
    return {"reply": await _query(runtime.context, "debug", trial), "_trial": trial, "attempts": state["attempts"] + 1}


def after_execute(state: State) -> str:
    return "end_round" if state["executed"] else "fix"


def after_fix(state: State) -> str:
    # Upstream asks for a fix after every failed run, including the last; that last fix is not run.
    return "execute" if state["attempts"] < ATTEMPTS[state["stage"]] else "end_round"


def end_round(state: State) -> dict[str, Any]:
    """Only the round's last code joins the conversation; the main round may be followed by one recovery round."""
    messages = state["messages"] + [AIMessage(state["reply"])]
    if state["stage"] != "main":
        return {"messages": messages, "stage": "done"}
    if state["executed"]:
        if state["solve"] is not None and state["solve"].objective is None:
            return {"messages": messages + [HumanMessage(INFEASIBLE_REQUEST)], "stage": "infeasible"}
        return {"messages": messages, "stage": "done"}
    return {"messages": messages + [HumanMessage(RECHECK_REQUEST)], "stage": "recheck"}


def or_llm_agent_graph():
    graph = StateGraph(State, context_schema=Context)
    for node in (math_model, write_code, execute, fix, end_round):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "math_model")
    graph.add_edge("math_model", "write_code")
    graph.add_edge("write_code", "execute")
    graph.add_conditional_edges("execute", after_execute, ["fix", "end_round"])
    graph.add_conditional_edges("fix", after_fix, ["execute", "end_round"])
    graph.add_conditional_edges("end_round", lambda state: END if state["stage"] == "done" else "write_code",
                                ["write_code", END])
    return graph.compile(name="or_llm_agent")


OR_LLM_AGENT = Method("or_llm_agent", "OR-LLM-Agent",
                      "数学建模、代码生成、按执行错误调试，最后按结果做一轮不可行检查或模型复查。", or_llm_agent_graph,
                      "https://github.com/bwz96sco/or_llm_agent/tree/5dccdaab89ab91c3cb28066fe849423dc124d287",
                      titles={"math_model": "数学模型", "write_code": "生成代码", "execute": "执行代码",
                              "fix": "按错误修复代码", "end_round": "本轮结束"},
                      languages=MILP_LANGUAGES)
