"""Load the explicit, input-bound Mock method response without execution."""

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm4om.contracts import (
    RunError, parse_json, read_artifact, validate_bindings, validate_formulation, validate_model_artifact,
)


@dataclass(frozen=True)
class MockOutput:
    artifact: dict[str, Any]
    formulation: dict[str, Any]
    structured_ir: dict[str, Any]
    source_sha256: str


def load_mock_output(response: Path, public: dict[str, Any], problem_sha256: str) -> MockOutput:
    raw = response.read_bytes()
    artifact = parse_json(raw)
    validate_model_artifact(artifact)
    validate_bindings(artifact, public)
    if problem_sha256 != artifact["problem_ref"].get("sha256"):
        raise RunError("artifact_problem_mismatch", "formulation", "Mock packet was authored for a different public input.")
    read_artifact(response.parent, artifact["problem_ref"], "0.2.0", "problem_id")
    formulation = read_artifact(response.parent, artifact["formulation_ref"], "0.2.0", "formulation_id")
    validate_formulation(formulation, public)
    ir = read_artifact(response.parent, formulation["structured_ir_ref"], "0.1.0", "model_id")
    validate_bindings(ir, public)
    return MockOutput(artifact, formulation, ir, hashlib.sha256(raw).hexdigest())
