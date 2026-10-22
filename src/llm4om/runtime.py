"""What a run keeps while a method models: its limits, counts and steps, and the context a method's nodes reach.

`Recorder` counts LLM calls, solves and tokens against the run's limits and records each step. The platform graph
creates one in each of its nodes from the state's `usage`, so counting continues across nodes; each recorded step is
sent at once as a custom stream event, so a client sees the run as it happens.

`Context` is what a method's nodes reach through `runtime.context`: data, code target, LLMs and the sandbox.
"""

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, TypedDict
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import LLMResult

from llm4om.languages import CodeTarget
from llm4om.sandbox import Sandbox, SolveResult

MAX_STEP_TEXT = 40000
TEXT_INTERVAL = 0.25  # seconds between two live-text events of one LLM call


class LimitExceeded(Exception):
    """A run limit stopped the method."""


@dataclass
class Limits:
    max_llm_calls: int = 200
    max_solves: int = 40
    solve_time_limit: float = 60
    run_timeout: float = 3600


class ModelingState(TypedDict, total=False):
    """The keys every method graph shares with the platform; a method's state extends it."""

    problem: str  # input: the problem description followed by the attached data files
    formulation: str | None  # output: Markdown with LaTeX
    code: str | None  # output: Python code that defines build_model(data)
    solve: SolveResult | None  # output, optional: the result of `code` when the method solved it itself
    failure: str | None  # output, optional: why the method stopped without code


class Recorder:
    """A run's counts and steps within one node of the platform graph, continued from the counts before it."""

    def __init__(self, limits: Limits, usage: dict[str, int] | None = None,
                 emit: Callable[[dict[str, Any]], None] | None = None,
                 charge: Callable[[int], None] | None = None) -> None:
        self.limits = limits
        self.charge = charge or (lambda _: None)  # the preset's daily budget: adds tokens, or checks it with 0
        self.usage = {"llm_calls": 0, "solves": 0, "input_tokens": 0, "output_tokens": 0, **(usage or {})}
        self.steps: dict[str, dict[str, Any]] = {}  # step id -> step, in the order the steps started
        self.emit = emit or (lambda _: None)  # sends one custom stream event
        self.callback = _LLMEvents(self)  # records the calls of every chat model it is attached to

    def count(self, kind: str) -> None:
        """Count one LLM call (`llm_calls`) or solve (`solves`); raises LimitExceeded past the run's limit or, for an
        LLM call, past the preset's daily token budget."""
        limit = self.limits.max_llm_calls if kind == "llm_calls" else self.limits.max_solves
        if self.usage[kind] >= limit:
            raise LimitExceeded(f"The run reached its limit of {limit} {'LLM calls' if kind == 'llm_calls' else 'solves'}.")
        if kind == "llm_calls":
            self.charge(0)
        self.usage[kind] += 1

    def step(self, type: str, title: str, content: str = "", *, id: str | None = None, **fields: Any) -> str:
        """Record a step (llm, artifact, solve or error) or update one by `id`; returns its id."""
        id = id or uuid.uuid4().hex[:12]
        entry = {**self.steps.get(id, {"id": id, "time": time.time()}), "type": type, "title": title,
                 "content": content[:MAX_STEP_TEXT], **fields}
        self.steps[id] = entry
        self.emit({"step": entry})
        return id

    def update(self) -> dict[str, Any]:
        """The state update of this node: its steps and the run's counts."""
        return {"steps": list(self.steps.values()), "usage": dict(self.usage)}


