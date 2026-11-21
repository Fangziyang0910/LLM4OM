"""Domain-agnostic operators bound strictly to the 5 canonical VarTypes (NumPy + SciPy continuous polish)."""

from __future__ import annotations

from typing import Callable

import numpy as np

from .problem import VarSpec
from .specs import OPERATOR_SPECS


def init_individual(specs: list[VarSpec], rng: np.random.Generator) -> list[np.ndarray]:
    """Sample one uniform random individual across all variable blocks."""
    blocks: list[np.ndarray] = []
    for s in specs:
        if s.var_type == "binary":
            blocks.append(rng.integers(0, 2, size=s.size, dtype=np.int64))
        elif s.var_type == "assignment":
            blocks.append(rng.integers(0, s.n_categories, size=s.size, dtype=np.int64))
        elif s.var_type == "permutation":
            blocks.append(rng.permutation(s.size).astype(np.int64))
        elif s.var_type == "integer":
            blocks.append(rng.integers(int(np.ceil(s.lb)), int(np.floor(s.ub)) + 1, size=s.size, dtype=np.int64))
        else:
            blocks.append(rng.uniform(s.lb, s.ub, size=s.size).astype(np.float64))
    return blocks


def copy_blocks(blocks: list[np.ndarray]) -> list[np.ndarray]:
    return [b.copy() for b in blocks]


def apply_neighbor_move(
    blocks: list[np.ndarray],
    specs: list[VarSpec],
    rng: np.random.Generator,
    op: str = "auto",
    step_scale: float = 0.1,
) -> tuple[list[np.ndarray], tuple[object, ...]]:
    """Apply one local neighborhood step to a size-weighted variable block."""
    out = copy_blocks(blocks)
    if len(specs) > 1:
        weights = np.array([max(1, s.size) for s in specs], dtype=float)
        b_idx = int(rng.choice(len(specs), p=weights / weights.sum()))
    else:
        b_idx = 0
    s = specs[b_idx]
    arr = out[b_idx]
    n = s.size

    if s.var_type == "permutation":
        if n < 2:
            return out, (b_idx, "noop")
        if op in ("2opt", "insert", "swap", "or_opt"):
            mode = op
        else:
            r = rng.random()
            mode = "insert" if r < 0.35 else ("swap" if r < 0.60 else ("or_opt" if (r < 0.80 and n >= 4) else "2opt"))

        if mode == "swap":
            i, j = rng.choice(n, size=2, replace=False).tolist()
            u, v = int(arr[i]), int(arr[j])
            arr[i], arr[j] = arr[j], arr[i]
            return out, (b_idx, "swap", min(u, v), max(u, v))
        if mode == "insert":
            src = int(rng.integers(0, n))
            dst = int(rng.integers(0, n - 1))
            if dst >= src:
                dst += 1
            val = int(arr[src])
            out[b_idx] = np.insert(np.delete(arr, src), dst, val)
            return out, (b_idx, "insert", val, dst)
        if mode == "or_opt" and n >= 4:
            seg_len = min(int(rng.integers(2, 4)), n - 1)
            src = int(rng.integers(0, n - seg_len + 1))
            seg = arr[src : src + seg_len].copy()
            rem = np.delete(arr, slice(src, src + seg_len))
            dst = int(rng.integers(0, rem.size + 1))
            if dst == src and rem.size > 0:
                dst = (dst + 1) % (rem.size + 1)
            out[b_idx] = np.insert(rem, dst, seg)
            return out, (b_idx, "or_opt", int(seg[0]), seg_len, dst)
        i, j = sorted(rng.choice(n, size=2, replace=False).tolist())
        u, v = int(arr[i]), int(arr[j])
        arr[i : j + 1] = arr[i : j + 1][::-1]
        return out, (b_idx, "2opt", min(u, v), max(u, v))

    if s.var_type == "binary":
        if op == "swap_01" or (op in ("auto", "vnd") and rng.random() < 0.30):
            ones, zeros = np.flatnonzero(arr == 1), np.flatnonzero(arr == 0)
            if ones.size > 0 and zeros.size > 0:
                i1, i0 = int(rng.choice(ones)), int(rng.choice(zeros))
                arr[i1], arr[i0] = 0, 1
                return out, (b_idx, "swap_01", i1, i0)
        idx = int(rng.integers(0, n))
        old_v = int(arr[idx])
        arr[idx] = 1 - old_v
        return out, (b_idx, "bitflip", idx, old_v)

    if s.var_type == "assignment":
        if (op == "swap" or (op in ("auto", "vnd") and rng.random() < 0.30)) and n >= 2:
            i, j = rng.choice(n, size=2, replace=False).tolist()
            if arr[i] != arr[j]:
                arr[i], arr[j] = arr[j], arr[i]
                return out, (b_idx, "asgn_swap", min(int(i), int(j)), max(int(i), int(j)))
        idx = int(rng.integers(0, n))
        old_c = int(arr[idx])
        if s.n_categories > 1:
            if s.n_categories > 8 and rng.random() < 0.5:
                choices = np.unique(arr)
                choices = choices[choices != old_c]
                if choices.size > 0:
                    arr[idx] = int(rng.choice(choices))
                    return out, (b_idx, "reassign", idx, old_c)
            arr[idx] = (old_c + int(rng.integers(1, s.n_categories))) % s.n_categories
        return out, (b_idx, "reassign", idx, old_c)

    if s.var_type == "integer":
        idx = int(rng.integers(0, n))
        old_v = int(arr[idx])
        span = max(1, int(round((s.ub - s.lb) * step_scale)))
        delta = int(rng.integers(-span, span + 1)) or (1 if rng.random() < 0.5 else -1)
        arr[idx] = int(np.clip(old_v + delta, np.ceil(s.lb), np.floor(s.ub)))
        return out, (b_idx, "int_step", idx, old_v)

    idx = int(rng.integers(0, n))
    if op == "cauchy":
        scale = max(1e-12, (s.ub - s.lb) * step_scale * 0.5)
        arr[idx] = float(np.clip(arr[idx] + scale * rng.standard_cauchy(), s.lb, s.ub))
    else:
        sigma = max(1e-12, (s.ub - s.lb) * step_scale)
        arr[idx] = float(np.clip(arr[idx] + rng.normal(0.0, sigma), s.lb, s.ub))
    return out, (b_idx, "cont_step", idx)


