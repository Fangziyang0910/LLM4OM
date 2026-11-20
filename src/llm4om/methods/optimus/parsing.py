"""OptiMUS output parsing, adapted from upstream utils.py, objective.py, constraint_model.py and execute_code.py."""

import json
import re
import textwrap
from typing import Any

from llm4om.methods.common import split_formulation_and_code

# ---- upstream utils.py ----

def _fences(text: str) -> str:
    """llm4om: read a run of five or more "=" as one "=====" fence. Upstream finds the closing fence inside a longer
    opening run (e.g. "=======") and extracts nothing; DeepSeek writes such runs."""
    return re.sub(r"={5,}", "=====", text)


def extract_json_from_end(text: str, kind: type = dict) -> Any:
    """llm4om: decode the last JSON container; strip line comments only outside strings."""
    text = re.sub(r'"(?:\\.|[^"\\])*"|//[^\r\n]*',
                  lambda match: "" if match[0].startswith("//") else match[0], text)
    decoder = json.JSONDecoder()
    end, result = 0, None
    while (start := text.find("{" if kind is dict else "[", end)) >= 0:
        end = start + 1
        try:
            value, length = decoder.raw_decode(text[start:])
        except json.JSONDecodeError:
            continue
        result, end = value, start + length
    if result is None:
        raise ValueError(f"No JSON {kind.__name__} found in the reply.")
    return result


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
    if not pairs:
        raise ValueError("The reply needs opening and closing ===== fences.")
    return textwrap.dedent(pairs[-1].strip("\r\n")).strip()


# ---- upstream objective.py, constraint_model.py, target_code.py, execute_code.py ----

def extract_objective(text: str) -> str:
    return extract_equal_sign_closed(text).removeprefix("OBJECTIVE:").strip()


def extract_formulation_from_end(text: str) -> tuple[str, dict[str, Any], list[str]]:
    ind_1 = text.rfind('"FORMULATION":')
    if ind_1 < 0 or "$" not in text[ind_1:]:
        raise Exception("No formulation found")
    ind_2 = text.rfind("NEW VARIABLES")
    if ind_2 < ind_1:
        raise Exception("No formulation found")
    while ind_1 < ind_2 and text[ind_1] != "$":
        ind_1 += 1
    if ind_1 >= ind_2 or text[ind_1] != "$":
        raise Exception("No formulation found")
    while ind_2 > ind_1 and text[ind_2] != "$":
        ind_2 -= 1
    if ind_2 <= ind_1 or text[ind_2] != "$":
        raise Exception("No formulation found")
    formulation = text[ind_1: ind_2 + 1].strip()
    text = text[:ind_1] + text[ind_2 + 1:]
    auxiliaries = []
    aux_key = text.rfind('"AUXILIARY CONSTRAINTS":')
    if aux_key >= 0:
        ind_1 = aux_key
        while ind_1 < len(text) and text[ind_1] != "$":
            ind_1 += 1
        while ind_1 < len(text) - 1 and text[ind_1] == "$":
            ind_2 = ind_1 + 1
            while ind_2 + 2 < len(text) and text[ind_2: ind_2 + 2] != '$"':
                ind_2 += 1
            if ind_2 >= len(text) or text[ind_2] != "$":
                break
            auxiliaries.append(text[ind_1: ind_2 + 1].strip())
            text = text[:ind_1] + text[ind_2 + 1:]
            while ind_1 < len(text) - 1 and text[ind_1] != "$":
                ind_1 += 1
            if ind_1 >= len(text) - 1 or text[ind_1] != "$":
                break
    json_res = extract_json_from_end(text)
    auxiliaries = [a for a in auxiliaries if len(a) > 5]
    json_res["FORMULATION"] = formulation
    json_res["AUXILIARY CONSTRAINTS"] = auxiliaries
    return json_res["FORMULATION"], json_res["NEW VARIABLES"], json_res["AUXILIARY CONSTRAINTS"]


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


def extract_debugged_code(text: str) -> str:
    """execute_code.extract_code."""
    return extract_code_from_end(text)
