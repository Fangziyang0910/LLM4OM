"""Modeling methods. A method is a LangGraph graph over a state that extends `ModelingState`.

The graph reads `problem` and writes `formulation` and `code` (and `solve` when it solved the code itself).
Its nodes take `runtime: Runtime[Context]` to reach the LLM, the solver and the run log. The run view shows each
update of a titled node as one step.
"""

from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any, Callable, Mapping

from llm4om.runtime import Limits


@dataclass(frozen=True)
class Method:
    id: str
    name: str  # the method's short name, as its paper calls it
    description: str  # shown in the Web method list
    graph: Callable[[], Any]  # builds the compiled LangGraph graph
    source: str | None = None  # upstream code at the pinned commit the port follows
    titles: Mapping[str, str] = field(default_factory=dict)  # node name -> step title; only these nodes are shown
    hidden: frozenset[str] = frozenset()  # state keys not shown in the steps, besides problem, solve and "_..." keys
    languages: frozenset[str] | None = None  # code languages the method supports; None means all
    limits: Limits | None = None  # replaces the service limits for methods that need many more calls


def methods() -> dict[str, Method]:
    """Built-in methods plus any installed under the `llm4om.methods` entry-point group."""
    from llm4om.methods import autoformulation, coe, direct, llmopt, optimus, optitree, or_llm_agent, orthought, trival

    found = [direct.DIRECT, direct.FEEDBACK_REPAIR, trival.TRIVAL, optimus.OPTIMUS, coe.COE, optitree.OPTITREE,
             or_llm_agent.OR_LLM_AGENT, orthought.ORTHOUGHT, llmopt.LLMOPT, autoformulation.AUTOFORMULATION]
    found += [entry.load() for entry in entry_points(group="llm4om.methods")]
    return {method.id: method for method in found}
