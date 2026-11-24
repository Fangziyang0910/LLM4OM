"""Minimal mathematical problem definition for AutoCO's intelligent optimization solver."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Literal, get_args

import numpy as np

VarType = Literal["binary", "integer", "continuous", "permutation", "assignment"]
Sense = Literal["min", "max"]
ConstraintHandling = Literal["feasibility", "penalty", "adaptive_penalty"]


@dataclass(frozen=True)
class VarSpec:
    """Specification of one decision-variable block in its natural domain."""

    name: str
    var_type: VarType
    size: int
    lb: float = 0.0
    ub: float = 1.0
    n_categories: int = 2  # Used when var_type == "assignment" (values in 0..n_categories-1)

    def __post_init__(self) -> None:
        if self.var_type not in get_args(VarType):
            raise ValueError(f"Unknown variable type {self.var_type!r}. Choose one of {get_args(VarType)}.")
        if self.size <= 0:
            raise ValueError(f"VarSpec '{self.name}' size must be positive, got {self.size}.")
        if self.var_type == "assignment" and self.n_categories < 1:
            raise ValueError(f"VarSpec '{self.name}' n_categories must be >= 1.")
        if self.var_type in ("integer", "continuous") and self.lb > self.ub:
            raise ValueError(f"VarSpec '{self.name}' has lb ({self.lb}) > ub ({self.ub}).")


@dataclass
class Problem:
    """Unified problem contract corresponding to the Typed 4-Tuple M = (P, X, F, C).

    `evaluate` accepts:
      - a single 1D `np.ndarray` if `len(variables) == 1` and `unpack_single=True` (default),
      - otherwise a `dict[str, np.ndarray]` mapping each `VarSpec.name` to its value array.
    `evaluate` returns either:
      - `(objectives, violation)` where `violation >= 0` is total constraint violation (`0` = feasible),
      - or just `objectives` (treated as unconstrained, `violation = 0.0`).
    """

    name: str
    variables: list[VarSpec]
    evaluate: Callable[..., object]
    senses: list[Sense] = field(default_factory=lambda: ["min"])
    unpack_single: bool = True
    decode: Callable[..., object] | None = None

    def __post_init__(self) -> None:
        if not self.senses or any(sense not in get_args(Sense) for sense in self.senses):
            raise ValueError("Each objective must declare its sense as 'min' or 'max'.")
        object.__setattr__(self, "_signs", np.array([1.0 if s == "min" else -1.0 for s in self.senses], dtype=float))

    def decode_solution(self, x: object) -> object:
        return self.decode(x) if callable(self.decode) else x

    @property
    def n_objectives(self) -> int:
        return len(self.senses)

    @property
    def is_multi_objective(self) -> bool:
        return len(self.senses) > 1

    @property
    def total_dim(self) -> int:
        return sum(s.size for s in self.variables)

    def format_solution(self, blocks: list[np.ndarray]) -> np.ndarray | dict[str, np.ndarray]:
        if self.unpack_single and len(self.variables) == 1:
            return blocks[0].copy()
        return {spec.name: arr.copy() for spec, arr in zip(self.variables, blocks)}

    def eval_blocks(self, blocks: list[np.ndarray]) -> tuple[np.ndarray, float]:
        """Evaluate internal variable blocks and return `(minimized_obj_vector, violation >= 0)`."""
        arg = blocks[0] if (self.unpack_single and len(self.variables) == 1) else {
            spec.name: arr for spec, arr in zip(self.variables, blocks)
        }
        raw = self.evaluate(arg)
        if isinstance(raw, tuple) and len(raw) == 2:
            raw_obj, raw_cv = raw
            cv = float(raw_cv)
        else:
            raw_obj, cv = raw, 0.0

        f_arr = np.atleast_1d(np.asarray(raw_obj, dtype=float)).reshape(-1)
        if f_arr.shape[0] != len(self.senses):
            raise ValueError(
                f"Expected {len(self.senses)} objective(s) in `(objectives, violation)`, got {f_arr.shape[0]} from return {raw!r}."
            )

        if not np.isfinite(cv) or not np.all(np.isfinite(f_arr)):
            raise ValueError("Objective values and constraint violation must be finite.")
        return f_arr * self._signs, max(0.0, cv)  # type: ignore[attr-defined]

    def restore_objectives(self, internal_f: np.ndarray) -> float | np.ndarray:
        """Convert internal minimized objective vector back to original sense(s)."""
        orig = internal_f * self._signs  # type: ignore[attr-defined]
        return float(orig[0]) if orig.size == 1 else orig


def scalar_score(
    f: float,
    cv: float,
    mode: ConstraintHandling = "feasibility",
    penalty_weight: float = 1e4,
    progress: float = 0.0,
) -> tuple[int, float]:
    """Comparable key (lower is better) for single-objective selection/ranking."""
    feasible = cv <= 1e-9
    if mode == "feasibility":
        return (0, f) if feasible else (1, cv)
    if mode == "adaptive_penalty":
        p = float(np.clip(progress, 0.0, 1.0))
        scale = penalty_weight * (0.25 + 49.75 * (p * p))
        return (0, f + scale * cv)
    return (0, f + penalty_weight * cv)


def energy_delta(
    f_new: float,
    cv_new: float,
    f_cur: float,
    cv_cur: float,
    mode: ConstraintHandling = "feasibility",
    penalty_weight: float = 1e4,
    progress: float = 0.0,
) -> float:
    """Compute signed energy change (negative = improvement) for SA acceptance."""
    if mode == "feasibility":
        feas_new, feas_cur = cv_new <= 1e-9, cv_cur <= 1e-9
        if feas_new and feas_cur:
            return f_new - f_cur
        if not feas_new and not feas_cur:
            return cv_new - cv_cur
        return -abs(f_cur) - cv_cur - 1.0 if feas_new else abs(f_new) + cv_new + 1.0
    _, s_new = scalar_score(f_new, cv_new, mode, penalty_weight, progress)
    _, s_cur = scalar_score(f_cur, cv_cur, mode, penalty_weight, progress)
    return s_new - s_cur
