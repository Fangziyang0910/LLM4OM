"""LLMOPT: the test-time pipeline of `inference/inference_q2f2c.py` at the pinned commit, with the paper's self-correction.

The LLM writes the five-element formulation (sets, parameters, variables, objective, constraints) from the problem
(`Q2F`), then code from the five-element alone (`F2C`); the code runs. A self-correction call (`self_correction`)
reads the problem, both artifacts and the execution result and judges each True or False. A false five-element
sends the run back to the formulation step, a false code back to the code step; both true ends the run. The paper
(arXiv 2410.13213, Section 4.1) allows at most 12 re-solves. The run keeps the last attempt.

LLMOPT's main contribution is a fine-tuned model (LLMOPT-Qwen2.5-14B on Hugging Face). This port runs the
pipeline with the chosen preset; serve the fine-tuned model behind an OpenAI-compatible preset to run the original.

Prompts are the upstream text, sent as one user message as in `inference_q2f2c.py`. Adaptations: the code request
names the platform code contract instead of "Pyomo code ... print the optimal solution ... in the form of a class and
add a main function", "Pyomo" names the selected language's library, and the execution output is the sandbox's
feedback; the self-correction prompt says that the code returns the model and the platform solves it. Upstream has
no loop code; the routing from the two verdicts follows the paper's description, and a reply without a verdict
counts as true.
"""

import re
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.methods import Method, presets
from llm4om.methods.llmopt import prompts
from llm4om.runtime import Context, ModelingState

# Upstream code_suffix, without its Pyomo-specific instructions.
CODE_SUFFIX = "Please write the corresponding {library} code. {contract}\n\n```python\n[write your code here]\n```\n"
# Replaces upstream "pyomo code is generated and executed based on the modeling." in the self-correction prompt.
JUDGE_CONTEXT = ("{library} code is generated based on the modeling. The code defines build_model(data) and returns the "
                 "model without solving it; the platform solves the model and reports the result.")


class State(ModelingState, total=False):
    corrections: int  # re-solves so far
    verdict: dict[str, bool]  # the latest self-correction: five_element and code


async def _ask(context: Context, role: str, prompt: str) -> str:
    return (await context.llm(role).ainvoke([HumanMessage(prompt)])).text


SECTIONS = ("## Sets", "## Parameters", "## Variables", "## Objective", "## Constraints")


def _five_element(reply: str) -> str:
    """Upstream infer_five_elem: the ```text, ```plaintext or first ``` block."""
    block = next((reply.split(fence)[1].split("```")[0].strip() for fence in ("```text", "```plaintext", "```")
                  if fence in reply), "")
    # llm4om: a general LLM often fences each section on its own or none at all; the first block then holds only the
    # sets. Without all five sections in it, take the whole reply without its fence lines.
    if not all(section in block for section in SECTIONS):
        block = re.sub(r"^[ \t]*```.*\n?", "", reply, flags=re.M).strip()
    if not block:
        raise ValueError("The reply contains no five-element formulation.")
    return block


async def define(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    return {"formulation": _five_element(await _ask(runtime.context, "five_element", prompts.Q2F(state["problem"])))}


async def write_code(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    library = context.target.library
    prompt = (prompts.five_description_simple.replace("Pyomo", library) + prompts.five_description_code
              + prompts.bound_symbol + (state["formulation"] or "") + prompts.bound_symbol
              + CODE_SUFFIX.format(library=library, contract=context.target.prompt))
    reply = await _ask(context, "code", prompt)
    if "```python" not in reply:
        raise ValueError("The reply contains no ```python code block.")
    return {"code": reply.split("```python")[1].split("```")[0].strip() + "\n"}


async def execute(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    corrections = state.get("corrections", 0)
    title = "执行代码" if corrections == 0 else f"执行代码（重解 {corrections}）"
    return {"solve": await runtime.context.solve(state["code"] or "", title=title)}


async def self_correct(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    assert state["solve"] is not None
    prompt = prompts.self_correction(state["problem"], state["formulation"], state["code"], state["solve"].feedback(), "")
    # The judge learns the platform contract: the code returns the model, and the platform solves it.
    prompt = prompt.replace("pyomo code is generated and executed based on the modeling.",
                            JUDGE_CONTEXT.format(library=context.target.library), 1)
    reply = await _ask(context, "self_correction", prompt)

    def correct(part: str) -> bool:
        found = re.search(rf"The {part} is\W*(true|false)", reply, re.I)
        return found is None or found.group(1).lower() == "true"

    verdict = {"five_element": correct("five-element"), "code": correct("code")}
    return {"verdict": verdict, "corrections": state.get("corrections", 0) + (not all(verdict.values()))}


def after_execute(state: State) -> str:
    return END if state.get("corrections", 0) >= presets.LLMOPT.max_resolves else "self_correct"


def after_self_correct(state: State) -> str:
    verdict = state["verdict"]
    return "define" if not verdict["five_element"] else "write_code" if not verdict["code"] else END


def llmopt_graph():
    graph = StateGraph(State, context_schema=Context)
    for node in (define, write_code, execute, self_correct):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "define")
    graph.add_edge("define", "write_code")
    graph.add_edge("write_code", "execute")
    graph.add_conditional_edges("execute", after_execute, ["self_correct", END])
    graph.add_conditional_edges("self_correct", after_self_correct, ["define", "write_code", END])
    return graph.compile(name="llmopt")


LLMOPT = Method("llmopt", "LLMOPT",
                f"先写五要素模型（集合、参数、变量、目标、约束），再按它生成代码并执行；LLM 判断模型和代码对错，"
                f"错误时回到对应步骤重写，最多重解 {presets.LLMOPT.max_resolves} 次。", llmopt_graph,
                "https://github.com/antgroup/LLMOPT/tree/1492dd33e39ea13f1afe32a0adc13d4217334195",
                titles={"define": "五要素模型", "write_code": "生成代码", "self_correct": "自我校正"},
                hidden=frozenset({"verdict", "corrections"}))
