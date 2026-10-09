"""Original micro-task snapshots with privileged independent-checker policy."""

import hashlib
from pathlib import Path
import shutil
import tempfile
from decimal import Decimal
from typing import Any
from collections.abc import Iterator

import jsonschema

from llm4om.checkers import SolutionChecker, load_checker, checked_solution, _validate
from llm4om.contracts import RunError, parse_json, parse_reference_json, public_path, validate_problem, validate_data
from llm4om.storage import RunStore
from llm4om.tasks import _json, _FrozenTaskAdapter, EvaluationCase
from llm4om.evaluation import _evaluate_outcome, _read_ref
from llm4om.task_policy import supplied_numeric_match

PROTOCOL = "llm4om.eval.checker-v0.1"


def _material(value: dict[str, Any]) -> None:
    point = {"type": "object", "minProperties": 1, "additionalProperties": {"type": "number"}}
    points = {"type": "array", "maxItems": 5000, "items": point}
    fields = {"schema_version": {"const": "0.1.0"}, "checker": {"anyOf": [{"type": "null"}, {
        "type": "object", "additionalProperties": False, "required": ["plugin_id", "version", "config"],
        "properties": {"plugin_id": {"type": "string", "minLength": 1}, "version": {"type": "string", "minLength": 1},
            "config": {"type": "object"}}}]}, "decision_mapping": {"type": ["object", "null"]},
        "reported_objective_mapping": {"anyOf": [{"type": "null"}, {"type": "object", "additionalProperties": False,
            "required": ["scale", "offset"], "properties": {"scale": {"type": "number", "exclusiveMinimum": 0}, "offset": {"type": "number"}}}]},
        "reference_objective": {"type": ["object", "null"]}, "probe_points": points,
        "data_perturbations": {"type": "array", "maxItems": 50, "items": {"type": "object", "additionalProperties": False,
            "required": ["id", "replacement_data", "probe_points"], "properties": {"id": {"type": "string", "minLength": 1},
                "replacement_data": {"type": "object", "minProperties": 1, "additionalProperties": {"type": "string", "maxLength": 1000000}},
                "probe_points": points}}}}
    _validate(value, {"type": "object", "additionalProperties": False, "required": list(fields), "properties": fields},
              "invalid_evaluation_material")
    if len(value["probe_points"]) + sum(len(item["probe_points"]) for item in value["data_perturbations"]) > 5000:
        raise RunError("invalid_evaluation_material", "import", "At most 5000 total predeclared probe points are supported.")
    mapping = value["decision_mapping"]
    if mapping is not None and (not isinstance(mapping, dict) or not mapping
            or any(not isinstance(key, str) or not isinstance(item, str) or not key or not item for key, item in mapping.items())
            or len(set(mapping.values())) != len(mapping)):
        raise RunError("invalid_evaluation_material", "import", "Decision mapping must be explicit and one-to-one.")
    all_points = [*value["probe_points"], *[point for group in value["data_perturbations"] for point in group["probe_points"]]]
    if mapping is not None and any(set(point) != set(mapping) for point in all_points):
        raise RunError("invalid_evaluation_material", "import", "Every probe must provide all predeclared original decisions.")
    reference = value["reference_objective"]
    if reference is not None:
        schema = {"type": "object", "additionalProperties": False, "required": [
            "value", "sense", "quality", "source", "abs_tol", "rel_tol"], "properties": {
            "value": {"type": "number"}, "sense": {"enum": ["min", "max"]},
            "quality": {"enum": ["proven_optimum", "best_known", "feasible"]}, "source": {"type": "string", "minLength": 1},
            "abs_tol": {"type": "number", "minimum": 0}, "rel_tol": {"type": "number", "minimum": 0}}}
        _validate(reference, schema, "invalid_evaluation_material")


