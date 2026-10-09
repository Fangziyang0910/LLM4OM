"""Public mathematical reviews shared by the two supplied-reference tasks."""

from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from typing import Any

import jsonschema

ROUNDING_SCHEMA = {"oneOf": [
    {"type": "object", "additionalProperties": False, "required": ["kind", "decimal_places"],
     "properties": {"kind": {"const": "none"}, "decimal_places": {"type": "null"}}},
    {"type": "object", "additionalProperties": False, "required": ["kind", "decimal_places"],
     "properties": {"kind": {"const": "decimal_half_away_from_zero"},
                    "decimal_places": {"type": "integer", "minimum": 0, "maximum": 12}}}]}
BASE_REVIEW_SCHEMA: dict[str, Any] = {"type": "object", "additionalProperties": False, "required": [
    "subset", "sample_id", "question_sha256", "classification", "domain_policy", "rounding_policy",
    "evidence", "reviewer", "reason"], "properties": {
    "subset": {"enum": ["easy_lp", "complex_lp"]},
    "sample_id": {"type": "string", "pattern": "^[1-9][0-9]*$"},
    "question_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
    "classification": {"enum": ["lp", "milp", "unsupported", "unresolved"]},
    "domain_policy": {"type": ["null", "string"]},
    "rounding_policy": {"anyOf": [ROUNDING_SCHEMA, {"type": "null"}]},
    "evidence": {"type": "array", "minItems": 1, "items": {
        "type": "object", "additionalProperties": False, "required": ["aspect", "start", "end", "text"],
        "properties": {"aspect": {"enum": ["problem_type", "variable_domains", "rounding"]},
                       "start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1},
                       "text": {"type": "string", "minLength": 1}}}},
    "reviewer": {"type": "string", "minLength": 1}, "reason": {"type": ["null", "string"]}}}


def review_schema(subsets: tuple[str, ...], *, with_data: bool = False) -> dict[str, Any]:
    schema = deepcopy(BASE_REVIEW_SCHEMA)
    schema["properties"]["subset"] = {"enum": list(subsets)}
    if with_data:
        schema["required"] += ["data_sha256", "data_binding_policy"]
        schema["properties"]["data_sha256"] = {"type": "string", "pattern": "^[a-f0-9]{64}$"}
        schema["properties"]["data_binding_policy"] = {"type": ["null", "string"]}
        schema["properties"]["evidence"]["items"]["properties"]["aspect"]["enum"].append("data_binding")
    return schema


def _review_shape(review: dict[str, Any], subsets: tuple[str, ...] = ("easy_lp", "complex_lp"), *, with_data: bool = False) -> None:
    jsonschema.Draft202012Validator(review_schema(subsets, with_data=with_data)).validate(review)
    if review["classification"] in ("lp", "milp"):
        if (not isinstance(review["domain_policy"], str) or not review["domain_policy"].strip()
                or review["rounding_policy"] is None or review["reason"] is not None
                or {span["aspect"] for span in review["evidence"]} != ({"problem_type", "variable_domains", "rounding", "data_binding"} if with_data else {"problem_type", "variable_domains", "rounding"})):
            raise ValueError("Supported review needs explicit domains, rounding and all public evidence aspects.")
        if with_data and (not isinstance(review["data_binding_policy"], str) or not review["data_binding_policy"].strip()):
            raise ValueError("Supported data review needs explicit public bindings.")
    elif not isinstance(review["reason"], str) or not review["reason"].strip():
        raise ValueError("Unsupported/unresolved review requires a reason.")


def _review_policy(review: dict[str, Any], question: str, subsets: tuple[str, ...] = ("easy_lp", "complex_lp"), *, data_sha256: str | None = None) -> None:
    _review_shape(review, subsets, with_data=data_sha256 is not None)
    if data_sha256 is not None and review["data_sha256"] != data_sha256:
        raise ValueError("Review belongs to different public parameter bytes.")
    if review["question_sha256"] != hashlib.sha256(question.encode()).hexdigest():
        raise ValueError("Review belongs to another public question.")
    for span in review["evidence"]:
        if not 0 <= span["start"] < span["end"] <= len(question) or question[span["start"]:span["end"]] != span["text"]:
            raise ValueError("Review evidence is not an exact public question span.")


def supplied_numeric_match(candidate: float, reference: int | float | str,
                           rounding: dict[str, Any], tolerance: dict[str, Any]) -> bool:
    """Normalize the candidate only, then apply the frozen absolute/relative rule."""
    predicted, supplied = Decimal(str(candidate)), Decimal(str(reference))
    if rounding["kind"] == "decimal_half_away_from_zero":
        predicted = predicted.quantize(Decimal(1).scaleb(-rounding["decimal_places"]), rounding=ROUND_HALF_UP)
    return abs(predicted - supplied) <= Decimal(str(tolerance["abs_tol"])) + Decimal(str(tolerance["rel_tol"])) * abs(supplied)
