"""Pure-Python catalog of AutoCO's 12 algorithms, operators, aliases and config sanitization (no solver deps)."""

from __future__ import annotations

_ALL_VARS = ["permutation", "binary", "assignment", "integer", "continuous"]
_ALL_CONS = ["unconstrained", "bound", "capacity", "precedence", "conflict", "equality", "nonlinear"]
_DISC_NB = ["vnd", "insert", "or_opt", "swap", "2opt", "bitflip", "swap_01", "reassign"]
_ALL_MUT = ["auto", *_DISC_NB, "lbfgsb", "powell", "gaussian", "polynomial"]
_ALL_CX = ["auto", "ox", "pmx", "uniform", "two_point", "sbx", "blend"]
_CH = ["feasibility", "adaptive_penalty", "penalty"]
_ALL_OBJ = ["linear", "quadratic", "nonlinear", "minmax"]


def _op(
    summary: str,
    vars_: list[str],
    cons: list[str],
    avoid: list[str] | None = None,
    mech: list[str] | None = None,
) -> dict[str, object]:
    return {
        "summary": summary,
        "mechanism_features": mech or [],
        "suited_variables": vars_,
        "suited_constraints": cons,
        "not_suited_for": avoid or [],
    }


OPERATOR_SPECS: dict[str, dict[str, dict[str, object]]] = {
    "init_strategy": {
        "auto": _op("Greedy seed for trajectory search; mixed greedy+random for populations.", _ALL_VARS, _ALL_CONS),
        "greedy": _op("Step-by-step feasibility-first constructive seed.", _ALL_VARS, ["precedence", "conflict", "capacity", "equality"], mech=["pure_greedy_init"]),
        "mixed": _op("Seeds ~10-15% greedy cornerstones + ~85-90% random diversity.", _ALL_VARS, _ALL_CONS, mech=["diverse_seeded_init"]),
        "random": _op("Uniform random sampling.", _ALL_VARS, ["unconstrained", "bound"], ["precedence", "conflict", "equality"], mech=["uniform_random_init"]),
    },
    "neighborhood_and_mutation": {
        "vnd": _op("Cycles complementary moves across blocks (insert+swap+or_opt+2opt on permutation; single+swap on binary/assignment).", ["permutation", "binary", "assignment", "integer"], _ALL_CONS, mech=["composite_neighborhood_scan"]),
        "insert": _op("Relocates 1 permutation element, preserving relative order of others.", ["permutation"], ["precedence", "capacity", "unconstrained"], mech=["order_preserving_move", "lightweight_local_move"]),
        "or_opt": _op("Relocates 2-3 consecutive permutation elements without reversing their order.", ["permutation"], ["precedence", "capacity"], mech=["order_preserving_move", "lightweight_local_move"]),
        "swap": _op("Exchanges two positions or two items' categories (preserves category counts).", ["permutation", "assignment"], ["capacity", "equality", "conflict", "unconstrained"], mech=["cardinality_preserving_swap", "lightweight_local_move"]),
        "2opt": _op("Reverses a contiguous permutation segment.", ["permutation"], ["unconstrained", "bound"], ["precedence"], mech=["segment_reversing_move", "lightweight_local_move"]),
        "bitflip": _op("Flips 0/1 bits independently.", ["binary"], ["unconstrained", "bound", "capacity", "conflict"], ["equality"], mech=["cardinality_changing_flip", "lightweight_local_move"]),
        "swap_01": _op("Flips one 1->0 and one 0->1 simultaneously, preserving selected count.", ["binary"], ["capacity", "equality", "conflict"], mech=["cardinality_preserving_swap", "lightweight_local_move"]),
        "reassign": _op("Reassigns an item to another category (preferring active categories when K is large).", ["assignment"], ["capacity", "conflict", "unconstrained"], ["equality"], mech=["cardinality_changing_flip", "lightweight_local_move"]),
        "lbfgsb": _op("SciPy L-BFGS-B bounded quasi-Newton continuous optimization sliding all continuous coordinates jointly.", ["continuous"], ["unconstrained", "bound", "capacity", "nonlinear", "equality"], mech=["coupled_continuous_relaxation"]),
        "powell": _op("SciPy Powell derivative-free directional continuous optimization for non-smooth/min-max landscapes.", ["continuous"], ["unconstrained", "bound", "capacity", "nonlinear", "equality"], mech=["coupled_continuous_relaxation"]),
        "gaussian": _op("Bounded Gaussian step perturbation.", ["continuous", "integer"], ["unconstrained", "bound", "capacity", "nonlinear"], mech=["coordinate_perturbation"]),
        "polynomial": _op("Bounded polynomial mutation.", ["continuous", "integer"], ["unconstrained", "bound", "capacity", "nonlinear"], mech=["coordinate_perturbation"]),
        "cauchy": _op("Heavy-tailed Cauchy jump for multimodal continuous landscapes.", ["continuous"], ["unconstrained", "bound", "nonlinear"], mech=["coordinate_perturbation", "stochastic_uphill_acceptance"]),
    },
    "crossover": {
        "ox": _op("Order Crossover preserving subtour and relative sequence.", ["permutation"], ["precedence", "capacity", "unconstrained"], mech=["order_preserving_move"]),
        "pmx": _op("Partially Mapped Crossover preserving absolute position mappings.", ["permutation"], ["conflict", "equality", "unconstrained"], mech=["position_mapping_crossover"]),
        "uniform": _op("Independent 0.5-probability gene inheritance.", ["binary", "assignment"], ["capacity", "conflict", "unconstrained"], mech=["independent_gene_mixing", "cardinality_changing_flip"]),
        "two_point": _op("Exchanges one contiguous index segment.", ["binary", "assignment"], ["capacity", "unconstrained"], mech=["contiguous_slice_crossover"]),
        "sbx": _op("Simulated Binary Crossover for metric coordinates.", ["continuous", "integer"], ["bound", "capacity", "nonlinear", "unconstrained"], mech=["metric_interval_crossover"]),
        "blend": _op("BLX-alpha interval interpolation/extrapolation.", ["continuous", "integer"], ["bound", "nonlinear", "unconstrained"], mech=["metric_interval_crossover"]),
    },
    "lns_destroy_and_repair": {
        "destroy_op:auto": _op("ALNS adaptive roulette across 'random', 'block', 'worst', and 'group' removal.", ["permutation", "assignment", "binary", "integer"], ["precedence", "capacity", "conflict", "equality"], mech=["bottleneck_targeted_ruin", "group_emptying_ruin"]),
        "destroy_op:random": _op("Removes scattered positions to rebalance load across vehicles/bins.", ["permutation", "assignment", "binary", "integer"], ["capacity", "conflict", "equality"], mech=["scattered_subset_ruin"]),
        "destroy_op:block": _op("Removes one contiguous index slice arr[i:i+d].", ["permutation", "assignment", "binary"], ["precedence", "unconstrained"], mech=["contiguous_slice_ruin"]),
        "destroy_op:worst": _op("Removes active bottleneck/low-efficiency elements causing highest cost or violation.", ["permutation", "assignment", "binary", "integer"], ["capacity", "precedence", "conflict", "nonlinear"], mech=["bottleneck_targeted_ruin"]),
        "destroy_op:group": _op("Empties an entire sparsely loaded category/group plus slack items to consolidate bins/colors.", ["assignment", "permutation"], ["capacity", "conflict"], mech=["group_emptying_ruin"]),
        "repair_op:greedy": _op("Re-inserts/reassigns each destroyed variable into its best feasible slot.", ["permutation", "assignment", "binary", "integer"], ["capacity", "conflict", "unconstrained"], mech=["fast_greedy_repair"]),
        "repair_op:regret": _op("2-regret lookahead repair prioritizing bottleneck variables first.", ["permutation", "assignment"], ["precedence", "capacity", "conflict", "equality"], mech=["lookahead_regret_repair"]),
    },
    "constraint_handling": {
        "feasibility": _op("Deb parameter-free feasibility rule (feasible strictly beats infeasible).", _ALL_VARS, ["capacity", "precedence", "conflict", "equality", "nonlinear"], mech=["strict_feasibility_dominance"]),
        "adaptive_penalty": _op("Auto-scaled penalty ramping smoothly across budget to cross narrow infeasible ridges.", _ALL_VARS, ["equality", "conflict", "capacity", "precedence", "nonlinear"], mech=["barrier_tunneling_penalty"]),
        "penalty": _op("Static auto-scaled linear penalty.", _ALL_VARS, ["bound", "capacity"], ["precedence", "equality"], mech=["static_linear_penalty"]),
    },
    "algorithm_specific": {
        "selection:tournament": _op("k-way tournament parent selection.", _ALL_VARS, _ALL_CONS),
        "selection:rank": _op("Rank-proportional parent selection.", _ALL_VARS, _ALL_CONS),
        "strategy:current-to-best/1/bin": _op("Balances attraction to best vector with differential exploration.", ["continuous", "integer"], ["bound", "capacity", "nonlinear", "unconstrained"]),
        "strategy:rand/1/bin": _op("Diversity-preserving random-base differential mutation.", ["continuous", "integer"], ["bound", "nonlinear", "unconstrained"]),
        "strategy:best/1/bin": _op("Greedy best-base differential mutation.", ["continuous", "integer"], ["bound", "unconstrained"]),
        "topology:global": _op("Global-best swarm attraction.", ["continuous", "integer"], ["bound", "unconstrained"]),
        "topology:ring": _op("Ring-neighborhood swarm attraction preventing premature collapse.", ["continuous", "integer"], ["bound", "capacity", "nonlinear"]),
        "local_polish:lbfgsb": _op("Periodic SciPy L-BFGS-B polish on best continuous candidates.", ["continuous"], ["unconstrained", "bound", "capacity", "nonlinear", "equality"], mech=["coupled_continuous_relaxation"]),
        "local_polish:powell": _op("Periodic SciPy Powell derivative-free polish on best continuous candidates.", ["continuous"], ["unconstrained", "bound", "capacity", "nonlinear", "equality"], mech=["coupled_continuous_relaxation"]),
        "local_polish:none": _op("Pure covariance evolution without SciPy local polish.", ["continuous", "integer"], _ALL_CONS),
        "pheromone_update:mmas": _op("Bounded MAX-MIN pheromone update.", ["permutation", "assignment", "binary"], ["capacity", "precedence", "conflict", "unconstrained"]),
        "pheromone_update:elitist": _op("Global-best pheromone reinforcement.", ["permutation", "assignment", "binary"], ["capacity", "unconstrained"]),
        "accept:sa": _op("Boltzmann acceptance escaping initial repaired basins.", ["permutation", "assignment", "binary", "integer"], ["precedence", "capacity", "conflict", "equality"], mech=["stochastic_uphill_acceptance"]),
        "accept:greedy": _op("Monotone non-worsening acceptance.", ["permutation", "assignment", "binary", "integer"], ["unconstrained", "bound"], mech=["monotone_greedy_acceptance"]),
        "aggregation:tchebycheff": _op("Normalized Tchebycheff scalarization reaching convex and non-convex Pareto points.", _ALL_VARS, _ALL_CONS, mech=["nonconvex_pareto_scalarization"]),
        "aggregation:weighted_sum": _op("Linear weighted-sum scalarization for convex Pareto fronts.", _ALL_VARS, ["unconstrained", "bound", "capacity"], mech=["linear_convex_scalarization"]),
    },
}


