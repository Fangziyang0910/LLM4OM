"""Sandbox helpers for AutoCO: safe Problem loading, smoke tests, pilot verification and full solving."""

from __future__ import annotations

import inspect
import json
import linecache
import math
import time
from typing import Any

import numpy as np

from .algorithms import SolveResult, solve
from .operators import init_individual
from .problem import Problem, VarSpec
from .specs import ALGORITHM_SPECS, canonical_algorithm, sanitize_config

MAX_PARETO_RETURNED = 100


def _clean_float(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return 0.0 if num == 0 else num


def _json_safe(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return [_json_safe(item) for item in value.tolist()]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return _clean_float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, float):
        return _clean_float(value)
    return value


def load_problem(code: str, data: dict[str, str] | None = None) -> tuple[Problem, dict[str, Any]]:
    """Execute generated code in an isolated module namespace and return `(Problem, autoco_config)`."""
    namespace: dict[str, Any] = {"__name__": "generated_model", "np": np, "Problem": Problem, "VarSpec": VarSpec}
    linecache.cache["model.py"] = (len(code), None, code.splitlines(True), "model.py")
    exec(compile(code, "model.py", "exec"), namespace)
    build_fn = namespace.get("build_model") or namespace.get("build_problem")
    if not callable(build_fn):
        raise ValueError("Generated code must define callable `build_model(data) -> Problem`.")
    params = inspect.signature(build_fn).parameters
    raw = build_fn(data or {}) if params else build_fn()
    config: dict[str, Any] = {}
    if isinstance(namespace.get("AUTOCO_CONFIG"), dict):
        config.update(namespace["AUTOCO_CONFIG"])
    if isinstance(raw, dict) and isinstance(raw.get("problem"), Problem):
        problem = raw["problem"]
        for key in ("algorithm", "operators", "hyperparameters", "seed", "objective_names"):
            if key in raw and raw[key] is not None:
                config[key] = raw[key]
    elif isinstance(raw, Problem):
        problem = raw
    else:
        raise TypeError(f"`build_model(data)` must return `autoco.Problem`, got {type(raw).__name__}.")
    return problem, config


def smoke_test_problem(code: str, data: dict[str, str] | None = None) -> dict[str, Any]:
    """Run AutoCO's 5-sample validity and speed check inside the sandbox and return problem metadata."""
    problem, _ = load_problem(code, data)
    if not problem.variables:
        raise ValueError("Problem must define at least one VarSpec in `variables`.")
    rng = np.random.default_rng(0)
    t0 = time.perf_counter()
    for index in range(5):
        blocks = init_individual(problem.variables, rng)
        f_vec, cv = problem.eval_blocks(blocks)
        if not np.all(np.isfinite(f_vec)) or not np.isfinite(cv):
            raise ValueError(f"Non-finite evaluation output: f={f_vec}, cv={cv}")
        if index == 0 and callable(problem.decode):
            json.dumps(_json_safe(problem.decode(problem.format_solution(blocks))))
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    if elapsed_ms > 250.0:
        raise RuntimeError(
            f"`evaluate(x)` averaged {elapsed_ms / 5:.1f}ms/call (>50ms); precompute constant matrices outside `evaluate(x)` and vectorize."
        )
    return {
        "ok": True,
        "name": problem.name,
        "variable_types": list(dict.fromkeys(v.var_type for v in problem.variables)),
        "is_mixed_variables": len(problem.variables) > 1,
        "n_objectives": problem.n_objectives,
        "objective_mode": "multi" if problem.is_multi_objective else "single",
        "senses": list(problem.senses),
        "total_dim": problem.total_dim,
        "scale_level": "small" if problem.total_dim <= 30 else ("medium" if problem.total_dim <= 200 else "large"),
        "eval_ms": round(elapsed_ms / 5.0, 2),
    }


def _pilot_one(problem: Problem, cand: dict[str, Any], trial_sec: float) -> dict[str, Any]:
    alg = canonical_algorithm(str(cand.get("algorithm", "auto")))
    if alg not in ALGORITHM_SPECS:
        return {"algorithm": alg, "error": f"Unknown algorithm '{alg}'. Valid: {list(ALGORITHM_SPECS)}"}
    kwargs = sanitize_config(alg, cand.get("operators") or {}, cand.get("hyperparameters") or {})
    try:
        res = solve(problem, alg, time_limit=trial_sec, seed=101, **kwargs)
    except ValueError as exc:
        return {"algorithm": alg, "error": str(exc)}
    stag_tail = round(1.0 - (res.last_improve_eval / max(1, res.n_evals)), 2) if res.feasible else 1.0
    out: dict[str, Any] = {
        "algorithm": res.algorithm,
        "applied_config": res.config,
        "feasible": res.feasible,
        "best_violation": round(res.best_violation, 6),
        "best_objective": (
            np.round(res.best_objective, 4).tolist()
            if isinstance(res.best_objective, np.ndarray)
            else (round(float(res.best_objective), 4) if res.best_objective is not None else None)
        ),
        "pareto_count": len(res.pareto_solutions) if problem.is_multi_objective else 0,
        "strict_improvements": res.strict_improvements,
        "stagnation_tail_ratio": stag_tail,
        "n_evals": res.n_evals,
        "evals_per_sec": int(round(res.n_evals / max(1e-3, res.elapsed_sec))),
    }
    if problem.is_multi_objective and res.pareto_objectives is not None and len(res.pareto_objectives) > 0:
        signs = np.array([1.0 if s == "min" else -1.0 for s in problem.senses], dtype=float)
        min_f = res.pareto_objectives * signs
        out["pareto_ideal"] = np.round(min_f.min(axis=0), 4).tolist()
        out["pareto_nadir"] = np.round(min_f.max(axis=0), 4).tolist()
    return out


def pilot_trial(code: str, data: dict[str, str] | None, candidates: list[dict[str, Any]], trial_seconds: float) -> list[dict[str, Any]]:
    problem, _ = load_problem(code, data)
    return [_pilot_one(problem, cand, trial_seconds) for cand in candidates]


def flatten_solution(problem: Problem, solution: Any) -> dict[str, float]:
    """Flatten a single AutoCO solution into `name[i] -> float` (or `name -> float` when size == 1)."""
    if solution is None:
        return {}
    if isinstance(solution, dict):
        items = [(spec, solution.get(spec.name)) for spec in problem.variables]
    else:
        items = [(problem.variables[0], solution)]
    flat: dict[str, float] = {}
    for spec, arr in items:
        if arr is None:
            continue
        values = np.atleast_1d(np.asarray(arr)).reshape(-1)
        if values.size == 1:
            if (cleaned := _clean_float(values[0])) is not None:
                flat[spec.name] = cleaned
        else:
            for idx, item in enumerate(values):
                if (cleaned := _clean_float(item)) is not None:
                    flat[f"{spec.name}[{idx}]"] = cleaned
    return flat


def _safe_decode(problem: Problem, solution: Any) -> Any:
    if solution is None or not callable(problem.decode):
        return None
    try:
        return _json_safe(problem.decode(solution))
    except Exception:
        return None


def _build_pareto(problem: Problem, res: SolveResult, objective_names: list[str] | None) -> dict[str, Any] | None:
    if not problem.is_multi_objective or res.pareto_objectives is None or len(res.pareto_solutions) == 0:
        return None
    names = objective_names if (objective_names and len(objective_names) == problem.n_objectives) else [
        f"f{i + 1}" for i in range(problem.n_objectives)
    ]
    objectives_meta = [{"name": str(name), "sense": sense} for name, sense in zip(names, problem.senses)]
    pareto_objs = np.asarray(res.pareto_objectives, dtype=float)
    best_arr = np.asarray(res.best_objective, dtype=float) if res.best_objective is not None else None
    knee_idx = 0
    if best_arr is not None and pareto_objs.ndim == 2 and len(pareto_objs) > 0:
        dists = np.linalg.norm(pareto_objs - best_arr[None, :], axis=1)
        knee_idx = int(np.argmin(dists))
    total = len(res.pareto_solutions)
    if total <= MAX_PARETO_RETURNED:
        indices = list(range(total))
    else:
        sampled = sorted(set(np.linspace(0, total - 1, MAX_PARETO_RETURNED - 1, dtype=int).tolist() + [knee_idx]))
        indices = sampled[:MAX_PARETO_RETURNED]
    solutions = []
    for idx in indices:
        sol = res.pareto_solutions[idx]
        row: dict[str, Any] = {
            "objectives": [_clean_float(v) for v in pareto_objs[idx].tolist()],
            "knee": idx == knee_idx,
            "variables": flatten_solution(problem, sol),
        }
        decoded = _safe_decode(problem, sol)
        if decoded is not None:
            row["decoded"] = decoded
        solutions.append(row)
    return {"objectives": objectives_meta, "solutions": solutions, "total": total}


def solve_problem(code: str, data: dict[str, str] | None, solver: str | None, time_limit: float) -> dict[str, Any]:
    """Build and solve an AutoCO problem inside the sandbox and shape a platform SolveResult payload."""
    problem, config = load_problem(code, data)
    alg_req = str(config.get("algorithm") or solver or "AUTO")
    alg = "AUTO" if alg_req.strip().upper() == "AUTO" else canonical_algorithm(alg_req)
    operators = config.get("operators") if isinstance(config.get("operators"), dict) else {}
    hyperparameters = config.get("hyperparameters") if isinstance(config.get("hyperparameters"), dict) else {}
    seed = int(config.get("seed", 42))
    kwargs = sanitize_config(alg, operators, hyperparameters) if alg != "AUTO" else {}
    res = solve(problem, alg, time_limit=float(time_limit), seed=seed, **kwargs)

    status = "feasible" if res.feasible else "infeasible"
    variables = flatten_solution(problem, res.best_solution) if res.feasible else {}
    objective: float | None = None
    pareto: dict[str, Any] | None = None
    if res.feasible:
        if problem.is_multi_objective:
            obj_names = config.get("objective_names") if isinstance(config.get("objective_names"), list) else None
            pareto = _build_pareto(problem, res, obj_names)
        elif res.best_objective is not None:
            objective = _clean_float(res.best_objective)

    lines = [
        f"Algorithm: {res.algorithm}",
        f"Config: {json.dumps(res.config, ensure_ascii=False)}",
        f"Evaluations: {res.n_evals} in {res.elapsed_sec:.2f}s (feasible={res.feasible}, violation={res.best_violation:g})",
    ]
    if pareto is not None:
        lines.append(f"Pareto front: {pareto['total']} non-dominated solutions")
        knee = next((item for item in pareto["solutions"] if item.get("knee")), None)
        if knee is not None:
            pairs = ", ".join(f"{meta['name']}={val:g}" for meta, val in zip(pareto["objectives"], knee["objectives"]) if val is not None)
            lines.append(f"Knee compromise solution: {pairs}")
    decoded = _safe_decode(problem, res.best_solution) if res.feasible else None
    if decoded is not None:
        lines.append("Decoded solution:\n" + json.dumps(decoded, ensure_ascii=False, indent=2))
    return {
        "status": status,
        "objective": objective,
        "variables": variables,
        "output": "\n".join(lines),
        "error": None,
        "diagnosis": None,
        "solver": res.algorithm,
        "pareto": pareto,
    }
