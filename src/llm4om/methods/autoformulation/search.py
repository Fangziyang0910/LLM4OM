"""Pure helpers of the upstream search (MCTS_used.py and utils_metrics.py at 5214801), ported line by line."""

import math
import re
from dataclasses import dataclass, field
from typing import Any

from llm4om.methods import presets
from llm4om.methods.autoformulation.upstream import prompts as P
from llm4om.sandbox import SolveResult

# ---- MCTS_used.py: node checks ----

def parse_dict_with_comments(constraints_dict: dict, comments_list: list) -> str:
    result = "{\n"
    for (key, value), comment in zip(constraints_dict.items(), comments_list):
        if comment:
            result += f"    # {comment}\n"
        # llm4om: values are strings, but can themselves contain quotes or line breaks.
        result += f"    {str(key)!r}: {str(value)!r},\n\n"
    result = result.rstrip(",\n\n") + "\n}"
    return result


def extract_comment(constraints_str: str, key: Any) -> str | None:
    pattern = r"#(.+)\n\s*'{}':".format(re.escape(str(key)))
    match = re.search(pattern, constraints_str)
    return match.group(1).strip() if match else None


def create_dict_string(this_dict_eval: dict, this_dict_str: str) -> str:
    """Re-compose a dict-string preserving comments found in the original text."""
    all_comments = [extract_comment(this_dict_str, key) for key in this_dict_eval]
    return parse_dict_with_comments(this_dict_eval, all_comments)


def check_constraints_for_correctness_obj(objective_dict: dict) -> bool:
    """Ensure objective has a single entry and does not contain '#'."""
    if len(objective_dict) != 1:
        return False
    return "#" not in list(objective_dict.values())[0]


def solution_prompt(step: str, forms: list[dict]) -> str:
    """ReasoningMCTSNode._get_solution_prompt over the candidates' formalization strings."""
    text = ""
    for idx, form in enumerate(forms):
        if idx == 0:
            text = "\\ \\n["
        text += f"{step}_{idx}: {form[step]}\n"
    return text + "]"


def compute_ranking(pairwise_comparisons: dict[int, dict[int, float]]) -> list[int]:
    """Bradley-Terry ranking by logistic regression, best first."""
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    data, labels = [], []
    solutions = sorted(set(pairwise_comparisons) | {j for sub in pairwise_comparisons.values() for j in sub})
    for i in solutions:
        for j in solutions:
            if i < j:
                score_ij = pairwise_comparisons.get(i, {}).get(j, None)
                score_ji = pairwise_comparisons.get(j, {}).get(i, None)
                if score_ij is not None:
                    if score_ij > 0.5:
                        data.append([i, j])
                        labels.append(1)
                    elif score_ij < 0.5:
                        data.append([i, j])
                        labels.append(0)
                elif score_ji is not None:
                    if score_ji > 0.5:
                        data.append([i, j])
                        labels.append(0)
                    elif score_ji < 0.5:
                        data.append([i, j])
                        labels.append(1)
    if len(set(labels)) < 2:
        raise ValueError("Insufficient variation in labels. The model requires both wins and losses.")
    x = np.zeros((len(data), max(solutions) + 1))
    for idx, (i, j) in enumerate(data):
        x[idx, i] = 1
        x[idx, j] = -1
    model = LogisticRegression(fit_intercept=False, solver="lbfgs")
    model.fit(x, np.array(labels))
    abilities = model.coef_[0]
    return [int(solution) for solution in np.argsort(-abilities) if solution in solutions]


# ---- utils_metrics.py: pairwise comparison of complete formalizations ----

def comparison_prompt(sol1: Any, sol2: Any, problem_str: str, library: str) -> str:
    """obtain_prompt_solution_compar_string_form_2; for other languages "Gurobipy" names the selected language's library."""
    this_prompt = P.INST_RANK_FINAL_STEP_2 if library == "Gurobi" else P.INST_RANK_FINAL_STEP_2.replace("Gurobipy", library)
    this_prompt = this_prompt.replace("###PROBLEM DESCRIPTION###", problem_str)
    this_prompt = this_prompt.replace("solution_A = {}", f'solution_A = \\\n"""{str(sol1)}\n"""')
    return this_prompt.replace("solution_B = {}", f'solution_B = \\\n"""{str(sol2)}\n"""')


def extract_best_solution(text: str) -> dict[str, str]:
    """extract_dictionary_rank_final_form_2."""
    dict_pattern = re.search(r'best_solution\s*=\s*\{(.*?)\}', text, re.DOTALL)
    if not dict_pattern:
        return {}
    key_value_pairs = re.findall(r'(\d+):\s*["\'\s]?(solution_A|solution_B)["\'\s]?', dict_pattern.group(1).strip())
    return {str(key): str(value) for key, value in key_value_pairs}


STEPS = {1: "parameters", 2: "decision_variables", 3: "objective", 4: "equality_constraints", 5: "inequality_constraints"}


@dataclass
class Node:
    """ReasoningMCTSNode without the files: one partial formalization."""

    id: int
    depth: int
    form_dict_str: dict[str, str]
    form_dict_eval: dict[str, Any]
    parent: int | None = None
    idx: int = 0  # position among the parent's parsed samples
    status: str = "kept"  # kept, empty, incorrect, clustered or low-scored
    run_code: bool = True
    correct: bool = True
    output: str = ""  # the check script output, or the solver feedback of a complete formulation
    solve: SolveResult | None = None
    r0: float = 0.0  # the prior reward from the parent's ranking
    children: list[int] = field(default_factory=list)

    @property
    def step(self) -> str | None:
        return STEPS.get(self.depth)

    @property
    def achieved(self) -> bool:
        return self.solve is not None and self.solve.objective is not None


@dataclass
class Search:
    """The MCTS object's bookkeeping, keyed by node id."""

    N: dict[int, int] = field(default_factory=dict)
    Q: dict[int, float] = field(default_factory=dict)
    order: dict[int, int] = field(default_factory=dict)  # leaf -> order of first visit
    comparisons: dict[int, dict[int, float]] = field(default_factory=dict)
    baselines: list[int] = field(default_factory=list)
    r_baseline: dict[int, float] = field(default_factory=dict)
    dumb: list[int] = field(default_factory=list)  # visited leaves without a solution
    ranking: list[int] | None = None  # leaf orders, best first
    attempts: int = 0
    effective: int = 0


def _uct(search: Search, node: Node, log_n: float) -> float:
    preset, n = presets.AUTOFORMULATION, search.N.get(node.id, 0)
    if n == 0:
        return node.r0 + preset.w_exp * math.sqrt(log_n)
    value = preset.lambda_cte * node.r0 + (1 - preset.lambda_cte) * search.Q[node.id] / n
    return value + preset.w_exp * math.sqrt(log_n / n)


def _ranking(search: Search) -> list[int] | None:
    """MCTS.get_ranking_from_pairwise_comparison, in leaf orders; None where update_collected_result_rollout fails."""
    order = search.order
    pairwise = {order[leaf]: {order[other]: value for other, value in search.comparisons[leaf].items()}
                for leaf in order if leaf not in search.dumb}
    try:
        if len(search.baselines) < 2:
            return None
        if len(search.baselines) == 2:
            # pairwise[1][0] is the share of judgments that prefer leaf 1; upstream ranks leaf 0 first exactly then,
            # the reverse of its Bradley-Terry branch. The preferred leaf comes first here.
            ranking = [1, 0] if pairwise[1][0] >= 0.5 else [0, 1]
        else:
            ranking = compute_ranking(pairwise)
    except Exception:
        return None
    return ranking + [order[leaf] for leaf in search.dumb]
