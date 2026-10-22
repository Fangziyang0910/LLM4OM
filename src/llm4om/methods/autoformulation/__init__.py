"""AutoFormulation: the search of https://github.com/jumpynitro/AutoFormulator at 5214801 as a graph.

Build the tree depth first, one node expansion per step (`MCTS.dfs_from_scratch`): for the next component
(parameters, decision variables, objective, equality constraints, inequality constraints) sample `n_used_gpt`
completions, drop empty ones, check the code of the executable steps, remove equivalent candidates (parameters by
mode, decision variables by LLM grouping, the rest by SymPy/Z3 scripts), score the rest by LLM ranking and keep the
best `n_top`. Then run `total_rollouts` MCTS rollouts over the tree (`MCTS.many_rollouts` with global ranking):
UCT selects a complete formulation, which is compared pairwise with the warm-up baselines. The selected model is the
first solved one in the Bradley-Terry ranking.

Prompts and parsing are the upstream modules in `upstream/` (prompts.py, utils_prompt.py, utils_general.py,
utils_diff.py); search.py ports the rest of the helpers. Adaptations:
- Library. Upstream writes gurobipy code; codegen.py writes the selected language's code, and the variable-type rule
  and the comparison prompt name that language's library. The Gurobi text is upstream's.
- Execution. Check scripts and equivalence scripts run in the platform sandbox; complete formulations are solved by
  the platform with the selected solver. A formulation "achieves a solution" when the solver returns an objective
  (upstream parses "Best objective" from the Gurobi log).
- Entry. Upstream's run_NL4OPT.py only builds the tree; ranking selection lives in `many_rollouts`. Both run here.
- Correction: with two solved formulations upstream ranks the less preferred one first; here the preferred one.
- Error avoidance: bounded retries of a pairwise comparison (upstream retries forever); a failed decision-variable
  grouping keeps all candidates (upstream fails); equality-border variables without host exec(); bare iteration
  spaces accepted (see the `# llm4om:` lines in upstream/).
"""

import asyncio
import json
import math
from collections.abc import Coroutine
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from llm4om.languages import MILP_LANGUAGES
from llm4om.methods import Method, presets
from llm4om.methods.autoformulation import codegen
from llm4om.methods.autoformulation.search import (
    check_constraints_for_correctness_obj,
    comparison_prompt,
    compute_ranking,
    create_dict_string,
    extract_best_solution,
    solution_prompt,
)
from llm4om.methods.autoformulation.upstream import prompts as P
from llm4om.methods.autoformulation.upstream.utils_diff import (
    extract_equivalence_value,
    filter_parameters,
    obtain_code_compar,
)
from llm4om.methods.autoformulation.upstream.utils_general import check_none_key_value
from llm4om.methods.autoformulation.upstream.utils_prompt import (
    convert_tuple_keys_to_str,
    extract_dict_from_string,
    extract_dictionary_rank,
    extract_unique_group_idx,
    get_normalized_rank,
    get_rank_filtering_prompt,
    obtain_new_prompt,
    update_rank,
)
from llm4om.runtime import Context, ModelingState
from llm4om.sandbox import SolveResult

STEPS = {1: "parameters", 2: "decision_variables", 3: "objective", 4: "equality_constraints", 5: "inequality_constraints"}
INSTRUCTIONS = {1: P.INST_PARAMETERS, 2: P.INST_DV, 3: P.INST_OBJ, 4: P.INST_EQ_CONST, 5: P.INST_INEQ_CONST}
DEPTH_TERMINAL = 5
EXECUTABLE_STEPS = ("objective", "equality_constraints", "inequality_constraints")
ERROR_KEYWORDS = ("Error", "Exception", "Traceback", "fatal", "failed")  # utils_exec.check_script_output
GUROBI_TYPE_RULE = ("Replace <type> with a string representing the Gurobi variable type (e.g., GRB.INTEGER), as this "
                    "will be used to create the variable via Gurobi's addVar function.")
DV_TYPE_RULES = {
    "pyomo": "Replace <type> with a string representing the Pyomo variable domain (e.g., pyo.NonNegativeIntegers), as "
             "this will be used to create the variable via Pyomo's Var component.",
    "pywraplp": "Replace <type> with a string representing the OR-Tools variable type ('integer', 'continuous' or "
               "'binary'), as this will be used to create the variable via OR-Tools' IntVar, NumVar or BoolVar.",
}


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


class State(ModelingState, total=False):
    _nodes: dict[int, Node]
    _stack: list[int]  # nodes left to expand, depth first
    _search: Search
    expansion: str  # what the latest expansion produced
    rollout: str  # what the latest effective rollout did


