"""OptiMUS output parsing, adapted from upstream utils.py, objective.py, constraint_model.py and execute_code.py."""

import json
import re
import textwrap
from typing import Any

import json_repair

from llm4om.methods.common import split_formulation_and_code

# ---- upstream utils.py ----

def _fences(text: str) -> str:
    """llm4om: read a run of five or more "=" as one "=====" fence. Upstream finds the closing fence inside a longer
    opening run (e.g. "=======") and extracts nothing; DeepSeek writes such runs."""
    return re.sub(r"={5,}", "=====", text)


def _norm_key(key: str) -> str:
    return re.sub(r"[\s_-]+", "", key.strip().lower())


def _find_balanced_end(text: str, start: int, opener: str, closer: str) -> int | None:
    """Return index right after the matching closer for `text[start] == opener`, respecting JSON strings."""
    depth = 0
    in_string = False
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return None


def extract_json_from_end(text: str, kind: type = dict) -> Any:
    """llm4om: decode the last top-level JSON container; strip outside-string // comments, with json_repair fallback."""
    text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\r\n]*',
                  lambda match: "" if match[0].startswith("//") else match[0], text)
    opener, closer = ("{", "}") if kind is dict else ("[", "]")
    decoder = json.JSONDecoder()
    end, result = 0, None
    while (start := text.find(opener, end)) >= 0:
        span_end = _find_balanced_end(text, start, opener, closer)
        if span_end is not None:
            candidate = text[start:span_end]
            try:
                value = json.loads(candidate)
            except json.JSONDecodeError:
                value = None
                try:
                    repaired = json_repair.loads(candidate)
                except Exception:
                    repaired = None
                if isinstance(repaired, kind):
                    value = repaired
            if isinstance(value, kind):
                result, end = value, span_end
                continue
        end = start + 1
        try:
            value, length = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, kind):
            result, end = value, start + length
    if result is not None:
        return result
    raise ValueError(f"No JSON {kind.__name__} found in the reply.")


def shape_string_to_list(shape_string: Any) -> list[Any]:
    if shape_string is None:
        return []
    if isinstance(shape_string, list):
        return [int(x) if isinstance(x, str) and x.strip().isdigit() else x.strip().strip("'\"") if isinstance(x, str) else x
                for x in shape_string if x not in ("", None)]
    if isinstance(shape_string, int):
        return [shape_string]
    text = str(shape_string).strip()
    if not text:
        return []
    if (text.startswith("[") and text.endswith("]")) or (text.startswith("(") and text.endswith(")")):
        text = text[1:-1].strip()
    if not text:
        return []
    shape_list = []
    for raw in text.split(","):
        item = raw.strip().strip("'\"")
        if not item:
            continue
        shape_list.append(int(item) if item.isdigit() else item)
    return shape_list


def extract_equal_sign_closed(text: str) -> str:
    text = _fences(text)
    pairs = re.findall(r"=====(.*?)=====", text, re.S)
    if pairs:
        return textwrap.dedent(pairs[-1].strip("\r\n")).strip()
    # llm4om: accept a complete fenced block when the model substitutes Markdown fences for =====.
    blocks = re.findall(r"```[A-Za-z0-9_+-]*[ \t]*\r?\n(.*?)```", text, re.S)
    if blocks:
        return textwrap.dedent(blocks[-1].strip("\r\n")).strip()
    raise ValueError("The reply needs opening and closing ===== fences.")


# ---- upstream objective.py, constraint_model.py, target_code.py, execute_code.py ----

def extract_objective(text: str) -> str:
    try:
        raw = extract_equal_sign_closed(text)
    except ValueError:
        # llm4om: accept an explicit OBJECTIVE: line when the model omits ===== fences.
        matches = re.findall(r"^\s*OBJECTIVE\s*:\s*(.+)$", text, re.I | re.M)
        if not matches:
            raise ValueError("The reply needs opening and closing ===== fences or an OBJECTIVE: line.") from None
        raw = matches[-1].strip()
    cleaned = re.sub(r"^OBJECTIVE\s*:\s*", "", raw.strip(), flags=re.I).strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in ('"', "'"):
        cleaned = cleaned[1:-1].strip()
    if not cleaned:
        raise ValueError("The extracted objective description is empty.")
    return cleaned


def extract_objective_formulation(text: str) -> str:
    """llm4om: extract objective LaTeX from ===== fences, or fall back to closed math delimiters."""
    try:
        found = extract_equal_sign_closed(text)
        if found:
            return found
    except ValueError:
        pass
    for pattern in (r"\$\$(.+?)\$\$", r"\\\[(.+?)\\\]", r"\$([^$\r\n]+)\$"):
        matches = re.findall(pattern, text, re.S)
        if matches and matches[-1].strip():
            expr = matches[-1].strip()
            return f"$${expr}$$" if pattern.startswith((r"\$\$", r"\\\[")) else f"${expr}$"
    raise ValueError("The reply needs opening and closing ===== fences or a LaTeX objective expression.")


