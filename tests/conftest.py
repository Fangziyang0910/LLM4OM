"""A scripted chat model and in-process runs that solve generated code locally."""

import asyncio
import uuid
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool

from llm4om.graph import Resources, run
from llm4om.llm import LLMPresetStore, LLMSettings
from llm4om.methods import presets
from llm4om.runtime import Limits
from llm4om.sandbox import Sandbox

LLM = LLMSettings(provider="openai_compatible", model="scripted", api_key="test-key", base_url="http://localhost:9")

PRODUCTION_PROBLEM = ("A factory makes products A and B in nonnegative integer quantities. Profit is 3 per A and 2 per B. "
                      "A uses 2 cutting and 1 machining unit; B uses 1 cutting and 2 machining units. "
                      "8 units of each resource are available. Maximize profit.")
PRODUCTION_CODE = '''import pyomo.environ as pyo

def build_model(data):
    m = pyo.ConcreteModel()
    m.P = pyo.Set(initialize=["A", "B"])
    m.x = pyo.Var(m.P, domain=pyo.NonNegativeIntegers)
    m.profit = pyo.Objective(expr=3 * m.x["A"] + 2 * m.x["B"], sense=pyo.maximize)
    m.cutting = pyo.Constraint(expr=2 * m.x["A"] + m.x["B"] <= 8)
    m.machining = pyo.Constraint(expr=m.x["A"] + 2 * m.x["B"] <= 8)
    return m
'''
FORMULATION = "$$\\max\\ 3x_A + 2x_B$$ subject to $2x_A + x_B \\le 8$, $x_A + 2x_B \\le 8$, $x \\in \\mathbb{Z}_+$."
TWO_PART_REPLY = f"### Formulation\n{FORMULATION}\n\n```python\n{PRODUCTION_CODE}```"


def tool_call(name: str, **args: Any) -> AIMessage:
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": "call_" + uuid.uuid4().hex[:8]}])


class ScriptedChat(BaseChatModel):
    """Replies with script(role, messages, tool_names); the role comes from the platform's metadata."""

    script: Any
    tool_names: list[str] = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages: list[BaseMessage], stop: Any = None, run_manager: Any = None, **kwargs: Any) -> ChatResult:
        role = (self.metadata or {}).get("llm4om_role", "llm")
        reply = self.script(role, messages, self.tool_names)
        message = AIMessage(reply) if isinstance(reply, str) else reply
        message.usage_metadata = {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}
        return ChatResult(generations=[ChatGeneration(message=message)])

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ScriptedChat":
        names = [convert_to_openai_tool(tool)["function"]["name"] for tool in tools]
        return self.model_copy(update={"tool_names": names})


Script = Callable[[str, list[BaseMessage], list[str]], Any]


@pytest.fixture(autouse=True)
def no_environment_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests see no LLM4OM_LLM_* preset unless they set one: neither the shell's nor the repository's .env."""
    for name in ("PROVIDER", "MODEL", "API_KEY", "BASE_URL", "EXTRA_BODY"):
        monkeypatch.delenv(f"LLM4OM_LLM_{name}", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)


@pytest.fixture
def make_resources(tmp_path: Path) -> Callable[..., Resources]:
    def make(script: Script, limits: Limits | None = None, llm: LLMSettings | None = LLM) -> Resources:
        def factory(settings: LLMSettings, *, callbacks: Any = None, metadata: Any = None) -> ScriptedChat:
            return ScriptedChat(script=script, callbacks=callbacks, metadata=metadata)

        return Resources(LLMPresetStore(tmp_path / "workspace"), Sandbox("local"), limits or Limits(), factory, llm)

    return make


@pytest.fixture
def run_method(make_resources: Callable[..., Resources]) -> Callable[..., dict[str, Any]]:
    """Run a method in process; returns the final state."""
    def execute(method: str, script: Script, *, language: str = "pyomo", limits: Limits | None = None,
                problem: str = PRODUCTION_PROBLEM) -> dict[str, Any]:
        return asyncio.run(run(problem, method=method, language=language, resources=make_resources(script, limits)))

    return execute


@pytest.fixture
def preset(monkeypatch: pytest.MonkeyPatch) -> Callable[..., None]:
    """Change fields of one method's preset for a test, e.g. preset("AUTOFORMULATION", n_top=1)."""
    def change(name: str, **fields: Any) -> None:
        monkeypatch.setattr(presets, name, replace(getattr(presets, name), **fields))

    return change