@dataclass
class Context:
    """The runtime context of a method graph: data, code target, LLMs and solving. Method parameters live in
    `llm4om.methods.presets`."""

    recorder: Recorder
    sandbox: Sandbox
    chat_model: Callable[[str], BaseChatModel]  # role -> a chat model whose calls the recorder records
    target: CodeTarget
    data: dict[str, str]
    solved: dict[str, SolveResult] = field(default_factory=dict, init=False)  # latest result for each solved code
    _models: dict[str, BaseChatModel] = field(default_factory=dict, init=False, repr=False)

    @property
    def solves(self) -> int:
        """Solves so far in this run."""
        return self.recorder.usage["solves"]

    def llm(self, role: str) -> BaseChatModel:
        """The configured chat model. `role` names its calls in the run's steps."""
        if role not in self._models:
            self._models[role] = self.chat_model(role)
        return self._models[role]

    async def solve(self, code: str, *, title: str = "求解") -> SolveResult:
        """Build the model from `code` in the sandbox and solve it with the selected language's solver."""
        recorder = self.recorder
        recorder.count("solves")
        start = time.monotonic()
        id = recorder.step("solve", title, code=code, running=True)
        try:
            result = await self.sandbox.solve(code, self.data, self.target.language, recorder.limits.solve_time_limit)
        except BaseException as error:
            recorder.step("solve", title, f"{type(error).__name__}: {error}", id=id, running=False, failed=True,
                          seconds=round(time.monotonic() - start, 1))
            raise
        self.solved[code] = result
        recorder.step("solve", title, result.feedback(), id=id, running=False, seconds=round(time.monotonic() - start, 1),
                      status=result.status, objective=result.objective)
        return result

    async def run_script(self, script: str) -> SolveResult:
        """Run a method's own check script in the sandbox as __main__; `output` holds stdout and any traceback.

        Not a solve: it is neither counted nor recorded. Methods use it where the original runs helper scripts.
        """
        return await self.sandbox.run_script(script, self.recorder.limits.solve_time_limit)


class _LLMEvents(BaseCallbackHandler):
    """Counts LLM calls against the limit and records each call as a step, with its text while it streams."""

    raise_error = True
    run_inline = True

    def __init__(self, recorder: Recorder) -> None:
        self.recorder = recorder
        self.calls: dict[UUID, dict[str, Any]] = {}

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[Any]], *, run_id: UUID,
                            metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        self.recorder.count("llm_calls")
        metadata = metadata or {}
        role = metadata.get("llm4om_role") or metadata.get("langgraph_node", "llm")
        self.recorder.step("llm", role, id=str(run_id), running=True)
        self.calls[run_id] = {"role": role, "start": time.monotonic(), "sent": time.monotonic(), "text": "", "reasoning": ""}

    def on_llm_new_token(self, token: str, *, chunk: Any = None, run_id: UUID, **kwargs: Any) -> None:
        call = self.calls.get(run_id)
        if call is None:
            return
        message = getattr(chunk, "message", None)
        call["reasoning"] += (getattr(message, "additional_kwargs", None) or {}).get("reasoning_content") or ""
        call["text"] += token
        if time.monotonic() - call["sent"] >= TEXT_INTERVAL:
            self._send(run_id, call)

    def _send(self, run_id: UUID, call: dict[str, Any]) -> None:
        """Send the text streamed since the last event of this call."""
        if call["text"] or call["reasoning"]:
            self.recorder.emit({"delta": {"id": str(run_id), "text": call["text"], "reasoning": call["reasoning"]}})
        call.update(text="", reasoning="", sent=time.monotonic())

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        call = self.calls.pop(run_id, {"role": "llm", "start": time.monotonic()})
        message = response.generations[0][0].message
        usage = message.usage_metadata or {}
        text = message.text
        calls = [f"{item['name']}({json.dumps(item['args'], ensure_ascii=False)})"
                 for item in message.tool_calls]
        self.recorder.usage["input_tokens"] += usage.get("input_tokens") or 0
        self.recorder.usage["output_tokens"] += usage.get("output_tokens") or 0
        self.recorder.charge((usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0))
        self.recorder.step("llm", call["role"], "\n\n".join(part for part in (text, *calls) if part), id=str(run_id),
                           running=False, seconds=round(time.monotonic() - call["start"], 1),
                           input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens"))

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        call = self.calls.pop(run_id, {"role": "llm"})
        self.recorder.step("llm", call["role"], f"{type(error).__name__}: {error}", id=str(run_id), running=False,
                           failed=True)
