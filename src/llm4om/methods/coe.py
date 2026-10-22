"""Chain-of-Experts: `chain_of_experts` of main.py at the pinned commit as a graph, with its expert, conductor and
reducer prompts.

Each trial: the conductor picks `max_collaborate_nums` experts one by one; each expert comments on the problem with the
comments so far; the reducer writes the final code. With reflection on, the code is tested; on failure the experts are
asked, from the last to the first, whether they caused it, and the first one that says yes refines its comment.
Every trial starts with an empty comment pool, as upstream does: each trial is an independent run.

Adaptations: the starter `code_example` is the platform's empty `build_model` for the selected language instead of a
dataset's `prob_*` function; "Gurobi" in the programmer role names the selected language's library; the test runs that
code in the platform sandbox instead of calling the function on an LLM-generated input (so the evaluator's
test-input prompt is not used).
"""

import ast
import json
import random
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.prompts import PromptTemplate
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.languages import MILP_LANGUAGES
from llm4om.methods import Method, presets
from llm4om.runtime import Context, ModelingState
from llm4om.sandbox import SolveResult

BACKWARD_TASK = '''When you are solving a problem, you get a feedback from the external environment. You need to judge whether this is a problem caused by you or by other experts (other experts have given some results before you). If it is your problem, you need to give Come up with solutions and refined code.

The original problem is as follow:
{problem_description}

The feedback is as follow:
{feedback}

The {previous_label} you give previously is as follow:
{previous_answer}

The output format is a JSON structure followed by refined code:
{{
    {json_quote}is_caused_by_you{json_quote}: false,
    {json_quote}reason{json_quote}: {json_quote}leave empty string if the problem is not caused by you{json_quote},
    {json_quote}refined_result{json_quote}: {json_quote}{refined}{json_quote}
}}
'''
# The upstream backward prompts differ only in these details and in the order of the two middle sections.
BACKWARD_FEEDBACK_LAST = '''When you are solving a problem, you get a feedback from the external environment. You need to judge whether this is a problem caused by you or by other experts (other experts have given some results before you). If it is your problem, you need to give Come up with solutions and refined code.

The original problem is as follow:
{problem_description}

The {previous_label} you give previously is as follow:
{previous_answer}

The feedback is as follow:
{feedback}

The output format is a JSON structure followed by refined code:
{{
    {json_quote}is_caused_by_you{json_quote}: false,
    {json_quote}reason{json_quote}: {json_quote}leave empty string if the problem is not caused by you{json_quote},
    {json_quote}refined_result{json_quote}: {json_quote}{refined}{json_quote}
}}
'''


def _backward(feedback_last: bool, previous_label: str, json_quote: str, refined: str) -> str:
    template = BACKWARD_FEEDBACK_LAST if feedback_last else BACKWARD_TASK
    return template.replace("{previous_label}", previous_label).replace("{json_quote}", json_quote).replace(
        "{refined}", refined)


PROGRAMMER_ROLE = ('You are a Python programmer in the field of operations research and optimization. Your proficiency '
                   'in utilizing third-party libraries such as Gurobi is essential. In addition to your expertise in '
                   'Gurobi, it would be great if you could also provide some background in related libraries or tools, '
                   'like NumPy, SciPy, or PuLP.')
PROGRAMMING_DESCRIPTION = 'Skilled in programming and coding, capable of implementing the optimization solution in a programming language.'
CODE_TASK = '''You are given a specific problem. You aim to develop an efficient Python program that addresses the given problem.
Now the origin problem is as follow:
{problem_description}
Let's analyse the problem step by step, and then give your Python code.
Here is a starter code:
{code_example}
And the comments from other experts are as follow:
{comments_text}

Give your Python code directly.'''


@dataclass(frozen=True)
class Expert:
    name: str
    description: str
    role: str
    forward: str
    backward: str