def _alg(
    summary: str,
    mode: str,
    mech: list[str],
    objs: list[str],
    vars_: list[str],
    mixed: bool,
    cons: list[str],
    scales: list[str],
    avoid: list[str],
    ops: dict[str, list[str]],
    hps: dict[str, object],
) -> dict[str, object]:
    return {
        "summary": summary,
        "features": {
            "objective_mode": mode,
            "mechanism_features": mech,
            "suited_objectives": objs,
            "suited_variables": vars_,
            "mixed_variables": mixed,
            "suited_constraints": cons,
            "suited_scales": scales,
            "not_suited_for": avoid,
        },
        "configurable_operators": ops,
        "hyperparameters": hps,
    }


ALGORITHM_SPECS: dict[str, dict[str, object]] = {
    "SA": _alg("Boltzmann annealing trajectory with auto-calibrated temperature and stagnation reheating.", "single", ["single_step_trajectory", "stochastic_uphill_acceptance"], _ALL_OBJ, ["permutation", "binary", "assignment", "integer", "continuous"], True, ["unconstrained", "bound", "capacity", "conflict", "nonlinear"], ["small", "medium", "large"], ["precedence", "equality"], {"init_strategy": ["auto", "greedy", "random"], "neighborhood": ["auto", *_DISC_NB, "cauchy"], "constraint_handling": _CH}, {"t_start": 0.0, "t_end": 1e-3, "step_scale": 0.1}),
    "TS": _alg("Memory-guided discrete trajectory picking best non-tabu neighbor with aspiration and diversification kicks.", "single", ["single_step_trajectory", "tabu_memory_guidance"], _ALL_OBJ, ["permutation", "assignment", "binary", "integer"], False, ["conflict", "capacity", "precedence", "equality", "unconstrained"], ["small", "medium", "large"], ["continuous"], {"init_strategy": ["auto", "greedy", "random"], "neighborhood": ["auto", *_DISC_NB], "constraint_handling": _CH}, {"tabu_tenure": 12, "candidate_size": 25, "step_scale": 0.1}),
    "ILS": _alg("Iterated Local Search alternating VND/SciPy local descent with double-bridge / multi-step perturbation kicks.", "single", ["kick_local_descent"], _ALL_OBJ, ["permutation", "binary", "assignment", "integer", "continuous"], True, ["unconstrained", "capacity", "precedence", "conflict", "nonlinear"], ["small", "medium", "large"], ["equality"], {"init_strategy": ["auto", "greedy", "random"], "neighborhood": [*_DISC_NB, "lbfgsb", "powell"], "constraint_handling": _CH}, {"kick_strength": 3, "descent_patience": 80, "step_scale": 0.1}),
    "LNS": _alg("Adaptive Large Neighborhood Search (ALNS) with subset destroy, constructive repair, and local polish.", "single", ["ruin_and_recreate"], _ALL_OBJ, ["permutation", "assignment", "binary", "integer"], True, ["precedence", "capacity", "conflict", "equality", "nonlinear"], ["small", "medium", "large"], ["continuous"], {"init_strategy": ["auto", "greedy", "random"], "destroy_op": ["auto", "random", "block", "worst", "group"], "repair_op": ["greedy", "regret"], "neighborhood": _DISC_NB, "accept": ["sa", "greedy"], "constraint_handling": _CH}, {"destroy_ratio": 0.2, "candidate_trials": 48, "local_search_steps": 10}),
    "GA": _alg("Memetic Genetic Algorithm combining block-matched crossover/mutation with VND or SciPy (L-BFGS-B/Powell) local polish.", "single", ["two_parent_recombination", "memetic_local_polish"], _ALL_OBJ, ["binary", "assignment", "permutation", "integer", "continuous"], True, ["capacity", "conflict", "equality", "nonlinear", "bound", "unconstrained"], ["small", "medium"], ["precedence", "large"], {"init_strategy": ["auto", "mixed", "greedy", "random"], "selection": ["tournament", "rank"], "crossover": _ALL_CX, "mutation": _ALL_MUT, "constraint_handling": _CH}, {"pop_size": 40, "crossover_rate": 0.85, "mutation_rate": 0.2, "tournament_k": 3, "elitism": 2, "local_search_steps": 3}),
    "CMA-ES": _alg("IPOP Covariance Matrix Adaptation Evolution Strategy (pycma) with SciPy local polish for coupled continuous landscapes.", "single", ["covariance_distribution", "coupled_continuous_relaxation"], _ALL_OBJ, ["continuous", "integer"], False, ["bound", "nonlinear", "capacity", "equality", "unconstrained"], ["small", "medium"], ["permutation", "assignment", "binary"], {"init_strategy": ["auto", "greedy", "random"], "local_polish": ["lbfgsb", "powell", "none"], "constraint_handling": _CH}, {"pop_size": 0, "sigma0": 0.25}),
    "DE": _alg("Differential Evolution mutating vectors via scaled population differences with collapse re-diversification.", "single", ["vector_difference_step"], _ALL_OBJ, ["continuous", "integer"], False, ["bound", "nonlinear", "capacity", "unconstrained"], ["small", "medium"], ["permutation", "assignment", "binary"], {"init_strategy": ["auto", "mixed", "greedy", "random"], "strategy": ["current-to-best/1/bin", "rand/1/bin", "best/1/bin"], "constraint_handling": _CH}, {"pop_size": 40, "F": 0.7, "CR": 0.9}),
    "PSO": _alg("Particle Swarm Optimization with decaying inertia and stagnation re-dispersal.", "single", ["vector_difference_step"], ["nonlinear", "quadratic", "linear"], ["continuous", "integer"], False, ["bound", "nonlinear", "unconstrained"], ["small", "medium"], ["permutation", "assignment", "binary", "equality"], {"init_strategy": ["auto", "mixed", "greedy", "random"], "topology": ["global", "ring"], "constraint_handling": _CH}, {"pop_size": 40, "w": 0.72, "c1": 1.49, "c2": 1.49, "v_max_ratio": 0.2}),
    "ACO": _alg("Ant Colony Optimization learning discrete transition pheromones with greedy warm-start and local search.", "single", ["pheromone_constructive"], ["linear", "nonlinear", "quadratic"], ["permutation", "assignment", "binary"], False, ["capacity", "conflict", "precedence", "unconstrained"], ["small", "medium"], ["continuous", "large"], {"init_strategy": ["auto", "greedy", "random"], "pheromone_update": ["mmas", "elitist"], "neighborhood": _DISC_NB, "constraint_handling": _CH}, {"n_ants": 25, "evaporation": 0.15, "alpha": 1.0, "local_search_steps": 3}),
    "NSGA-II": _alg("Constrained Pareto non-dominated sorting + crowding-distance evolutionary algorithm (pymoo RankAndCrowding).", "multi", ["two_parent_recombination", "pareto_crowding_ranking"], _ALL_OBJ, ["binary", "assignment", "permutation", "integer", "continuous"], True, ["capacity", "conflict", "precedence", "nonlinear", "bound", "unconstrained"], ["small", "medium"], ["single", "many_objective"], {"init_strategy": ["auto", "mixed", "greedy", "random"], "crossover": _ALL_CX, "mutation": _ALL_MUT}, {"pop_size": 50, "crossover_rate": 0.9, "mutation_rate": 0.2, "local_search_steps": 0}),
    "MOEA/D": _alg("Decomposition-based multi-objective EA solving cooperative scalarized subproblems with neighborhood local search.", "multi", ["two_parent_recombination", "scalarized_decomposition"], _ALL_OBJ, ["assignment", "binary", "permutation", "integer", "continuous"], True, ["capacity", "conflict", "precedence", "equality", "bound", "unconstrained"], ["small", "medium"], ["single"], {"init_strategy": ["auto", "mixed", "greedy", "random"], "aggregation": ["tchebycheff", "weighted_sum"], "crossover": _ALL_CX, "mutation": _ALL_MUT}, {"pop_size": 50, "neighbor_size": 10, "crossover_rate": 0.9, "mutation_rate": 0.2, "local_search_steps": 2}),
    "NSGA-III": _alg("Reference-direction hyperplane niche-preservation multi-objective EA (pymoo) excelling on >=3 objectives.", "multi", ["two_parent_recombination", "reference_direction_niching"], _ALL_OBJ, ["binary", "assignment", "permutation", "integer", "continuous"], True, ["capacity", "conflict", "precedence", "equality", "nonlinear", "bound", "unconstrained"], ["small", "medium"], ["single"], {"init_strategy": ["auto", "mixed", "greedy", "random"], "crossover": _ALL_CX, "mutation": _ALL_MUT}, {"pop_size": 60, "crossover_rate": 0.9, "mutation_rate": 0.2, "local_search_steps": 0}),
}

