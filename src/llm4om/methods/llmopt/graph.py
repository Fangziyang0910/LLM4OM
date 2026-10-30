"""LLMOPT: the test-time pipeline of `inference/inference_q2f2c.py` at the pinned commit, with the paper's self-correction.

The LLM writes the five-element formulation (sets, parameters, variables, objective, constraints) from the problem
(`Q2F`), then code from the problem and formulation; the code runs. Unlike upstream's formulation-only `F2C`, this
platform variant keeps the original description and complete data files at the code boundary. A self-correction call
reads the problem, both artifacts and the execution result and judges each True or False. A false five-element
sends the run back to the formulation step, a false code back to the code step; both true ends the run. The paper
(arXiv 2410.13213, Section 4.1) allows at most 12 re-solves. The run keeps the last attempt.

LLMOPT's main contribution is a fine-tuned model (LLMOPT-Qwen2.5-14B on Hugging Face). This port runs the
pipeline with the chosen preset; serve the fine-tuned model behind an OpenAI-compatible preset to run the original.

Upstream prompt text is preserved in prompts.py, sent as one user message as in `inference_q2f2c.py`. The platform
adds source-data rules and uses the problem-plus-formulation code context (recorded in method parameters); this is
not an unchanged F2C reproduction. Adaptations: the code request
names the platform code contract instead of "Pyomo code ... print the optimal solution ... in the form of a class and
add a main function", "Pyomo" names the selected language's library, and the execution output is the sandbox's
feedback; the self-correction prompt says that the code returns the model and the platform solves it. Upstream has
no loop code; the routing from the two verdicts follows the paper's description. Rejected steps receive the
actual self-correction, and a missing or conflicting verdict is reported as a failed review.
"""

import re
from dataclasses import asdict
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
SOURCE_RULES = ("\n\nSource-data requirements: The original problem and attached data files are the factual source for "
                "entity IDs, coordinates, demands, coefficients, bounds and units. The formulation describes the model "
                "structure; it does not replace those source facts. Preserve the supplied values and their associations "
                "with original IDs. Do not invent, substitute, or silently repair input values, and do not use sample "
                "or default data to fill gaps. If the formulation conflicts with the source, identify the discrepancy "
                "rather than silently choosing invented values.")
MISSING_DATA = "MISSING_PROBLEM_DATA:"


class State(ModelingState, total=False):
    corrections: int  # re-solves so far
    verdict: dict[str, bool]  # the latest self-correction: five_element and code
    reflection: str  # exact judge reply, visible in the process and used by the rejected step


async def _ask(context: Context, role: str, prompt: str) -> str:
    return (await context.llm(role).ainvoke([HumanMessage(prompt)])).text


SECTIONS = ("## Sets", "## Parameters", "## Variables", "## Objective", "## Constraints")


def _source_problem(state: State, context: Context) -> str:
    # The platform's problem preview can truncate attachments; code and review need their complete source text.
    parts = ["## Problem description\n" + (state.get("description") or state["problem"])]
    parts.extend(f"## Data file `{name}`\n```\n{content}\n```" for name, content in context.data.items())
    return "\n\n".join(parts)


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
    prompt = prompts.Q2F(_source_problem(state, runtime.context)) + SOURCE_RULES
    prompt += ("\nKeep the supplied numerical values explicit in the Parameters section, or reference the supplied "
               "file and its exact fields. Do not replace a necessary data table with an ellipsis or a reference "
               "to an unavailable table. Identify essential missing data without inventing it.")
    if state.get("reflection"):
        prompt += (f"\n\nPrevious five-element formulation:\n{state.get('formulation') or ''}"
                   f"\n\nSelf-correction feedback:\n{state['reflection']}"
                   "\nRevise the rejected formulation using this feedback and the original problem.")
    return {"formulation": _five_element(await _ask(runtime.context, "five_element", prompt))}


