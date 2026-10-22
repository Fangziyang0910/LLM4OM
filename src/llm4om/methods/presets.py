"""The parameters of every method, in one place. Each run uses these values; runs cannot change them.

The values of the ported methods are upstream's defaults at the pinned commit (see docs/methods.md). Change a
value here to run a method with other settings.
"""

from dataclasses import dataclass, field

from llm4om.runtime import Limits


@dataclass(frozen=True)
class FeedbackRepair:
    max_repairs: int = 3  # repairs after the first solve when it found no solution


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
class ORThought:
    temperature: float = 0.0  # upstream main.sh
    debug_max_try: int = 3  # upstream main.sh


@dataclass(frozen=True)
class LLMOpt:
    max_resolves: int = 12  # self-correction re-solves after the first; the paper's Section 4.1


@dataclass(frozen=True)
class AutoFormulation:
    temperature: float = 1.0  # upstream samples n completions at the API default
    n_used_gpt: int = 8  # completions sampled per tree node
    n_top: int = 3  # candidates kept per node after ranking
    n_reward: int = 5  # ranking samples per node
    total_rollouts: int = 16
    n_dv_unique_gpt: int = 8  # samples that group equivalent decision variables
    n_eval: int = 5  # judgments per pairwise comparison
    num_warmup: int = 3  # rollouts that become comparison baselines
    w_exp: float = 1  # UCT exploration weight
    lambda_cte: float = 0.5  # UCT weight of a node's own reward
    max_rollout_attempts: int = 1000  # many_rollouts stops after this many rollouts that reach no new leaf
    max_comparison_tries: int = 5  # llm4om: upstream retries an unparsable comparison forever
    # The tree needs about 500 LLM calls and each rollout about 30, so the run limits are far above the service's.
    limits: Limits = field(default_factory=lambda: Limits(max_llm_calls=20000, max_solves=1000, run_timeout=6 * 3600))


FEEDBACK_REPAIR = FeedbackRepair()
TRIVAL = TriVAL()
OPTIMUS = OptiMUS()
COE = ChainOfExperts()
OPTITREE = OptiTree()
OR_LLM_AGENT = ORLLMAgent()
AUTOFORMULATION = AutoFormulation()
ORTHOUGHT = ORThought()
LLMOPT = LLMOpt()
