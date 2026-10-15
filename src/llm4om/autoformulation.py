"""Bounded AutoFormulation MCTS with public self-evaluation and SMT pruning."""

from copy import deepcopy
from dataclasses import asdict, dataclass, field
import json
import math
from typing import Any

from llm4om.contracts import RunError
from llm4om.linear import compile_ir
from llm4om.methods import DirectFactory, MethodContext, MethodOutcome, ModelProposal
from llm4om.prompt_methods import PromptSession, json_reply


SOURCE: dict[str, Any] = {"upstream_url": "https://github.com/jumpynitro/AutoFormulator",
    "upstream_commit": "52148018d04de23dc2d36d4281eb6244c2a42ffc",
    "variant_id": "autoformulation-bounded_mcts-grounded_lpir-smt/0.1.0",
    "adaptation": "original_prompts_numeric_lpir_terminal_smt_score_evaluation",
    "license": "original_implementation_no_upstream_vendoring"}
STAGES = ("parameters", "decision_variables", "objective", "equality_constraints", "inequality_constraints")


def equivalent_models(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Only prune proven equivalence; unknown SMT results retain both proposals."""
    import z3

    left_vars = {entry["id"]: entry["domain"] for entry in left["variables"]}
    right_vars = {entry["id"]: entry["domain"] for entry in right["variables"]}
    if left_vars != right_vars or left["objective"]["sense"] != right["objective"]["sense"]:
        return False
    variables = {key: z3.Real(key) if domain == "continuous" else z3.Int(key) for key, domain in left_vars.items()}

    def expression(value: dict[str, Any]) -> Any:
        return z3.RealVal(str(value["constant"])) + z3.Sum([
            z3.RealVal(str(term["coefficient"])) * variables[term["variable_id"]] for term in value["terms"]])

    def feasible(ir: dict[str, Any]) -> Any:
        clauses = []
        for entry in ir["variables"]:
            variable = variables[entry["id"]]
            for key, relation in (("lower_bound", "ge"), ("upper_bound", "le")):
                if entry[key] is not None:
                    bound = z3.RealVal(str(entry[key]))
                    clauses.append(variable >= bound if relation == "ge" else variable <= bound)
            if entry["domain"] == "binary":
                clauses.extend([variable >= 0, variable <= 1])
        for entry in ir["constraints"]:
            body, rhs = expression(entry["expression"]), z3.RealVal(str(entry["rhs"]))
            clauses.append(body == rhs if entry["sense"] == "eq" else body <= rhs if entry["sense"] == "le" else body >= rhs)
        return z3.And(clauses)

    solver = z3.Solver()
    solver.set(timeout=200)
    solver.add(z3.Or(z3.Xor(feasible(left), feasible(right)),
        expression(left["objective"]["expression"]) != expression(right["objective"]["expression"])))
    return bool(solver.check() == z3.unsat)


@dataclass
class SearchNode:
    node_id: int
    depth: int
    partial: dict[str, Any]
    prior: float = 0
    children: list[int] = field(default_factory=list)
    expanded: bool = False
    visits: int = 0
    reward_sum: float = 0
    check_id: str | None = None
    terminal_reward: float | None = None


GROUNDING = (
    "Translate the selected five-stage formulation into a grounded LP/MILP without changing its meaning. "
    "Use only public problem numbers and data. Return JSON {representation, structured_ir}. "
    "representation has sets=[{id,elements}], parameters=[{id,index_sets,value}], "
    "variables=[{id,index_sets,domain,lower_bound,upper_bound,requirement_ids}], "
    "objective={sense,expression_text,requirement_ids}, constraints=[{id,expression_text,requirement_ids}]. "
    "structured_ir has exactly problem_type:lp|milp, variables, objective, constraints, assumptions. "
    "IR variables=[{id,name,domain:continuous|integer|binary,lower_bound,upper_bound,requirement_ids}]. "
    "IR objective={sense:min|max,expression,requirement_ids}. IR constraints=[{id,expression,sense:le|ge|eq,rhs,requirement_ids}]. "
    "Every expression={constant:number,terms:[{variable_id,coefficient:number}]}. Null bounds mean unbounded. "
    "assumptions is an array. Use only original public requirement IDs. Do not produce platform IDs, hashes, references or answers."
)


def _score(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1:
        raise RunError("invalid_method_reply", "formulation", "Self-evaluation scores must be finite numbers in [0,1].")
    return float(value)


class AutoFormulationMethod:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        if checkpoint is not None:
            raise RunError("checkpoint_incompatible", "admission", "AutoFormulation has no internal continuation checkpoint.")
        session = PromptSession("autoformulation", SOURCE, problem, context)
        nodes = [SearchNode(0, 0, {})]
        evaluated: list[tuple[dict[str, Any] | None, str, float]] = []
        legal: dict[str, float] = {}
        pruned: list[dict[str, Any]] = []

        def record() -> None:
            session.record("search-tree.json", {"stages": STAGES, "nodes": [asdict(node) for node in nodes],
                "pruned": pruned, "rollouts": nodes[0].visits, "selection": "public_semantic_score_with_solver_validity"})

        async def expand(node: SearchNode) -> None:
            stage = STAGES[node.depth]
            generated = json_reply(await session.complete("generate." + stage, "Propose distinct alternative formulations for "
                "only the next component of the optimization model. Preserve earlier components. Ground all facts in the "
                "public description; do not invent requirements. Return JSON {hypotheses:[value,...]}, with between one and "
                f"{self.config['branching']} alternatives. Values may be mathematical text or JSON; never executable Python.",
                {**session.inputs, "next_component": stage, "partial_formulation": node.partial}))
            values = generated.get("hypotheses") if isinstance(generated, dict) else None
            if not isinstance(values, list) or not 1 <= len(values) <= self.config["branching"] or any(value is None for value in values):
                raise RunError("invalid_method_reply", "formulation", "Hypothesis generation returned an invalid branching set.")
            unique = []
            fingerprints = set()
            for value in values:
                fingerprint = json.dumps(value, sort_keys=True, allow_nan=False)
                if fingerprint not in fingerprints:
                    unique.append(value)
                    fingerprints.add(fingerprint)
                else:
                    pruned.append({"parent_id": node.node_id, "reason": "identical_partial_hypothesis"})
            ranking = json_reply(await session.complete("evaluate." + stage, "Independently evaluate each proposed component "
                "for consistency with the public problem and earlier components. Return JSON {scores:[number,...]} in the same "
                "order, with values in [0,1]. Reward semantic correctness, never larger objective values.",
                {**session.inputs, "component": stage, "partial_formulation": node.partial, "hypotheses": unique}))
            scores = ranking.get("scores") if isinstance(ranking, dict) else None
            if not isinstance(scores, list) or len(scores) != len(unique):
                raise RunError("invalid_method_reply", "formulation", "Self-evaluation must score every retained hypothesis.")
            for value, score in zip(unique, scores):
                child = SearchNode(len(nodes), node.depth + 1, {**node.partial, stage: value}, _score(score))
                nodes.append(child)
                node.children.append(child.node_id)
            node.expanded = True
            record()

        async def evaluate(node: SearchNode) -> float:
            if node.terminal_reward is not None:
                return node.terminal_reward
            value = json_reply(await session.complete("grounding", GROUNDING,
                {**session.inputs, "selected_formulation": node.partial}, phase="code"))
            if (not isinstance(value, dict) or set(value) != {"representation", "structured_ir"}
                    or not isinstance(value["representation"], dict) or not isinstance(value["structured_ir"], dict)):
                raise RunError("invalid_method_reply", "code", "AutoFormulation grounding requires a Formulation and LPIR.")
            ir = deepcopy(value["structured_ir"])
            if set(ir) != {"problem_type", "variables", "objective", "constraints", "assumptions"}:
                raise RunError("invalid_method_reply", "code", "Grounded LPIR contains unsupported or missing fields.")
            check_id = f"{len(evaluated) + 1:03d}"
            provenance = {**SOURCE, "origin": "mcts_selected_hypotheses", "node_id": node.node_id,
                "call_ids": [call["call_id"] for call in session.calls], "ir_relationship": "grounded_from_selected_hypotheses"}
            ir.update(schema_version="0.1.0", ir_kind="grounded_lp", model_id="autoformulation-ir-" + check_id,
                problem_id=problem["problem_id"], problem_revision=problem["revision"], data_bindings=session.bindings, provenance=provenance)
            # Symbolic code is constructed from validated affine IR, never LLM Python.
            validated = True
            try:
                compile_ir(ir)
            except RunError as error:
                if error.code != "invalid_ir":
                    raise
                validated = False
            for previous, previous_id, reward in evaluated:
                if validated and previous is not None and equivalent_models(previous, ir):
                    node.check_id, node.terminal_reward = previous_id, reward
                    pruned.append({"node_id": node.node_id, "equivalent_check_id": previous_id, "reason": "smt_proven_equivalent"})
                    return reward
            formulation = {"schema_version": "0.2.0", "formulation_id": "autoformulation-formulation-" + check_id,
                "problem_id": problem["problem_id"], "problem_revision": problem["revision"], "representation_kind": "five_element",
                "representation": value["representation"], "structured_ir_ref": {}, "data_bindings": session.bindings, "provenance": provenance}
            artifact = {"schema_version": "0.2.0", "artifact_id": "autoformulation-artifact-" + check_id,
                "problem_ref": {"sha256": context.problem_sha256}, "formulation_ref": {}, "code_ref": None,
                "data_bindings": session.bindings, "assumptions": ir["assumptions"], "requirement_traces": [],
                "diagnostics": [], "warnings": [], "optional_views": [], "provenance": provenance,
                "stage_status": {"formulation": {"status": "available", "reason": None},
                    "code": {"status": "pending", "reason": "Deterministic compilation has not run."}}}
            checked = await session.resources.check(check_id, ModelProposal(artifact, formulation, ir))
            judgment = json_reply(await session.complete("evaluate.complete", "Evaluate whether the complete formulation "
                "faithfully models every public requirement. Solver success verifies execution, not semantic correctness. "
                "Do not compare objective values between different models. Return JSON {score:number,reason:string}, score in [0,1].",
                {**session.inputs, "selected_hypotheses": node.partial, "formulation": value["representation"], "solver_feedback": checked}))
            if not isinstance(judgment, dict) or not isinstance(judgment.get("reason"), str):
                raise RunError("invalid_method_reply", "formulation", "Complete self-evaluation needs a score and reason.")
            reward = _score(judgment.get("score")) if not checked["diagnostics"] and checked["has_primal_solution"] else 0
            if not checked["diagnostics"] and checked["solve_result_ref"] is not None:
                legal[check_id] = reward
            evaluated.append((ir if validated else None, check_id, reward))
            node.check_id, node.terminal_reward = check_id, reward
            session.record("rewards.json", {"checks": legal, "latest_judgment": judgment})
            return reward

        for _ in range(self.config["rollouts"]):
            context.cancellation.check()
            remaining = session.resources.remaining_budget()
            if any(remaining[key] <= 0 for key in ("checks", "solver_calls", "llm_attempts", "total_tokens", "wall_time_s")):
                break
            path = [nodes[0]]
            try:
                while path[-1].depth < len(STAGES):
                    node = path[-1]
                    if not node.expanded:
                        await expand(node)
                    unvisited = [nodes[index] for index in node.children if nodes[index].visits == 0]
                    child = max(unvisited, key=lambda item: item.prior) if unvisited else max(
                        (nodes[index] for index in node.children), key=lambda item: item.reward_sum / item.visits
                            + self.config["exploration"] * math.sqrt(math.log(max(1, node.visits)) / item.visits))
                    path.append(child)
                reward = await evaluate(path[-1])
            except RunError as error:
                if error.code in {"budget_exhausted", "deadline_exhausted"} and legal:
                    break
                raise
            for node in path:
                node.visits += 1
                node.reward_sum += reward
            record()
        record()
        if not legal:
            return MethodOutcome("exhausted", None, None)
        selected = max(legal, key=lambda key: legal[key])
        return session.resources.select(selected, rule="mcts-public-semantic-reward/0.1.0",
            reason=f"Selected trusted legal check {selected} with the highest public formulation self-evaluation score ({legal[selected]:g}).")


class AutoFormulationFactory:
    def describe(self) -> dict[str, Any]:
        manifest = DirectFactory().describe()
        manifest.update(plugin_id="llm4om.methods.autoformulation", plugin_version="0.1.0", display_name="AutoFormulation · MCTS",
            description="Five-stage formulation search with UCT, independent self-evaluation, SMT pruning and trusted LP/MILP solving.",
            source=SOURCE, dependencies={"python": ["z3-solver"]},
            config_schema={"type": "object", "properties": {"rollouts": {"type": "integer", "minimum": 1, "maximum": 20},
                "branching": {"type": "integer", "minimum": 1, "maximum": 8},
                "exploration": {"type": "number", "minimum": 0, "maximum": 10}}, "additionalProperties": False})
        manifest["capabilities"].update(method_profile="grounded_checked/0.2.0", data_access="full", supports_checkpoint=False)
        return manifest

    def create(self, config: dict[str, Any]) -> AutoFormulationMethod:
        return AutoFormulationMethod({"rollouts": 2, "branching": 2, "exploration": 1.4, **config})
