"""AutoCO's intelligent optimization solver pool (runs inside the sandbox; specs also load on the host)."""

from __future__ import annotations

from typing import Any

from .problem import Problem, VarSpec
from .specs import ALGORITHM_SPECS, OPERATOR_SPECS, canonical_algorithm, sanitize_config


def solve(*args: Any, **kwargs: Any) -> Any:
    from .algorithms import solve as _solve

    return _solve(*args, **kwargs)


__all__ = [
    "ALGORITHM_SPECS",
    "OPERATOR_SPECS",
    "Problem",
    "VarSpec",
    "canonical_algorithm",
    "sanitize_config",
    "solve",
]
