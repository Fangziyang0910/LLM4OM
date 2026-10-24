"""Chain-of-Experts: `chain_of_experts` of main.py at the pinned commit as a graph, with its expert, conductor and
reducer prompts.

Each trial: the conductor picks `max_collaborate_nums` experts one by one; each expert comments on the problem with the
comments so far; the reducer writes the final code. With reflection on, the code is tested; on failure the experts are
asked, from the last to the first, whether they caused it, and the first one that says yes refines its comment.
Every trial starts with an empty comment pool, as upstream does: each trial is an independent run.

Adaptations: the starter `code_example` is the platform's native reference and code contract instead of a
dataset's `prob_*` function; "Gurobi" in the programmer role names the selected language's library; the test runs that
code in the platform sandbox instead of calling the function on an LLM-generated input (so the evaluator's
test-input prompt is not used).
"""

import random
from dataclasses import asdict
from typing import Any

from langchain_core.prompts import PromptTemplate
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.methods import Method, presets
from llm4om.methods.coe.parsing import extract_code_from_string, parse_json_from_string
from llm4om.methods.coe.prompts import CONDUCTOR, EXPERTS, EXPERTS_BY_NAME, REDUCER, Expert
from llm4om.runtime import Context, ModelingState
from llm4om.sandbox import SolveResult


def _comment_text(comments: list[tuple[str, str]]) -> str:
    """Upstream CommentPool.get_current_comment_text."""
    if not comments:
        return 'There is no comment available, please ignore this section.\n'
    return "".join(f"{name}: ```{text}```\n" for name, text in comments)


async def _predict(context: Context, role: str, template: str, bind: dict[str, Any] | None = None, **values: Any) -> str:
    """Upstream PromptModelChain: the formatted template as one user message, temperature 0."""
    prompt = PromptTemplate.from_template(template).invoke(values)
    return (await context.llm(role).bind(temperature=presets.COE.temperature, **(bind or {})).ainvoke(prompt)).text


def _role(expert: Expert, context: Context) -> str:
    return expert.role.replace("Gurobi", context.target.library)


def _terminology_answer(output: str) -> str:
    try:
        parsed: Any = parse_json_from_string(output)
    except ValueError:
        parsed = output
    if isinstance(parsed, dict):
        parsed = [parsed]
    answer = ''
    if isinstance(parsed, list):
        for item in parsed:
            if isinstance(item, dict) and not (item.get('terminology') is None and item.get('interpretation') is None):
                answer += f"{item.get('terminology')}:{item.get('interpretation')}\n"
    return answer if answer.strip() else str(output).strip()


def _test_feedback(result: SolveResult) -> str | None:
    """Upstream Evaluator.evaluate: None when the code runs, else the error with its traceback."""
    if result.executed:
        return None
    error = result.error or ''
    kind = 'There is grammar error in generated code!\n' if 'SyntaxError' in error else 'Runtime error!\n'
    return kind + error + '\n'


class State(ModelingState, total=False):
    trial: int
    expert: str  # the expert the conductor chose
    comment: str  # that expert's comment
    _comments: list[tuple[str, str]]  # the comment pool of this trial: (expert, comment)
    _stack: list[str]  # experts in the order they commented
    feedback: str | None  # the test result of the reducer's code
    _feedback_pool: list[tuple[str, str]]
    blamed: str | None  # the expert that said it caused the failure


def _collaborate_nums() -> int:
    return min(presets.COE.max_collaborate_nums, len(EXPERTS))


def start_trial(state: State) -> dict[str, Any]:
    return {"trial": state.get("trial", 0) + 1, "_comments": [], "_stack": [], "blamed": None}


