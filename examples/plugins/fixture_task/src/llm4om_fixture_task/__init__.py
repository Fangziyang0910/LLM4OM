"""Independent micro-task projection and supplied-number post-run evaluation."""

import hashlib
import json
from pathlib import Path
from typing import Any, Iterator

from llm4om.contracts import RunError, parse_reference_json, public_path, validate_problem
from llm4om.tasks import EvaluationCase, FrozenTaskAdapter
from llm4om.evaluation import evaluate_outcome

PROTOCOL = "llm4om.examples.fixture-numeric-v0.1"
TASK_ID = "llm4om.examples.micro_task"
EVALUATOR_ID = "llm4om.examples.micro_evaluator"


def _reference(path: str, raw: bytes, namespace: str) -> dict[str, Any]:
    return {"relative_path": path, "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw),
            "namespace": namespace, "schema_version": "0.1.0"}


class FixtureTask(FrozenTaskAdapter):
    def __init__(self, dataset_id: str) -> None:
        self.dataset_id = dataset_id

    def import_source(self, config: Path, output: Path, settings: dict[str, Any]) -> Path:
        problem_path = public_path(config.parent, settings["problem_path"])
        raw = problem_path.read_bytes()
        private_raw = public_path(config.parent, settings["reference_path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != settings["problem_sha256"] or hashlib.sha256(private_raw).hexdigest() != settings["reference_sha256"]:
            raise RunError("source_hash_mismatch", "import", "Fixture source bytes changed.")
        problem = parse_reference_json(raw)
        validate_problem(problem)
        parse_reference_json(private_raw)
        output.mkdir(mode=0o700)
        (output / "public").mkdir()
        (output / "private").mkdir(mode=0o700)
        (output / "public/problem.json").write_bytes(raw)
        (output / "private/reference.json").write_bytes(private_raw)
        (output / "private/reference.json").chmod(0o600)
        for data in problem["data_refs"]:
            target = public_path(output / "public", data["path"], require_file=False)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(public_path(problem_path.parent, data["path"]).read_bytes())
        entry = {"case_id": problem["problem_id"], "sample_id": problem["problem_id"], "selected": True,
            "eligible": True, "exclusion_reason": None, "reference_quality": "supplied_numeric_answer",
            "public_ref": _reference("public/problem.json", raw, "task_public"),
            "oracle_ref": _reference("private/reference.json", private_raw, "task_private")}
        manifest = {"schema_version": "0.2.0", "adapter_id": TASK_ID, "protocol_id": PROTOCOL,
            "source": {"dataset_id": self.dataset_id, "source_version": hashlib.sha256(raw).hexdigest(), "source_kind": "fixture"},
            "projection_revision": "original-public-v0.1", "N_selected": 1, "N_eligible": 1, "cases": [entry]}
        path = output / "manifest.json"
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        return path

    def _cases(self, config: Path) -> Iterator[EvaluationCase]:
        raw = config.read_bytes()
        manifest = parse_reference_json(raw)
        if manifest["adapter_id"] != TASK_ID or manifest["protocol_id"] != PROTOCOL:
            raise RunError("invalid_manifest", "evaluation", "This Adapter requires its own frozen protocol.")
        for entry in manifest["cases"]:
            yield EvaluationCase(entry["case_id"], public_path(config.parent, entry["public_ref"]["relative_path"], require_file=False),
                public_path(config.parent, entry["oracle_ref"]["relative_path"], require_file=False), raw,
                json.dumps(entry, ensure_ascii=False).encode())


class FixtureEvaluator:
    def __init__(self, abs_tol: float) -> None:
        self.abs_tol = abs_tol

    def evaluate(self, case: EvaluationCase, outcome: Path) -> dict[str, Any]:
        manifest, entry = parse_reference_json(case.manifest), parse_reference_json(case.entry)
        unavailable = {"status": "not_available"}
        result = {"schema_version": "0.2.0", "protocol_id": PROTOCOL, "case_id": case.case_id,
            "manifest_sha256": hashlib.sha256(case.manifest).hexdigest(), "source": manifest["source"],
            "projection_revision": manifest["projection_revision"], "reference_quality": entry["reference_quality"],
            "eligible": entry["eligible"], "N_selected": manifest["N_selected"], "N_eligible": manifest["N_eligible"], "N_evaluated": 1,
            "objective_match_numerator": 0, "objective_match_denominator": int(entry["eligible"]), "objective_match_rate": 0.0,
            "objective_match": dict(unavailable), "independent_feasibility": dict(unavailable), "semantic_validation": dict(unavailable),
            "formulation_validation": dict(unavailable), "code_validation": dict(unavailable), "execution": dict(unavailable),
            "candidate_primal": dict(unavailable), "case_binding": dict(unavailable), "checker_error": None,
            "run_id": None, "run_status": "unknown", "run_error": None}
        def compare(oracle: dict[str, Any], public: dict[str, Any], observed: dict[str, Any]) -> None:
            primal = observed["candidate_primal"]
            if primal["has_primal_solution"] and entry["eligible"]:
                passed = abs(primal["reported_objective"] - oracle["value"]) <= self.abs_tol
                observed["objective_match"] = {"status": "pass" if passed else "fail", "level": "supplied_numeric_reference_match"}
                observed["objective_match_numerator"] = int(passed)
                observed["objective_match_rate"] = float(passed)
        return evaluate_outcome(case, outcome, result, compare)


class FixtureFactory:
    def __init__(self, kind: str) -> None:
        self.kind = kind

    def describe(self) -> dict[str, Any]:
        task = self.kind == "task_adapter"
        caps = {"problem_types": ["lp", "milp"], "protocol_ids": [PROTOCOL]}
        caps.update({"task_profile": "frozen_task/0.1.0", "oracle_separation": "separate_public_private/0.1.0",
            "default_evaluator_id": EVALUATOR_ID, "input_artifact_kinds": ["task_source"], "output_artifact_kinds": ["evaluation_manifest"]}
            if task else {"evaluator_profile": "frozen_evaluation/0.1.0", "evidence_levels": ["structural", "objective_match"],
                "input_artifact_kinds": ["evaluation_case", "run_bundle"], "output_artifact_kinds": ["evaluation_result"], "oracle_requirements": ["task_private"]})
        return {"schema_version": "0.2.0", "kind": self.kind, "plugin_id": TASK_ID if task else EVALUATOR_ID,
            "plugin_version": "0.1.0", "contract_range": ">=0.2.0,<0.3.0", "display_name": "Independent micro-task fixture",
            "description": "Engineering fixture with separate hidden numeric material; no semantic proof.", "capabilities": caps,
            "config_schema": {"type": "object", "properties": {"dataset_id": {"type": "string", "minLength": 1, "default": "installed-micro"}}
                if task else {"abs_tol": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.000001}}, "additionalProperties": False},
            "dependencies": {"python": []}, "source": {"kind": "engineering_fixture"}}

    def create(self, config: dict[str, Any]) -> FixtureTask | FixtureEvaluator:
        return FixtureTask(config.get("dataset_id", "installed-micro")) if self.kind == "task_adapter" else FixtureEvaluator(config.get("abs_tol", 0.000001))


task_plugin = FixtureFactory("task_adapter")
evaluator_plugin = FixtureFactory("evaluator")
