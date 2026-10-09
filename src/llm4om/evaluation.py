"""Post-run evidence for raw NL4Opt; declarations are not independent optima."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable

from llm4om.contracts import RunError, parse_json, parse_reference_json, public_path
from llm4om.tasks import EvaluationCase, Evaluator, TaskAdapter, PROTOCOL


def _verify_ref(root: Path, ref: dict[str, Any]) -> bytes:
    raw = public_path(root, ref["relative_path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != ref["sha256"] or len(raw) != ref["size_bytes"]:
        raise RunError("evidence_hash_mismatch", "evaluation", "Evidence bytes differ from their frozen reference.")
    return raw


def _read_ref(root: Path, ref: dict[str, Any]) -> dict[str, Any]:
    return parse_json(_verify_ref(root, ref))


class NL4OptEvaluator:
    def evaluate(self, case: EvaluationCase, outcome: Path) -> dict[str, Any]:
        """Consume one frozen case and actual persisted application outcome."""
        manifest = parse_reference_json(case.manifest)
        entry = parse_reference_json(case.entry)
        if (manifest.get("protocol_id") != PROTOCOL or manifest.get("N_eligible") != 0
                or entry not in manifest["cases"] or entry["case_id"] != case.case_id):
            raise RunError("invalid_case", "evaluation", "Case must belong to the frozen raw NL4Opt protocol.")
        unavailable = {"status": "not_available", "reason": "Raw declarations lack independent domains, solution and optimum evidence."}
        result: dict[str, Any] = {
            "schema_version": "0.1.0", "protocol_id": PROTOCOL, "case_id": case.case_id,
            "manifest_sha256": hashlib.sha256(case.manifest).hexdigest(), "source": manifest["source"],
            "projection_revision": manifest["projection_revision"], "domain_policy": manifest["domain_policy"],
            "normalization_policy": manifest["normalization_policy"], "raw_record_sha256": entry["raw_record_sha256"],
            "reference_quality": entry["reference_quality"], "eligible": False,
            "exclusion_reason": entry["exclusion_reason"], "N_selected": manifest["N_selected"], "N_eligible": 0,
            "N_evaluated": 1, "objective_match_rate": None,
            "independent_feasibility": dict(unavailable), "objective_match": dict(unavailable),
            "semantic_validation": dict(unavailable),
            "formulation_validation": {"status": "not_available"}, "code_validation": {"status": "not_available"},
            "execution": {"status": "not_available"}, "candidate_primal": {"status": "not_available"},
            "case_binding": {"status": "not_available"}, "run_id": None, "run_status": "unknown", "run_error": None, "checker_error": None,
        }
        return evaluate_outcome(case, outcome, result)


def evaluate_outcome(case: EvaluationCase, outcome: Path, result: dict[str, Any],
                      reference_check: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Verify frozen material and actual outcome before privileged scoring."""
    entry = parse_reference_json(case.entry)
    try:
        bundle = parse_json((outcome / "bundle.json").read_bytes())
        if bundle.get("schema_version") != "0.2.0" or bundle.get("status") not in {"failed", "cancelled", "completed", "artifact_ready"}:
            raise RunError("invalid_outcome", "evaluation", "Unsupported application outcome schema or status.")
        result.update(run_id=bundle["run_id"], run_status=bundle["status"], run_error=bundle["error"])
        public = _read_ref(case.public_problem.parent.parent, entry["public_ref"])
        if public["problem_id"] != case.case_id:
            raise RunError("case_identity_mismatch", "evaluation", "Public problem differs from the selected case.")
        oracle_raw = case.oracle_ref.read_bytes()
        if (hashlib.sha256(oracle_raw).hexdigest() != entry["oracle_ref"]["sha256"]
                or len(oracle_raw) != entry["oracle_ref"]["size_bytes"]):
            raise RunError("snapshot_hash_mismatch", "evaluation", "Private annotations changed after import.")
        for ref in bundle["artifacts"]:
            _verify_ref(outcome, ref)
        for name, ref in bundle.get("public_projections", {}).items():
            _verify_ref(outcome, {**ref, "relative_path": name})
        problems = ([bundle["public_problem_ref"]] if bundle.get("public_problem_ref") else
                    [ref for ref in bundle["artifacts"] if ref["relative_path"] == "public-problem.json"])
        if problems:
            observed = _read_ref(outcome, problems[0])
            expected = deepcopy(public)
            if len(observed["data_refs"]) != len(expected["data_refs"]):
                raise RunError("outcome_case_mismatch", "evaluation", "Public data references differ from the frozen case.")
            for original, bound in zip(expected["data_refs"], observed["data_refs"]):
                source_data = public_path(case.public_problem.parent, original["path"]).read_bytes()
                run_data = public_path(outcome, bound["path"]).read_bytes()
                if (source_data != run_data or hashlib.sha256(source_data).hexdigest() != original["sha256"]
                        or {key: value for key, value in original.items() if key != "path"} !=
                           {key: value for key, value in bound.items() if key != "path"}):
                    raise RunError("outcome_case_mismatch", "evaluation", "Run data do not match exact frozen public bytes and schema.")
                original["path"] = bound["path"]
            if observed != expected:
                raise RunError("outcome_case_mismatch", "evaluation", "Run belongs to another public problem revision.")
            result["case_binding"] = {"status": "pass"}
        elif bundle["status"] not in {"failed", "cancelled"}:
            raise RunError("outcome_case_mismatch", "evaluation", "Successful run must identify its public problem.")
        for stage, field in (("formulation", "formulation_validation"), ("code", "code_validation")):
            if bundle["stages"][stage]["status"] == "available":
                level = "structural"
                if stage == "code":
                    artifact = _read_ref(outcome, bundle["model_artifact_ref"])
                    code = _read_ref(outcome, artifact["code_ref"])
                    origin = code["provenance"]["origin"]
                    if origin == "deterministic_compilation":
                        level = "deterministic_compilation"
                    elif origin == "method_generated" and code.get("factory_contract") in ("python_factory/0.1.0", "native_gurobipy/0.1.0"):
                        level = "factory_contract"
                    elif origin == "method_generated" and code.get("factory_contract") == "native_script/0.1.0":
                        level = "native_script_contract"
                    else:
                        raise RunError("invalid_code_evidence", "evaluation", "Code origin is not supported by this evaluator.")
                result[field] = {"status": "pass", "level": level}
        if bundle["execution_result_ref"]:
            execution = _read_ref(outcome, bundle["execution_result_ref"])
            result["execution"] = {"status": execution["status"], "mode": execution["mode"]}
        if bundle["solve_result_ref"]:
            solve = _read_ref(outcome, bundle["solve_result_ref"])
            result["candidate_primal"] = {
                "status": "available" if solve["has_primal_solution"] else "not_available",
                "level": "solver_reported_candidate_feasibility", "termination": solve["termination"],
                "has_primal_solution": solve["has_primal_solution"], "reported_objective": solve["objective_value"]}
        if reference_check is not None:
            reference_check(parse_reference_json(oracle_raw), public, result)
    except (OSError, ValueError, KeyError, TypeError, IndexError, ArithmeticError) as error:
        result["checker_error"] = {"code": error.code if isinstance(error, RunError) else "checker_error",
                                   "message": str(error) if isinstance(error, RunError) else "Cannot read valid frozen evaluation evidence."}
        for field in ("formulation_validation", "code_validation", "execution", "candidate_primal"):
            result[field] = {"status": "error"}
    return result


def evaluate_case(manifest: Path, case_id: str, outcome: Path, output: Path) -> dict[str, Any]:
    """Persist one public evaluation result without exporting oracle references."""
    from llm4om.task_plugins import load_registered_case, validate_evaluation_result, _call
    plugin, evaluator, case, identity = load_registered_case(manifest, case_id)
    try:
        result = _call(plugin, lambda: evaluator.evaluate(case, outcome), "evaluation")
    except RunError as error:
        from llm4om.task_plugins import evaluation_error
        result = evaluation_error(case, outcome, plugin, error)
    validate_evaluation_result(result, case, plugin, outcome)
    result["plugin_identity"] = identity
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return result
