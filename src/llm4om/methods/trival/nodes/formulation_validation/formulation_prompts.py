FORMULATION_SHARED_RULES: str = """
1. Only base on given semantic information: strictly model based on problem_description, semantic_facts, ambiguity_resolutions; do not introduce new assumptions, new constraints, new objectives, or new parameter meanings beyond the problem statement.
2. Only output mathematical formulation: only output the four parts of formulation (parameters / variables / constraints / objective), do not output any other titles, explanations, processes, or comments.
3. No implementation or solving: must not include solver names, algorithm strategies, Big-M/ε, linearization details, encoding/data structures, or other implementation content.
4. Consistent symbols and indices: all symbols used in constraints and objectives must be defined first in parameters or variables; names, index sets, and types are globally consistent with self-consistent dimensions.
5. Semantic fidelity and simplicity: variables and constraints must accurately express the problem semantics; avoid redundant constraints and unnecessary auxiliary variables (keep the model lean).
""".strip()

FORMULATION_FORMAT_PROMPT: str = """
Output the formulation in Markdown format, containing only four top-level sections: parameters, variables, constraints, and objectives. Do not output any other top-level titles or text.

Section Schema Requirements:
1) parameters: List all known data used by the model. For each entry, provide: description, value, and unit (if applicable).
2) variables: List all decision variables. For each entry, provide: description, var_type (real | int | bool), domain, shape (scalar | [i] | [i,j] | ...), and unit (if applicable).
3) constraints: List all constraints. For each entry, provide: description and expr.
4) objectives: List the objective(s). For each entry, provide: description, type (min | max | satisfy), and expr. If type is satisfy, expr may be omitted.
""".strip()