async def conductor(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    collaborate_nums = _collaborate_nums()
    commented = [name for name, _ in state["_comments"]]
    remaining = [expert for expert in EXPERTS if expert.name not in commented]
    experts_info = '\n'.join(f'{expert.name}: {expert.description}' for expert in EXPERTS)
    choice = await _predict(context, "conductor", CONDUCTOR, bind={"max_tokens": 10}, problem_description=state["problem"],
                            experts_info=experts_info, commented_experts=str(commented),
                            remaining_experts=str([e.name for e in remaining]), max_collaborate_nums=collaborate_nums,
                            remaining_collaborate_nums=max(0, collaborate_nums - len(commented)))
    rng = random.Random(f"{state['trial']}-{len(commented)}")
    expert = (next((e for e in remaining if e.name in choice), None) or next((e for e in EXPERTS if e.name in choice), None)
              or rng.choice(remaining or EXPERTS))
    return {"expert": expert.name}


async def expert(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    chosen = EXPERTS_BY_NAME[state["expert"]]
    output = await _predict(context, chosen.name, _role(chosen, context) + '\n' + chosen.forward,
                            problem_description=state["problem"], code_example=context.target.prompt,
                            comments_text=_comment_text(state["_comments"]), knowledge='None')
    if chosen.name == 'Terminology Interpreter':
        output = _terminology_answer(output)
    elif chosen.name == 'Modeling Expert':
        output = output.replace(' < ', ' \\leq ').replace(' > ', ' \\geq ')  # "Meet the rule of MIP"
    return {"comment": output, "_comments": state["_comments"] + [(chosen.name, output)],
            "_stack": state["_stack"] + [chosen.name]}


async def reducer(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    answer = await _predict(runtime.context, "reducer", REDUCER + '\n\n{code_contract}', problem_description=state["problem"],
                            comment_text=_comment_text(state["_comments"]), code_contract=runtime.context.target.prompt)
    return {"code": extract_code_from_string(answer)}


async def evaluate(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    result = await runtime.context.solve(state["code"] or "", title=f"测试代码（第 {state['trial']} 轮）")
    feedback = _test_feedback(result)
    return {"feedback": feedback, "_feedback_pool": [("Evaluator", feedback)] if feedback else []}


async def backward(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """Ask the most recent remaining expert whether it caused the failure."""
    context = runtime.context
    stack, comments, pool = list(state["_stack"]), list(state["_comments"]), list(state["_feedback_pool"])
    previous = EXPERTS_BY_NAME[stack.pop()]
    previous_name, previous_comment = comments.pop()
    reply = await _predict(context, f"{previous.name} (backward)", _role(previous, context) + '\n' + previous.backward + '\n\n{code_contract}',
                           problem_description=state["problem"], previous_answer=previous_comment,
                           feedback=_comment_text(pool), code_contract=context.target.prompt)
    try:
        result = parse_json_from_string(reply, expected_type=dict)
    except ValueError:
        return {"_stack": stack, "_comments": comments, "_feedback_pool": pool + [(previous.name, reply)]}
    if result.get('is_caused_by_you'):
        refined = result.get('refined_result', previous_comment)
        return {"_stack": stack + [previous.name], "_comments": comments + [(previous_name, refined)],
                "blamed": previous.name, "comment": refined}
    return {"_stack": stack, "_comments": comments, "_feedback_pool": pool + [(previous.name, result.get('reason', ''))]}


def finish(state: State) -> dict[str, Any]:
    formulation = "\n\n".join(text for name, text in state["_comments"] if name == 'Modeling Expert')
    return {"formulation": formulation or None}


def after_expert(state: State) -> str:
    return "conductor" if len(state["_stack"]) < _collaborate_nums() else "reducer"


def after_reducer(state: State) -> str:
    return "evaluate" if presets.COE.enable_reflection else "finish"


def after_evaluate(state: State) -> str:
    return "finish" if state["feedback"] is None else "backward"


def after_backward(state: State) -> str:
    if not state.get("blamed") and state["_stack"]:
        return "backward"
    return "start_trial" if state["trial"] < presets.COE.max_trials else "finish"  # backward runs with reflection on


def coe_graph():
    graph = StateGraph(State, context_schema=Context)
    for node in (start_trial, conductor, expert, reducer, evaluate, backward, finish):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "start_trial")
    graph.add_edge("start_trial", "conductor")
    graph.add_edge("conductor", "expert")
    graph.add_conditional_edges("expert", after_expert, ["conductor", "reducer"])
    graph.add_conditional_edges("reducer", after_reducer, ["evaluate", "finish"])
    graph.add_conditional_edges("evaluate", after_evaluate, ["backward", "finish"])
    graph.add_conditional_edges("backward", after_backward, ["backward", "start_trial", "finish"])
    graph.add_edge("finish", END)
    return graph.compile(name="coe")


COE = Method("coe", "Chain-of-Experts",
             "协调者逐个挑选专家发表意见，汇总器给出最终代码；开启反思时，测试失败后从后往前询问专家是否由自己导致。", coe_graph,
             "https://github.com/xzymustbexzy/Chain-of-Experts/tree/afb89bf602690ea621f13a23c42722f20f653a43",
             titles={"start_trial": "开始一轮", "conductor": "协调者选择专家", "expert": "专家意见", "reducer": "汇总代码",
                     "evaluate": "测试代码", "backward": "反向反思", "finish": "数学模型"},
             linear_only=True,
             parameters=lambda: asdict(presets.COE))
