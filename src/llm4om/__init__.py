"""General Intelligent Optimization Solver: a general solver for complex optimization problems."""

import asyncio
from typing import Any

from llm4om.graph import Resources, RunContext, platform_graph, run
from llm4om.llm import LLMSettings
from llm4om.llm_presets import LLMPresetStore
from llm4om.runtime import Context, Limits
from llm4om.sandbox import Sandbox, SolveResult

__all__ = ["Context", "LLMPresetStore", "LLMSettings", "Limits", "Resources", "RunContext", "Sandbox", "SolveResult", "platform_graph",
           "run", "run_problem"]


def run_problem(problem: str, **options: Any) -> dict[str, Any]:
    """Synchronous entry over `run()`: model and solve one problem and return its final state."""
    options.setdefault("workspace", "runs/web")
    options.setdefault("sandbox", "docker")
    return asyncio.run(run(problem, **options))
