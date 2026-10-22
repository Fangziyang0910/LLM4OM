"""LLMOPT prompt text, verbatim from https://github.com/antgroup/LLMOPT at commit
1492dd33e39ea13f1afe32a0adc13d4217334195: prompts/generate_prompt.py, then prompts/self_correction_prompt.py.

The repository states no license; the text is included for research reproduction only (see NOTICE).
"""

# --- prompts/generate_prompt.py ---

ques_description = "The following is an optimization problem. "

five_description_complex = """In mathematics, any optimization problem can be modeled as the following expression $\\\\min_{\\\\boldsymbol{x} \\\\in \\\\mathcal{X}} f(\\\\boldsymbol{x}), {\\\\rm s.t.} g(\\\\boldsymbol{x}) \\\\leq b$, where $\\\\boldsymbol{x} = (x_1, x_2, \\\\ldots, x_d)^\\\\top$ is the $d$-dimensional decision variable, $\\\\mathcal{X} \\\\subset \\\\mathbb{R}^d$ is the feasible domain, $f: \\\\mathcal{X} \\\\rightarrow \\\\mathbb{R}$ is the objective function and the goal is to find the minima of $f$, $g(\\\\boldsymbol{x}) \\\\leq b$ is the constraint of $\\\\boldsymbol{x}$. 
The above definition can be mapped to a five-element consisting of ``Variables, Objective, Constraints, Sets, Parameters\\'\\'. Variables indicates what $\\\\boldsymbol{x}$ is, Objective describes the form of the objective function $f(\\\\boldsymbol{x})$, and Constraints indicates the constraints $g(\\\\boldsymbol{x})$ and $\\\\mathcal{X}$. These three can abstract the optimization problem. Sets and Parameters are their specific explanations: Sets describes and explains the subscripts of the vectors or matrices in them, and Parameters supplements their specific values. 
"""

five_description_simple = "The five-element model is the abstraction of an optimization problem, which transforms specific problem scenarios into formal mathematical problems. You need to write the corresponding Pyomo code based on the five-element model provided. "

ques_description_code = """You need to write the corresponding Pyomo code based on the problem description and information provided. 
The problem description is as follows: 
"""

ques_description_five = """You need to write the corresponding five-element model based on the problem description and information provided. 
The problem description is as follows: 
"""

five_description_code = "The following is the five-element model of an optimization problem: "

five_suffix = """Please write the corresponding five-element model. Please use LaTeX and ``` plain text environment to complete the following template to model the above optimization problem into five elements: 

```
## Sets: 
[You need to fill in]

## Parameters: 
[You need to fill in]

## Variables: 
[You need to fill in]

## Objective: 
[You need to fill in]

## Constraints: 
[You need to fill in]
```
"""

code_suffix = """Please write the corresponding Pyomo code. Please add `from pyomo.environ import *` at the beginning of your code (You can add other `import` as well). Please print the optimal solution and the value of the objective function. Please do not output the running log. You need to write it in the form of a class and add a main function: 

```python
[write your code here]
```
"""

bound_symbol = """
```
"""

generate_system_info = "You are an expert in the field of operations and optimization. You need to complete some optimization problem modeling tasks."

id_gt = """Identify the optimal value corresponding to the solution of the problem in the following string. Your output only needs to be a numeric value. If you encounter an exception, please output "NAN". 
Here is the problem:
"""




def Q2F(ques):
    ques = bound_symbol + ques + bound_symbol
    return five_description_complex + ques_description_five + ques + five_suffix


def Q2C(ques):
    ques = bound_symbol + ques + bound_symbol
    return ques_description + ques_description_code + ques + code_suffix


def QF2C(ques, five):
    ques = bound_symbol + ques + bound_symbol
    five = bound_symbol + five + bound_symbol
    return ques_description + ques_description_code + ques + five_description_code + five + code_suffix


def F2C(five):
    five = bound_symbol + five + bound_symbol
    return five_description_simple + five_description_code + five + code_suffix


# --- prompts/self_correction_prompt.py ---
def self_correction(ques, five, code, output, error):
    return f"""For the following optimization problem, modeling is performed, and pyomo code is generated and executed based on the modeling. Please judge whether the modeling and code are correct.
        The problem is as follows.

        {ques}

        The five-element formulation is as follows.

        {five}

        The code is as follows.

        {code}

        Run the code and get the following running information. 

        {output}
        {error}

        Please judge whether the above five-element and code are correct, and give your analysis according to the template below.

        ```
        The five-element is [Fill in True/False here].

        The code is [Fill in True/False here].

        Analysis:
        [Fill in your analysis here]
        ```"""

