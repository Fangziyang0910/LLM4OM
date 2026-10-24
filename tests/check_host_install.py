"""Run with a freshly installed base CLI's Python, without pytest or optional extras."""

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def command(*args: str) -> dict | list:
    result = subprocess.run([sys.executable, "-m", "llm4om.cli", *args], capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def main() -> None:
    for module in ("fastapi", "langgraph_api", "langchain_openai", "langchain_anthropic",
                   "langchain_deepseek", "langchain_openrouter", "openrouter", "dotenv"):
        assert importlib.util.find_spec(module) is None, f"Unexpected optional dependency: {module}"
    assert len(command("methods")) == 13
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "session"
        first = command("host", "start", "--problem", "Maximize integer x with 0 <= x <= 3.",
                        "--session", str(path), "--sandbox", "local")
        assert first["status"] == "waiting" and first["pending"][0]["role"] == "generate"
        assert command("host", "status", "--session", str(path))["pending"] == first["pending"]
    print("Base CLI: no provider/Web extras, 13 methods, persistent host request passed.")


if __name__ == "__main__":
    main()
