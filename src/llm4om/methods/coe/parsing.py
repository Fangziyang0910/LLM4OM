"""Chain-of-Experts reply parsing, preserving its JSON and Python-literal formats."""

import ast
import json
import re
from typing import Any


def extract_code_from_string(text: str) -> str:
    """Upstream utils.extract_code_from_string: all code blocks joined, without pip lines; the text if none."""
    blocks = re.findall(r'```(?:python)?\s*(.*?)\s*```', text, re.DOTALL)
    if not blocks:
        return text
    if len(blocks) == 1:
        return blocks[0]
    return '\n'.join(code for code in blocks if 'pip' not in code)


def _extract_first_json_blob(text: str) -> str | None:
    starts = [i for i, c in enumerate(text) if c in ['{', '[']]
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
            if ch in ['"', "'"]:
                quote_char = ch
            elif ch in ['{', '[']:
                stack.append(ch)
            elif ch in ['}', ']']:
                if not stack:
                    break
                left = stack.pop()
                if (left == '{' and ch != '}') or (left == '[' and ch != ']'):
                    break
                if not stack:
                    return text[start:idx + 1]
    return None


def parse_json_from_string(text: Any, expected_type: type | None = None) -> Any:
    """Upstream utils.parse_json_from_string: JSON or a Python literal, from the text, its code block or its first blob."""
    raw = str(text).strip()
    candidates = [raw] if raw else []
    code = extract_code_from_string(raw).strip()
    if code and code not in candidates:
        candidates.append(code)
    for source in (raw, code):
        blob = _extract_first_json_blob(source)
        if blob and blob not in candidates:
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
    raise ValueError(f'Cannot parse JSON from text: {raw[:200]}')
