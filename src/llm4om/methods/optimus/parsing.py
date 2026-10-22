"""OptiMUS output parsing, adapted from upstream utils.py, objective.py, constraint_model.py and execute_code.py."""

import json
import re
from typing import Any

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
    if isinstance(shape_string, list):
        return shape_string
    shape_string = shape_string.strip()
    shape_string = shape_string[1:-1]
    shape_list = [x.strip() for x in shape_string.split(",")]
    shape_list = [int(x) if x.isdigit() else x for x in shape_list]
    if len(shape_list) == 1 and shape_list[0] == "":
        shape_list = []
    return shape_list


def extract_equal_sign_closed(text: str) -> str:
    text = _fences(text)
    ind_1 = text.find("=====")
    ind_2 = text.find("=====", ind_1 + 1)
    return text[ind_1 + 6: ind_2].strip()


# ---- upstream objective.py, constraint_model.py, target_code.py, execute_code.py ----

def extract_objective(text: str) -> str:
    text = _fences(text)
    ind_1 = text.find("=====")
    ind_2 = text.find("=====", ind_1 + 1)
    objective = text[ind_1:ind_2]
    objective = objective.replace("=====", "").strip()
    return objective.replace("OBJECTIVE:", "").strip()


def extract_formulation_from_end(text: str) -> tuple[str, dict[str, Any], list[str]]:
    ind_1 = text.find('"FORMULATION":')
    iloop = 0
    iloop_max = 1e05
    if "$" not in text:
        raise Exception("No formulation found")
    while text[ind_1] != "$":
        ind_1 += 1
        iloop += 1
        if iloop > iloop_max:
            raise Exception("No formulation found")
    ind_2 = text.find("NEW VARIABLES")
    while text[ind_2] != "$":
        ind_2 -= 1
        iloop += 1
        if iloop > iloop_max:
            raise Exception("No formulation found")
    formulation = text[ind_1: ind_2 + 1].strip()
    text = text[:ind_1] + text[ind_2 + 1:]
    ind_1 = text.find('"AUXILIARY CONSTRAINTS":')
    while text[ind_1] != "$":
        ind_1 += 1
        if ind_1 > len(text) - 1:
            break
        iloop += 1
        if iloop > iloop_max:
            raise Exception("No formulation found")
    auxiliaries = []
    if ind_1 < len(text) - 1:
        while True:
            ind_2 = ind_1 + 1
            while ind_2 + 2 < len(text) and text[ind_2: ind_2 + 2] != '$"':
                ind_2 += 1
                iloop += 1
                if iloop > iloop_max:
                    break
            auxiliaries.append(text[ind_1: ind_2 + 1].strip())
            text = text[:ind_1] + text[ind_2 + 1:]
            while ind_1 < len(text) - 1 and text[ind_1] != "$":
                ind_1 += 1
                if ind_1 > len(text) - 1:
                    break
                iloop += 1
                if iloop > iloop_max:
                    break
            if ind_1 > len(text) - 1:
                break
    json_res = extract_json_from_end(text)
    auxiliaries = [a for a in auxiliaries if len(a) > 5]
    json_res["FORMULATION"] = formulation
    json_res["AUXILIARY CONSTRAINTS"] = auxiliaries
    return json_res["FORMULATION"], json_res["NEW VARIABLES"], json_res["AUXILIARY CONSTRAINTS"]


def extract_code_from_end(text: str) -> str:
    """llm4om: without "=====" fences, take the last ```python block. Upstream takes the first; models that answer
    in Markdown often show a fragment first and the full statement last (a bare objective, then setObjective)."""
    text = _fences(text)
    if "=====" in text:
        ind_1 = text.find("=====")
        ind_2 = text.find("=====", ind_1 + 1)
        code = text[ind_1 + len("====="): ind_2].strip()
    else:
        ind_1 = text.rfind("```python")
        ind_2 = text.find("```", ind_1 + 1)
        code = text[ind_1 + len("```"): ind_2].strip()
    if "```" in code:
        code = code.replace("```python", "").replace("```", "").strip()
    if code.startswith("====="):
        code = code[len("====="):].strip()
    if code.endswith("====="):
        code = code[: -len("=====")].strip()
    if "python" in code:
        code = code.replace("python", "").strip()
    return code


def extract_debugged_code(text: str) -> str:
    """execute_code.extract_code."""
    text = _fences(text)
    ind_1 = text.find("=====")
    ind_2 = text.find("=====", ind_1 + 1)
    code = text[ind_1 + 5: ind_2].strip()
    return code.replace("```python", "").replace("```", "").strip()
