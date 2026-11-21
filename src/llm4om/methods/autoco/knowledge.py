"""Feature-to-Feature Optimization Knowledge Graph (Problem Features <-> Algorithm Features) for AutoCO."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from llm4om.methods.autoco.modeling import Formulation
from llm4om.sandbox.autoco.specs import ALGORITHM_SPECS, OPERATOR_SPECS, canonical_algorithm

FeatureKind = Literal["problem_feature", "algorithm_feature"]
RelationKind = Literal["SUITS", "CONFLICTS_WITH", "SYNERGIZES_WITH"]


@dataclass(frozen=True)
class FeatureNode:
    id: str
    kind: FeatureKind
    title: str
    summary: str


@dataclass(frozen=True)
class FeatureRelation:
    source: str
    relation: RelationKind
    target: str
    explanation: str


_EXPLICIT_PFEATS = (
    "single_objective", "bi_objective", "many_objective",
    "permutation", "assignment", "binary", "integer", "continuous", "mixed_blocks",
    "linear_obj", "quadratic_obj", "minmax_obj", "nonlinear_obj",
    "precedence", "capacity", "equality", "conflict", "nonlinear_con", "large_scale",
)

PROBLEM_FEATURES: tuple[FeatureNode, ...] = (
    *(FeatureNode(f"pfeat:{f}", "problem_feature", f, f"Explicit problem feature '{f}'.") for f in _EXPLICIT_PFEATS),
    FeatureNode("pfeat:step_count_obj", "problem_feature", "Step-Count Objective", "Minimizes/maximizes discrete count of active bins, colors, vehicles, or placed items (flat integer plateaus)."),
    FeatureNode("pfeat:group_symmetry", "problem_feature", "Unlabeled Group Symmetry", "Categories 0..K-1 are interchangeable so permuting group IDs represents the identical partition."),
    FeatureNode("pfeat:prefix_delimiter", "problem_feature", "Delimiter / Prefix Sequence", "Permutation partitioned or truncated by delimiters where tail elements may be inactive."),
    FeatureNode("pfeat:master_slave_blocks", "problem_feature", "Master-Slave Block Coupling", "One discrete block selects active elements while another block indexes relative to them."),
    FeatureNode("pfeat:dense_pairwise_coupling", "problem_feature", "Dense All-Pairs Coupling", "Every pair of positions/decisions interacts globally in the objective (e.g. QAP flow-distance products)."),
)

ALGORITHM_FEATURES: tuple[FeatureNode, ...] = (
    FeatureNode("afeat:single_step_trajectory", "algorithm_feature", "Single-Step Trajectory Search", "High-turnover 1-move neighborhood walk along a single incumbent trajectory."),
    FeatureNode("afeat:stochastic_uphill_acceptance", "algorithm_feature", "Boltzmann Uphill / Plateau Acceptance", "Accepts lateral and controlled worsening moves to cross flat plateaus and shallow basins."),
    FeatureNode("afeat:tabu_memory_guidance", "algorithm_feature", "Short-Term Tabu Memory", "Forbids recent move reversals to traverse flat plateaus and conflict landscapes without cycling."),
    FeatureNode("afeat:kick_local_descent", "algorithm_feature", "Local Descent + Macro Perturbation Kick", "Alternates fast local descent to basin floor with multi-step perturbation kicks."),
    FeatureNode("afeat:ruin_and_recreate", "algorithm_feature", "Multi-Variable Ruin and Constructive Recreate", "Destroys a coupled subset of variables simultaneously and rebuilds feasibly across constraint barriers."),
    FeatureNode("afeat:two_parent_recombination", "algorithm_feature", "Two-Parent Population Recombination", "Combines building blocks across diverse individuals via crossover."),
    FeatureNode("afeat:memetic_local_polish", "algorithm_feature", "Offspring Local Refinement", "Applies block-matched local search to refine recombined offspring."),
    FeatureNode("afeat:covariance_distribution", "algorithm_feature", "Adaptive Covariance Distribution", "Learns full second-order coordinate correlations on continuous landscapes."),
    FeatureNode("afeat:vector_difference_step", "algorithm_feature", "Population Vector-Difference Step", "Moves continuous candidates along scaled inter-individual difference/velocity vectors."),
    FeatureNode("afeat:pheromone_constructive", "algorithm_feature", "Pheromone Constructive Sampling", "Reconstructs discrete solutions probabilistically from learned transition trails."),
    FeatureNode("afeat:pareto_crowding_ranking", "algorithm_feature", "Non-Dominated Sorting + Axis Crowding", "Ranks multi-objective fronts via Pareto dominance and axis-aligned crowding distance."),
    FeatureNode("afeat:scalarized_decomposition", "algorithm_feature", "Cooperative Scalarized Decomposition", "Decomposes multi-objective search into weighted scalar subproblems supporting directional local repair."),
    FeatureNode("afeat:reference_direction_niching", "algorithm_feature", "Hyperplane Reference-Direction Niching", "Associates solutions with uniform reference rays to preserve high-dimensional (>=3 obj) front coverage."),
    FeatureNode("afeat:composite_neighborhood_scan", "algorithm_feature", "Composite Multi-Move Neighborhood", "Cycles complementary discrete move types across blocks."),
    FeatureNode("afeat:lightweight_local_move", "algorithm_feature", "Lightweight O(1) Local Move", "Executes single elementary moves with minimal per-step evaluation overhead."),
    FeatureNode("afeat:order_preserving_move", "algorithm_feature", "Chronology / Relative-Order Preservation", "Relocates or recombines subsequences without inverting forward chronological order."),
    FeatureNode("afeat:segment_reversing_move", "algorithm_feature", "Contiguous Subsequence Reversal", "Inverts the traversal direction of a contiguous permutation slice."),
    FeatureNode("afeat:cardinality_preserving_swap", "algorithm_feature", "Cardinality-Preserving Exchange", "Swaps positions, group labels, or 1/0 pairs while keeping selection/group counts invariant."),
    FeatureNode("afeat:cardinality_changing_flip", "algorithm_feature", "Independent Single-Variable Flip/Reassign", "Changes one variable's value/category independently, altering group or selection totals."),
    FeatureNode("afeat:coupled_continuous_relaxation", "algorithm_feature", "Joint Multi-Axis Continuous Relaxation", "Slides all continuous coordinates simultaneously along smooth or directional descent paths."),
    FeatureNode("afeat:coordinate_perturbation", "algorithm_feature", "Bounded Coordinate Perturbation", "Applies random metric steps to continuous/integer coordinates."),
    FeatureNode("afeat:position_mapping_crossover", "algorithm_feature", "Absolute Position-Mapping Crossover", "Transfers exact index-to-element placements between permutation parents."),
    FeatureNode("afeat:independent_gene_mixing", "algorithm_feature", "Independent Per-Gene Mixing", "Inherits each categorical/binary locus independently from two parents."),
    FeatureNode("afeat:contiguous_slice_crossover", "algorithm_feature", "Contiguous Segment Crossover", "Exchanges a contiguous index interval between parents."),
    FeatureNode("afeat:metric_interval_crossover", "algorithm_feature", "Metric Interval Interpolation", "Generates continuous/integer offspring inside/near parent coordinate intervals."),
    FeatureNode("afeat:bottleneck_targeted_ruin", "algorithm_feature", "High-Cost / Active Bottleneck Ruin", "Targets active elements responsible for high cost or constraint violation during removal."),
    FeatureNode("afeat:group_emptying_ruin", "algorithm_feature", "Whole-Group / Bin Consolidation Ruin", "Clears an entire underutilized category/bin so repair can reduce active group count."),
    FeatureNode("afeat:scattered_subset_ruin", "algorithm_feature", "Scattered Multi-Position Ruin", "Removes dispersed elements simultaneously across routes/groups."),
    FeatureNode("afeat:contiguous_slice_ruin", "algorithm_feature", "Contiguous Subsequence Ruin", "Removes an adjacent slice of elements along a sequence."),
    FeatureNode("afeat:fast_greedy_repair", "algorithm_feature", "Low-Overhead Greedy Reinsertion", "Rebuilds destroyed variables sequentially with O(d) cost for high iteration turnover."),
    FeatureNode("afeat:lookahead_regret_repair", "algorithm_feature", "Bottleneck-First Regret Lookahead Repair", "Prioritizes scarce-slot variables via 2-step regret lookahead at higher per-iteration cost."),
    FeatureNode("afeat:strict_feasibility_dominance", "algorithm_feature", "Strict Feasibility Dominance", "Always prefers lower violation before objective value without penalty tuning."),
    FeatureNode("afeat:barrier_tunneling_penalty", "algorithm_feature", "Progressive Penalty Barrier Tunneling", "Starts with mild violation penalty to cross infeasible ridges, then tightens to enforce feasibility."),
    FeatureNode("afeat:static_linear_penalty", "algorithm_feature", "Static Linear Penalty", "Applies constant violation weighting throughout search."),
    FeatureNode("afeat:pure_greedy_init", "algorithm_feature", "Constructive Greedy Initialization", "Builds a single feasibility-first starting solution."),
    FeatureNode("afeat:diverse_seeded_init", "algorithm_feature", "Hybrid Seeded + Random Initialization", "Combines a small fraction of constructive feasible anchors with diverse random individuals."),
    FeatureNode("afeat:uniform_random_init", "algorithm_feature", "Uniform Random Initialization", "Samples starting solutions uniformly across variable bounds."),
    FeatureNode("afeat:monotone_greedy_acceptance", "algorithm_feature", "Strict Non-Worsening Acceptance", "Accepts only non-worsening states."),
    FeatureNode("afeat:nonconvex_pareto_scalarization", "algorithm_feature", "Normalized Tchebycheff Scalarization", "Captures both convex and non-convex discrete Pareto trade-off points."),
    FeatureNode("afeat:linear_convex_scalarization", "algorithm_feature", "Linear Weighted-Sum Scalarization", "Optimizes linear combinations supported only on the convex hull of the Pareto front."),
)

FEATURE_RELATIONS: tuple[FeatureRelation, ...] = (
    FeatureRelation("pfeat:precedence", "SUITS", "afeat:order_preserving_move", "Relocating items or short segments without reversal preserves chronological arrival/processing order."),
    FeatureRelation("pfeat:precedence", "SUITS", "afeat:ruin_and_recreate", "Simultaneous multi-stop removal and constructive reinsertion jumps between disconnected time-window schedules."),
    FeatureRelation("pfeat:precedence", "SUITS", "afeat:lookahead_regret_repair", "Regret lookahead places tight-window stops before flexible ones run out of feasible slots."),
    FeatureRelation("pfeat:precedence", "CONFLICTS_WITH", "afeat:segment_reversing_move", "Reversing a contiguous segment directly inverts arrival order and violates precedence/time windows."),
    FeatureRelation("pfeat:precedence", "CONFLICTS_WITH", "afeat:single_step_trajectory", "Random single-step uphill moves overwhelmingly break tight chronological feasibility."),
    FeatureRelation("pfeat:precedence", "CONFLICTS_WITH", "afeat:uniform_random_init", "Uniform random permutations severely violate tight time windows at start; constructive seeding is needed."),
    FeatureRelation("pfeat:capacity", "SUITS", "afeat:ruin_and_recreate", "Multi-item destroy/repair rebalances tightly packed bins or routes when 1-item moves are blocked."),
    FeatureRelation("pfeat:capacity", "SUITS", "afeat:cardinality_preserving_swap", "Swapping items across bins/routes exchanges load without overflowing full capacities."),
    FeatureRelation("pfeat:conflict", "SUITS", "afeat:ruin_and_recreate", "Jointly clearing conflicting subsets allows clean conflict-free reassignment."),
    FeatureRelation("pfeat:conflict", "SUITS", "afeat:tabu_memory_guidance", "Tabu memory escapes local conflict traps without oscillating between adjacent clashes."),
    FeatureRelation("pfeat:conflict", "SUITS", "afeat:barrier_tunneling_penalty", "Gradual penalty ramping tunnels through intermediate conflict states toward zero violation."),
    FeatureRelation("pfeat:equality", "SUITS", "afeat:cardinality_preserving_swap", "Pairwise exchanges preserve exact group sizes and fixed selection totals invariant."),
    FeatureRelation("pfeat:equality", "SUITS", "afeat:barrier_tunneling_penalty", "Allows controlled traversal across narrow equality-constrained manifolds."),
    FeatureRelation("pfeat:equality", "CONFLICTS_WITH", "afeat:cardinality_changing_flip", "Single-bit flips or unilateral single-item reassignments immediately break exact quota/headcount equality."),
    FeatureRelation("pfeat:group_symmetry", "SUITS", "afeat:ruin_and_recreate", "Modifies and repairs subsets within a single incumbent, avoiding parent group-ID permutation clash."),
    FeatureRelation("pfeat:group_symmetry", "SUITS", "afeat:single_step_trajectory", "Single-trajectory moves never mix incompatible group labelings from two parents."),
    FeatureRelation("pfeat:group_symmetry", "CONFLICTS_WITH", "afeat:two_parent_recombination", "Group 0 in Parent A does not match Group 0 in Parent B under K! label symmetry, scrambling partitions."),
    FeatureRelation("pfeat:group_symmetry", "CONFLICTS_WITH", "afeat:independent_gene_mixing", "Uniformly mixing symmetric group IDs across two parents destroys balanced group structure."),
    FeatureRelation("pfeat:step_count_obj", "SUITS", "afeat:group_emptying_ruin", "Emptying an entire sparse bin/color enables constructive consolidation across integer step plateaus."),
    FeatureRelation("pfeat:step_count_obj", "SUITS", "afeat:stochastic_uphill_acceptance", "Lateral/Boltzmann acceptance traverses equal-count states where greedy acceptance stalls."),
    FeatureRelation("pfeat:step_count_obj", "CONFLICTS_WITH", "afeat:monotone_greedy_acceptance", "Strict non-worsening acceptance stalls on flat discrete count plateaus."),
    FeatureRelation("pfeat:minmax_obj", "SUITS", "afeat:kick_local_descent", "Fast local descent on critical paths paired with macro kicks escapes bottleneck makespan plateaus."),
    FeatureRelation("pfeat:minmax_obj", "SUITS", "afeat:bottleneck_targeted_ruin", "Targets critical-load elements determining the maximum objective."),
    FeatureRelation("pfeat:dense_pairwise_coupling", "SUITS", "afeat:lightweight_local_move", "All-pairs quadratic objectives (e.g. QAP) have rugged global basins requiring millions of fast O(1) swap/tabu/annealing steps."),
    FeatureRelation("pfeat:dense_pairwise_coupling", "SUITS", "afeat:cardinality_preserving_swap", "2-element position swap cleanly perturbs pairwise assignments without shifting an entire suffix."),
    FeatureRelation("pfeat:dense_pairwise_coupling", "SUITS", "afeat:single_step_trajectory", "High-frequency SA/TS trajectory steps cover far more basins than heavy constructive rebuilds on dense pairwise landscapes."),
    FeatureRelation("pfeat:dense_pairwise_coupling", "CONFLICTS_WITH", "afeat:lookahead_regret_repair", "Marginal regret lookahead is misled by unplaced pairwise interactions while wasting O(n^2) evaluations per step."),
    FeatureRelation("pfeat:large_scale", "SUITS", "afeat:kick_local_descent", "O(1) local descent + macro kicks sustain high iteration counts on high-dimensional instances."),
    FeatureRelation("pfeat:large_scale", "SUITS", "afeat:fast_greedy_repair", "O(d) greedy repair avoids O(d^2) lookahead budget dilution on large dimensions."),
    FeatureRelation("pfeat:large_scale", "CONFLICTS_WITH", "afeat:pheromone_constructive", "Full constructive sampling per ant per generation converges too slowly on large dimensions."),
    FeatureRelation("pfeat:large_scale", "CONFLICTS_WITH", "afeat:lookahead_regret_repair", "Quadratic regret lookahead exhausts time budget in very few iterations at large scale."),
    FeatureRelation("pfeat:prefix_delimiter", "SUITS", "afeat:bottleneck_targeted_ruin", "Focuses removals on active prefix stops rather than wasting perturbations in the inactive tail."),
    FeatureRelation("pfeat:master_slave_blocks", "SUITS", "afeat:ruin_and_recreate", "Single-incumbent coordinated block ruin/repair updates master and slave indices without crossover mismatch."),
    FeatureRelation("pfeat:master_slave_blocks", "CONFLICTS_WITH", "afeat:two_parent_recombination", "Recombining master facility prefixes invalidates relative slave assignment indices across parents."),
    FeatureRelation("pfeat:continuous", "SUITS", "afeat:covariance_distribution", "Adapts search directions to correlated, rotated continuous valleys."),
    FeatureRelation("pfeat:continuous", "SUITS", "afeat:coupled_continuous_relaxation", "Simultaneous multi-coordinate descent resolves smooth boundary and non-overlap geometry."),
    FeatureRelation("pfeat:nonlinear_con", "SUITS", "afeat:coupled_continuous_relaxation", "Curved geometric/physical constraints jam axis-by-axis steps and benefit from joint coordinate relaxation."),
    FeatureRelation("pfeat:continuous", "CONFLICTS_WITH", "afeat:ruin_and_recreate", "Discrete subset destroy/repair lacks coordinated continuous gradient/directional relaxation."),
    FeatureRelation("pfeat:mixed_blocks", "SUITS", "afeat:composite_neighborhood_scan", "Coordinates variable-matched moves across heterogeneous discrete blocks."),
    FeatureRelation("pfeat:mixed_blocks", "SUITS", "afeat:memetic_local_polish", "Combines discrete block variation with continuous/VND local refinement on hybrid problems."),
    FeatureRelation("pfeat:bi_objective", "SUITS", "afeat:scalarized_decomposition", "Scalarized subproblems enable directional local search to repair tight constraints and flatten minmax objectives."),
    FeatureRelation("pfeat:bi_objective", "SUITS", "afeat:pareto_crowding_ranking", "Crowding-distance sorting spreads smooth 2-objective fronts effectively when local repair is not bottlenecked."),
    FeatureRelation("pfeat:bi_objective", "SUITS", "afeat:nonconvex_pareto_scalarization", "Tchebycheff aggregation reaches non-convex discrete Pareto points missed by linear weights."),
    FeatureRelation("pfeat:many_objective", "SUITS", "afeat:reference_direction_niching", "Uniform reference-ray niching maintains balanced diversity across >=3 conflicting objectives."),
    FeatureRelation("pfeat:many_objective", "CONFLICTS_WITH", "afeat:pareto_crowding_ranking", "Axis-aligned crowding distance degenerates in >=3 objectives, leaving large Pareto regions uncovered."),
    FeatureRelation("pfeat:many_objective", "CONFLICTS_WITH", "afeat:linear_convex_scalarization", "Linear weighted sums miss non-convex discrete trade-offs on high-dimensional combinatorial fronts."),
    FeatureRelation("afeat:two_parent_recombination", "SYNERGIZES_WITH", "afeat:diverse_seeded_init", "Hybrid greedy+random seeding provides feasible anchors while preserving genetic diversity for crossover."),
    FeatureRelation("afeat:two_parent_recombination", "CONFLICTS_WITH", "afeat:pure_greedy_init", "Pure deterministic greedy initialization collapses population diversity and causes premature convergence."),
    FeatureRelation("afeat:single_step_trajectory", "SYNERGIZES_WITH", "afeat:pure_greedy_init", "Single-trajectory search benefits directly from starting inside a constructive feasible basin."),
    FeatureRelation("afeat:kick_local_descent", "SYNERGIZES_WITH", "afeat:pure_greedy_init", "Constructive greedy warm-start saves initial descent budget for basin-hopping kicks."),
    FeatureRelation("afeat:ruin_and_recreate", "SYNERGIZES_WITH", "afeat:pure_greedy_init", "Starting from a constructive feasible solution lets destroy/repair immediately optimize objective quality."),
    FeatureRelation("afeat:scalarized_decomposition", "SYNERGIZES_WITH", "afeat:composite_neighborhood_scan", "Scalar subproblem weights provide a clear descent criterion for neighborhood local search steps."),
    FeatureRelation("afeat:pareto_crowding_ranking", "CONFLICTS_WITH", "afeat:coupled_continuous_relaxation", "Heavy single-point local search inside dominance-only sorting stalls generation turnover because strict dominance rarely holds."),
    FeatureRelation("afeat:covariance_distribution", "SYNERGIZES_WITH", "afeat:coupled_continuous_relaxation", "Global covariance exploration paired with local gradient/directional polish reaches high basin precision."),
)


def reconcile_features(
    formulation: Formulation,
    problem_meta: dict[str, Any] | None = None,
    *,
    time_limit: float = 60.0,
) -> dict[str, object]:
    """Align Formulation features with ground-truth sandbox Problem dimensions and types."""
    feats: dict[str, object] = dict(formulation.features())
    feats["n_objectives"] = len(formulation.objectives)
    feats["time_limit"] = time_limit
    if problem_meta:
        for key in ("variable_types", "is_mixed_variables", "n_objectives", "objective_mode", "total_dim", "scale_level"):
            if key in problem_meta:
                feats[key] = problem_meta[key]
    return feats


def auto_problem_feature_ids(features: dict[str, object]) -> list[str]:
    """Map explicit problem features to canonical `pfeat:*` node IDs."""
    n_obj = int(features.get("n_objectives", 1))  # type: ignore[arg-type]
    out = ["pfeat:single_objective" if n_obj == 1 else ("pfeat:many_objective" if n_obj >= 3 else "pfeat:bi_objective")]
    for v in features.get("variable_types", []):  # type: ignore[attr-defined]
        out.append(f"pfeat:{v}")
    if features.get("is_mixed_variables"):
        out.append("pfeat:mixed_blocks")
    for f in features.get("objective_forms", []):  # type: ignore[attr-defined]
        out.append(f"pfeat:{f}_obj")
    for c in features.get("constraint_categories", []):  # type: ignore[attr-defined]
        if c == "nonlinear":
            out.append("pfeat:nonlinear_con")
        elif c in ("precedence", "capacity", "equality", "conflict"):
            out.append(f"pfeat:{c}")
    if features.get("scale_level") == "large":
        out.append("pfeat:large_scale")
    return list(dict.fromkeys(out))


class SolvingKnowledgeGraph:
    """Relational knowledge base mapping Problem Features <-> Algorithm Mechanism Features."""

    def __init__(self) -> None:
        self.nodes: dict[str, FeatureNode] = {n.id: n for n in (*PROBLEM_FEATURES, *ALGORITHM_FEATURES)}
        self.relations: list[FeatureRelation] = list(FEATURE_RELATIONS)

        self.alg_by_afeat: dict[str, list[str]] = {n.id: [] for n in ALGORITHM_FEATURES}
        self.op_by_afeat: dict[str, list[str]] = {n.id: [] for n in ALGORITHM_FEATURES}
        for alg, spec in ALGORITHM_SPECS.items():
            for mf in spec["features"].get("mechanism_features", []):  # type: ignore[index,union-attr]
                self.alg_by_afeat.setdefault(f"afeat:{mf}", []).append(alg)
        for group, ops in OPERATOR_SPECS.items():
            for name, card in ops.items():
                label = f"{group}:{name}" if group in ("init_strategy", "constraint_handling", "crossover") else name
                for mf in card.get("mechanism_features", []):  # type: ignore[union-attr]
                    self.op_by_afeat.setdefault(f"afeat:{mf}", []).append(label)

    def concept_catalog(self) -> dict[str, list[str]]:
        return {
            "problem_features": [k for k, n in self.nodes.items() if n.kind == "problem_feature"],
            "algorithm_features": [k for k, n in self.nodes.items() if n.kind == "algorithm_feature"],
        }

    def resolve_concepts(self, raw_concepts: list[str]) -> list[str]:
        resolved: list[str] = []
        for raw in raw_concepts:
            tok = raw.strip()
            if not tok:
                continue
            for cand in (tok, tok.replace("feature:", "pfeat:"), f"pfeat:{tok.lower()}", f"afeat:{tok.lower()}"):
                if cand in self.nodes:
                    resolved.append(cand)
                    break
            else:
                ca = canonical_algorithm(tok.removeprefix("alg:"))
                if ca in ALGORITHM_SPECS:
                    resolved.extend(f"afeat:{m}" for m in ALGORITHM_SPECS[ca]["features"]["mechanism_features"])  # type: ignore[index]
                else:
                    low = tok.lower()
                    resolved.extend([nid for nid in self.nodes if low in nid.lower()][:3])
        return list(dict.fromkeys(resolved))

    def query_knowledge(self, concepts: list[str], features: dict[str, object] | None = None) -> dict[str, object]:
        seed_ids = self.resolve_concepts(concepts)
        seed_set = set(seed_ids)

        p2a = [r for r in self.relations if r.source.startswith("pfeat:") and (r.source in seed_set or r.target in seed_set)]
        active_afeats = {c for c in seed_ids if c.startswith("afeat:")} | {r.target for r in p2a}
        a2a = [r for r in self.relations if r.source.startswith("afeat:") and (r.source in active_afeats or r.target in active_afeats)]

        obj_mode = str((features or {}).get("objective_mode", ""))
        vtypes = set((features or {}).get("variable_types", []))  # type: ignore[arg-type]

        def _compat_algs(a_id: str) -> list[str]:
            algs = self.alg_by_afeat.get(a_id, [])
            if not features:
                return algs
            return [
                a for a in algs
                if (not obj_mode or ALGORITHM_SPECS[a]["features"]["objective_mode"] == obj_mode)  # type: ignore[index]
                and (not vtypes or bool(vtypes & set(ALGORITHM_SPECS[a]["features"]["suited_variables"])))  # type: ignore[index]
            ]

        carriers = {
            aid: {
                "title": self.nodes[aid].title,
                "algorithms": _compat_algs(aid),
                "operators": self.op_by_afeat.get(aid, []),
            }
            for aid in sorted(active_afeats)
            if aid in self.nodes
        }
        return {
            "problem_to_algorithm_relations": [
                {"problem_feature": r.source, "relation": r.relation, "algorithm_feature": r.target, "why": r.explanation}
                for r in p2a
            ],
            "algorithm_feature_couplings": [
                {"source_feature": r.source, "relation": r.relation, "target_feature": r.target, "why": r.explanation}
                for r in a2a
            ],
            "algorithm_feature_carriers": carriers,
        }

    def inspect_solver_specs(self, algorithms: list[str], features: dict[str, object]) -> dict[str, object]:
        vtypes = set(features.get("variable_types", []))  # type: ignore[arg-type]
        out: dict[str, object] = {}
        for raw_a in algorithms:
            alg = canonical_algorithm(raw_a)
            if alg not in ALGORITHM_SPECS:
                out[raw_a] = {"error": f"Unknown algorithm '{raw_a}'. Valid: {list(ALGORITHM_SPECS)}"}
                continue
            spec = ALGORITHM_SPECS[alg]
            slots_info: dict[str, dict[str, object]] = {}
            for slot, opts in spec["configurable_operators"].items():  # type: ignore[attr-defined]
                slot_ops: dict[str, object] = {}
                for opt in opts:
                    card = self._operator_card(slot, opt)
                    if card is not None and opt != "auto" and vtypes and not (vtypes & set(card["suited_variables"])):  # type: ignore[arg-type]
                        continue
                    slot_ops[opt] = (
                        {"summary": card["summary"], "mechanism_features": card["mechanism_features"]}
                        if card
                        else {"summary": "Automatic variable-matched default.", "mechanism_features": []}
                    )
                slots_info[slot] = slot_ops
            out[alg] = {
                "summary": spec["summary"],
                "features": spec["features"],
                "valid_operators": slots_info,
                "default_hyperparameters": spec["hyperparameters"],
            }
        return out

    @staticmethod
    def _operator_card(slot: str, opt: str) -> dict[str, object] | None:
        if slot == "init_strategy":
            return OPERATOR_SPECS["init_strategy"].get(opt)
        if slot in ("neighborhood", "mutation"):
            return OPERATOR_SPECS["neighborhood_and_mutation"].get(opt)
        if slot == "crossover":
            return OPERATOR_SPECS["crossover"].get(opt)
        if slot in ("destroy_op", "repair_op"):
            return OPERATOR_SPECS["lns_destroy_and_repair"].get(f"{slot}:{opt}")
        if slot == "constraint_handling":
            return OPERATOR_SPECS["constraint_handling"].get(opt)
        return OPERATOR_SPECS["algorithm_specific"].get(f"{slot}:{opt}")

    def _chosen_algorithm_features(self, alg: str, operators: dict[str, str]) -> set[str]:
        spec = ALGORITHM_SPECS.get(alg, {})
        afeats = {f"afeat:{m}" for m in spec.get("features", {}).get("mechanism_features", [])}  # type: ignore[union-attr]
        for slot, choice in operators.items():
            card = self._operator_card(slot, choice)
            if card:
                afeats.update(f"afeat:{m}" for m in card.get("mechanism_features", []))  # type: ignore[union-attr]
        return afeats

    def validate_configuration(
        self,
        algorithm: str,
        operators: dict[str, str],
        hyperparameters: dict[str, float],
        features: dict[str, object],
        active_pfeats: set[str] | None = None,
    ) -> tuple[bool, list[str], list[str]]:
        alg = canonical_algorithm(algorithm)
        if alg not in ALGORITHM_SPECS:
            return False, [f"Unknown algorithm '{algorithm}'. Valid: {list(ALGORITHM_SPECS)}."], []

        hard_errors: list[str] = []
        warnings: list[str] = []
        spec = ALGORITHM_SPECS[alg]
        af = spec["features"]  # type: ignore[index]
        obj_mode = str(features.get("objective_mode", "single"))
        vtypes = set(features.get("variable_types", []))  # type: ignore[arg-type]

        if af["objective_mode"] != obj_mode:
            hard_errors.append(f"Algorithm '{alg}' requires '{af['objective_mode']}' objective mode, but problem is '{obj_mode}'.")
        if vtypes and not (vtypes & set(af["suited_variables"])):
            hard_errors.append(f"Algorithm '{alg}' does not support variables {sorted(vtypes)} (suited: {af['suited_variables']}).")
        if vtypes and "continuous" in vtypes and features.get("is_mixed_variables") and "continuous" in af["not_suited_for"]:
            hard_errors.append(f"Algorithm '{alg}' cannot optimize continuous blocks in mixed variables {sorted(vtypes)}.")

        valid_slots: dict[str, list[str]] = spec["configurable_operators"]  # type: ignore[assignment]
        for slot, choice in operators.items():
            if slot not in valid_slots or choice not in valid_slots[slot]:
                hard_errors.append(f"Invalid operator '{slot}={choice}' on {alg} (valid: {valid_slots.get(slot)}).")

        valid_hps: dict[str, object] = spec["hyperparameters"]  # type: ignore[assignment]
        for hp, val in hyperparameters.items():
            if hp not in valid_hps:
                hard_errors.append(f"Unknown hyperparameter '{hp}' on {alg} (valid: {list(valid_hps)}).")
            elif hp in ("crossover_rate", "mutation_rate", "destroy_ratio", "evaporation", "CR", "v_max_ratio") and not (0.0 < val <= 1.0):
                hard_errors.append(f"Hyperparameter '{hp}={val}' must lie in (0, 1].")
            elif hp in ("pop_size", "n_ants") and not (alg == "CMA-ES" and val == 0) and val < 6:
                hard_errors.append(f"Hyperparameter '{hp}={val}' must be >= 6 (or 0 on CMA-ES).")

        pfeats = set(auto_problem_feature_ids(features)) | {c for c in (active_pfeats or set()) if c.startswith("pfeat:")}
        chosen_afeats = self._chosen_algorithm_features(alg, operators)
        for r in self.relations:
            if r.relation == "CONFLICTS_WITH":
                if r.source in pfeats and r.target in chosen_afeats:
                    warnings.append(f"[{r.source} CONFLICTS_WITH {r.target}] {r.explanation}")
                elif r.source in chosen_afeats and r.target in chosen_afeats:
                    warnings.append(f"[{r.source} CONFLICTS_WITH {r.target}] {r.explanation}")

        return len(hard_errors) == 0, hard_errors, warnings


DEFAULT_KG = SolvingKnowledgeGraph()

KG_AGENT_PROMPT = """
You are an Optimization Solver Configuration Agent. Select and configure an algorithm, operators, and hyperparameters by aligning Problem Features (`pfeat:*`) with Algorithm & Operator Mechanism Features (`afeat:*`).