def _probe_candidate(ir: dict[str, Any], values: dict[str, int | float]) -> tuple[bool, Decimal]:
    numbers = {key: Decimal(str(value)) for key, value in values.items()}
    feasible = True
    for variable in ir["variables"]:
        value = numbers[variable["id"]]
        if ((variable["lower_bound"] is not None and value < Decimal(str(variable["lower_bound"])) - Decimal("1e-7"))
                or (variable["upper_bound"] is not None and value > Decimal(str(variable["upper_bound"])) + Decimal("1e-7"))
                or (variable["domain"] in ("integer", "binary") and abs(value - value.to_integral_value()) > Decimal("1e-6"))
                or (variable["domain"] == "binary" and (value < Decimal("-1e-7") or value > Decimal("1.0000001")))):
            feasible = False

    def expression(item: dict[str, Any]) -> Decimal:
        return Decimal(str(item["constant"])) + sum((Decimal(str(term["coefficient"])) * numbers[term["variable_id"]]
            for term in item["terms"]), Decimal(0))

    for row in ir["constraints"]:
        residual = expression(row["expression"]) - Decimal(str(row["rhs"]))
        if ((row["sense"] == "le" and residual > Decimal("1e-7"))
                or (row["sense"] == "ge" and residual < Decimal("-1e-7"))
                or (row["sense"] == "eq" and abs(residual) > Decimal("1e-7"))):
            feasible = False
    return feasible, expression(ir["objective"]["expression"])


def _property_checks(checker: SolutionChecker, identity: dict[str, Any], public: dict[str, Any], data: dict[str, bytes],
                     material: dict[str, Any], outcome: Path, bundle: dict[str, Any]) -> dict[str, Any]:
    artifact_ref = bundle.get("model_artifact_ref")
    if artifact_ref is None:
        return {"status": "not_available", "reason": "No inspectable candidate artifact."}
    formulation_ref = _read_ref(outcome, artifact_ref).get("formulation_ref")
    ir_ref = _read_ref(outcome, formulation_ref).get("structured_ir_ref") if formulation_ref else None
    if ir_ref is None:
        return {"status": "not_available", "reason": "No inspectable grounded candidate IR; opaque Code is unsupported."}
    ir = _read_ref(outcome, ir_ref)
    artifact = _read_ref(outcome, artifact_ref)
    code = _read_ref(outcome, artifact["code_ref"])
    if code["provenance"].get("origin") != "deterministic_compilation" or code["provenance"].get("source_ir_ref") != ir_ref:
        return {"status": "not_available", "reason": "Grounded IR is not the verified deterministic Code source."}
    mapping = material["decision_mapping"]
    if set(mapping.values()) != {variable["id"] for variable in ir["variables"]}:
        return {"status": "not_available", "reason": "Complete candidate variable mapping is required; auxiliary values are not guessed."}
    groups = [("original_instance", data, material["probe_points"])]
    for item in material["data_perturbations"]:
        if not set(item["replacement_data"]) <= set(data):
            raise RunError("invalid_evaluation_material", "evaluation", "Perturbation names undeclared public data.")
        changed = {**data, **{key: value.encode("utf-8") for key, value in item["replacement_data"].items()}}
        for ref in public["data_refs"]:
            validate_data(changed[ref["data_id"]], ref)
        groups.append(("fixed_candidate_under_declared_data_perturbation", changed, item["probe_points"]))
    counterexamples, total = [], 0
    for group_index, (scope, changed, points) in enumerate(groups):
        for point_index, point in enumerate(points):
            if set(point) != set(mapping):
                raise RunError("invalid_evaluation_material", "evaluation", "Probe points require all original decisions.")
            original = checked_solution(checker, identity, public, changed, point)
            candidate_feasible, candidate_objective = _probe_candidate(ir, {mapping[key]: number for key, number in point.items()})
            original_feasible = original["independent_feasibility"]["status"] == "pass"
            objective_mapping = material["reported_objective_mapping"]
            if objective_mapping is not None:
                candidate_objective = Decimal(str(objective_mapping["scale"])) * candidate_objective + Decimal(str(objective_mapping["offset"]))
            objective_match = abs(candidate_objective - Decimal(str(original["original_objective"]))) <= Decimal("1e-6") + Decimal("1e-5") * abs(Decimal(str(original["original_objective"])))
            direction_match = ir["objective"]["sense"] == original["objective_sense"]
            if candidate_feasible != original_feasible or candidate_feasible and original_feasible and (not objective_match or not direction_match):
                counterexamples.append({"group_index": group_index, "point_index": point_index, "scope": scope,
                    "candidate_feasible": candidate_feasible, "original_feasible": original_feasible,
                    "objective_match": objective_match, "objective_direction_match": direction_match})
            total += 1
    return {"status": "fail" if counterexamples else "pass" if total else "not_available",
        "level": "finite_predeclared_grounded_instance_probes", "points_evaluated": total,
        "coverage": [scope for scope, _, points in groups if points], "counterexamples": counterexamples,
        "complete_semantic_proof": False, "data_rebinding_tested": False}


