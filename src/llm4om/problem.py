"""The problem description and attached data files shared by the Web, host and conversation entries.

`problem_text` renders the description and a bounded preview of each attachment for prompts. The full attachment
texts always travel separately in `Context.data`; validation here never rewrites the user's description or names.
"""

from collections.abc import Mapping
from hashlib import sha256

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
    if not isinstance(description, str) or not description.strip():
        raise ValueError("Describe the optimization problem first.")


def validate_data_files(data: Mapping[str, str]) -> None:
    """Reject attachment names that are not a single file name; accepted names stay byte for byte."""
    if not isinstance(data, Mapping):
        raise ValueError("Attached data files must be a mapping from file name to text content.")
    for name, content in data.items():
        if not isinstance(name, str) or not name.strip() or name in {".", ".."} or any(char in name for char in "/\\\0\r\n"):
            raise ValueError(f"Invalid data file name {name!r}; supply a single file name without path separators or line breaks.")
        if not isinstance(content, str):
            raise ValueError(f"Invalid content for data file {name!r}; attachment content must be text.")


def input_changed(expected: str | None, data: Mapping[str, str], description: str = "") -> bool:
    """Check the browser-visible inputs against the checkpoint actually selected for this turn."""
    if expected is None:  # Native clients and previously created runs can omit the check.
        return False
    files = []
    for name, content in data.items():
        digest = sha256(name.encode("utf-8") + b"\0")
        digest.update(content.encode("utf-8"))
        files.append(digest.hexdigest())
    inputs = sha256(description.encode("utf-8")).hexdigest() + "".join(sorted(files))
    return sha256(inputs.encode("ascii")).hexdigest() != expected


def changed_input_message(locale: str) -> str:
    return ("另一处已修改本轮输入。请刷新页面，核对最新内容后重试。" if locale == "zh" else
            "The inputs for this turn changed in another session. Reload, review the latest inputs and retry.")
