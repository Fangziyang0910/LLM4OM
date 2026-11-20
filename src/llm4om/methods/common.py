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


def split_formulation_and_code(text: str) -> tuple[str, str]:
    """Split a reply into the Markdown before the last code block and that code."""
    blocks = list(re.finditer(r"^[ \t]*```([^\r\n`]*)\r?\n(.*?)```", text, re.S | re.M))
    python = [match for match in blocks if match.group(1).strip().lower() in ("python", "py", "python3")]
    matches = python or [match for match in blocks if not match.group(1).strip()]
    if not matches:
        raise ValueError("The reply does not contain a ```python code block.")
    code = textwrap.dedent(matches[-1].group(2).strip("\r\n")).strip()
    return text[:matches[-1].start()].strip(), (code + "\n") if code else ""