def import_checker_fixture(config: Path, output: Path, settings: dict[str, Any]) -> Path:
    """Freeze public inputs independently of hidden checker/reference material."""
    schema = {"type": "object", "additionalProperties": False, "required": [
        "schema_version", "adapter_id", "dataset_id", "source_version", "cases", "selected"], "properties": {
        "schema_version": {"const": "0.2.0"}, "adapter_id": {"const": "llm4om.tasks.checker_fixture"},
        "dataset_id": {"type": "string", "minLength": 1}, "source_version": {"type": "string", "minLength": 1},
        "cases": {"type": "array", "minItems": 1, "items": {"type": "object", "additionalProperties": False,
            "required": ["problem_path", "problem_sha256", "evaluation_path", "evaluation_sha256"], "properties": {
                "problem_path": {"type": "string", "minLength": 1}, "problem_sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "evaluation_path": {"type": ["null", "string"]}, "evaluation_sha256": {"type": ["null", "string"]}}}},
        "selected": {"anyOf": [{"type": "null"}, {"type": "array", "uniqueItems": True, "minItems": 1, "items": {"type": "string"}}]}}}
    try:
        jsonschema.Draft202012Validator(schema).validate(settings)
    except jsonschema.ValidationError as error:
        raise RunError("invalid_task_config", "import", "Invalid checker-fixture import configuration.") from error
    records, seen = [], set()
    for entry in settings["cases"]:
        path = public_path(config.parent, entry["problem_path"])
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["problem_sha256"]:
            raise RunError("source_hash_mismatch", "import", "Public micro-task bytes changed.")
        problem = parse_json(raw)
        validate_problem(problem)
        if problem["problem_id"] in seen:
            raise RunError("duplicate_or_invalid_id", "import", "Micro-task IDs must be unique.")
        seen.add(problem["problem_id"])
        data = []
        for ref in problem["data_refs"]:
            content = public_path(path.parent, ref["path"]).read_bytes()
            if hashlib.sha256(content).hexdigest() != ref["sha256"]:
                raise RunError("source_hash_mismatch", "import", "Public micro-task data changed.")
            validate_data(content, ref)
            data.append(content)
        material: dict[str, Any] = {"schema_version": "0.1.0", "checker": None, "decision_mapping": None,
                    "reported_objective_mapping": None, "reference_objective": None, "probe_points": [], "data_perturbations": []}
        if entry["evaluation_path"] is not None:
            raw = public_path(config.parent, entry["evaluation_path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry["evaluation_sha256"]:
                raise RunError("source_hash_mismatch", "import", "Privileged micro-task material changed.")
            material = parse_reference_json(raw)
        _material(material)
        manifest, availability = None, "not_available"
        if material["checker"] is not None:
            try:
                _, manifest = load_checker(material["checker"])
                availability = "available"
            except RunError as error:
                availability = error.code
        records.append((problem, data, material, manifest, availability))
    selected = set(settings["selected"] if settings["selected"] is not None else seen)
    if not selected <= seen:
        raise RunError("invalid_task_config", "import", "Unknown selected micro-task.")
    if output.exists():
        raise RunError("snapshot_exists", "import", "Frozen snapshots cannot be overwritten.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".checker-", dir=output.parent))
    store: RunStore | None = None
    try:
        store = RunStore(staging, versioned=False)
        private = store.path / "private"
        private.mkdir(mode=0o700)
        entries = []
        for index, (problem, data, material, checker_manifest, availability) in enumerate(records):
            case_id = problem["problem_id"]
            for number, (ref, content) in enumerate(zip(problem["data_refs"], data)):
                name = f"data-{index}-{number}.{ref['format']}"
                store.write("public/" + name, content, ref["data_id"])
                ref["path"] = name
            public_ref = store.json(f"public/{index}.json", problem, case_id)
            public_ref["namespace"] = "task_public"
            oracle = _json(material)
            name = f"private/{index}.json"
            (store.path / name).write_bytes(oracle)
            (store.path / name).chmod(0o600)
            mapping = material["decision_mapping"]
            independent = case_id in selected and availability == "available" and checker_manifest is not None and mapping is not None and set(mapping) == set(checker_manifest["required_decisions"])
            verified = independent and material["reference_objective"] is not None
            entries.append({"case_id": case_id, "sample_id": str(index), "public_ref": public_ref,
                "oracle_ref": {"relative_path": name, "sha256": hashlib.sha256(oracle).hexdigest(), "size_bytes": len(oracle),
                    "namespace": "task_private", "schema_version": "0.1.0"},
                "selected": case_id in selected, "eligible": independent, "verified_eligible": verified,
                "checker_availability": availability, "checker_manifest": checker_manifest,
                "reference_quality": material["reference_objective"]["quality"] if material["reference_objective"] is not None else "not_available"})
        manifest = {"schema_version": "0.2.0", "adapter_id": "llm4om.tasks.checker_fixture", "protocol_id": PROTOCOL,
            "source": {"dataset_id": settings["dataset_id"], "source_version": settings["source_version"], "source_kind": "original_fixture"},
            "projection_revision": "original-public-checker-v0.1", "N_selected": len(selected),
            "N_independent_eligible": sum(entry["eligible"] for entry in entries),
            "N_verified_eligible": sum(entry["verified_eligible"] for entry in entries), "cases": entries}
        store.json("manifest.json", manifest, "manifest")
        saved = store.path
        store.close()
        store = None
        saved.rename(output)
    finally:
        if store is not None:
            store.close()
        shutil.rmtree(staging)
    return output.resolve() / "manifest.json"


class CheckerFixtureAdapter(_FrozenTaskAdapter):
    def _cases(self, config: Path) -> Iterator[EvaluationCase]:
        raw = config.read_bytes()
        manifest = parse_reference_json(raw)
        try:
            if (manifest["schema_version"] != "0.2.0" or manifest["adapter_id"] != "llm4om.tasks.checker_fixture"
                    or manifest["protocol_id"] != PROTOCOL or manifest["projection_revision"] != "original-public-checker-v0.1"
                    or manifest["N_selected"] != sum(entry["selected"] for entry in manifest["cases"])
                    or manifest["N_independent_eligible"] != sum(entry["eligible"] for entry in manifest["cases"])
                    or manifest["N_verified_eligible"] != sum(entry["verified_eligible"] for entry in manifest["cases"])):
                raise ValueError("Invalid independent-checker manifest/counts.")
            seen, cases = set(), []
            for entry in manifest["cases"]:
                if (entry["case_id"] in seen or any(type(entry[key]) is not bool for key in ("selected", "eligible", "verified_eligible"))
                        or entry["eligible"] and (not entry["selected"] or entry["checker_availability"] != "available")
                        or entry["verified_eligible"] and not entry["eligible"]):
                    raise ValueError("Invalid micro-task eligibility.")
                seen.add(entry["case_id"])
                paths = [public_path(config.parent, entry[key]["relative_path"], require_file=False) for key in ("public_ref", "oracle_ref")]
                cases.append(EvaluationCase(entry["case_id"], paths[0], paths[1], raw, _json(entry)))
            yield from cases
        except (KeyError, TypeError, ValueError) as error:
            raise RunError("invalid_manifest", "evaluation", "Unsupported frozen checker fixture.") from error


class IndependentCheckerEvaluator:
    def evaluate(self, case: EvaluationCase, outcome: Path) -> dict[str, Any]:
        """Check original business decisions after outcome/hidden-source binding."""
        manifest, entry = parse_reference_json(case.manifest), parse_reference_json(case.entry)
        if manifest.get("protocol_id") != PROTOCOL or entry not in manifest["cases"] or entry["case_id"] != case.case_id:
            raise RunError("invalid_case", "evaluation", "Case must belong to the independent-checker protocol.")
        unavailable = {"status": "not_available"}
        result: dict[str, Any] = {"schema_version": "0.2.0", "protocol_id": PROTOCOL, "case_id": case.case_id,
            "manifest_sha256": hashlib.sha256(case.manifest).hexdigest(), "source": manifest["source"],
            "projection_revision": manifest["projection_revision"], "reference_quality": entry["reference_quality"],
            "selected": entry["selected"], "eligible": entry["eligible"], "N_selected": manifest["N_selected"],
            "N_eligible": manifest["N_independent_eligible"], "N_evaluated": 1,
            "N_verified_eligible": manifest["N_verified_eligible"], "verified_eligible": entry["verified_eligible"],
            "independent_feasibility": dict(unavailable), "original_objective": None,
            "original_objective_quality": dict(unavailable), "reported_objective_match": dict(unavailable),
            "objective_match": dict(unavailable), "objective_consistency": dict(unavailable),
            "verified_solution": dict(unavailable), "verified_solution_numerator": 0,
            "verified_solution_denominator": int(entry["verified_eligible"]),
            "verified_solution_rate": 0.0 if entry["verified_eligible"] else None,
            "independent_feasibility_numerator": 0, "independent_feasibility_denominator": int(entry["eligible"]),
            "independent_feasibility_rate": 0.0 if entry["eligible"] else None,
            "semantic_validation": {"status": "not_available", "reason": "Solution checks cannot certify complete Formulation equivalence."},
            "property_checks": dict(unavailable), "decision_mapping": dict(unavailable),
            "checker_identity": entry["checker_manifest"], "checker_error": None,
            "formulation_validation": dict(unavailable), "code_validation": dict(unavailable),
            "execution": dict(unavailable), "candidate_primal": dict(unavailable), "case_binding": dict(unavailable),
            "run_id": None, "run_status": "unknown", "run_error": None}

        def check(material: dict[str, Any], public: dict[str, Any], observed: dict[str, Any]) -> None:
            _material(material)
            reference = material["reference_objective"]
            primal = observed["candidate_primal"]
            if reference is not None and primal["status"] == "available":
                match = supplied_numeric_match(primal["reported_objective"], reference["value"], {"kind": "none"}, reference)
                observed["reported_objective_match"] = {"status": "pass" if match else "fail", "level": "candidate_reported_reference_match"}
            if material["checker"] is None:
                observed["independent_feasibility"] = {"status": "not_available", "reason": "No independent checker was supplied."}
                return
            if entry["checker_availability"] != "available":
                observed["independent_feasibility"] = {"status": "not_available", "reason": entry["checker_availability"]}
                return
            try:
                checker, identity = load_checker(material["checker"])
                if identity != entry["checker_manifest"]:
                    raise RunError("checker_identity_changed", "evaluation", "Checker code/version/origin changed after admission.")
                mapping = material["decision_mapping"]
                if mapping is None or set(mapping) != set(identity["required_decisions"]):
                    observed["decision_mapping"] = {"status": "unknown", "reason": "No explicit complete original-decision mapping."}
                    observed["independent_feasibility"] = {"status": "unknown", "reason": "Original decisions are not mapped."}
                    return
                if primal["status"] != "available" or observed["case_binding"]["status"] != "pass":
                    observed["independent_feasibility"] = {"status": "not_available", "reason": "No bound candidate primal solution."}
                    return
                bundle = parse_json((outcome / "bundle.json").read_bytes())
                solve = _read_ref(outcome, bundle["solve_result_ref"])
                solution = _read_ref(outcome, solve["solution_ref"])["variables"]
                if any(name not in solution for name in mapping.values()):
                    observed["decision_mapping"] = {"status": "unknown", "reason": "Candidate vector lacks declared original decisions."}
                    observed["independent_feasibility"] = {"status": "unknown", "reason": "Original decisions are incomplete."}
                    return
                decisions = {name: solution[source] for name, source in mapping.items()}
                observed["decision_mapping"] = {"status": "pass", "level": "predeclared_original_decision_mapping"}
                data = {ref["data_id"]: public_path(case.public_problem.parent, ref["path"]).read_bytes() for ref in public["data_refs"]}
                checked = checked_solution(checker, identity, public, data, decisions)
                observed["independent_feasibility"] = checked["independent_feasibility"]
                observed["original_objective"] = checked["original_objective"]
                feasible = checked["independent_feasibility"]["status"] == "pass"
                observed["independent_feasibility_numerator"] = int(feasible)
                observed["independent_feasibility_rate"] = float(feasible) if entry["eligible"] else None
                original = checked["original_objective"]
                mapping_objective = material["reported_objective_mapping"]
                reported = primal["reported_objective"]
                if mapping_objective is not None:
                    reported = mapping_objective["scale"] * reported + mapping_objective["offset"]
                consistency = supplied_numeric_match(reported, original, {"kind": "none"}, {"abs_tol": 1e-6, "rel_tol": 1e-5})
                observed["objective_consistency"] = {"status": "pass" if consistency else "fail",
                    "level": "reported_to_original_objective_predeclared_mapping" if mapping_objective is not None else "reported_to_original_objective_identity"}
                if reference is not None:
                    if checked["objective_sense"] != reference["sense"]:
                        raise RunError("reference_sense_mismatch", "evaluation", "Reference objective direction differs from original checker.")
                    match = supplied_numeric_match(original, reference["value"], {"kind": "none"}, reference)
                    if reference["quality"] != "proven_optimum":
                        tolerance = reference["abs_tol"] + reference["rel_tol"] * abs(reference["value"])
                        match = original >= reference["value"] - tolerance if reference["sense"] == "max" else original <= reference["value"] + tolerance
                    observed["original_objective_quality"] = {"status": "pass" if match else "fail", "level": reference["quality"] + "_original_objective"}
                    observed["objective_match"] = dict(observed["original_objective_quality"])
                    success = feasible and match
                    observed["verified_solution"] = {"status": "pass" if success else "fail", "level": "original_feasibility_and_objective_quality"}
                    observed["verified_solution_numerator"] = int(success)
                    observed["verified_solution_rate"] = float(success) if entry["verified_eligible"] else None
                try:
                    observed["property_checks"] = _property_checks(checker, identity, public, data, material, outcome, bundle)
                except (Exception, SystemExit):
                    observed["property_checks"] = {"status": "error", "reason": "Cannot evaluate the declared finite probe policy."}
            except (Exception, SystemExit) as error:
                observed["checker_error"] = {"code": error.code if isinstance(error, RunError) else "checker_error",
                    "message": "Independent checker failed; privileged input is not exposed."}
                for key in ("independent_feasibility", "original_objective_quality", "verified_solution"):
                    observed[key] = {"status": "error"}
                observed["verified_solution_numerator"] = 0
                observed["independent_feasibility_numerator"] = 0
                observed["verified_solution_rate"] = 0.0 if entry["verified_eligible"] else None
                observed["independent_feasibility_rate"] = 0.0 if entry["eligible"] else None

        _evaluate_outcome(case, outcome, result, check)
        if result["checker_error"] is not None and not case.oracle_ref.is_file():
            result["checker_error"] = {"code": "oracle_unavailable", "message": "Frozen privileged evaluation material is missing."}
        return result
