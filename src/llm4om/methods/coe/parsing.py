"""Chain-of-Experts reply parsing, preserving its JSON and Python-literal formats."""

import ast
import json
import re
import textwrap
from collections.abc import Iterator
from typing import Any

import json_repair

from llm4om.methods.common import python_code_blocks


def extract_code_from_string(text: str) -> str:
    """Upstream utils.extract_code_from_string: all code blocks joined, without pip lines; the text if none."""
    blocks = [textwrap.dedent(match.group(2).strip("\r\n")).strip() for match in python_code_blocks(text)]
    if not blocks:
        return text
    if len(blocks) == 1:
        return blocks[0]
    return '\n'.join(code for code in blocks if not re.search(r'(?m)^\s*!?\s*pip3?\s+install\b', code))


def _extract_json_blobs(text: str) -> Iterator[str]:
    starts = [i for i, c in enumerate(text) if c in ('{', '[')]
    for start in starts:
        stack: list[str] = []
        quote_char = None
        escaped = False
        for idx in range(start, len(text)):
            ch = text[idx]
            if quote_char is not None:
                if escaped:
                    escaped = False
                    continue
                if ch == '\\':
                    escaped = True
                    continue
                if ch == quote_char:
                    quote_char = None
                continue
            if ch in ('"', "'"):
                quote_char = ch
            elif ch in ('{', '['):
                stack.append(ch)
            elif ch in ('}', ']'):
                if not stack:
                    break
                left = stack.pop()
                if (left == '{' and ch != '}') or (left == '[' and ch != ']'):
                    break
                if not stack:
                    yield text[start:idx + 1]
                    break


def parse_json_from_string(text: Any, expected_type: type | None = None) -> Any:
    """Upstream utils.parse_json_from_string: JSON or a Python literal, from the text, its code block or its blobs."""
    raw = str(text).strip()
    candidates = [raw] if raw else []
    code = extract_code_from_string(raw).strip()
    if code and code not in candidates:
        candidates.append(code)
    for source in (raw, code):
        for blob in _extract_json_blobs(source):
            if blob not in candidates:
                candidates.append(blob)
    for candidate in candidates:
        for parser in (json.loads, ast.literal_eval):
            try:
                value = parser(candidate)
            except (ValueError, SyntaxError, json.JSONDecodeError):
                continue
            if expected_type is not None and not isinstance(value, expected_type):
                continue
            return value
    for candidate in candidates:
        if not candidate or candidate[0] not in ('{', '['):
            continue
        try:
            value = json_repair.loads(candidate)
        except Exception:
            continue
        if value in ('', None):
            continue
        if expected_type is not None and not isinstance(value, expected_type):
            continue
        return value
    raise ValueError(f'Cannot parse JSON from text: {raw[:200]}')
