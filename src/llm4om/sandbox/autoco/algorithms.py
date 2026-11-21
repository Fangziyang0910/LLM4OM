"""Configurable intelligent optimization solver pool (12 orthogonal algorithms: NumPy combinatorial + cma/SciPy/pymoo)."""

from __future__ import annotations

import inspect
import time
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from .operators import (
    apply_neighbor_move,
    copy_blocks,
    crossover_individuals,
    decode_latent,
    encode_latent,
    init_individual,
    latent_bounds,
    mutate_individual,
    perturb_individual,
    scipy_polish_continuous,
)
from .problem import ConstraintHandling, Problem, VarSpec, energy_delta, scalar_score
from .specs import canonical_algorithm


class _BudgetStop(Exception):
    """Signal raised when time_limit or max_evals is reached."""


@dataclass
class SolveResult:
    algorithm: str
    best_solution: np.ndarray | dict[str, np.ndarray] | None
    best_objective: float | np.ndarray | None
    best_violation: float
    feasible: bool
    n_evals: int
    elapsed_sec: float
    pareto_solutions: list[np.ndarray | dict[str, np.ndarray]] = field(default_factory=list)
    pareto_objectives: np.ndarray | None = None
    config: dict[str, object] = field(default_factory=dict)
    first_feasible_eval: int | None = None
    strict_improvements: int = 0
    last_improve_eval: int = 0


def _crowding_distance(F_front: np.ndarray) -> np.ndarray:
    k, m = F_front.shape
    if k <= 2:
        return np.full(k, float("inf"))
    dist = np.zeros(k, dtype=float)
    for obj_i in range(m):
        order = np.argsort(F_front[:, obj_i])
        f_min, f_max = F_front[order[0], obj_i], F_front[order[-1], obj_i]
        dist[order[0]] = dist[order[-1]] = float("inf")
        if f_max - f_min > 1e-12:
            dist[order[1:-1]] += (F_front[order[2:], obj_i] - F_front[order[:-2], obj_i]) / (f_max - f_min)
    return dist


class _BudgetEvaluator:
    """Enforces evaluation/time budgets, auto-calibrates penalty scale, and tracks best/Pareto solutions."""

    def __init__(self, problem: Problem, time_limit: float | None, max_evals: int | None) -> None:
        self.problem = problem
        self.time_limit = time_limit
        self.max_evals = max_evals
        self.t0 = time.perf_counter()
        self.n_evals = 0

        self.best_blocks: list[np.ndarray] | None = None
        self.best_f: np.ndarray | None = None
        self.best_cv: float = float("inf")
        self.first_feasible_eval: int | None = None
        self.strict_improvements: int = 0
        self.last_improve_eval: int = 0

        self.archive_blocks: list[list[np.ndarray]] = []
        self.archive_f: list[np.ndarray] = []

        self._f_samples: list[float] = []
        self._cv_samples: list[float] = []
        self._auto_pw: float = 1e3
        self.f_min: np.ndarray | None = None
        self.f_max: np.ndarray | None = None

    def progress(self) -> float:
        ratios = []
        if self.time_limit and self.time_limit > 0:
            ratios.append((time.perf_counter() - self.t0) / self.time_limit)
        if self.max_evals and self.max_evals > 0:
            ratios.append(self.n_evals / self.max_evals)
        return float(np.clip(max(ratios) if ratios else 0.0, 0.0, 1.0))

    def resolve_penalty(self, penalty_weight: float | None) -> float:
        return float(penalty_weight) if (penalty_weight is not None and penalty_weight > 0) else self._auto_pw

    def eval(self, blocks: list[np.ndarray]) -> tuple[np.ndarray, float]:
        if self.n_evals > 0:
            if self.max_evals is not None and self.n_evals >= self.max_evals:
                raise _BudgetStop
            if self.time_limit is not None and (time.perf_counter() - self.t0) >= self.time_limit:
                raise _BudgetStop

        f_vec, cv = self.problem.eval_blocks(blocks)
        self.n_evals += 1
        if self.f_min is None:
            self.f_min, self.f_max = f_vec.copy(), f_vec.copy()
        else:
            self.f_min = np.minimum(self.f_min, f_vec)
            self.f_max = np.maximum(self.f_max, f_vec)
        if len(self._f_samples) < 48:
            self._f_samples.append(max(1.0, float(np.abs(f_vec).sum())))
            if cv > 1e-9:
                self._cv_samples.append(cv)
            if self._cv_samples:
                self._auto_pw = max(1.0, 6.0 * float(np.median(self._f_samples)) / max(1e-6, float(np.median(self._cv_samples))))
        self._update_best(blocks, f_vec, cv)
        return f_vec, cv

    def _update_best(self, blocks: list[np.ndarray], f_vec: np.ndarray, cv: float) -> None:
        feas_new, feas_cur = cv <= 1e-9, self.best_cv <= 1e-9
        if feas_new and self.first_feasible_eval is None:
            self.first_feasible_eval = self.n_evals
        if (
            self.best_f is None
            or (feas_new and not feas_cur)
            or (not feas_new and not feas_cur and cv < self.best_cv)
            or (feas_new and feas_cur and float(f_vec.sum()) < float(self.best_f.sum()) - 1e-9)
        ):
            if feas_new and feas_cur and self.best_f is not None:
                self.strict_improvements += 1
                self.last_improve_eval = self.n_evals
            self.best_blocks, self.best_f, self.best_cv = copy_blocks(blocks), f_vec.copy(), cv

        if self.problem.is_multi_objective and feas_new:
            keep_b, keep_f = [], []
            for ab, af in zip(self.archive_blocks, self.archive_f):
                if np.allclose(af, f_vec, atol=1e-9, rtol=1e-9) or (np.all(af <= f_vec) and np.any(af < f_vec)):
                    return
                if not (np.all(f_vec <= af) and np.any(f_vec < af)):
                    keep_b.append(ab)
                    keep_f.append(af)
            keep_b.append(copy_blocks(blocks))
            keep_f.append(f_vec.copy())
            if len(keep_f) > 200:
                top_idx = np.argsort(-_crowding_distance(np.array(keep_f, dtype=float)))[:200]
                keep_b = [keep_b[int(i)] for i in top_idx]
                keep_f = [keep_f[int(i)] for i in top_idx]
            self.archive_blocks, self.archive_f = keep_b, keep_f


# --- Domain-Agnostic Constructive Initialization ---