EXPERTS = [
    Expert('Terminology Interpreter',
           'Provides additional domain-specific knowledge to enhance problem understanding and formulation.',
           'You are a terminology interpreter who provides additional domain-specific knowledge to enhance problem understanding and formulation.',
           '''As a domain knowledge terminology interpreter, your role is to provide additional information and insights related to the problem domain.
Here are some relevant background knowledge about this problem: {knowledge}.

You can contribute by sharing your expertise, explaining relevant concepts, and offering suggestions to improve the problem understanding and formulation.
Please provide your input based on the given problem description:
{problem_description}

Your output format should be a JSON like this (choose at most 3 hardest terminology):
[
  {{
    "terminology": "...",
    "interpretation": "..."
  }}
]
''',
           _backward(False, "answer", "'", "Your refined result")),
    Expert('Parameter Extractor', PROGRAMMING_DESCRIPTION,
           'You are an expert that identifies and extracts relevant variables from the problem statement.',
           '''As a parameter extraction expert, your role is to identify and extract the relevant variables, constrans, objective from the problem statement.
Your expertise in the problem domain will help in accurately identifying and describing these variables.
Please review the problem description and provide the extracted variables along with their definitions:
{problem_description}

And the comments from other experts are as follow:
{comments_text}

Please note that the information you extract is for the purpose of modeling, which means your variables, constraints, and objectives need to meet the requirements of a solvable LP or MIP model. Within the constraints, the comparison operators must be equal to, greater than or equal to, or less than or equal to (> or < are not allowed to appear and should be replaced to be \\geq or \\leq).
''',
           _backward(True, "code", "'", "Your refined code...")),
    Expert('Modeling Expert', 'Proficient in constructing mathematical optimization models based on the extracted information.',
           'You are a modeling expert specialized in the field of Operations Research and Optimization. Your expertise lies in Mixed-Integer Programming (MIP) models, and you possess an in-depth understanding of various modeling techniques within the realm of operations research. At present, you are given an Operations Research problem, alongside additional insights provided by other experts. The goal is to holistically incorporate these inputs and devise a comprehensive model that addresses the given production challenge.',
           '''Now the origin problem is as follow:
{problem_description}
And the comments from other experts are as follow:
{comments_text}

Give your MIP model of this problem. Additionally, please note that your model needs to be a solvable linear programming model or a mixed-integer programming model. This also means that the expressions of the constraint conditions can only be equal to, greater than or equal to, or less than or equal to (> or < are not allowed to appear and should be replaced to be \\geq or \\leq).

Your output format should be a JSON like this:
{{
    "VARIABLES": "A mathematical description about variables",
    "CONSTRAINS": "A mathematical description about constrains",
    "OBJECTIVE": "A mathematical description about objective"
}}
''',
           _backward(False, "modeling", '"', "Your refined result")),
    Expert('Programming Example Provider', PROGRAMMING_DESCRIPTION, PROGRAMMER_ROLE, CODE_TASK,
           _backward(False, "code", '"', "Your refined result")),
    Expert('Programming Expert', PROGRAMMING_DESCRIPTION, PROGRAMMER_ROLE,
           CODE_TASK + ' You should follow the format of given code example strictly. No code is required outside the '
           'function except for the import package (No test code). In your code, the model must be a solvable LP or MIP model.',
           _backward(True, "code", "'", "Your refined code...")),
    Expert('Modeling Knowledge Supplement Expert', PROGRAMMING_DESCRIPTION,
           'You are an experts that offers supplementary knowledge related to modeling techniques and best practices.',
           CODE_TASK, _backward(True, "code", "'", "Your refined code...")),
    Expert('Code Reviewer', PROGRAMMING_DESCRIPTION,
           'You are a code reviewer that conducts thorough reviews of the implemented code to identify any errors, inefficiencies, or areas for improvement.',
           '''As a Code Reviewer, your responsibility is to conduct thorough reviews of implemented code related to optimization problems.
You will identify possible errors, inefficiencies, or areas for improvement in the code, ensuring that it adheres to best practices and delivers optimal results. Now, here is the problem:
{problem_description}.

You are supposed to refer to the comments given by your colleagues from other aspects: {comments_text}''',
           _backward(True, "answer", "'", "Your refined answer...")),
]
EXPERTS_BY_NAME = {expert.name: expert for expert in EXPERTS}