Workflow:
1. Identify Problem Features (`pfeat:*`):
   - Combine explicit features with implicit structural features visible in M = (P, X, F, C):
     * `pfeat:step_count_obj`: discrete bin/color/vehicle/item-count objective (staircase landscape);
     * `pfeat:group_symmetry`: interchangeable unlabeled groups 0..K-1;
     * `pfeat:prefix_delimiter`: permutation with stop/route delimiters;
     * `pfeat:master_slave_blocks`: active-selection block coupled with relative-index assignment block;
     * `pfeat:dense_pairwise_coupling`: all-pairs quadratic/global interactions across positions (e.g. QAP).
2. Query Feature-to-Feature Knowledge (`query_knowledge`):
   - Retrieve which `afeat:*` mechanisms SUIT or CONFLICT_WITH the active `pfeat:*` set, internal `afeat <-> afeat` synergies/conflicts, and which pool algorithms/operators carry those features.
3. Inspect Candidate Solver Specs (`inspect_solver_specs`):
   - Check the exact configurable operator slots and default hyperparameters of your top 1-3 feature-aligned frameworks.
4. Optional Empirical Check (`pilot_verify`, when available):
   - When two feature-compatible configurations represent genuinely different trade-offs (e.g. high-turnover trajectory vs ruin-and-recreate, or decomposition vs reference-direction niching), compare them briefly via `pilot_verify` to observe feasibility attainment, `evals_per_sec`, Pareto spread, and stagnation behavior.
5. Commit Complete Configuration (`commit_configuration`):
   - Provide complete `algorithm`, `operators` (explicitly filling key slots), `hyperparameters`, and a concise feature-alignment `rationale`.
""".strip()
