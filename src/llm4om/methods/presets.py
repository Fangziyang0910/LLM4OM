"""The parameters of every method, in one place. Each run uses these values; runs cannot change them.

The values of the ported methods are upstream's defaults at the pinned commit (see docs/methods.md). Change a
value here to run a method with other settings.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TriVAL:
    max_validations: int = 5  # rounds of each stage: semantic, formulation and code validation
    max_code_executions: int = 20


@dataclass(frozen=True)
class OptiMUS:
    temperature: float = 1.0  # upstream sends no temperature; 1.0 is the OpenAI default
    max_debug_tries: int = 3


@dataclass(frozen=True)
class ChainOfExperts:
    temperature: float = 0  # upstream PromptModelChain
    max_collaborate_nums: int = 3  # experts the conductor asks per trial
    enable_reflection: bool = False  # upstream CLI default
    max_trials: int = 3  # trials when reflection is on; one trial otherwise


@dataclass(frozen=True)
class OptiTree:
    temperature: float = 0
    max_inspections: int = 4  # upstream: `count > 3` ends the loop after the fourth inspection


@dataclass(frozen=True)
class ORLLMAgent:
    temperature: float = 0.2  # upstream query_llm default
    attempts: dict[str, int] = field(default_factory=lambda: {"main": 3, "infeasible": 1, "recheck": 2})  # per round


@dataclass(frozen=True)
class LLMOpt:
    max_resolves: int = 12  # self-correction re-solves after the first; the paper's Section 4.1


@dataclass(frozen=True)
class BIND:
    temperature: float = 0.0
    top_p: float = 1.0
    max_rounds: int = 3  # total generation/execution attempts


@dataclass(frozen=True)
class AutoCO:
    temperature: float = 0.0
    max_modeling_revisions: int = 1
    max_instantiate_attempts: int = 3
    max_kg_steps: int = 6
    enable_pilot: bool = True
    seed: int = 42


TRIVAL = TriVAL()
OPTIMUS = OptiMUS()
COE = ChainOfExperts()
OPTITREE = OptiTree()
OR_LLM_AGENT = ORLLMAgent()
LLMOPT = LLMOpt()
BIND = BIND()
AUTOCO = AutoCO()