async def _sample(context: Context, role: str, prompt: str, n: int) -> list[str]:
    """Upstream chat_gpt with n_used: n completions of one user message."""
    model = context.llm(role).bind(temperature=presets.AUTOFORMULATION.temperature)
    return [reply.text for reply in await _gather(*(model.ainvoke([HumanMessage(prompt)]) for _ in range(n)))]


async def _gather(*calls: Coroutine[Any, Any, Any]) -> list[Any]:
    """Cancel and join siblings before a failed or cancelled batch returns."""
    tasks = [asyncio.create_task(call) for call in calls]
    try:
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def _instruction(context: Context, depth: int) -> str:
    rule = DV_TYPE_RULES.get(context.target.language)
    return INSTRUCTIONS[depth].replace(GUROBI_TYPE_RULE, rule) if rule else INSTRUCTIONS[depth]


async def _check(context: Context, node: Node) -> None:
    """The checks of ReasoningMCTSNode.__init__: non-empty, objective form, and the executable steps' code."""
    step = node.step
    assert step is not None
    value = node.form_dict_eval[step]
    if step == "equality_constraints" and check_none_key_value(value):
        node.run_code = False
    elif step == "equality_constraints":
        node.form_dict_str[step] = create_dict_string(value, node.form_dict_str[step])
    not_empty = len(value) > 0
    if not not_empty:
        node.run_code = False
    elif node.run_code and step == "objective" and not check_constraints_for_correctness_obj(value):
        not_empty = node.run_code = False
    if step in EXECUTABLE_STEPS and node.run_code:
        language = context.target.language
        try:
            code = codegen.model_code(language, node.form_dict_eval) if step == "inequality_constraints" \
                else codegen.check_script(language, node.form_dict_eval, step)
        except Exception as error:
            node.correct, node.output = False, "Could not create code: " + str(error)
        else:
            if step == "inequality_constraints":
                node.solve = await context.solve(code, title=f"求解完整模型（节点 {node.id}）")
                node.correct, node.output = node.solve.executed, node.solve.feedback()
                node.run_code = not check_none_key_value(value)
            else:
                result = await context.run_script(code)
                node.output = result.output
                node.correct = result.executed and not any(keyword in result.output for keyword in ERROR_KEYWORDS)
    try:
        json.dumps(convert_tuple_keys_to_str(node.form_dict_eval))
    except Exception:
        not_empty = False
    if not not_empty:
        node.status = "empty"
    elif not node.correct:
        node.status = "incorrect"


async def _equivalent(context: Context, first: Node, second: Node) -> bool:
    """utils_diff.get_equivalence_function: run the SymPy/Z3 comparison script."""
    code = obtain_code_compar(dict(first.form_dict_eval), dict(second.form_dict_eval), first.step)
    return extract_equivalence_value((await context.run_script(code)).output)


async def _unique_by_scripts(context: Context, nodes: list[Node]) -> list[Node]:
    """utils_diff.filter_functionally_equivalent; each round's comparisons run concurrently."""
    objects = [node for node in nodes if node.run_code]
    aux = [node for node in nodes if not node.run_code]
    unique: list[Node] = []
    while objects:
        current = objects.pop(0)
        unique.append(current)
        same = await _gather(*(_equivalent(context, current, other) for other in objects))
        objects = [other for other, equivalent in zip(objects, same) if not equivalent]
    return unique + aux[:1]


async def _unique_by_llm(context: Context, parent: Node, nodes: list[Node], problem: str) -> list[Node]:
    """ReasoningMCTSNode._get_gpt_unique_dv."""
    step = STEPS[parent.depth + 1]
    prompt = get_rank_filtering_prompt(P.INST_GROUP_DV, problem, parent.form_dict_str,
                                       solution_prompt(step, [node.form_dict_str for node in nodes]))
    replies = await _sample(context, "group_decision_variables", prompt, presets.AUTOFORMULATION.n_dv_unique_gpt)
    try:
        return [nodes[index] for index in extract_unique_group_idx(replies, len(nodes), step)]
    except Exception:
        return nodes


async def _rewards(context: Context, parent: Node, nodes: list[Node], problem: str) -> list[float]:
    """ReasoningMCTSNode._get_children_reward: normalized LLM ranking of the candidates."""
    if len(nodes) <= 1:
        return [1.0] * len(nodes)
    step = STEPS[parent.depth + 1]
    prompt = get_rank_filtering_prompt(P.INST_RANK.replace("#VARIABLE#", step), problem, parent.form_dict_str,
                                       solution_prompt(step, [node.form_dict_str for node in nodes]))
    current = {f"{step}_{idx}": 0 for idx in range(len(nodes))}
    for reply in await _sample(context, f"rank.{step}", prompt, presets.AUTOFORMULATION.n_reward):
        try:
            rank = extract_dictionary_rank(reply, len(nodes), step)
            if rank is not None:
                current = update_rank(current, rank)
        except Exception:
            pass
    return [float(reward) for reward in get_normalized_rank(current)]


