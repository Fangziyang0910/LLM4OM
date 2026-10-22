"""Upstream expert definitions and prompts for Chain-of-Experts."""

from dataclasses import dataclass

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