def _extract_formulation_fields(obj: dict[str, Any], *, fallback_formulation: str | None = None,
                                fallback_aux: list[str] | None = None) -> tuple[str, dict[str, Any], list[str]]:
    by_norm = {_norm_key(str(k)): v for k, v in obj.items()}
    formulation = fallback_formulation if fallback_formulation is not None else by_norm.get("formulation")
    if not isinstance(formulation, str) or not formulation.strip():
        raise ValueError("Missing non-empty FORMULATION field in constraint model JSON.")
    raw_vars = by_norm.get("newvariables")
    if raw_vars is None:
        raw_vars = {}
    if not isinstance(raw_vars, dict):
        raise ValueError("NEW VARIABLES must be a JSON object mapping variable symbols to metadata.")
    if fallback_aux is not None:
        auxiliaries = list(fallback_aux)
    else:
        raw_aux = by_norm.get("auxiliaryconstraints")
        if raw_aux is None:
            auxiliaries = []
        elif isinstance(raw_aux, str):
            auxiliaries = [raw_aux.strip()] if raw_aux.strip() else []
        elif isinstance(raw_aux, list):
            auxiliaries = [str(item).strip() for item in raw_aux if isinstance(item, str) and item.strip()]
        else:
            raise ValueError("AUXILIARY CONSTRAINTS must be a JSON list of strings.")
    auxiliaries = [a for a in auxiliaries if len(a) > 5]
    return formulation.strip(), raw_vars, auxiliaries


def extract_formulation_from_end(text: str) -> tuple[str, dict[str, Any], list[str]]:
    # Primary upstream path: strip LaTeX $...$ expressions before JSON decoding so raw backslashes do not break json.
    ind_1 = text.rfind('"FORMULATION":')
    ind_2 = text.rfind("NEW VARIABLES")
    if ind_1 >= 0 and ind_2 > ind_1 and "$" in text[ind_1:ind_2]:
        left, right = ind_1, ind_2
        while left < right and text[left] != "$":
            left += 1
        while right > left and text[right] != "$":
            right -= 1
        if left < right and text[left] == "$" and text[right] == "$":
            formulation = text[left: right + 1].strip()
            stripped = text[:left] + text[right + 1:]
            auxiliaries: list[str] = []
            aux_key = stripped.rfind('"AUXILIARY CONSTRAINTS":')
            if aux_key >= 0:
                a1 = aux_key
                while a1 < len(stripped) and stripped[a1] != "$":
                    a1 += 1
                while a1 < len(stripped) - 1 and stripped[a1] == "$":
                    a2 = a1 + 1
                    while a2 + 2 < len(stripped) and stripped[a2: a2 + 2] != '$"':
                        a2 += 1
                    if a2 >= len(stripped) or stripped[a2] != "$":
                        break
                    auxiliaries.append(stripped[a1: a2 + 1].strip())
                    stripped = stripped[:a1] + stripped[a2 + 1:]
                    while a1 < len(stripped) - 1 and stripped[a1] != "$":
                        a1 += 1
                    if a1 >= len(stripped) - 1 or stripped[a1] != "$":
                        break
            try:
                json_res = extract_json_from_end(stripped, dict)
                return _extract_formulation_fields(
                    json_res, fallback_formulation=formulation, fallback_aux=auxiliaries,
                )
            except ValueError:
                pass
    # llm4om: fallback for missing $ delimiters, alternate key casing, omitted optional keys, or unescaped LaTeX.
    json_res = extract_json_from_end(text, dict)
    return _extract_formulation_fields(json_res)


def extract_code_from_end(text: str) -> str:
    """llm4om: without "=====" fences, take the last Python block. Upstream takes the first; models that answer
    in Markdown often show a fragment first and the full statement last (a bare objective, then setObjective)."""
    text = _fences(text)
    if text.count("=====") >= 2:
        code = extract_equal_sign_closed(text)
    else:
        _, code = split_formulation_and_code(text)
    if "```" in code:
        fenced = re.search(r"```(?:python3?|py)?[ \t]*\r?\n(.*?)```", code, re.S | re.I)
        code = fenced.group(1) if fenced else re.sub(r"```(?:python3?|py)?", "", code, flags=re.I)
    if code.startswith("====="):
        code = code[len("====="):]
    if code.endswith("====="):
        code = code[:-len("=====")]
    # llm4om: strip only the fence's language label, not identifiers or string contents.
    code = re.sub(r"^(?:python3?|py)[ \t]*\r?\n", "", code.lstrip("\r\n"), flags=re.I)
    return textwrap.dedent(code.strip("\r\n")).strip()
