"""Record each method's public node outputs in both platform and host-model runs."""

import json
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler

from llm4om.methods import Method
from llm4om.runtime import Recorder

HIDDEN_KEYS = {"problem", "description", "solve", "messages", "failure"}


def render_update(update: dict[str, Any], hidden: frozenset[str] = frozenset()) -> str:
    """A node update as Markdown: text as is, code in a Python block, flags and numbers on one line, anything else
    as JSON. Several keys get a heading each, named after the key."""
    shown = {key: value for key, value in update.items() if key not in HIDDEN_KEYS and key not in hidden
             and not key.startswith("_") and value not in (None, "", [], {})}
    parts = []
    for key, value in shown.items():
        name = key.replace("_", " ").capitalize()
        if isinstance(value, bool):
            parts.append(f"{'✅' if value else '❌'} **{name}**")
            continue
        if isinstance(value, (int, float)):
            parts.append(f"**{name}**: {value}")
            continue
        if isinstance(value, str):
            body = f"```python\n{value.rstrip()}\n```" if key == "code" or key.endswith("_code") else value
        else:
            body = "```json\n" + json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n```"
        parts.append(body if len(shown) == 1 else f"#### {name}\n\n{body}")
    return "\n\n".join(parts)


class NodeSteps(BaseCallbackHandler):
    """Records the update of each titled method node as an artifact step the moment the node ends.

    A node's end callback runs before the next node starts, so the step lands between the LLM calls and solves
    that produced it and those that follow; a consumer of the graph's update stream would see it late.
    """

    run_inline = True

    def __init__(self, method: Method, recorder: Recorder) -> None:
        self.method, self.recorder = method, recorder
        self.nodes: dict[UUID, str] = {}  # run id -> node name, for the runs of titled nodes

    def on_chain_start(self, serialized: dict[str, Any] | None, inputs: Any, *, run_id: UUID,
                       tags: list[str] | None = None, metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        node = (metadata or {}).get("langgraph_node")
        # A node's own run carries its name and a graph-step tag; runnables inside it inherit only the metadata.
        if node in self.method.titles and kwargs.get("name") == node and any(
                tag.startswith("graph:step:") for tag in tags or []):
            self.nodes[run_id] = node

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        node = self.nodes.pop(run_id, None)
        if node and isinstance(outputs, dict) and (text := render_update(outputs, self.method.hidden)):
            produced = {key: outputs[key] for key in ("formulation", "code") if isinstance(outputs.get(key), str)}
            self.recorder.step("artifact", self.method.titles[node], text, node=node, **produced)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self.nodes.pop(run_id, None)
