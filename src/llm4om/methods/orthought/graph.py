"""ORThought: `ORThoughtModelAgent` (mode "formalized") and `ORThoughtSolveAgent` of `workflow.py` at the pinned commit.

One call writes an expert-guided solution path, the mathematical model and code (`formalized_solution_path_prompt`).
While the code fails to run, a debug call (`debug_prompt`) reads the problem, the model, the code and the error and
returns corrected code, up to `debug_max_try` times (3 in upstream `main.sh`). The run keeps the last code.

Prompts are the upstream text. Adaptations: the code requests name the platform code contract instead of "a callable
function whose parameters have default values ... and whose return value is the optimal objective function value",
"Gurobipy" names the selected language's library, and code runs in the platform sandbox.
"""

import re
from dataclasses import asdict
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.methods import Method, presets
from llm4om.methods.orthought import prompts
from llm4om.runtime import Context, ModelingState

UPSTREAM_CODE_SECTION = """Translate your mathematical model into a complete and executable Gurobipy Python function(Everything should be defined inside of the function).
- The function has arguments **with default values extracted directly from the provided problem description**
- The function should return only the optimal objective function value if a feasible solution is found, or `None` if the problem is infeasible or unbounded.
- Enclose the Python code within **```python** and **```** tags.
"""
CODE_SECTION = """Translate your mathematical model into complete and executable Gurobipy Python code that follows the code contract below.
- Enclose the Python code within **```python** and **```** tags.

{contract}
"""
UPSTREAM_DEBUG_CONTRACT = ("  - The code should be a callable function whose parameters have default values and whose return value is "
                           "the optimal objective function value of the model (if it exists), otherwise return None.\n")
DEBUG_CONTRACT = "  - The code must follow the code contract below.\n\n{contract}\n"
assert UPSTREAM_CODE_SECTION in prompts.formalized_solution_path_prompt
assert UPSTREAM_DEBUG_CONTRACT in prompts.debug_prompt


class State(ModelingState, total=False):
    solution_path: str  # the reasoning before the model: understanding the problem, then building the model
    debug_round: int


async def _ask(context: Context, role: str, prompt: str) -> str:
    model = context.llm(role).bind(temperature=presets.ORTHOUGHT.temperature)
    return (await model.ainvoke([HumanMessage(prompt.replace("Gurobipy", context.target.library))])).text


def _code(reply: str) -> str:
    """Upstream extract_code_model: the longest ```python (or ```code) block, else the <code> block."""
    if "```python\n```python" in reply:
        reply = reply.replace("```python\n```python", "```python", 1)
    blocks = re.findall(r"```(?:python|code)\s*\n(.*?)\n```", reply, re.S)
    # llm4om: upstream ignores blocks of 400 characters or less; a build_model function is often shorter.
    if blocks:
        return max(blocks, key=lambda block: len(block.strip())).strip() + "\n"
    found = re.search(r"<code>\s*\n(.*?)\n</code>", reply, re.S)
    return found.group(1).strip() + "\n" if found else "No code found"


def _target_text(reply: str, mark: str) -> str:
    """Upstream extract_target_text: the text after the last <mark> line, up to </mark>."""
    start = reply.rfind(f"<{mark}>")
    if mark == "code" and start == -1:
        start = reply.rfind("```python")
    if start == -1:
        return "No target text found"
    start = reply.find("\n", start) + 1
    end = reply.find(f"</{mark}>", start)
    if mark == "code" and end == -1:
        end = reply.find("```", start)
    return reply[start:end].strip()


async def model(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    prompt = prompts.formalized_solution_path_prompt.format(nlp=state["problem"]).replace(
        UPSTREAM_CODE_SECTION, CODE_SECTION.format(contract=context.target.prompt))
    reply = await _ask(context, "model", prompt)
    found = re.search(r"```(?:model|latex|markdown)\s*\n(.*?)\n```", reply, re.S)
    return {"solution_path": _target_text(reply, "solution_path"),
            "formulation": found.group(1).strip() if found else "No model found", "code": _code(reply)}


async def execute(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    rounds = state.get("debug_round", 0)
    return {"solve": await runtime.context.solve(state["code"] or "", title="执行代码" if rounds == 0 else f"执行代码（调试 {rounds}）")}


async def debug(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    assert state["solve"] is not None
    prompt = prompts.debug_prompt.format(nlp=state["problem"], model_text=state["formulation"], code_text=state["code"],
                                         error_message=state["solve"].feedback())
    reply = await _ask(context, "debug", prompt.replace(UPSTREAM_DEBUG_CONTRACT, DEBUG_CONTRACT.format(contract=context.target.prompt)))
    code = _target_text(reply, "code")
    return {"code": code + "\n", "debug_round": state.get("debug_round", 0) + 1}


def after_execute(state: State) -> str:
    assert state["solve"] is not None
    failed = not state["solve"].executed
    return "debug" if failed and state.get("debug_round", 0) < presets.ORTHOUGHT.debug_max_try else END


def orthought_graph():
    graph = StateGraph(State, context_schema=Context)
    for node in (model, execute, debug):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "model")
    graph.add_edge("model", "execute")
    graph.add_conditional_edges("execute", after_execute, ["debug", END])
    graph.add_edge("debug", "execute")
    return graph.compile(name="orthought")


ORTHOUGHT = Method("orthought", "ORThought",
                   "按专家建模思路一次写出求解思路、数学模型和代码；代码无法运行时，带上模型和错误信息调试，"
                   f"最多 {presets.ORTHOUGHT.debug_max_try} 次。", orthought_graph,
                   "https://github.com/BeinuoYang/ORThought/tree/5293e24861a65d1e4a2f61f4fad0a81de901ee38",
                   titles={"model": "求解思路、数学模型与代码", "debug": "按错误调试代码"},
                   hidden=frozenset({"debug_round"}),
                   parameters=lambda: asdict(presets.ORTHOUGHT))