async def write_code(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    library = context.target.library
    prompt = (prompts.ques_description + prompts.ques_description_code.replace("Pyomo", library)
              + prompts.bound_symbol + _source_problem(state, context) + prompts.bound_symbol
              + prompts.five_description_code
              + prompts.bound_symbol + (state["formulation"] or "") + prompts.bound_symbol
              + CODE_SUFFIX.format(library=library, contract=context.target.prompt))
    if state.get("reflection"):
        prompt += (f"\n\nPrevious code:\n```python\n{state.get('code') or ''}```"
                   f"\n\nSelf-correction feedback:\n{state['reflection']}"
                   f"\n\nPrevious execution:\n{state['solve'].feedback() if state.get('solve') else ''}"
                   "\nImplement the current formulation, addressing the feedback without relaxing its requirements.")
    prompt += SOURCE_RULES
    prompt += ("\nRead the complete original problem and attached source files even when the formulation abbreviates "
               "them. Verify every hardcoded input against those sources, and use the supplied data mapping when "
               "reading attachments. If essential input data is genuinely absent or contradictory and no unique "
               f"model can be built, reply only with '{MISSING_DATA} <specific missing or conflicting fields>' "
               "instead of a Python block. Never supply a fabricated default dataset to make the code runnable.")
    reply = await _ask(context, "code", prompt)
    if reply.strip().startswith(MISSING_DATA):
        raise ValueError("LLMOPT cannot generate code without the required source data: "
                         + reply.strip()[len(MISSING_DATA):].strip())
    if "```python" not in reply:
        raise ValueError("The reply contains no ```python code block.")
    return {"code": reply.split("```python")[1].split("```")[0].strip() + "\n"}


async def execute(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    corrections = state.get("corrections", 0)
    title = "执行代码" if corrections == 0 else f"执行代码（重解 {corrections}）"
    result = {"solve": await runtime.context.solve(state["code"] or "", title=title)}
    if corrections >= presets.LLMOPT.max_resolves:
        result["failure"] = (f"LLMOPT self-correction reached its limit of {presets.LLMOPT.max_resolves} re-solves; "
                             "the final attempt has not passed review.")
    return result


async def self_correct(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    assert state["solve"] is not None
    prompt = prompts.self_correction(_source_problem(state, context), state["formulation"], state["code"],
                                     state["solve"].feedback(), "")
    # The judge learns the platform contract: the code returns the model, and the platform solves it.
    prompt = prompt.replace("pyomo code is generated and executed based on the modeling.",
                            JUDGE_CONTEXT.format(library=context.target.library), 1)
    prompt += SOURCE_RULES
    prompt += ("\nBefore judging, compare the formulation and implemented input data with the original problem and "
               "complete attachments: check entity IDs, coordinates, demands, coefficients and units, including "
               "their row/column associations. Report specific mismatches or fabricated defaults in Analysis and "
               "mark the affected artifact False. Judge formulation structure separately from code data errors. "
               "An optimal solver status does not prove that the code used the correct problem data.")
    reply = await _ask(context, "self_correction", prompt)

    plain = re.sub(r"[*`]", "", reply)

    def correct(part: str) -> bool:
        # Require a template verdict line, but include verdicts with explanations when checking for conflicts.
        pattern = rf"\bThe {part} is\s*[\[(]?\s*(true|false)\b"
        matches = re.findall(pattern, plain, re.I)
        values = {value.lower() for value in matches}
        verdict_line = re.search(rf"^\s*(?:[-+]\s+)?{pattern}\s*[\])]?\s*[.!]?\s*$", plain, re.I | re.M)
        if verdict_line is None or len(values) != 1:
            raise ValueError(f"Missing or conflicting verdict for {part}.")
        return values == {"true"}

    try:
        verdict = {"five_element": correct("five-element"), "code": correct("code")}
    except ValueError as error:
        return {"reflection": reply, "failure": f"Could not read LLMOPT self-correction: {error}"}
    result = {"reflection": reply, "verdict": verdict,
              "corrections": state.get("corrections", 0) + (not all(verdict.values()))}
    if all(verdict.values()) and not state["solve"].executed:
        result["failure"] = "LLMOPT self-correction accepted code that did not execute successfully."
    return result


def after_execute(state: State) -> str:
    return END if state.get("corrections", 0) >= presets.LLMOPT.max_resolves else "self_correct"


def after_self_correct(state: State) -> str:
    if state.get("failure"):
        return END
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
                hidden=frozenset({"verdict", "corrections"}),
                parameters=lambda: {**asdict(presets.LLMOPT), "code_context": "problem_and_formulation"})