_ALIASES = {
    "NSGA2": "NSGA-II",
    "NSGA3": "NSGA-III",
    "MOEAD": "MOEA/D",
    "MOEA-D": "MOEA/D",
    "CMAES": "CMA-ES",
    "CMA": "CMA-ES",
    "ALNS": "LNS",
    "MA": "GA",
    "VNS": "ILS",
}


def canonical_algorithm(name: str) -> str:
    raw = name.strip()
    if raw.lower().startswith("alg:"):
        raw = raw[4:].strip()
    raw = raw.upper()
    return _ALIASES.get(raw, raw)


def sanitize_config(algorithm: str, operators: dict[str, object], hyperparameters: dict[str, object]) -> dict[str, object]:
    spec = ALGORITHM_SPECS.get(canonical_algorithm(algorithm), {})
    valid_ops: dict[str, list[str]] = spec.get("configurable_operators", {})  # type: ignore[assignment]
    valid_hps: dict[str, object] = spec.get("hyperparameters", {})  # type: ignore[assignment]
    cfg: dict[str, object] = {str(s): str(c) for s, c in operators.items() if str(s) in valid_ops and str(c) in valid_ops[str(s)]}
    for k, v in hyperparameters.items():
        if str(k) in valid_hps and v is not None:
            cfg[str(k)] = int(round(float(v))) if isinstance(valid_hps[str(k)], int) else float(v)  # type: ignore[arg-type]
    return cfg
