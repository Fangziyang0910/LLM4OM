"""Private LLM presets and the optional environment preset."""

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from llm4om.llm import LLMSettings
from llm4om.storage import write_private_json


@dataclass(frozen=True)
class LLMPreset:
    """A fixed LLM configuration that runs choose by id. `source` is "env" for the LLM4OM_LLM_* preset."""

    id: str
    settings: LLMSettings
    source: str = "saved"
    name: str = ""

    def public(self) -> dict[str, Any]:
        """The preset without its key: what the browser and run records may see."""
        values = asdict(self.settings)
        del values["api_key"], values["timeout"], values["max_retries"]
        return {"id": self.id, "source": self.source, "name": self.name or self.settings.model, **values}


ENV_PRESET = "env"


class LLMPresetStore:
    """LLM presets in `<workspace>/.private/llm-presets.json` (mode 600), plus the LLM4OM_LLM_* preset.

    Presets can be added and deleted but never changed, and their keys never leave the server: no route returns a
    key, and a key is only sent to the base URL saved with it. The first preset is the default.
    """

    _lock = threading.RLock()  # All store instances in the service share the read/modify/write transaction.

    def __init__(self, workspace: Path) -> None:
        self.path = workspace / ".private" / "llm-presets.json"

    def _saved(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return self._migrate()
        return json.loads(self.path.read_text(encoding="utf-8"))["presets"]

    def _migrate(self) -> list[dict[str, Any]]:
        """v0.38 kept one profile per provider in llm-settings.json; each becomes a preset named after its provider."""
        old = self.path.with_name("llm-settings.json")
        if not old.exists():
            return []
        profiles = json.loads(old.read_text(encoding="utf-8"))["profiles"]
        presets = [{"id": provider, "provider": provider, **values} for provider, values in profiles.items()]
        self._write(presets)
        old.unlink()
        return presets

    def presets(self) -> list[LLMPreset]:
        """The environment preset first, then the saved ones in the order they were added."""
        with self._lock:
            saved = []
            for values in self._saved():
                identity, name = values.pop("id"), values.pop("name", "")
                saved.append(LLMPreset(identity, LLMSettings(**values), name=name))
        environment = settings_from_env()
        return ([LLMPreset(ENV_PRESET, environment, "env", os.environ.get("LLM4OM_LLM_NAME", ""))] if environment else []) + saved

    def find(self, preset: str | None = None) -> LLMPreset:
        """The preset `preset`, or the default preset."""
        presets = self.presets()
        if not presets:
            raise ValueError("Add an LLM preset first (Web workbench, or LLM4OM_LLM_* environment variables).")
        if preset is None:
            return presets[0]
        for item in presets:
            if item.id == preset:
                return item
        raise ValueError(f"No LLM preset {preset!r}; choose one of {[item.id for item in presets]}.")

    def get(self, preset: str | None = None) -> LLMSettings:
        """The settings of `preset`, or of the default preset."""
        return self.find(preset).settings

    def add(self, settings: LLMSettings, name: str = "") -> LLMPreset:
        """Save a new preset with an identity that is never reused after deletion."""
        settings.validate()
        preset = LLMPreset(uuid4().hex, settings, name=name.strip())
        with self._lock:
            saved = self._saved()
            self._write(saved + [{"id": preset.id, "name": preset.name, **asdict(settings)}])
        return preset

    def delete(self, preset: str) -> None:
        if preset == ENV_PRESET:
            raise ValueError("This preset comes from the server's LLM4OM_LLM_* variables; remove it there.")
        with self._lock:
            saved = self._saved()
            if not any(values["id"] == preset for values in saved):
                raise ValueError(f"No saved LLM preset {preset!r}.")
            self._write([values for values in saved if values["id"] != preset])

    def _write(self, presets: list[dict[str, Any]]) -> None:
        write_private_json(self.path, {"presets": presets})

    def public(self) -> dict[str, Any]:
        return {"presets": [preset.public() for preset in self.presets()]}


def settings_from_env() -> LLMSettings | None:
    """Default settings from LLM4OM_LLM_* variables (a `.env` file in the working directory is read first)."""
    from dotenv import load_dotenv

    load_dotenv()
    model = os.environ.get("LLM4OM_LLM_MODEL", "")
    if not model:
        return None
    return LLMSettings(provider=os.environ.get("LLM4OM_LLM_PROVIDER", "openai_compatible"), model=model,
                       api_key=os.environ.get("LLM4OM_LLM_API_KEY", ""),
                       base_url=os.environ.get("LLM4OM_LLM_BASE_URL", ""),
                       extra_body=json.loads(os.environ.get("LLM4OM_LLM_EXTRA_BODY") or "{}"))