CONDUCTOR = '''you will take on the role of the conductor for a multi-expert system.
Now, you are presented with an operational optimization-related problem:
{problem_description}

In this multi-expert system, there are many experts, each of whom is responsible for solving part of the problem.
Your task is to CHOOSE THE NEXT EXPERT TO CONSULT.

The names of the experts and their capabilities are listed below:
{experts_info}

Experts that have already been commented include:
{commented_experts}

Please select an expert to consult from the remaining expert names {remaining_experts}.

Please note that the maximum number of asked experts is {max_collaborate_nums}, and you can ask {remaining_collaborate_nums} more times.

You should output the name of expert directly. The next expert is:'''

REDUCER = '''You are an expert that responsible for summarize the comment of all other experts then conclude the final answer
Now, you are an expert of Operations Research.
You are supposed to give the final code of an problem.
Text description of the problem: {problem_description}
Your colleagues are all experts in various related fields. They have given their own insights. I hope you will carefully refer to these comments when giving the final code:
{comment_text}

No code is required outside the function except for the import package (No test code).
Your final code is as following:
'''


def _comment_text(comments: list[tuple[str, str]]) -> str:
    """Upstream CommentPool.get_current_comment_text."""
    if not comments:
        return 'There is no comment available, please ignore this section.\n'
    return "".join(f"{name}: ```{text}```\n" for name, text in comments)


def extract_code_from_string(text: str) -> str:
    """Upstream utils.extract_code_from_string: all code blocks joined, without pip lines; the text if none."""
    blocks = re.findall(r'```(?:python)?\s*(.*?)\s*```', text, re.DOTALL)
    if not blocks:
        return text
    if len(blocks) == 1:
        return blocks[0]
    return '\n'.join(code for code in blocks if 'pip' not in code)


def _extract_first_json_blob(text: str) -> str | None:
    starts = [i for i, c in enumerate(text) if c in ['{', '[']]
    for start in starts:
        stack: list[str] = []
        quote_char = None
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if quote_char is not None:
                if escaped:
                    escaped = False
                    continue
                if ch == '\\':
                    escaped = True
                    continue
                if ch == quote_char:
                    quote_char = None
                continue
            if ch in ['"', "'"]:
                quote_char = ch
            elif ch in ['{', '[']:
                stack.append(ch)
            elif ch in ['}', ']']:
                if not stack:
                    break
                left = stack.pop()
                if (left == '{' and ch != '}') or (left == '[' and ch != ']'):
                    break
                if not stack:
                    return text[start:idx + 1]
    return None


def parse_json_from_string(text: Any, expected_type: type | None = None) -> Any:
    """Upstream utils.parse_json_from_string: JSON or a Python literal, from the text, its code block or its first blob."""
    raw = str(text).strip()
    candidates = [raw] if raw else []
    code = extract_code_from_string(raw).strip()
    if code and code not in candidates:
        candidates.append(code)
    for source in (raw, code):
        blob = _extract_first_json_blob(source)
        if blob and blob not in candidates:
            candidates.append(blob)
    for candidate in candidates:
        for parser in (json.loads, ast.literal_eval):
            try:
                value = parser(candidate)
            except (ValueError, SyntaxError, json.JSONDecodeError):
                continue
            if expected_type is not None and not isinstance(value, expected_type):
                continue
            return value
    raise ValueError(f'Cannot parse JSON from text: {raw[:200]}')


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
                            problem_description=state["problem"], code_example=context.target.starter,
                            comments_text=_comment_text(state["_comments"]), knowledge='None')
    if chosen.name == 'Terminology Interpreter':
        output = _terminology_answer(output)
    elif chosen.name == 'Modeling Expert':
        output = output.replace(' < ', ' \\leq ').replace(' > ', ' \\geq ')  # "Meet the rule of MIP"
    return {"comment": output, "_comments": state["_comments"] + [(chosen.name, output)],
            "_stack": state["_stack"] + [chosen.name]}


async def reducer(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    answer = await _predict(runtime.context, "reducer", REDUCER, problem_description=state["problem"],
                            comment_text=_comment_text(state["_comments"]))
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
    reply = await _predict(context, f"{previous.name} (backward)", _role(previous, context) + '\n' + previous.backward,
                           problem_description=state["problem"], previous_answer=previous_comment,
                           feedback=_comment_text(pool))
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
             languages=MILP_LANGUAGES)