def _sample_positions(n: int, k: int, rng: np.random.Generator) -> list[int]:
    if n <= k:
        return list(range(n))
    grid = np.linspace(0, n - 1, k // 2, dtype=int).tolist()
    rnd = rng.choice(n, size=k - len(grid), replace=False).tolist()
    return sorted(set(grid + rnd))


def _greedy_construct(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    weight_vec: np.ndarray | None = None,
    rcl_k: int = 1,
    budget_cap: float = 0.15,
) -> tuple[list[np.ndarray], np.ndarray, float]:
    """Construct a feasibility-seeking seed using only Problem + VarSpec."""
    specs = ev.problem.variables
    t_init0 = time.perf_counter()

    def _over_cap() -> bool:
        return ev.progress() >= budget_cap or (
            ev.time_limit is not None and (time.perf_counter() - t_init0) >= min(2.5, ev.time_limit * budget_cap)
        )

    def _score(fv: np.ndarray, cv: float) -> tuple[int, float]:
        if cv > 1e-9:
            return (1, cv)
        if weight_vec is not None and ev.f_min is not None and ev.f_max is not None:
            return (0, float(np.dot(weight_vec, (fv - ev.f_min) / np.maximum(1e-9, ev.f_max - ev.f_min))))
        return (0, float(fv[0]))

    # Probe 3 structural anchors (random, compact/low/identity, balanced/high/reverse)
    c_rand = init_individual(specs, rng)
    c_low, c_bal = [], []
    for s in specs:
        if s.var_type == "binary":
            c_low.append(np.zeros(s.size, dtype=np.int64))
            c_bal.append(np.ones(s.size, dtype=np.int64))
        elif s.var_type == "assignment":
            c_low.append(np.zeros(s.size, dtype=np.int64))
            c_bal.append((rng.permutation(s.size) % s.n_categories).astype(np.int64))
        elif s.var_type == "permutation":
            c_low.append(np.arange(s.size, dtype=np.int64))
            c_bal.append(np.arange(s.size - 1, -1, -1, dtype=np.int64))
        elif s.var_type == "integer":
            mid = int(np.clip(np.rint(0.5 * (s.lb + s.ub)), np.ceil(s.lb), np.floor(s.ub)))
            c_low.append(np.full(s.size, mid, dtype=np.int64))
            c_bal.append(rng.integers(int(np.ceil(s.lb)), int(np.floor(s.ub)) + 1, size=s.size, dtype=np.int64))
        else:
            c_low.append(np.full(s.size, 0.5 * (s.lb + s.ub), dtype=np.float64))
            c_bal.append(rng.uniform(s.lb, s.ub, size=s.size).astype(np.float64))

    best_b = c_rand
    best_f, best_cv = ev.eval(best_b)
    best_k = _score(best_f, best_cv)
    for cand in (c_low, c_bal):
        if _over_cap():
            return best_b, best_f, best_cv
        fv, cv = ev.eval(cand)
        if _score(fv, cv) < best_k:
            best_b, best_f, best_cv, best_k = cand, fv, cv, _score(fv, cv)

    cur = copy_blocks(best_b)
    for b_idx, s in enumerate(specs):
        if _over_cap():
            break
        n = s.size
        if s.var_type == "permutation" and n >= 2:
            for pass_i in range(2):
                if pass_i == 1 and best_cv <= 1e-9:
                    break
                for val_raw in rng.permutation(cur[b_idx])[: min(n, 90)]:
                    if _over_cap():
                        break
                    val = int(val_raw)
                    pos = int(np.flatnonzero(cur[b_idx] == val)[0])
                    short = np.delete(cur[b_idx], pos)
                    cand_pos = list(range(n)) if (n <= 100 and pass_i == 1) else sorted(set(_sample_positions(n, 40, rng) + [pos]))
                    scored = []
                    for p in cand_pos:
                        if _over_cap():
                            break
                        trial_arr = np.insert(short, p, val)
                        cur[b_idx] = trial_arr
                        fv, cv = ev.eval(cur)
                        scored.append((_score(fv, cv), trial_arr, fv, cv))
                    if scored:
                        scored.sort(key=lambda x: x[0])
                        top = [it for it in scored[: max(1, rcl_k)] if it[0][0] == scored[0][0][0]]
                        best_k, cur[b_idx], best_f, best_cv = top[int(rng.integers(0, len(top)))]
                    else:
                        cur[b_idx] = np.insert(short, pos, val)

        elif s.var_type == "binary":
            for idx in rng.permutation(n)[: min(n, 160)]:
                if _over_cap():
                    break
                i, orig = int(idx), int(cur[b_idx][int(idx)])
                cur[b_idx][i] = 1 - orig
                fv, cv = ev.eval(cur)
                k = _score(fv, cv)
                if k < best_k or (rcl_k > 1 and k[0] == best_k[0] == 0 and rng.random() < 0.1):
                    best_k, best_f, best_cv = k, fv, cv
                else:
                    cur[b_idx][i] = orig

        elif s.var_type == "assignment" and s.n_categories > 1:
            k_cat = s.n_categories
            for pass_i in range(2):
                if pass_i == 1 and best_cv <= 1e-9:
                    break
                for idx in rng.permutation(n)[: min(n, 120)]:
                    if _over_cap():
                        break
                    i, orig = int(idx), int(cur[b_idx][int(idx)])
                    if k_cat <= 16:
                        cats = list(range(k_cat))
                    else:
                        active = np.unique(cur[b_idx]).tolist()
                        unused = next((c for c in range(k_cat) if c not in active), 0)
                        cats = sorted(set(active[:16] + [unused] + rng.integers(0, k_cat, size=4).tolist()))
                    scored_c = [(best_k, orig, best_f, best_cv)]
                    for c in cats:
                        if c == orig or _over_cap():
                            continue
                        cur[b_idx][i] = c
                        fv, cv = ev.eval(cur)
                        scored_c.append((_score(fv, cv), c, fv, cv))
                    scored_c.sort(key=lambda x: x[0])
                    top_c = [it for it in scored_c[: max(1, rcl_k)] if it[0][0] == scored_c[0][0][0]]
                    best_k, cur[b_idx][i], best_f, best_cv = top_c[int(rng.integers(0, len(top_c)))]

        else:
            for idx in rng.permutation(n)[: min(n, 80)]:
                if _over_cap():
                    break
                i, best_val = int(idx), cur[b_idx][int(idx)]
                for pv in np.linspace(s.lb, s.ub, 5).tolist() + [float(rng.uniform(s.lb, s.ub))]:
                    if _over_cap():
                        break
                    val = int(np.clip(np.rint(pv), np.ceil(s.lb), np.floor(s.ub))) if s.var_type == "integer" else float(np.clip(pv, s.lb, s.ub))
                    cur[b_idx][i] = val
                    fv, cv = ev.eval(cur)
                    if _score(fv, cv) < best_k:
                        best_k, best_val, best_f, best_cv = _score(fv, cv), val, fv, cv
                cur[b_idx][i] = best_val

    return cur, best_f, best_cv


def _init_single_point(ev: _BudgetEvaluator, rng: np.random.Generator, init_strategy: str = "auto") -> tuple[list[np.ndarray], np.ndarray, float]:
    if init_strategy in ("auto", "greedy", "mixed"):
        return _greedy_construct(ev, rng, rcl_k=1, budget_cap=0.16)
    ind = init_individual(ev.problem.variables, rng)
    fv, cv = ev.eval(ind)
    return ind, fv, cv


def _init_population(
    ev: _BudgetEvaluator, rng: np.random.Generator, pop_size: int, init_strategy: str = "auto", multi_obj_weights: np.ndarray | None = None
) -> tuple[list[list[np.ndarray]], list[tuple[np.ndarray, float]]]:
    specs, m_obj = ev.problem.variables, ev.problem.n_objectives
    n_greedy = min(4, max(2, pop_size // 12)) if init_strategy in ("auto", "mixed") else (min(pop_size, 10) if init_strategy == "greedy" else 0)
    pop, evals = [], []

    for g_idx in range(n_greedy):
        if ev.progress() >= 0.12:
            break
        w_vec: np.ndarray | None = None
        if m_obj > 1:
            if multi_obj_weights is not None and g_idx < len(multi_obj_weights):
                w_vec = multi_obj_weights[g_idx]
            elif g_idx < m_obj:
                w_vec = np.zeros(m_obj, dtype=float)
                w_vec[g_idx] = 1.0
            else:
                w_vec = rng.exponential(1.0, size=m_obj)
                w_vec /= w_vec.sum()
        ind, fv, cv = _greedy_construct(ev, rng, weight_vec=w_vec, rcl_k=1 if g_idx < max(1, m_obj) else 2, budget_cap=0.12)
        pop.append(ind)
        evals.append((fv, cv))

    while len(pop) < pop_size:
        ind = init_individual(specs, rng)
        pop.append(ind)
        evals.append(ev.eval(ind))
    return pop, evals


# --- 10 Orthogonal Metaheuristic Runners ---


def _run_sa(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    neighborhood: str = "auto",
    constraint_handling: ConstraintHandling = "adaptive_penalty",
    t_start: float | None = None,
    t_end: float = 1e-3,
    step_scale: float = 0.1,
    penalty_weight: float | None = None,
) -> None:
    specs = ev.problem.variables
    cur, f_vec, cur_cv = _init_single_point(ev, rng, init_strategy)
    cur_f, pw = float(f_vec[0]), ev.resolve_penalty(penalty_weight)

    if t_start is None or t_start <= 0:
        deltas = []
        for _ in range(min(15, max(3, ev.problem.total_dim))):
            cand, _ = apply_neighbor_move(cur, specs, rng, op=neighborhood, step_scale=step_scale)
            cf, ccv = ev.eval(cand)
            d = abs(energy_delta(float(cf[0]), ccv, cur_f, cur_cv, constraint_handling, pw, 0.0))
            if d > 0:
                deltas.append(d)
        t_start = float(np.median(deltas)) if deltas else 1.0
    t_start = max(t_start, t_end * 10.0)

    best_key = scalar_score(cur_f, cur_cv, constraint_handling, pw, 0.0)
    stagnation, stag_limit, reheat = 0, max(800, 25 * ev.problem.total_dim), 0.0

    while True:
        prog, pw = ev.progress(), ev.resolve_penalty(penalty_weight)
        temp = max(t_end, t_start * ((t_end / t_start) ** prog), reheat)
        reheat *= 0.996
        cand, _ = apply_neighbor_move(cur, specs, rng, op=neighborhood, step_scale=step_scale)
        cf_vec, cand_cv = ev.eval(cand)
        cand_f = float(cf_vec[0])
        delta = energy_delta(cand_f, cand_cv, cur_f, cur_cv, constraint_handling, pw, prog)
        if delta <= 0.0 or rng.random() < np.exp(-min(50.0, delta / temp)):
            cur, cur_f, cur_cv = cand, cand_f, cand_cv

        cand_key = scalar_score(cand_f, cand_cv, constraint_handling, pw, prog)
        if cand_key < best_key:
            best_key, stagnation = cand_key, 0
        else:
            stagnation += 1
            if stagnation >= stag_limit and ev.best_blocks is not None:
                cur = perturb_individual(ev.best_blocks, specs, rng, strength=3)
                bf, bcv = ev.eval(cur)
                cur_f, cur_cv, reheat, stagnation = float(bf[0]), bcv, 0.25 * t_start, 0


def _run_ts(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    neighborhood: str = "auto",
    constraint_handling: ConstraintHandling = "feasibility",
    tabu_tenure: int = 12,
    candidate_size: int = 25,
    step_scale: float = 0.1,
    penalty_weight: float | None = None,
) -> None:
    specs = ev.problem.variables
    cur, f_vec, cur_cv = _init_single_point(ev, rng, init_strategy)
    best_global_key = scalar_score(float(f_vec[0]), cur_cv, constraint_handling, ev.resolve_penalty(penalty_weight), 0.0)
    tabu: deque[tuple[object, ...]] = deque(maxlen=max(1, tabu_tenure))
    no_imp = 0

    while True:
        prog, pw = ev.progress(), ev.resolve_penalty(penalty_weight)
        best_cand, best_sig, best_key = None, None, None
        for _ in range(max(2, candidate_size)):
            cand, sig = apply_neighbor_move(cur, specs, rng, op=neighborhood, step_scale=step_scale)
            cf_vec, ccv = ev.eval(cand)
            key = scalar_score(float(cf_vec[0]), ccv, constraint_handling, pw, prog)
            if (sig not in tabu or key < best_global_key) and (best_key is None or key < best_key):
                best_cand, best_sig, best_key = cand, sig, key

        if best_cand is None or no_imp >= 90:
            cur = perturb_individual(ev.best_blocks if ev.best_blocks is not None else cur, specs, rng, strength=3)
            ev.eval(cur)
            tabu.clear()
            no_imp = 0
            continue

        cur = best_cand
        if best_sig is not None:
            tabu.append(best_sig)
        if best_key is not None and best_key < best_global_key:
            best_global_key, no_imp = best_key, 0
        else:
            no_imp += 1


def _run_ils(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    neighborhood: str = "vnd",
    constraint_handling: ConstraintHandling = "feasibility",
    kick_strength: int = 3,
    descent_patience: int = 80,
    step_scale: float = 0.1,
    penalty_weight: float | None = None,
) -> None:
    specs = ev.problem.variables
    cur, fv, cv = _init_single_point(ev, rng, init_strategy)
    cur_key = scalar_score(float(fv[0]), cv, constraint_handling, ev.resolve_penalty(penalty_weight), 0.0)
    home, home_key = copy_blocks(cur), cur_key

    while True:
        prog, pw = ev.progress(), ev.resolve_penalty(penalty_weight)
        if neighborhood in ("lbfgsb", "powell") and any(s.var_type == "continuous" for s in specs):
            cur, cf, ccv = scipy_polish_continuous(cur, specs, ev.eval, method=neighborhood, maxiter=max(10, descent_patience // 3), penalty_scale=pw)
            cur_key = scalar_score(float(cf[0]), ccv, constraint_handling, pw, prog)
        else:
            idle, limit = 0, max(15, descent_patience)
            while idle < limit:
                cand, _ = apply_neighbor_move(cur, specs, rng, op=neighborhood, step_scale=step_scale)
                cf, ccv = ev.eval(cand)
                ckey = scalar_score(float(cf[0]), ccv, constraint_handling, pw, prog)
                if ckey < cur_key:
                    cur, cur_key, idle = cand, ckey, 0
                else:
                    idle += 1
        if cur_key <= home_key:
            home, home_key = copy_blocks(cur), cur_key
        cur = perturb_individual(home, specs, rng, strength=kick_strength)
        kf, kcv = ev.eval(cur)
        cur_key = scalar_score(float(kf[0]), kcv, constraint_handling, pw, ev.progress())


def _regret_gap(keys: list[tuple[int, float]]) -> float:
    if len(keys) <= 1:
        return 0.0
    return keys[1][1] - keys[0][1] if keys[0][0] == keys[1][0] else (1e6 if keys[0][0] < keys[1][0] else 0.0)


def _select_destroy_indices(
    ev: _BudgetEvaluator,
    work: list[np.ndarray],
    b_idx: int,
    s: VarSpec,
    d: int,
    max_d: int,
    destroy_mode: str,
    constraint_handling: ConstraintHandling,
    pw: float,
    prog: float,
    rng: np.random.Generator,
) -> tuple[list[int], int | None]:
    n = s.size
    if destroy_mode == "group" and s.var_type == "assignment" and s.n_categories > 1:
        vals, counts = np.unique(work[b_idx], return_counts=True)
        inv = (1.0 / np.maximum(1.0, counts.astype(float))) ** 1.5
        evicted = int(rng.choice(vals, p=inv / inv.sum()))
        g_idxs = np.flatnonzero(work[b_idx] == evicted).tolist()
        if len(g_idxs) > max_d:
            return rng.choice(g_idxs, size=max_d, replace=False).tolist(), evicted
        others = np.flatnonzero(work[b_idx] != evicted).tolist()
        extra = min(3, max_d - len(g_idxs), len(others))
        if extra > 0:
            g_idxs.extend(rng.choice(others, size=extra, replace=False).tolist())
        return g_idxs, evicted

    if destroy_mode == "worst" and n > d:
        f0, cv0 = ev.eval(work)
        probes = rng.choice(n, size=min(n, 20), replace=False).tolist()
        ranked: list[tuple[int, tuple[int, float], int]] = []
        orig_arr = work[b_idx].copy()
        for idx in probes:
            if s.var_type == "permutation":
                work[b_idx] = np.append(np.delete(orig_arr, idx), orig_arr[idx])
            elif s.var_type == "binary":
                work[b_idx][idx] = 1 - int(orig_arr[idx])
            elif s.var_type == "assignment" and s.n_categories > 1:
                work[b_idx][idx] = (int(orig_arr[idx]) + 1) % s.n_categories
            else:
                work[b_idx][idx] = int(np.rint(0.5 * (s.lb + s.ub))) if s.var_type == "integer" else 0.5 * (s.lb + s.ub)
            fi, cvi = ev.eval(work)
            work[b_idx] = orig_arr.copy()
            changed = 0 if (abs(float(fi[0]) - float(f0[0])) > 1e-9 or abs(cvi - cv0) > 1e-9) else 1
            ranked.append((changed, scalar_score(float(fi[0]), cvi, constraint_handling, pw, prog), idx))
        ranked.sort(key=lambda t: (t[0], t[1]))
        m_r = len(ranked)
        w_r = np.arange(m_r, 0, -1, dtype=float) ** 2
        picks = rng.choice(m_r, size=min(d, m_r), replace=False, p=w_r / w_r.sum()).tolist()
        return [ranked[p][2] for p in picks], None

    if destroy_mode in ("block", "group") and n > d:
        start = int(rng.integers(0, n - d + 1))
        return list(range(start, start + d)), None
    return rng.choice(n, size=d, replace=False).tolist(), None


def _lns_destroy_and_repair(
    ev: _BudgetEvaluator,
    base: list[np.ndarray],
    specs: list[VarSpec],
    rng: np.random.Generator,
    destroy_mode: str,
    repair_op: str,
    destroy_ratio: float,
    candidate_trials: int,
    constraint_handling: ConstraintHandling,
    pw: float,
    prog: float,
) -> tuple[list[np.ndarray], tuple[int, float]]:
    work = copy_blocks(base)
    weights = np.array([max(1, s.size) for s in specs], dtype=float)
    b_idx = int(rng.choice(len(specs), p=weights / weights.sum())) if len(specs) > 1 else 0
    s, n = specs[b_idx], specs[b_idx].size
    max_d = 7 if repair_op == "regret" else 14
    target_d = max(2 if n >= 2 else 1, int(round(destroy_ratio * n)))
    d = min(n, max_d, int(rng.integers(2, max(3, min(max_d, target_d) + 1))) if n >= 2 else 1)
    idxs, evicted_cat = _select_destroy_indices(ev, work, b_idx, s, d, max_d, destroy_mode, constraint_handling, pw, prog, rng)

    if s.var_type == "permutation" and n >= 2:
        rem_vals = [int(work[b_idx][i]) for i in idxs]
        shuf = rem_vals.copy()
        rng.shuffle(shuf)
        for pos, val in zip(idxs, shuf):
            work[b_idx][pos] = val

        while rem_vals:
            pool = rem_vals if (repair_op == "regret" and len(rem_vals) > 1) else [rem_vals[-1]]
            best_reg, chosen_val, chosen_arr = -float("inf"), pool[0], work[b_idx]
            for val in pool:
                cur_pos = int(np.flatnonzero(work[b_idx] == val)[0])
                short = np.delete(work[b_idx], cur_pos)
                scored = []
                for p in _sample_positions(n, candidate_trials, rng):
                    trial = np.insert(short, p, val)
                    work[b_idx] = trial
                    fv, cv = ev.eval(work)
                    scored.append((scalar_score(float(fv[0]), cv, constraint_handling, pw, prog), float(rng.random()), trial))
                scored.sort(key=lambda x: (x[0], x[1]))
                reg = _regret_gap([x[0] for x in scored]) if len(pool) > 1 else 0.0
                if reg > best_reg or (reg == best_reg and rng.random() < 0.5):
                    best_reg, chosen_val, chosen_arr = reg, val, scored[0][2]
            work[b_idx] = chosen_arr
            rem_vals.remove(chosen_val)
        fv, cv = ev.eval(work)
        return work, scalar_score(float(fv[0]), cv, constraint_handling, pw, prog)

    if s.var_type == "binary":
        for i in idxs:
            work[b_idx][i] = 0
    elif idxs and s.var_type == "assignment" and s.n_categories > 1:
        if evicted_cat is not None:
            others = [int(c) for c in np.unique(work[b_idx]) if int(c) != evicted_cat]
            fill_cats = others if others else [c for c in range(s.n_categories) if c != evicted_cat]
            for i in idxs:
                if int(work[b_idx][i]) == evicted_cat:
                    work[b_idx][i] = int(rng.choice(fill_cats))
        else:
            work[b_idx][idxs[0]] = (int(work[b_idx][idxs[0]]) + int(rng.integers(1, s.n_categories))) % s.n_categories

    def _cands() -> list[float | int]:
        if s.var_type == "binary":
            return [0, 1]
        if s.var_type == "assignment":
            k = s.n_categories
            if k <= 16:
                return list(range(k))
            active = [int(c) for c in np.unique(work[b_idx])]
            unused = [c for c in range(k) if c not in active]
            extra_unused = (rng.choice(unused, size=min(4, len(unused)), replace=False).tolist() if unused else [])
            if evicted_cat is not None and evicted_cat not in active:
                extra_unused = [evicted_cat] + [u for u in extra_unused if u != evicted_cat][:2]
            return sorted(set(active + extra_unused))[:candidate_trials]
        if s.var_type == "integer":
            lo, hi = int(np.ceil(s.lb)), int(np.floor(s.ub))
            return list(range(lo, hi + 1)) if (hi - lo + 1) <= candidate_trials else rng.integers(lo, hi + 1, size=candidate_trials).tolist()
        return rng.uniform(s.lb, s.ub, size=max(4, candidate_trials)).tolist()

    rem_idxs = idxs.copy()
    rng.shuffle(rem_idxs)
    while rem_idxs:
        pool_i = rem_idxs if (repair_op == "regret" and len(rem_idxs) > 1) else [rem_idxs[-1]]
        best_reg, chosen_i, chosen_v = -float("inf"), pool_i[0], work[b_idx][pool_i[0]]
        for idx in pool_i:
            orig = work[b_idx][idx]
            scored_v = []
            for v in _cands():
                work[b_idx][idx] = v
                fv, cv = ev.eval(work)
                scored_v.append((scalar_score(float(fv[0]), cv, constraint_handling, pw, prog), float(rng.random()), v))
            work[b_idx][idx] = orig
            scored_v.sort(key=lambda x: (x[0], x[1]))
            reg = _regret_gap([x[0] for x in scored_v]) if len(pool_i) > 1 else 0.0
            if reg > best_reg or (reg == best_reg and rng.random() < 0.5):
                best_reg, chosen_i, chosen_v = reg, idx, scored_v[0][2]
        work[b_idx][chosen_i] = chosen_v
        rem_idxs.remove(chosen_i)

    fv, cv = ev.eval(work)
    return work, scalar_score(float(fv[0]), cv, constraint_handling, pw, prog)


_LNS_MODES = ["random", "block", "worst", "group"]


def _run_lns(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    destroy_op: str = "auto",
    repair_op: str = "greedy",
    neighborhood: str = "vnd",
    accept: str = "sa",
    destroy_ratio: float = 0.2,
    candidate_trials: int = 48,
    local_search_steps: int = 10,
    constraint_handling: ConstraintHandling = "feasibility",
    penalty_weight: float | None = None,
) -> None:
    specs = ev.problem.variables
    cur, fv, cv = _init_single_point(ev, rng, init_strategy)
    cur_key = scalar_score(float(fv[0]), cv, constraint_handling, ev.resolve_penalty(penalty_weight), 0.0)
    best_key, d_weights, stag = cur_key, np.ones(len(_LNS_MODES), dtype=float), 0
    ls_op = "vnd" if neighborhood == "auto" else neighborhood

    while True:
        prog, pw = ev.progress(), ev.resolve_penalty(penalty_weight)
        if destroy_op == "auto":
            m_idx = int(rng.choice(len(_LNS_MODES), p=d_weights / d_weights.sum()))
            d_mode = _LNS_MODES[m_idx]
        else:
            d_mode = destroy_op if destroy_op in _LNS_MODES else "random"
            m_idx = _LNS_MODES.index(d_mode)

        cand, cand_key = _lns_destroy_and_repair(
            ev, cur, specs, rng, d_mode, repair_op, destroy_ratio, candidate_trials, constraint_handling, pw, prog
        )
        for _ in range(max(0, local_search_steps)):
            nb, _ = apply_neighbor_move(cand, specs, rng, op=ls_op)
            nf, ncv = ev.eval(nb)
            nkey = scalar_score(float(nf[0]), ncv, constraint_handling, pw, prog)
            if nkey < cand_key:
                cand, cand_key = nb, nkey

        reward = 0.1
        if cand_key < best_key:
            best_key, cur, cur_key, reward, stag = cand_key, cand, cand_key, 5.0, 0
        elif cand_key <= cur_key:
            cur, cur_key, reward, stag = cand, cand_key, 2.0, stag + 1
        else:
            if accept == "sa" and cand_key[0] == cur_key[0]:
                temp = max(1e-3, (1.0 - 0.8 * prog) * max(1.0, abs(cur_key[1]) * 0.03))
                if rng.random() < np.exp(-min(50.0, (cand_key[1] - cur_key[1]) / temp)):
                    cur, cur_key, reward = cand, cand_key, 0.5
            stag += 1

        d_weights[m_idx] = 0.85 * d_weights[m_idx] + 0.15 * reward
        if stag >= 180 and ev.best_blocks is not None:
            cur = perturb_individual(ev.best_blocks, specs, rng, strength=3)
            kf, kcv = ev.eval(cur)
            cur_key, stag = scalar_score(float(kf[0]), kcv, constraint_handling, pw, prog), 0


def _select_parent_idx(keys: list[tuple[int, float]], rng: np.random.Generator, selection: str, tournament_k: int) -> int:
    n = len(keys)
    if selection == "rank":
        ranks = np.empty(n, dtype=float)
        for r, idx in enumerate(sorted(range(n), key=lambda i: keys[i])):
            ranks[idx] = n - r
        return int(rng.choice(n, p=ranks / ranks.sum()))
    picks = rng.choice(n, size=min(n, max(2, tournament_k)), replace=False).tolist()
    return min(picks, key=lambda i: keys[i])


def _run_ga(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    selection: str = "tournament",
    crossover: str = "auto",
    mutation: str = "auto",
    constraint_handling: ConstraintHandling = "feasibility",
    pop_size: int = 40,
    crossover_rate: float = 0.85,
    mutation_rate: float = 0.2,
    tournament_k: int = 3,
    elitism: int = 2,
    local_search_steps: int = 3,
    penalty_weight: float | None = None,
) -> None:
    specs, npop = ev.problem.variables, max(6, pop_size)
    has_cont = any(s.var_type == "continuous" for s in specs)
    ls_op = ("lbfgsb" if has_cont else "vnd") if mutation == "auto" else mutation
    pop, evals = _init_population(ev, rng, npop, init_strategy=init_strategy)
    if has_cont and ls_op in ("lbfgsb", "powell") and local_search_steps > 0:
        for idx_s in range(min(3, len(pop))):
            pb, pf, pcv = scipy_polish_continuous(pop[idx_s], specs, ev.eval, method=ls_op, maxiter=20, penalty_scale=ev.resolve_penalty(penalty_weight))
            pop[idx_s], evals[idx_s] = pb, (pf, pcv)
    best_gen_key, stag_gens = (2, float("inf")), 0

    while True:
        prog, pw = ev.progress(), ev.resolve_penalty(penalty_weight)
        keys = [scalar_score(float(f[0]), cv, constraint_handling, pw, prog) for f, cv in evals]
        elite_idxs = sorted(range(len(pop)), key=lambda i: keys[i])[: max(1, min(elitism, len(pop)))]
        if keys[elite_idxs[0]] < best_gen_key:
            best_gen_key, stag_gens = keys[elite_idxs[0]], 0
        else:
            stag_gens += 1

        if stag_gens >= 45:
            next_pop = [copy_blocks(pop[i]) for i in elite_idxs]
            next_evals = [evals[i] for i in elite_idxs]
            for _ in range(min(max(2, npop // 3), npop - len(next_pop))):
                kb = perturb_individual(pop[elite_idxs[0]], specs, rng, strength=3)
                if has_cont and ls_op in ("lbfgsb", "powell"):
                    kb, kf, kcv = scipy_polish_continuous(kb, specs, ev.eval, method=ls_op, maxiter=15, penalty_scale=pw)
                    next_pop.append(kb)
                    next_evals.append((kf, kcv))
                else:
                    next_pop.append(kb)
                    next_evals.append(ev.eval(kb))
            while len(next_pop) < npop:
                rb = init_individual(specs, rng)
                next_pop.append(rb)
                next_evals.append(ev.eval(rb))
            pop, evals, stag_gens = next_pop, next_evals, 0
            continue

        next_pop = [copy_blocks(pop[i]) for i in elite_idxs]
        next_evals = [evals[i] for i in elite_idxs]
        while len(next_pop) < npop:
            i1, i2 = _select_parent_idx(keys, rng, selection, tournament_k), _select_parent_idx(keys, rng, selection, tournament_k)
            c1, c2 = crossover_individuals(pop[i1], pop[i2], specs, rng, op=crossover) if rng.random() < crossover_rate else (copy_blocks(pop[i1]), copy_blocks(pop[i2]))
            for child in (c1, c2):
                if len(next_pop) >= npop:
                    break
                child = mutate_individual(child, specs, rng, op=mutation, mutation_rate=mutation_rate)
                cf, ccv = ev.eval(child)
                if local_search_steps > 0:
                    if has_cont and ls_op in ("lbfgsb", "powell") and rng.random() < 0.25:
                        child, cf, ccv = scipy_polish_continuous(
                            child, specs, ev.eval, method=ls_op, maxiter=max(8, local_search_steps * 3), penalty_scale=pw
                        )
                    else:
                        ckey = scalar_score(float(cf[0]), ccv, constraint_handling, pw, prog)
                        for _ in range(local_search_steps):
                            nb, _ = apply_neighbor_move(child, specs, rng, op=ls_op)
                            nf, ncv = ev.eval(nb)
                            nkey = scalar_score(float(nf[0]), ncv, constraint_handling, pw, prog)
                            if nkey < ckey:
                                child, cf, ccv, ckey = nb, nf, ncv, nkey
                next_pop.append(child)
                next_evals.append((cf, ccv))
        pop, evals = next_pop, next_evals


def _run_de(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    strategy: str = "current-to-best/1/bin",
    constraint_handling: ConstraintHandling = "feasibility",
    pop_size: int = 40,
    F: float = 0.7,
    CR: float = 0.9,
    penalty_weight: float | None = None,
) -> None:
    specs, npop = ev.problem.variables, max(6, pop_size)
    lb, ub = latent_bounds(specs)
    dim, span = lb.size, np.maximum(1e-9, ub - lb)
    seed_blocks, evals = _init_population(ev, rng, npop, init_strategy=init_strategy)
    pop = np.vstack([encode_latent(b, specs) for b in seed_blocks])

    while True:
        prog, pw = ev.progress(), ev.resolve_penalty(penalty_weight)
        keys = [scalar_score(float(f[0]), cv, constraint_handling, pw, prog) for f, cv in evals]
        best_idx = min(range(npop), key=lambda i: keys[i])
        if float(np.max(np.std(pop, axis=0) / span)) < 1e-5:
            for j in range(npop):
                if j != best_idx:
                    pop[j] = np.clip(pop[best_idx] + rng.normal(0.0, 0.15, size=dim) * span, lb, ub) if j % 2 == 0 else rng.uniform(lb, ub)
                    evals[j] = ev.eval(decode_latent(pop[j], specs))
            continue

        for i in range(npop):
            r1, r2, r3 = rng.choice([j for j in range(npop) if j != i], size=3, replace=False).tolist()
            if strategy == "best/1/bin":
                mutant = pop[best_idx] + F * (pop[r1] - pop[r2])
            elif strategy == "current-to-best/1/bin":
                mutant = pop[i] + F * (pop[best_idx] - pop[i]) + F * (pop[r1] - pop[r2])
            else:
                mutant = pop[r1] + F * (pop[r2] - pop[r3])
            mutant = np.clip(mutant, lb, ub)
            cross_mask = rng.random(dim) < CR
            cross_mask[int(rng.integers(0, dim))] = True
            trial = np.where(cross_mask, mutant, pop[i])
            tf, tcv = ev.eval(decode_latent(trial, specs))
            tkey = scalar_score(float(tf[0]), tcv, constraint_handling, pw, prog)
            if tkey <= keys[i]:
                pop[i], evals[i], keys[i] = trial, (tf, tcv), tkey
                if tkey < keys[best_idx]:
                    best_idx = i


def _run_pso(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    topology: str = "global",
    constraint_handling: ConstraintHandling = "feasibility",
    pop_size: int = 40,
    w: float = 0.72,
    c1: float = 1.49,
    c2: float = 1.49,
    v_max_ratio: float = 0.2,
    penalty_weight: float | None = None,
) -> None:
    specs, npop = ev.problem.variables, max(6, pop_size)
    lb, ub = latent_bounds(specs)
    span = np.maximum(1e-9, ub - lb)
    v_max = v_max_ratio * span
    seed_blocks, pbest_evals = _init_population(ev, rng, npop, init_strategy=init_strategy)
    pos = np.vstack([encode_latent(b, specs) for b in seed_blocks])
    vel = rng.uniform(-v_max, v_max, size=(npop, lb.size))
    pbest_pos = pos.copy()

    while True:
        prog, pw = ev.progress(), ev.resolve_penalty(penalty_weight)
        w_eff = w * (1.0 - 0.4 * prog)
        pbest_keys = [scalar_score(float(f[0]), cv, constraint_handling, pw, prog) for f, cv in pbest_evals]
        gbest_idx = min(range(npop), key=lambda i: pbest_keys[i])
        if float(np.max(np.std(pos, axis=0) / span)) < 1e-5:
            for j in range(npop):
                if j != gbest_idx:
                    pos[j] = rng.uniform(lb, ub) if j % 2 == 0 else np.clip(pbest_pos[gbest_idx] + rng.normal(0.0, 0.15, size=lb.size) * span, lb, ub)
                    vel[j] = rng.uniform(-v_max, v_max)
            continue

        for i in range(npop):
            leader = min([(i - 1) % npop, i, (i + 1) % npop], key=lambda j: pbest_keys[j]) if topology == "ring" else gbest_idx
            vel[i] = np.clip(w_eff * vel[i] + c1 * rng.random(lb.size) * (pbest_pos[i] - pos[i]) + c2 * rng.random(lb.size) * (pbest_pos[leader] - pos[i]), -v_max, v_max)
            pos[i] = np.clip(pos[i] + vel[i], lb, ub)
            f_vec, cv = ev.eval(decode_latent(pos[i], specs))
            key = scalar_score(float(f_vec[0]), cv, constraint_handling, pw, prog)
            if key <= pbest_keys[i]:
                pbest_pos[i], pbest_evals[i], pbest_keys[i] = pos[i].copy(), (f_vec, cv), key
                if key < pbest_keys[gbest_idx]:
                    gbest_idx = i


def _run_aco(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    pheromone_update: str = "mmas",
    neighborhood: str = "vnd",
    constraint_handling: ConstraintHandling = "feasibility",
    n_ants: int = 25,
    evaporation: float = 0.15,
    alpha: float = 1.0,
    local_search_steps: int = 3,
    n_bins: int = 20,
    penalty_weight: float | None = None,
) -> None:
    specs = ev.problem.variables
    tau_min, tau_max = 0.05, 5.0
    pheromones = [
        np.full((s.size + 1, s.size), 1.0) if s.var_type == "permutation"
        else np.full((s.size, 2 if s.var_type == "binary" else (s.n_categories if s.var_type == "assignment" else max(2, min(n_bins, int(np.floor(s.ub) - np.ceil(s.lb) + 1)) if s.var_type == "integer" else n_bins))), 1.0)
        for s in specs
    ]

    def _to_bins(blocks: list[np.ndarray]) -> list[np.ndarray]:
        return [
            arr.astype(np.int64) if s.var_type in ("permutation", "binary", "assignment")
            else np.clip(np.floor((arr.astype(float) - s.lb) / max(1e-12, s.ub - s.lb) * tau.shape[1]).astype(np.int64), 0, tau.shape[1] - 1)
            for arr, s, tau in zip(blocks, specs, pheromones)
        ]

    def _deposit(chosen_bins: list[np.ndarray], amount: float = 1.0) -> None:
        for s, tau, chosen in zip(specs, pheromones, chosen_bins):
            if s.var_type == "permutation":
                prev = s.size
                for nxt in chosen:
                    tau[prev, int(nxt)] += amount
                    prev = int(nxt)
            else:
                tau[np.arange(s.size), chosen] += amount
            np.clip(tau, tau_min if pheromone_update == "mmas" else 1e-4, tau_max if pheromone_update == "mmas" else 1e3, out=tau)

    global_best_bins, global_best_key = None, (2, float("inf"))
    if init_strategy in ("auto", "greedy", "mixed"):
        seed_b, sf, scv = _greedy_construct(ev, rng, rcl_k=1, budget_cap=0.14)
        global_best_key = scalar_score(float(sf[0]), scv, constraint_handling, ev.resolve_penalty(penalty_weight), 0.0)
        global_best_bins = _to_bins(seed_b)
        _deposit(global_best_bins, amount=2.5)

    ls_op = "vnd" if neighborhood == "auto" else neighborhood
    while True:
        prog, pw = ev.progress(), ev.resolve_penalty(penalty_weight)
        iter_best_bins, iter_best_key = None, (2, float("inf"))
        for _ in range(max(4, n_ants)):
            ant_blocks, ant_bins = [], []
            for s, tau in zip(specs, pheromones):
                if s.var_type == "permutation":
                    avail, perm, prev = np.ones(s.size, dtype=bool), np.empty(s.size, dtype=np.int64), s.size
                    for step in range(s.size):
                        choices = np.flatnonzero(avail)
                        w_vec = tau[prev, choices] ** alpha
                        nxt = int(rng.choice(choices, p=w_vec / w_vec.sum()))
                        perm[step], avail[nxt], prev = nxt, False, nxt
                    ant_blocks.append(perm)
                    ant_bins.append(perm)
                else:
                    w_mat = tau ** alpha
                    cum = np.cumsum(w_mat / w_mat.sum(axis=1, keepdims=True), axis=1)
                    picked = np.clip((rng.random((s.size, 1)) >= cum).sum(axis=1).astype(np.int64), 0, tau.shape[1] - 1)
                    if s.var_type in ("binary", "assignment"):
                        ant_blocks.append(picked)
                    else:
                        edges = np.linspace(s.lb, s.ub, tau.shape[1] + 1)
                        vals = rng.uniform(edges[picked], edges[picked + 1])
                        ant_blocks.append(np.clip(np.rint(vals), np.ceil(s.lb), np.floor(s.ub)).astype(np.int64) if s.var_type == "integer" else vals)
                    ant_bins.append(picked)

            af, acv = ev.eval(ant_blocks)
            akey = scalar_score(float(af[0]), acv, constraint_handling, pw, prog)
            for _ in range(max(0, local_search_steps)):
                nb, _ = apply_neighbor_move(ant_blocks, specs, rng, op=ls_op)
                nf, ncv = ev.eval(nb)
                nkey = scalar_score(float(nf[0]), ncv, constraint_handling, pw, prog)
                if nkey < akey:
                    ant_blocks, akey, ant_bins = nb, nkey, _to_bins(nb)
            if akey < iter_best_key:
                iter_best_key, iter_best_bins = akey, ant_bins
            if akey < global_best_key:
                global_best_key, global_best_bins = akey, ant_bins

        src = global_best_bins if (pheromone_update == "elitist" and global_best_bins is not None) else iter_best_bins
        if src is not None:
            for tau in pheromones:
                tau *= 1.0 - evaporation
            _deposit(src, amount=1.0)


def _constrained_dominates(f_a: np.ndarray, cv_a: float, f_b: np.ndarray, cv_b: float) -> bool:
    feas_a, feas_b = cv_a <= 1e-9, cv_b <= 1e-9
    if feas_a != feas_b:
        return feas_a
    return cv_a < cv_b if not feas_a else bool(np.all(f_a <= f_b) and np.any(f_a < f_b))


def _run_pareto_ea(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    survival: object,
    mu: int,
    *,
    init_strategy: str,
    crossover: str,
    mutation: str,
    crossover_rate: float,
    mutation_rate: float,
    local_search_steps: int,
    seed_weights: np.ndarray | None = None,
) -> None:
    from pymoo.core.population import Population
    from pymoo.core.problem import Problem as PymooProblem

    specs, m_obj = ev.problem.variables, ev.problem.n_objectives
    pymoo_prob = PymooProblem(n_var=1, n_obj=m_obj, n_ieq_constr=1)
    pop, evals = _init_population(ev, rng, mu, init_strategy=init_strategy, multi_obj_weights=seed_weights)
    F = np.array([e[0] for e in evals], dtype=float)
    CV = np.array([e[1] for e in evals], dtype=float)
    ls_op = "vnd" if mutation == "auto" else mutation

    while True:
        offspring, off_F, off_CV = [], [], []
        while len(offspring) < mu:
            p1, p2 = rng.choice(len(pop), size=2, replace=False).tolist()
            c1, c2 = crossover_individuals(pop[p1], pop[p2], specs, rng, op=crossover) if rng.random() < crossover_rate else (copy_blocks(pop[p1]), copy_blocks(pop[p2]))
            for child in (c1, c2):
                if len(offspring) >= mu:
                    break
                child = mutate_individual(child, specs, rng, op=mutation, mutation_rate=mutation_rate)
                cf, ccv = ev.eval(child)
                for _ in range(max(0, local_search_steps)):
                    nb, _ = apply_neighbor_move(child, specs, rng, op=ls_op)
                    nf, ncv = ev.eval(nb)
                    if _constrained_dominates(nf, ncv, cf, ccv):
                        child, cf, ccv = nb, nf, ncv
                offspring.append(child)
                off_F.append(cf)
                off_CV.append(ccv)

        comb_pop = pop + offspring
        comb_F = np.vstack([F, np.array(off_F, dtype=float)])
        comb_CV = np.concatenate([CV, np.array(off_CV, dtype=float)])
        pop_obj = Population.new("X", np.arange(len(comb_pop))[:, None], "F", comb_F, "G", (comb_CV - 1e-9)[:, None])
        kept = survival.do(pymoo_prob, pop_obj, n_survive=mu).get("X").ravel().astype(int).tolist()  # type: ignore[attr-defined]
        pop, F, CV = [comb_pop[i] for i in kept], comb_F[kept], comb_CV[kept]


def _run_nsga2(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    crossover: str = "auto",
    mutation: str = "auto",
    pop_size: int = 50,
    crossover_rate: float = 0.9,
    mutation_rate: float = 0.2,
    local_search_steps: int = 0,
) -> None:
    from pymoo.operators.survival.rank_and_crowding import RankAndCrowding

    mu = max(6, pop_size - (pop_size % 2))
    _run_pareto_ea(
        ev, rng, RankAndCrowding(), mu,
        init_strategy=init_strategy, crossover=crossover, mutation=mutation,
        crossover_rate=crossover_rate, mutation_rate=mutation_rate, local_search_steps=local_search_steps,
    )


def _run_nsga3(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    crossover: str = "auto",
    mutation: str = "auto",
    pop_size: int = 60,
    crossover_rate: float = 0.9,
    mutation_rate: float = 0.2,
    local_search_steps: int = 0,
) -> None:
    from pymoo.algorithms.moo.nsga3 import ReferenceDirectionSurvival
    from pymoo.util.ref_dirs import get_reference_directions

    mu = max(12, pop_size - (pop_size % 2))
    ref_dirs = get_reference_directions("energy", ev.problem.n_objectives, mu, seed=int(rng.integers(1, 2**31 - 1)))
    _run_pareto_ea(
        ev, rng, ReferenceDirectionSurvival(ref_dirs), mu,
        init_strategy=init_strategy, crossover=crossover, mutation=mutation,
        crossover_rate=crossover_rate, mutation_rate=mutation_rate, local_search_steps=local_search_steps,
        seed_weights=ref_dirs[: min(6, len(ref_dirs))],
    )


def _run_moead(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    aggregation: str = "tchebycheff",
    crossover: str = "auto",
    mutation: str = "auto",
    pop_size: int = 50,
    neighbor_size: int = 10,
    crossover_rate: float = 0.9,
    mutation_rate: float = 0.2,
    local_search_steps: int = 2,
) -> None:
    specs, m_obj, npop = ev.problem.variables, ev.problem.n_objectives, max(8, pop_size)
    if m_obj == 2:
        t = np.linspace(0.0, 1.0, npop)
        W = np.column_stack([t, 1.0 - t])
    else:
        W = np.zeros((npop, m_obj), dtype=float)
        for j in range(min(m_obj, npop)):
            W[j, j] = 1.0
        if npop > m_obj:
            raw = rng.exponential(1.0, size=(npop - m_obj, m_obj))
            W[m_obj:] = raw / raw.sum(axis=1, keepdims=True)
    W = np.maximum(1e-4, W)
    W /= W.sum(axis=1, keepdims=True)
    B = np.argsort(np.linalg.norm(W[:, None, :] - W[None, :, :], axis=-1), axis=1)[:, : min(npop, max(3, neighbor_size))]

    pop, evals = _init_population(ev, rng, npop, init_strategy=init_strategy, multi_obj_weights=W[np.linspace(0, npop - 1, min(6, npop), dtype=int)])
    F = np.array([e[0] for e in evals], dtype=float)
    CV = np.array([e[1] for e in evals], dtype=float)
    feas_mask = CV <= 1e-9
    z_ideal = F[feas_mask].min(axis=0) if feas_mask.any() else F.min(axis=0)
    z_nadir = F[feas_mask].max(axis=0) if feas_mask.any() else F.max(axis=0)
    ls_op = "vnd" if mutation == "auto" else mutation

    def _sub_key(fv: np.ndarray, cv: float, w: np.ndarray) -> tuple[int, float]:
        if cv > 1e-9:
            return (1, cv)
        norm_f = (fv - z_ideal) / np.maximum(1.0, z_nadir - z_ideal)
        return (0, float(np.dot(w, norm_f)) if aggregation == "weighted_sum" else float(np.max(w * np.abs(norm_f)) + 1e-3 * np.dot(w, norm_f)))

    while True:
        if ev.archive_f:
            arch_arr = np.array(ev.archive_f, dtype=float)
            z_ideal, z_nadir = np.minimum(z_ideal, arch_arr.min(axis=0)), arch_arr.max(axis=0)
        elif (CV <= 1e-9).any():
            z_nadir = F[CV <= 1e-9].max(axis=0)

        for idx in rng.permutation(npop).tolist():
            pool = B[idx] if rng.random() < 0.85 else np.arange(npop)
            p1, p2 = rng.choice(pool, size=2, replace=False).tolist()
            c1 = crossover_individuals(pop[p1], pop[p2], specs, rng, op=crossover)[0] if rng.random() < crossover_rate else copy_blocks(pop[p1])
            child = mutate_individual(c1, specs, rng, op=mutation, mutation_rate=mutation_rate)
            cf, ccv = ev.eval(child)
            if ccv <= 1e-9:
                z_ideal = np.minimum(z_ideal, cf)
            if local_search_steps > 0:
                if ls_op in ("lbfgsb", "powell") and any(s.var_type == "continuous" for s in specs) and rng.random() < 0.25:
                    child, cf, ccv = scipy_polish_continuous(
                        child, specs, ev.eval, method=ls_op, maxiter=max(6, local_search_steps * 2), penalty_scale=ev.resolve_penalty(None), weight_vec=W[idx]
                    )
                    if ccv <= 1e-9:
                        z_ideal = np.minimum(z_ideal, cf)
                else:
                    ck = _sub_key(cf, ccv, W[idx])
                    for _ in range(local_search_steps):
                        nb, _ = apply_neighbor_move(child, specs, rng, op=ls_op)
                        nf, ncv = ev.eval(nb)
                        if ncv <= 1e-9:
                            z_ideal = np.minimum(z_ideal, nf)
                        nk = _sub_key(nf, ncv, W[idx])
                        if nk < ck:
                            child, cf, ccv, ck = nb, nf, ncv, nk
            replaced = 0
            for j in rng.permutation(pool).tolist():
                if _sub_key(cf, ccv, W[j]) <= _sub_key(F[j], float(CV[j]), W[j]):
                    pop[j], F[j], CV[j], replaced = copy_blocks(child), cf, ccv, replaced + 1
                    if replaced >= 2:
                        break


def _run_cmaes(
    ev: _BudgetEvaluator,
    rng: np.random.Generator,
    *,
    init_strategy: str = "auto",
    local_polish: str = "lbfgsb",
    constraint_handling: ConstraintHandling = "adaptive_penalty",
    pop_size: int = 0,
    sigma0: float = 0.25,
    penalty_weight: float | None = None,
) -> None:
    specs = ev.problem.variables
    lb, ub = latent_bounds(specs)
    dim, span = lb.size, np.maximum(1e-9, ub - lb)
    cur, _, _ = _init_single_point(ev, rng, init_strategy)
    if dim < 2:
        while True:
            scipy_polish_continuous(cur, specs, ev.eval, method="powell" if local_polish == "powell" else "lbfgsb", maxiter=25, penalty_scale=ev.resolve_penalty(penalty_weight))
            cur = init_individual(specs, rng)

    import cma

    u0 = np.clip((encode_latent(cur, specs) - lb) / span, 0.0, 1.0)
    lam = max(6, int(pop_size)) if pop_size > 0 else max(6, 4 + int(3 * np.log(dim)))
    sig = float(np.clip(sigma0, 0.02, 0.5))

    while True:
        es = cma.CMAEvolutionStrategy(
            u0.tolist(),
            sig,
            {"bounds": [0.0, 1.0], "popsize": lam, "seed": int(rng.integers(1, 2**31 - 1)), "verbose": -9},
        )
        while not es.stop():
            prog, pw = ev.progress(), ev.resolve_penalty(penalty_weight)
            ask_u = es.ask()
            keys = []
            for u in ask_u:
                fv, cv = ev.eval(decode_latent(lb + np.clip(np.asarray(u, dtype=float), 0.0, 1.0) * span, specs))
                keys.append(scalar_score(float(fv[0]), cv, constraint_handling, pw, prog))
            ranks = np.empty(len(keys), dtype=float)
            for r, i in enumerate(sorted(range(len(keys)), key=lambda idx: keys[idx])):
                ranks[i] = float(r)
            es.tell(ask_u, ranks.tolist())

        if local_polish in ("lbfgsb", "powell") and ev.best_blocks is not None and any(s.var_type == "continuous" for s in specs):
            scipy_polish_continuous(ev.best_blocks, specs, ev.eval, method=local_polish, maxiter=30, penalty_scale=ev.resolve_penalty(penalty_weight))
        u0 = rng.uniform(0.1, 0.9, size=dim)
        lam = min(128, int(round(lam * 1.5)))


_MULTI_ALGS = ("NSGA-II", "MOEA/D", "NSGA-III")
_RUNNERS = {
    "SA": _run_sa,
    "TS": _run_ts,
    "ILS": _run_ils,
    "LNS": _run_lns,
    "GA": _run_ga,
    "CMA-ES": _run_cmaes,
    "DE": _run_de,
    "PSO": _run_pso,
    "ACO": _run_aco,
    "NSGA-II": _run_nsga2,
    "MOEA/D": _run_moead,
    "NSGA-III": _run_nsga3,
}


def _auto_pick_algorithm(problem: Problem) -> str:
    if problem.is_multi_objective:
        return "NSGA-III" if problem.n_objectives >= 3 else "MOEA/D"
    vtypes = {s.var_type for s in problem.variables}
    return "CMA-ES" if vtypes <= {"continuous"} else ("LNS" if vtypes == {"permutation"} else "GA")


def solve(
    problem: Problem,
    algorithm: str = "auto",
    *,
    time_limit: float | None = 60.0,
    max_evals: int | None = None,
    seed: int = 42,
    **config: object,
) -> SolveResult:
    """Run one configured algorithm from the pool on `problem` under the given budget."""
    is_auto = algorithm.strip().upper() == "AUTO"
    alg = _auto_pick_algorithm(problem) if is_auto else canonical_algorithm(algorithm)
    if alg not in _RUNNERS:
        raise ValueError(f"Unknown algorithm '{algorithm}'. Available: {list(_RUNNERS)}")
    if time_limit is None and max_evals is None:
        raise ValueError("Provide at least one stopping budget (`time_limit` or `max_evals`).")
    if problem.is_multi_objective and alg not in _MULTI_ALGS:
        raise ValueError(f"Single-objective algorithm '{alg}' cannot solve a multi-objective Problem (n_objectives={problem.n_objectives}).")
    if not problem.is_multi_objective and alg in _MULTI_ALGS:
        raise ValueError(f"Multi-objective algorithm '{alg}' cannot solve a single-objective Problem.")

    runner = _RUNNERS[alg]
    accepted = set(inspect.signature(runner).parameters) - {"ev", "rng"}
    clean_cfg = {k: v for k, v in config.items() if k in accepted and v is not None}

    ev = _BudgetEvaluator(problem, time_limit=time_limit, max_evals=max_evals)
    rng = np.random.default_rng(seed)
    try:
        runner(ev, rng, **clean_cfg)  # type: ignore[arg-type]
    except _BudgetStop:
        pass

    elapsed = time.perf_counter() - ev.t0
    best_sol = problem.format_solution(ev.best_blocks) if ev.best_blocks is not None else None
    best_obj = problem.restore_objectives(ev.best_f) if ev.best_f is not None else None

    pareto_sols: list[np.ndarray | dict[str, np.ndarray]] = []
    pareto_objs: np.ndarray | None = None
    if problem.is_multi_objective and ev.archive_blocks:
        internal_arch = np.array(ev.archive_f, dtype=float)
        f_lo = internal_arch.min(axis=0)
        knee_idx = int(np.argmin(np.linalg.norm((internal_arch - f_lo) / np.maximum(1e-9, internal_arch.max(axis=0) - f_lo), axis=1)))
        best_sol = problem.format_solution(ev.archive_blocks[knee_idx])
        best_obj = problem.restore_objectives(internal_arch[knee_idx])
        pareto_sols = [problem.format_solution(b) for b in ev.archive_blocks]
        pareto_objs = np.array([problem.restore_objectives(f) for f in ev.archive_f], dtype=float)
        if pareto_objs.ndim == 2 and len(pareto_objs) > 1:
            order = np.argsort(pareto_objs[:, 0])
            pareto_objs, pareto_sols = pareto_objs[order], [pareto_sols[int(i)] for i in order]

    return SolveResult(
        algorithm=alg,
        best_solution=best_sol,
        best_objective=best_obj,
        best_violation=ev.best_cv,
        feasible=ev.best_cv <= 1e-9,
        n_evals=ev.n_evals,
        elapsed_sec=elapsed,
        pareto_solutions=pareto_sols,
        pareto_objectives=pareto_objs,
        config=clean_cfg,
        first_feasible_eval=ev.first_feasible_eval,
        strict_improvements=ev.strict_improvements,
        last_improve_eval=ev.last_improve_eval,
    )
