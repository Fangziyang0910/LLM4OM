"""Helpers shared by the project's own methods."""

import re
import textwrap

from langchain_core.messages import HumanMessage, SystemMessage

from llm4om.runtime import Context

TWO_PARTS = ("Reply with the mathematical formulation in Markdown with LaTeX ($...$ inline, $$...$$ display), "
             "then the complete implementation in one ```python code block.")

FORMULATION_FORMAT = (
    "\n\nMathematical presentation requirements: Use Markdown prose and Markdown lists inside the required "
    "formulation section. Enclose mathematical expressions in $...$ inline or $$...$$ display delimiters. "
    "Do not use LaTeX document environments such as itemize, or leave symbolic constraints as indented plain text. "
    "State every decision variable's domain explicitly as continuous, integer or binary, with its decision unit. "
    "Preserve explicit whole-item and divisibility requirements; if divisibility is genuinely ambiguous, state "
    "the assumption rather than treating it as a supplied fact. Keep all required section headings, outer code "
    "fences and protocol labels exactly as specified. Formatting must not change mathematical meaning."
)


def output_language(context: Context) -> str:
    """Localize prose without changing a research method's machine-readable response protocol."""
    language = "Simplified Chinese" if context.locale == "zh" else "English"
    return (f"\n\nOutput language: Write explanatory prose in {language}, including model descriptions, solution "
            "reasoning and diagnostic explanations. Do not translate required section headings, protocol labels, "
            "verdict lines, code-fence language tags, JSON keys, JSON enum values, classification names, tool names, "
            "tool argument names, identifiers or supplied data. Natural-language explanation fields may use the "
            "selected language; enum and source-data values must remain unchanged. Preserve the exact response "
            "structure requested above. Mathematical expressions and executable code keep their meaning.")


async def ask(context: Context, role: str, system: str, user: str) -> str:
    reply = await context.llm(role).ainvoke([SystemMessage(system + output_language(context)), HumanMessage(user)])
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
