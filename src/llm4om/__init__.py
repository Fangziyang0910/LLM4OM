"""LLM4OM: automated optimization modeling with pluggable methods, LLMs and code languages."""

import asyncio
from pathlib import Path
from typing import Any, Literal

from llm4om.graph import Resources, RunContext, platform_graph, run
from llm4om.llm import LLMSettings
from llm4om.llm_presets import LLMPresetStore
from llm4om.runtime import Context, Limits
from llm4om.sandbox import Sandbox, SolveResult

__all__ = ["Context", "LLMPresetStore", "LLMSettings", "Limits", "Resources", "RunContext", "Sandbox", "SolveResult", "platform_graph",
           "run", "run_problem"]


def run_problem(problem: str, *, method: str = "direct", language: str = "pyomo",
                solver: str | None = None, data: dict[str, str] | None = None, preset: str | None = None,
                llm: LLMSettings | None = None, workspace: str | Path = "runs/web", sandbox: str = "docker",
                change: str | None = None, explain: bool = False, locale: Literal["zh", "en"] = "zh") -> dict[str, Any]:
    """Model and solve one problem; returns the final state with its formulation, code, solve result and steps.

    The LLM is `llm` when given, otherwise the workspace's `preset` (default: the first preset)."""
    resources = Resources(LLMPresetStore(Path(workspace)), Sandbox(sandbox), llm=llm)
    return asyncio.run(run(problem, method=method, language=language, solver=solver, data=data, preset=preset,
                           resources=resources, change=change, explain=explain, locale=locale))
