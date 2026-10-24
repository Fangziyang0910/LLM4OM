"""TriVAL: semantic, formulation and code validation, each a construct-validate-revise loop.

Ported from the TriVAL repository (stage routing, prompts and loop limits unchanged) with these adaptations:
the platform context supplies the LLM, `code_executor` solves through the platform sandbox, the code agent's
solver-selection and syntax sections are replaced by the platform code target, and an entry node maps the
platform's `problem` to `problem_description`. An exit node reports unresolved validation. See README.md here.
"""

from dataclasses import asdict

from llm4om.methods import Method, presets
from llm4om.methods.trival.graph import create_trival_graph

TITLES = {
    "semantic_fact_extractor": "语义事实与歧义",
    "ambiguity_resolver": "歧义处理",
    "semantic_validator": "语义验证",
    "parameter_index_expert": "候选模型：参数与索引专家",
    "decision_variable_expert": "候选模型：决策变量专家",
    "constraint_expert": "候选模型：约束专家",
    "objective_expert": "候选模型：目标专家",
    "formulation_selector": "选择候选模型",
    "formulation_validator": "数学模型验证",
    "revise_formulation": "局部修订数学模型",
    "code_agent": "生成或修订代码",
    "code_validator": "代码验证",
}
HIDDEN = frozenset({"problem_description", "failure", "code_executable", "execution_feedback", "semantic_validation_count",
                    "formulation_validation_count", "code_execution_count", "code_validation_count"})

TRIVAL = Method("trival", "TriVAL",
                "依次进行语义验证、数学模型验证和代码验证；每个阶段先构建、再验证、不通过就修订，代码缺陷可回溯到数学模型。",
                create_trival_graph, "https://github.com/SCUT-EIPI/TriVAL/tree/380a529", titles=TITLES, hidden=HIDDEN,
                parameters=lambda: asdict(presets.TRIVAL))