def perturb_individual(blocks: list[np.ndarray], specs: list[VarSpec], rng: np.random.Generator, strength: int = 3) -> list[np.ndarray]:
    """Macro-perturbation (4-opt double-bridge + multi-step kick) to escape deep local optima."""
    out = copy_blocks(blocks)
    k_steps = max(2, int(strength))
    for idx, s in enumerate(specs):
        if s.var_type == "permutation" and s.size >= 8 and rng.random() < 0.5:
            p1, p2, p3 = sorted(rng.choice(range(1, s.size), size=3, replace=False).tolist())
            arr = out[idx]
            out[idx] = np.concatenate([arr[:p1], arr[p3:], arr[p2:p3], arr[p1:p2]])
            k_steps = max(1, k_steps - 2)
    for _ in range(k_steps):
        out, _ = apply_neighbor_move(out, specs, rng, op="vnd", step_scale=0.25)
    return out


def _ox_crossover(p1: np.ndarray, p2: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    n = p1.size
    if n < 2:
        return p1.copy(), p2.copy()
    a, b = sorted(rng.choice(n, size=2, replace=False).tolist())

    def _build(a_par: np.ndarray, b_par: np.ndarray) -> np.ndarray:
        child = np.full(n, -1, dtype=np.int64)
        child[a : b + 1] = a_par[a : b + 1]
        used = set(a_par[a : b + 1].tolist())
        pos = (b + 1) % n
        for val in (int(x) for x in np.roll(b_par, -(b + 1)) if int(x) not in used):
            child[pos] = val
            pos = (pos + 1) % n
        return child

    return _build(p1, p2), _build(p2, p1)


def _pmx_crossover(p1: np.ndarray, p2: np.ndarray, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    n = p1.size
    if n < 2:
        return p1.copy(), p2.copy()
    a, b = sorted(rng.choice(n, size=2, replace=False).tolist())

    def _build(a_par: np.ndarray, b_par: np.ndarray) -> np.ndarray:
        child = np.full(n, -1, dtype=np.int64)
        child[a : b + 1] = a_par[a : b + 1]
        val_to_idx_b = {int(v): idx for idx, v in enumerate(b_par)}
        in_seg = set(a_par[a : b + 1].tolist())
        for i in range(a, b + 1):
            v = int(b_par[i])
            if v not in in_seg:
                pos = i
                while a <= pos <= b:
                    pos = val_to_idx_b[int(a_par[pos])]
                child[pos] = v
        mask = child == -1
        child[mask] = b_par[mask]
        return child

    return _build(p1, p2), _build(p2, p1)


def crossover_individuals(
    p1: list[np.ndarray], p2: list[np.ndarray], specs: list[VarSpec], rng: np.random.Generator, op: str = "auto"
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    """Recombine two parents block-by-block using variable-type-matched crossover."""
    c1_blocks, c2_blocks = [], []
    for b1, b2, s in zip(p1, p2, specs):
        if s.var_type == "permutation":
            c1, c2 = _pmx_crossover(b1, b2, rng) if op == "pmx" else _ox_crossover(b1, b2, rng)
        elif s.var_type in ("binary", "assignment"):
            if op == "two_point" and s.size >= 3:
                i, j = sorted(rng.choice(s.size, size=2, replace=False).tolist())
                c1, c2 = b1.copy(), b2.copy()
                c1[i:j], c2[i:j] = b2[i:j].copy(), b1[i:j].copy()
            else:
                mask = rng.random(s.size) < 0.5
                c1, c2 = np.where(mask, b1, b2), np.where(mask, b2, b1)
        else:
            p1f, p2f = b1.astype(float), b2.astype(float)
            if op == "blend":
                lo = np.minimum(p1f, p2f) - 0.5 * np.abs(p2f - p1f)
                hi = np.maximum(p1f, p2f) + 0.5 * np.abs(p2f - p1f)
                c1, c2 = np.clip(rng.uniform(lo, hi), s.lb, s.ub), np.clip(rng.uniform(lo, hi), s.lb, s.ub)
            else:
                u = rng.random(s.size)
                beta = np.where(u <= 0.5, (2.0 * u) ** (1.0 / 16.0), (1.0 / (2.0 * (1.0 - u))) ** (1.0 / 16.0))
                c1 = np.clip(0.5 * ((1.0 + beta) * p1f + (1.0 - beta) * p2f), s.lb, s.ub)
                c2 = np.clip(0.5 * ((1.0 - beta) * p1f + (1.0 + beta) * p2f), s.lb, s.ub)
            if s.var_type == "integer":
                c1 = np.clip(np.rint(c1), np.ceil(s.lb), np.floor(s.ub)).astype(np.int64)
                c2 = np.clip(np.rint(c2), np.ceil(s.lb), np.floor(s.ub)).astype(np.int64)
        c1_blocks.append(c1)
        c2_blocks.append(c2)
    return c1_blocks, c2_blocks


def mutate_individual(
    blocks: list[np.ndarray], specs: list[VarSpec], rng: np.random.Generator, op: str = "auto", mutation_rate: float = 0.15
) -> list[np.ndarray]:
    """Mutate an individual block-by-block according to `op` and `mutation_rate`."""
    out = copy_blocks(blocks)
    for idx, s in enumerate(specs):
        arr, n = out[idx], s.size
        if s.var_type == "permutation":
            if rng.random() < max(mutation_rate, 0.25):
                out[idx] = apply_neighbor_move([arr], [s], rng, op=op)[0][0]
        elif s.var_type == "binary":
            if op == "swap_01" or (op in ("auto", "vnd", "lbfgsb", "powell") and rng.random() < 0.35):
                if rng.random() < max(mutation_rate, 0.25):
                    out[idx] = apply_neighbor_move([arr], [s], rng, op="swap_01")[0][0]
            else:
                flips = rng.random(n) < min(0.5, max(1.0 / n, mutation_rate * 0.25))
                if not flips.any() and rng.random() < mutation_rate:
                    flips[int(rng.integers(0, n))] = True
                arr[flips] = 1 - arr[flips]
        elif s.var_type == "assignment":
            if (op == "swap" or (op in ("auto", "vnd", "lbfgsb", "powell") and rng.random() < 0.35)) and n >= 2 and rng.random() < max(mutation_rate, 0.25):
                out[idx] = apply_neighbor_move([arr], [s], rng, op="swap")[0][0]
            elif s.n_categories > 1:
                mask = rng.random(n) < min(0.5, max(1.0 / n, mutation_rate * 0.25))
                if not mask.any() and rng.random() < mutation_rate:
                    mask[int(rng.integers(0, n))] = True
                arr[mask] = rng.integers(0, s.n_categories, size=int(mask.sum()), dtype=np.int64)
        else:
            mask = rng.random(n) < min(1.0, max(1.0 / n, mutation_rate))
            if not mask.any():
                mask[int(rng.integers(0, n))] = True
            k = int(mask.sum())
            if op == "polynomial":
                u = rng.random(k)
                delta = np.where(u < 0.5, (2.0 * u) ** (1.0 / 21.0) - 1.0, 1.0 - (2.0 * (1.0 - u)) ** (1.0 / 21.0))
                vals = arr[mask].astype(float) + delta * (s.ub - s.lb)
            else:
                vals = arr[mask].astype(float) + rng.normal(0.0, 0.1 * (s.ub - s.lb), size=k)
            vals = np.clip(vals, s.lb, s.ub)
            arr[mask] = np.clip(np.rint(vals), np.ceil(s.lb), np.floor(s.ub)).astype(np.int64) if s.var_type == "integer" else vals
    return out


def latent_bounds(specs: list[VarSpec]) -> tuple[np.ndarray, np.ndarray]:
    lbs, ubs = [], []
    for s in specs:
        if s.var_type in ("continuous", "integer"):
            lbs.append(np.full(s.size, s.lb, dtype=float))
            ubs.append(np.full(s.size, s.ub, dtype=float))
        elif s.var_type == "assignment":
            lbs.append(np.zeros(s.size, dtype=float))
            ubs.append(np.full(s.size, float(s.n_categories) - 1e-7, dtype=float))
        else:
            lbs.append(np.zeros(s.size, dtype=float))
            ubs.append(np.ones(s.size, dtype=float))
    return np.concatenate(lbs), np.concatenate(ubs)


def decode_latent(vec: np.ndarray, specs: list[VarSpec]) -> list[np.ndarray]:
    blocks, offset = [], 0
    for s in specs:
        seg = vec[offset : offset + s.size]
        offset += s.size
        if s.var_type == "continuous":
            blocks.append(np.clip(seg, s.lb, s.ub).astype(np.float64))
        elif s.var_type == "integer":
            blocks.append(np.clip(np.rint(seg), np.ceil(s.lb), np.floor(s.ub)).astype(np.int64))
        elif s.var_type == "binary":
            blocks.append((seg >= 0.5).astype(np.int64))
        elif s.var_type == "assignment":
            blocks.append(np.clip(np.floor(seg), 0, s.n_categories - 1).astype(np.int64))
        else:
            blocks.append(np.argsort(seg, kind="mergesort").astype(np.int64))
    return blocks


def encode_latent(blocks: list[np.ndarray], specs: list[VarSpec]) -> np.ndarray:
    segs = []
    for arr, s in zip(blocks, specs):
        if s.var_type in ("continuous", "integer"):
            segs.append(np.clip(arr.astype(float), s.lb, s.ub))
        elif s.var_type == "binary":
            segs.append(np.where(arr > 0, 0.75, 0.25))
        elif s.var_type == "assignment":
            segs.append(np.clip(arr.astype(float) + 0.5, 0.0, float(s.n_categories) - 1e-7))
        else:
            ranks = np.empty(s.size, dtype=float)
            ranks[arr.astype(int)] = np.arange(s.size, dtype=float) / max(1, s.size - 1)
            segs.append(ranks)
    return np.concatenate(segs)


def scipy_polish_continuous(
    blocks: list[np.ndarray],
    specs: list[VarSpec],
    eval_fn: Callable[[list[np.ndarray]], tuple[np.ndarray, float]],
    *,
    method: str = "lbfgsb",
    maxiter: int = 20,
    penalty_scale: float = 1e4,
    weight_vec: np.ndarray | None = None,
) -> tuple[list[np.ndarray], np.ndarray, float]:
    """Optimize all continuous variable blocks jointly via SciPy L-BFGS-B or Powell while holding discrete blocks fixed."""
    c_idxs = [i for i, s in enumerate(specs) if s.var_type == "continuous"]
    work = copy_blocks(blocks)
    best_f, best_cv = eval_fn(work)
    if not c_idxs or maxiter <= 0:
        return work, best_f, best_cv

    w_pen = max(float(penalty_scale) * 20.0, 1e4)

    def _scalar(fv: np.ndarray, cv: float) -> float:
        f_s = float(np.dot(weight_vec, fv)) if weight_vec is not None else float(fv[0])
        return f_s + w_pen * cv

    best_b = copy_blocks(work)
    best_key = (0 if best_cv <= 1e-9 else 1, best_cv if best_cv > 1e-9 else _scalar(best_f, 0.0))
    z0 = np.concatenate([work[i].astype(float) for i in c_idxs])
    bounds = [(float(specs[i].lb), float(specs[i].ub)) for i in c_idxs for _ in range(specs[i].size)]

    def _loss(z: np.ndarray) -> float:
        nonlocal best_b, best_f, best_cv, best_key
        off = 0
        for i in c_idxs:
            s = specs[i]
            work[i] = np.clip(z[off : off + s.size], s.lb, s.ub).astype(np.float64)
            off += s.size
        fv, cv = eval_fn(work)
        val = _scalar(fv, cv)
        key = (0 if cv <= 1e-9 else 1, cv if cv > 1e-9 else _scalar(fv, 0.0))
        if key < best_key:
            best_key, best_b, best_f, best_cv = key, copy_blocks(work), fv, cv
        return val

    from scipy.optimize import minimize

    scipy_method = "Powell" if method == "powell" else "L-BFGS-B"
    minimize(_loss, z0, method=scipy_method, bounds=bounds, options={"maxiter": max(3, int(maxiter))})
    return best_b, best_f, best_cv


__all__ = [
    "OPERATOR_SPECS",
    "apply_neighbor_move",
    "copy_blocks",
    "crossover_individuals",
    "decode_latent",
    "encode_latent",
    "init_individual",
    "latent_bounds",
    "mutate_individual",
    "perturb_individual",
    "scipy_polish_continuous",
]
