"""Helpers shared by the project's own methods."""

import re
import textwrap

from langchain_core.messages import HumanMessage, SystemMessage

from llm4om.runtime import Context

TWO_PARTS = ("Reply with the mathematical formulation in Markdown with LaTeX ($...$ inline, $$...$$ display), "
             "then the complete implementation in one ```python code block.")


async def ask(context: Context, role: str, system: str, user: str) -> str:
    reply = await context.llm(role).ainvoke([SystemMessage(system), HumanMessage(user)])
    return reply.text


def strip_json_fence(text: str) -> str:
    """Strip a surrounding ``` or ```json Markdown fence from a JSON reply."""
    stripped = text.strip()
    match = re.fullmatch(r"```(?:json)?[ \t]*\r?\n?(.*?)\r?\n?```", stripped, re.S | re.I)
    return match.group(1).strip() if match else stripped


def python_code_blocks(text: str, *, allow_unclosed: bool = False) -> list[re.Match[str]]:
    """Fenced ```python blocks in `text`, falling back to untagged ``` blocks when none are labeled Python."""
    closing = r"(?:```|\Z)" if allow_unclosed else r"```"
    blocks = list(re.finditer(rf"^[ \t]*```([^\r\n`]*)\r?\n(.*?){closing}", text, re.S | re.M))
    python = [match for match in blocks if match.group(1).strip().lower() in ("python", "py", "python3")]
    return python or [match for match in blocks if not match.group(1).strip()]


def split_formulation_and_code(text: str) -> tuple[str, str]:
    """Split a reply into the Markdown before the last code block and that code."""
    matches = python_code_blocks(text)
    if not matches:
        raise ValueError("The reply does not contain a ```python code block.")
    code = textwrap.dedent(matches[-1].group(2).strip("\r\n")).strip()
    return text[:matches[-1].start()].strip(), (code + "\n") if code else ""
