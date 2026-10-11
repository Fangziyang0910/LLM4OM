"""Bounded public clarification requests and responses with explicit semantics."""

from copy import deepcopy
import hashlib
import json
from typing import Any

import jsonschema

from llm4om.contracts import RunError


def prepare_clarification(value: dict[str, Any], public: dict[str, Any], run_id: str,
                          problem_sha256: str, *, sequence_no: int = 1) -> dict[str, Any]:
    text = {"type": "string", "minLength": 1, "maxLength": 4096}
    identifier = {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,80}$"}
    ref = {"type": "object", "additionalProperties": False,
        "properties": {"kind": {"enum": ["requirement", "assumption"]}, "id": text}, "required": ["kind", "id"]}
    question = {"type": "object", "additionalProperties": False,
        "properties": {"question_id": identifier, "kind": {"enum": ["confirm_existing", "new_information"]},
            "question": text, "statement_ref": {"anyOf": [ref, {"type": "null"}]}},
        "required": ["question_id", "kind", "question", "statement_ref"]}
    schema = {"type": "object", "additionalProperties": False,
        "properties": {"questions": {"type": "array", "minItems": 1, "maxItems": 8, "items": question},
            "provenance": {"type": "object"}}, "required": ["questions"]}
    try:
        jsonschema.Draft202012Validator(schema).validate(value)
    except jsonschema.ValidationError as error:
        raise RunError("invalid_clarification", "formulation", "Invalid bounded clarification request.") from error
    if len(json.dumps(value, allow_nan=False).encode()) > 65536:
        raise RunError("invalid_clarification", "formulation", "Clarification metadata exceeds its byte limit.")
    questions = deepcopy(value["questions"])
    if len({q["question_id"] for q in questions}) != len(questions):
        raise RunError("invalid_clarification", "formulation", "Clarification question IDs must be unique.")
    for q in questions:
        anchor = q["statement_ref"]
        if q["kind"] == "new_information":
            if anchor is not None:
                raise RunError("invalid_clarification", "formulation", "New information cannot masquerade as an existing statement.")
            q["statement"] = None
            continue
        if anchor is None:
            raise RunError("invalid_clarification", "formulation", "Confirmation needs an existing public statement.")
        statements = public["requirements" if anchor["kind"] == "requirement" else "assumptions"]
        source = next((s for s in statements if s["id"] == anchor["id"]), None)
        if source is None:
            raise RunError("invalid_clarification", "formulation", "Confirmation anchor is absent from the original public input.")
        q["statement"] = source["text"]
    identity = json.dumps({"run_id": run_id, "problem_sha256": problem_sha256, "request": value,
                           "sequence_no": sequence_no}, sort_keys=True, allow_nan=False).encode()
    return {"schema_version": "0.1.0", "request_id": hashlib.sha256(identity).hexdigest()[:32], "run_id": run_id,
        "sequence_no": sequence_no,
        "problem_id": public["problem_id"], "problem_revision": public["revision"],
        "problem_sha256": problem_sha256, "questions": questions, "provenance": value.get("provenance", {})}


def validate_clarification_response(value: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    answer = {"type": "object", "additionalProperties": False,
        "properties": {"question_id": {"type": "string"}, "value": {"type": ["boolean", "string"]}},
        "required": ["question_id", "value"]}
    schema = {"type": "object", "additionalProperties": False,
        "properties": {"schema_version": {"const": "0.1.0"}, "request_id": {"const": request["request_id"]},
            "action": {"enum": ["confirm", "revise"]}, "answers": {"type": "array", "minItems": 1, "maxItems": 8, "items": answer}},
        "required": ["schema_version", "request_id", "action", "answers"]}
    try:
        jsonschema.Draft202012Validator(schema).validate(value)
    except jsonschema.ValidationError as error:
        raise RunError("invalid_clarification_response", "admission", "Response differs from the saved clarification request.") from error
    answers = {a["question_id"]: a for a in value["answers"]}
    if len(answers) != len(value["answers"]) or set(answers) != {q["question_id"] for q in request["questions"]}:
        raise RunError("invalid_clarification_response", "admission", "Every question needs exactly one bound answer.")
    if any(isinstance(a["value"], str) and (not a["value"].strip() or len(a["value"]) > 4096) for a in answers.values()):
        raise RunError("invalid_clarification_response", "admission", "New information must be bounded nonempty public text.")
    if value["action"] == "confirm" and any(q["kind"] != "confirm_existing" or answers[q["question_id"]]["value"] is not True
                                            for q in request["questions"]):
        raise RunError("problem_revision_required", "admission", "New information or rejection of an existing statement needs an explicit problem revision.")
    result = deepcopy(value)
    result["answers"] = [deepcopy(answers[q["question_id"]]) for q in request["questions"]]
    return result