def start(state: State) -> dict[str, Any]:
    return {"_nodes": {0: Node(0, 0, {}, {})}, "_stack": [0], "_search": Search()}


async def expand(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """ReasoningMCTSNode._get_children for the next node of the depth-first walk."""
    context = runtime.context
    nodes, stack = dict(state["_nodes"]), list(state["_stack"])
    parent = nodes[stack.pop()]
    step = STEPS[parent.depth + 1]
    template = P.TEMPLATE_PROBLEM.replace("###PROBLEM DESCRIPTION###", state["problem"])
    prompt = obtain_new_prompt(template, parent.form_dict_str, _instruction(context, parent.depth + 1))
    candidates: list[Node] = []
    for content in await _sample(context, f"generate.{step}", prompt, presets.AUTOFORMULATION.n_used_gpt):
        try:
            text, value = extract_dict_from_string(content, step)
        except Exception:
            continue
        candidates.append(Node(len(nodes) + len(candidates), parent.depth + 1, {**parent.form_dict_str, step: text},
                               {**parent.form_dict_eval, step: value}, parent.id, len(candidates)))
    await _gather(*(_check(context, node) for node in candidates))
    correct = [node for node in candidates if node.status == "kept"]
    if len(correct) <= 1:
        unique = correct
    elif step == "parameters":
        unique = filter_parameters(correct)[0]
    elif step == "decision_variables":
        unique = await _unique_by_llm(context, parent, correct, state["problem"])
    else:
        unique = await _unique_by_scripts(context, correct)
    for node in correct:
        if node not in unique:
            node.status = "clustered"
    rewards = await _rewards(context, parent, unique, state["problem"])
    highest = sorted(rewards, reverse=True)[:presets.AUTOFORMULATION.n_top]
    for node, reward in zip(unique, rewards):
        node.r0 = reward
        if reward in highest:
            parent.children.append(node.id)
        else:
            node.status = "low-scored"
    nodes.update({node.id: node for node in candidates})
    if parent.depth + 1 < DEPTH_TERMINAL:
        stack += reversed(parent.children)  # dfs visits the children in order
    counts = {status: sum(node.status == status for node in candidates)
              for status in ("empty", "incorrect", "clustered", "low-scored")}
    kept = "\n\n".join(f"```python\n# {step}_{nodes[child].idx}, reward {nodes[child].r0:.2f}\n"
                       f"{nodes[child].form_dict_str[step]}\n```" for child in parent.children)
    summary = (f"节点 {parent.id}（{parent.step or '根'}）→ {step}：解析出 {len(candidates)} 个候选；空 {counts['empty']}，"
               f"检查失败 {counts['incorrect']}，等价去重 {counts['clustered']}，低分 {counts['low-scored']}；"
               f"保留 {len(parent.children)} 个。")
    failed = "\n".join(f"- {step}_{node.idx}：{_last_line(node.output)}" for node in candidates if node.status == "incorrect")
    return {"_nodes": nodes, "_stack": stack,
            "expansion": "\n\n".join(part for part in (summary, failed and "检查失败：\n" + failed, kept) if part)}


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return (lines[-1] if lines else "无输出")[:300]


def _uct(search: Search, node: Node, log_n: float) -> float:
    preset, n = presets.AUTOFORMULATION, search.N.get(node.id, 0)
    if n == 0:
        return node.r0 + preset.w_exp * math.sqrt(log_n)
    value = preset.lambda_cte * node.r0 + (1 - preset.lambda_cte) * search.Q[node.id] / n
    return value + preset.w_exp * math.sqrt(log_n / n)


async def _compare(context: Context, problem: str, first: Node, second: Node) -> tuple[float, float]:
    """utils_metrics.compare_solutions_form: the shares of n_eval judgments that prefer each formalization."""
    preset = presets.AUTOFORMULATION
    prompt = comparison_prompt(second.form_dict_str, first.form_dict_str, problem, context.target.library)
    for attempt in range(preset.max_comparison_tries):
        picks = [extract_best_solution(reply).get("1") for reply in await _sample(context, "compare", prompt, preset.n_eval)]
        if all(picks) or attempt == preset.max_comparison_tries - 1:
            break
    wins_first, wins_second = picks.count("solution_B"), picks.count("solution_A")
    total = wins_first + wins_second
    return (wins_first / total, wins_second / total) if total else (0.5, 0.5)


async def _reward_by_ranking(context: Context, problem: str, nodes: dict[int, Node], search: Search,
                             leaf: Node) -> float | None:
    """MCTS.get_reward_update_ranking with global ranking: compare the leaf with every baseline in both orders."""
    if not search.baselines:
        return None
    wins_leaf = wins_other = 0.0
    for baseline in search.baselines:
        first_leaf, first_other = await _compare(context, problem, leaf, nodes[baseline])
        second_other, second_leaf = await _compare(context, problem, nodes[baseline], leaf)
        leaf_score, other_score = first_leaf + second_leaf, first_other + second_other
        wins_leaf += leaf_score
        wins_other += other_score
        search.comparisons[leaf.id][baseline] = leaf_score / (leaf_score + other_score)
        search.comparisons[baseline][leaf.id] = other_score / (leaf_score + other_score)
    return wins_leaf / (wins_leaf + wins_other)


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


async def rollout(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """MCTS.rollout over the built tree, repeated until one rollout reaches a leaf not yet evaluated."""
    nodes, search = state["_nodes"], state["_search"]
    while search.attempts < presets.AUTOFORMULATION.max_rollout_attempts:
        search.attempts += 1
        path = [nodes[0]]
        while path[-1].step != "inequality_constraints" and path[-1].children:  # _select_prior
            parent = path[-1]
            n = search.N.get(parent.id, 0)
            log_n = math.log(n) if n else 0.0
            path.append(max((nodes[child] for child in parent.children), key=lambda c: _uct(search, c, log_n)))
        leaf, effective, reward = path[-1], False, 0.0
        if leaf.step == "inequality_constraints":
            if leaf.id not in search.order:
                search.order[leaf.id] = len(search.order)
                search.comparisons[leaf.id] = {}
                if not leaf.achieved:
                    search.dumb.append(leaf.id)
            if leaf.id in search.r_baseline:
                reward = search.r_baseline[leaf.id]
            else:
                effective = True
                if leaf.achieved:
                    reward = await _reward_by_ranking(runtime.context, state["problem"], nodes, search, leaf) or 0.0
                    if len(search.baselines) < presets.AUTOFORMULATION.num_warmup:
                        search.baselines.append(leaf.id)
                        reward = 0.5
                search.r_baseline[leaf.id] = reward
                search.ranking = _ranking(search)
        for node in path:  # _back_propagate
            search.N[node.id] = search.N.get(node.id, 0) + 1
            search.Q[node.id] = search.Q.get(node.id, 0.0) + reward
        if effective:
            search.effective += 1
            outcome = f"有解，目标值 {leaf.solve.objective:g}" if leaf.achieved and leaf.solve else "无解"
            return {"_search": search, "rollout": f"第 {search.effective} 次有效 rollout：叶节点 {leaf.id}，"
                                                  f"{outcome}，奖励 {reward:.2f}。"}
    return {"_search": search}


def select(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    """The first solved formulation in the final ranking (upstream's all_results_best ranking_result)."""
    nodes, search = state["_nodes"], state["_search"]
    by_order = {order: leaf for leaf, order in search.order.items()}
    solved = [leaf for leaf in search.order if leaf not in search.dumb]
    if not solved:
        return {"failure": "No complete formulation produced a solution during the search."}
    ranked = [by_order[order] for order in search.ranking or [] if by_order[order] in solved]
    best = nodes[ranked[0] if ranked else solved[0]]
    formulation = "\n\n".join(f"### {step}\n```python\n{best.form_dict_str.get(step, '')}\n```" for step in STEPS.values())
    return {"formulation": formulation, "code": codegen.model_code(runtime.context.target.language, best.form_dict_eval),
            "solve": best.solve}


def after_expand(state: State) -> str:
    return "expand" if state["_stack"] else "rollout"


def after_rollout(state: State) -> str:
    search, preset = state["_search"], presets.AUTOFORMULATION
    done = search.effective >= preset.total_rollouts or search.attempts >= preset.max_rollout_attempts
    return "select" if done else "rollout"


def autoformulation_graph():
    graph = StateGraph(State, context_schema=Context)
    for node in (start, expand, rollout, select):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "start")
    graph.add_edge("start", "expand")
    graph.add_conditional_edges("expand", after_expand, ["expand", "rollout"])
    graph.add_conditional_edges("rollout", after_rollout, ["rollout", "select"])
    graph.add_edge("select", END)
    return graph.compile(name="autoformulation")


AUTOFORMULATION = Method("autoformulation", "AutoFormulation",
                         "逐层生成参数、变量、目标、等式和不等式约束；每层采样多个候选，执行检查，剪除等价项并排序。"
                         "再在建好的树上做 MCTS，用两两比较为完整模型排名。调用量很大。", autoformulation_graph,
                         "https://github.com/jumpynitro/AutoFormulator/tree/52148018d04de23dc2d36d4281eb6244c2a42ffc",
                         titles={"expand": "扩展建模树", "rollout": "MCTS rollout", "select": "选中的数学模型"},
                         hidden=frozenset({"solve"}),
                         limits=presets.AUTOFORMULATION.limits,
                         languages=MILP_LANGUAGES)
