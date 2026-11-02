"""The problem description and attached data files shared by the Web, host and conversation entries.

`problem_text` renders the description and a bounded preview of each attachment for prompts. The full attachment
texts always travel separately in `Context.data`; validation here never rewrites the user's description or names.
"""

from collections.abc import Mapping

MAX_DATA_CHARS = 20000  # preview only; Context.data always carries every attachment in full


def problem_text(description: str, data: Mapping[str, str]) -> str:
    """The problem description followed by every attached data file, each preview cut at MAX_DATA_CHARS."""
    parts = ["## Problem description\n" + description.strip()]
    for name, content in data.items():
        shown = content if len(content) <= MAX_DATA_CHARS else content[:MAX_DATA_CHARS] + "\n... (truncated)"
        parts.append(f"## Data file `{name}`\n```\n{shown}\n```")
    return "\n\n".join(parts)


def validate_description(description: str) -> None:
    """Reject a blank problem without changing the user's text."""
    if not description.strip():
        raise ValueError("Describe the optimization problem first.")


def validate_data_files(data: Mapping[str, str]) -> None:
    """Reject attachment names that are not a single file name; accepted names stay byte for byte."""
    for name in data:
        if not name.strip() or name in {".", ".."} or any(char in name for char in "/\\\0\r\n"):
            raise ValueError(f"Invalid data file name {name!r}; supply a single file name without path separators or line breaks.")
