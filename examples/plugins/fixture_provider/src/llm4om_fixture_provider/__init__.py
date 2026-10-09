"""Engineering Adapter: OpenAI-compatible text transport under a separate identity."""

from typing import Any
from llm4om.providers import HTTPTextFactory, OpenAICompatibleProvider


class FixtureProvider(OpenAICompatibleProvider):
    plugin_id = "llm4om.examples.openai_text"


class FixtureFactory(HTTPTextFactory):
    provider_type = FixtureProvider

    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest["display_name"] = "Installed OpenAI text fixture"
        manifest["source"] = {"kind": "engineering_fixture", "variant_id": "installed_openai_text",
                              "description": "Reuses the SDK OpenAI text protocol; no new modeling method."}
        return manifest


plugin = FixtureFactory()
