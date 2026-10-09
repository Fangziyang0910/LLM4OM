"""Fixed MAMO optimization questions, private numeric references and review policy."""

import hashlib
import math
from collections.abc import Iterator
from pathlib import Path
import shutil
import tempfile
from typing import Any

import jsonschema

from llm4om.contracts import RunError, parse_reference_json, public_path, validate_problem
from llm4om.storage import RunStore
from llm4om.tasks import _json, _FrozenTaskAdapter, EvaluationCase
from llm4om.evaluation import _evaluate_outcome, _verify_ref

COMMIT = "2c91069dee5c1e4db4b899eb176ec987d0251bb3"
PROTOCOL = "llm4om.eval.mamo-numeric-v0.1"
SOURCE_FILES = {
    "easy_lp": ("data/optimization/Easy_LP/mamo_easy_lp.jsonl", "b37ae7d9fc0b8c39e172d070aed84e600549407886ef970083c0f6cadc2e60a6", 652),
    "complex_lp": ("data/optimization/Complex_LP/mamo_complex_lp.jsonl", "07eb3db3d2af099871dfa4425b14887775179c158c38944fe4fe152b615bbfc3", 211),
    "ode": ("data/ode/mamo_ode.jsonl", "e877c8e12add7ec6b528e3cd64d83d48dac019f9d3f09327f803f802ef015dfa", 346),
}
LICENSE_HASH = "187442db4df3afd21f2f0525739fd4beac28a62daaba3ee8d3533f60e7c33ec7"
from llm4om.task_policy import review_schema, _review_shape, _review_policy, supplied_numeric_match

REVIEW_SCHEMA = review_schema(("easy_lp", "complex_lp"))

def import_mamo(config: Path, output: Path, settings: dict[str, Any]) -> Path:
    """Validate source and policy before publishing one immutable snapshot."""
    file_schema = {"type": "object", "additionalProperties": False,
        "required": ["subset", "path", "sha256"], "properties": {
            "subset": {"enum": list(SOURCE_FILES)}, "path": {"type": "string", "minLength": 1},
            "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}}
    schema = {"type": "object", "additionalProperties": False, "required": [
        "schema_version", "adapter_id", "dataset_id", "source_kind", "source_version", "files",
        "license_file", "reviews", "selected", "tolerance"], "properties": {
        "schema_version": {"const": "0.2.0"}, "adapter_id": {"const": "llm4om.tasks.mamo"},
        "dataset_id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]+$"},
        "source_kind": {"enum": ["official", "fixture", "fork"]},
        "source_version": {"type": "string", "minLength": 1},
        "files": {"type": "array", "items": file_schema, "minItems": 3, "maxItems": 3},
        "license_file": {"type": ["null", "string"]}, "reviews": {"type": "array", "items": REVIEW_SCHEMA},
        "selected": {"anyOf": [{"type": "null"}, {"type": "array", "minItems": 1, "uniqueItems": True,
            "items": {"type": "string", "pattern": "^(easy_lp|complex_lp):[1-9][0-9]*$"}}]},
        "tolerance": {"type": "object", "additionalProperties": False,
            "required": ["abs_tol", "rel_tol"], "properties": {
                key: {"type": "number", "minimum": 0, "maximum": 1} for key in ("abs_tol", "rel_tol")}}}}
    try:
        jsonschema.Draft202012Validator(schema).validate(settings)
    except jsonschema.ValidationError as error:
        raise RunError("invalid_task_config", "import", "Invalid MAMO import configuration.") from error
    official = settings["source_kind"] == "official"
    if ((official and (settings["dataset_id"] != "mamo" or settings["source_version"] != COMMIT))
            or (not official and (settings["dataset_id"] == "mamo" or settings["source_version"] == COMMIT))):
        raise RunError("source_identity_mismatch", "import", "Official and fixture/fork identities must differ.")
    if {file["subset"] for file in settings["files"]} != set(SOURCE_FILES):
        raise RunError("invalid_task_config", "import", "Supply each canonical MAMO subset exactly once.")
    license_raw = public_path(config.parent, settings["license_file"]).read_bytes() if settings["license_file"] else None
    if official and (license_raw is None or hashlib.sha256(license_raw).hexdigest() != LICENSE_HASH):
        raise RunError("source_identity_mismatch", "import", "Fixed MAMO license bytes are required.")
    sources: dict[str, dict[str, Any]] = {}
    records = []
    for file in settings["files"]:
        subset = file["subset"]
        raw = public_path(config.parent, file["path"]).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != file["sha256"] or official and digest != SOURCE_FILES[subset][1]:
            raise RunError("source_hash_mismatch", "import", "MAMO source bytes changed.")
        if not raw or not raw.endswith(b"\n") or b"\r" in raw or len(raw) > 32 * 1024 * 1024:
            raise RunError("invalid_source", "import", "Expected bounded UTF-8 JSONL with LF record terminators.")
        seen = set()
        for line_number, line in enumerate(raw.split(b"\n")[:-1], 1):
            record = parse_reference_json(line)
            if (set(record) != {"id", "Question", "Answer", "Category", "Type"}
                    or type(record["id"]) is not int or record["id"] < 1 or record["id"] in seen
                    or any(not isinstance(record[key], str) or not record[key].strip()
                           for key in ("Question", "Answer", "Category", "Type"))
                    or record["Category"] != ("ordinary_differential_equation" if subset == "ode" else "optimization")
                    or subset != "ode" and record["Type"] != subset):
                raise RunError("invalid_source", "import", "Malformed or duplicate MAMO record.")
            try:
                if not math.isfinite(float(record["Answer"])):
                    raise ValueError("Nonfinite numeric answer.")
            except ValueError as error:
                raise RunError("invalid_source", "import", "MAMO numeric reference is invalid.") from error
            seen.add(record["id"])
            if subset != "ode":
                records.append((subset, record, line_number, hashlib.sha256(line).hexdigest()))
        if official and len(seen) != SOURCE_FILES[subset][2]:
            raise RunError("source_identity_mismatch", "import", "Canonical MAMO record count changed.")
        sources[subset] = {"raw": raw, "sha256": digest, "records": len(seen)}
    questions = {f"{subset}:{record['id']}": record["Question"] for subset, record, _, _ in records}
    reviews = {}
    try:
        for review in settings["reviews"]:
            key = review["subset"] + ":" + review["sample_id"]
            if key not in questions or key in reviews:
                raise ValueError("Unknown or duplicate reviewed case.")
            _review_policy(review, questions[key])
            reviews[key] = review
        selected = set(settings["selected"] if settings["selected"] is not None else questions)
        if not selected <= questions.keys():
            raise ValueError("Unknown selected case.")
    except (jsonschema.ValidationError, ValueError) as error:
        raise RunError("invalid_public_review", "import", "Review/selection must identify exact public questions and explicit policy.") from error
    if output.exists():
        raise RunError("snapshot_exists", "import", "Frozen snapshots cannot be overwritten.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".mamo-", dir=output.parent))
    store: RunStore | None = None
    try:
        store = RunStore(staging, versioned=False)
        private = store.path / "private"
        private.mkdir(mode=0o700)
        for subset, source_file in sources.items():
            path = private / (subset + ".jsonl")
            path.write_bytes(source_file["raw"])
            path.chmod(0o600)
        source = {key: settings[key] for key in ("dataset_id", "source_kind", "source_version")}
        source.update(license="CC-BY-SA-4.0" if official else "unspecified", files=[{
            "subset": subset, "source_path": SOURCE_FILES[subset][0],
            "sha256": value["sha256"], "size_bytes": len(value["raw"]), "records": value["records"]} for subset, value in sources.items()])
        if license_raw is not None:
            store.write("LICENSE", license_raw, "source-license")
        if official:
            source["license_reference"] = f"https://github.com/FreedomIntelligence/Mamo/blob/{COMMIT}/LICENSE"
            store.write("ATTRIBUTION.txt", (
                f"MAMO, FreedomIntelligence. Fixed source {COMMIT}.\n"
                "https://github.com/FreedomIntelligence/Mamo\n"
                "Source data: CC BY-SA 4.0, separate from LLM4OM code license.\n"
                "Modification: public Question/provenance projections, private numeric references, frozen evaluation policy.\n"
            ).encode(), "source-attribution")
        policy_ref = store.json("evaluation-policy.json", {"schema_version": "0.1.0",
            "selected": sorted(selected), "reviews": settings["reviews"], "tolerance": settings["tolerance"]}, "evaluation-policy")
        policy_ref["namespace"] = "task_public"
        entries = []
        for subset, record, line_number, record_hash in records:
            sample_id = str(record["id"])
            key = subset + ":" + sample_id
            review = reviews.get(key)
            eligible = key in selected and review is not None and review["classification"] in ("lp", "milp")
            case_id = f"{settings['dataset_id']}:{settings['source_version']}:{subset}:{sample_id}"
            problem = {"schema_version": "0.2.0", "problem_id": case_id, "revision": record_hash,
                "description": record["Question"], "language": "en",
                "problem_type_hint": review["classification"] if review is not None and review["classification"] in ("lp", "milp") else "unknown",
                "requirements": [], "assumptions": [], "data_refs": [],
                "source": {**source, "subset": subset, "sample_id": sample_id}}
            validate_problem(problem)
            public_ref = store.json(f"public/{subset}-{sample_id}.json", problem, case_id)
            public_ref["namespace"] = "task_public"
            oracle = _json({"schema_version": "0.1.0", "reference_quality": "supplied_numeric_answer", "record": record})
            oracle_path = f"private/{subset}-{sample_id}.json"
            (store.path / oracle_path).write_bytes(oracle)
            (store.path / oracle_path).chmod(0o600)
            entries.append({"case_id": case_id, "subset": subset, "sample_id": sample_id,
                "source_line": line_number, "raw_record_sha256": record_hash,
                "question_sha256": hashlib.sha256(record["Question"].encode()).hexdigest(),
                "public_ref": public_ref, "oracle_ref": {"relative_path": oracle_path,
                    "sha256": hashlib.sha256(oracle).hexdigest(), "size_bytes": len(oracle),
                    "namespace": "task_private", "schema_version": "0.1.0"},
                "selected": key in selected, "eligible": eligible, "review": review,
                "exclusion_reason": None if eligible else "not_selected" if key not in selected else
                    review["reason"] if review is not None else "public_math_review_required",
                "reference_quality": "supplied_numeric_answer"})
        manifest = {"schema_version": "0.2.0", "adapter_id": "llm4om.tasks.mamo", "source": source,
            "projection_revision": "original-question-v0.1", "protocol_id": PROTOCOL,
            "N_imported": len(entries), "N_selected": len(selected), "N_eligible": sum(entry["eligible"] for entry in entries),
            "policy_ref": policy_ref, "tolerance": settings["tolerance"], "source_exclusions": [{"subset": "ode",
                "records": sources["ode"]["records"], "sha256": sources["ode"]["sha256"], "reason": "outside_lp_milp"}],
            "cases": entries}
        store.json("manifest.json", manifest, "manifest")
        saved_path = store.path
        store.close()
        store = None
        saved_path.rename(output)
    finally:
        if store is not None:
            store.close()
        shutil.rmtree(staging)
    return output.resolve() / "manifest.json"


class MAMOAdapter(_FrozenTaskAdapter):
    def iter_cases(self, config: Path) -> Iterator[EvaluationCase]:
        for case in super().iter_cases(config):
            entry = parse_reference_json(case.entry)
            if entry["review"] is not None:
                try:
                    _review_policy(entry["review"], parse_reference_json(case.public_problem.read_bytes())["description"])
                except (jsonschema.ValidationError, ValueError) as error:
                    raise RunError("invalid_public_review", "evaluation", "Selected review must match its exact public question.") from error
            yield case

    def _cases(self, config: Path) -> Iterator[EvaluationCase]:
        raw = config.read_bytes()
        manifest = parse_reference_json(raw)
        try:
            if (manifest["schema_version"] != "0.2.0" or manifest["adapter_id"] != "llm4om.tasks.mamo"
                    or manifest["protocol_id"] != PROTOCOL or manifest["projection_revision"] != "original-question-v0.1"
                    or manifest["N_imported"] != len(manifest["cases"])
                    or manifest["N_selected"] != sum(entry["selected"] for entry in manifest["cases"])
                    or manifest["N_eligible"] != sum(entry["eligible"] for entry in manifest["cases"])):
                raise ValueError("Invalid counts or protocol.")
            source = manifest["source"]
            if (len(source["files"]) != 3 or {file["subset"] for file in source["files"]} != set(SOURCE_FILES)
                    or manifest["N_imported"] != sum(file["records"] for file in source["files"] if file["subset"] != "ode")):
                raise ValueError("Imported cases must cover all optimization source records.")
            official = source["source_kind"] == "official"
            if (source["source_kind"] not in ("official", "fixture", "fork")
                    or (official and (source["source_version"] != COMMIT or source["dataset_id"] != "mamo"))
                    or (not official and (source["source_version"] == COMMIT or source["dataset_id"] == "mamo"))):
                raise ValueError("Invalid source identity.")
            if official and {file["subset"]: (file["sha256"], file["records"]) for file in source["files"]} != {
                    key: (value[1], value[2]) for key, value in SOURCE_FILES.items()}:
                raise ValueError("Official source metadata changed.")
            seen = set()
            for entry in manifest["cases"]:
                if entry["review"] is not None:
                    _review_shape(entry["review"])
                expected_id = f"{source['dataset_id']}:{source['source_version']}:{entry['subset']}:{entry['sample_id']}"
                supported = entry["review"] is not None and entry["review"]["classification"] in ("lp", "milp")
                exclusion = None if entry["selected"] and supported else "not_selected" if not entry["selected"] else (
                    entry["review"]["reason"] if entry["review"] is not None else "public_math_review_required")
                if (entry["case_id"] != expected_id or expected_id in seen
                        or entry["subset"] not in ("easy_lp", "complex_lp")
                        or type(entry["selected"]) is not bool or type(entry["eligible"]) is not bool
                        or type(entry["source_line"]) is not int or entry["source_line"] < 1
                        or entry["eligible"] != (entry["selected"] and supported)
                        or entry["exclusion_reason"] != exclusion
                        or entry["reference_quality"] != "supplied_numeric_answer"):
                    raise ValueError("Invalid case identity or eligibility.")
                seen.add(expected_id)
                paths = [public_path(config.parent, entry[name]["relative_path"], require_file=False)
                         for name in ("public_ref", "oracle_ref")]
                yield EvaluationCase(expected_id, paths[0], paths[1], raw, _json(entry))
        except (KeyError, TypeError, ValueError, jsonschema.ValidationError) as error:
            raise RunError("invalid_manifest", "evaluation", "Unsupported frozen MAMO manifest.") from error


class MAMOEvaluator:
    def evaluate(self, case: EvaluationCase, outcome: Path) -> dict[str, Any]:
        """Compare supplied numeric reference only after verifying the selected case."""
        manifest, entry = parse_reference_json(case.manifest), parse_reference_json(case.entry)
        if manifest.get("protocol_id") != PROTOCOL or entry not in manifest["cases"] or entry["case_id"] != case.case_id:
            raise RunError("invalid_case", "evaluation", "Case must belong to its frozen MAMO protocol.")
        unavailable = {"status": "not_available", "reason": "Canonical MAMO supplies a number, without model, vector or optimum certificate."}
        review = entry["review"]
        result: dict[str, Any] = {"schema_version": "0.2.0", "protocol_id": PROTOCOL, "case_id": case.case_id,
            "manifest_sha256": hashlib.sha256(case.manifest).hexdigest(), "source": manifest["source"],
            "projection_revision": manifest["projection_revision"], "raw_record_sha256": entry["raw_record_sha256"],
            "reference_quality": "supplied_numeric_answer", "selected": entry["selected"], "eligible": entry["eligible"],
            "exclusion_reason": entry["exclusion_reason"], "domain_policy": review["domain_policy"] if review else None,
            "normalization_policy": review["rounding_policy"] if review else None, "tolerance": manifest["tolerance"],
            "N_selected": manifest["N_selected"], "N_eligible": manifest["N_eligible"], "N_evaluated": 1,
            "objective_match_numerator": 0, "objective_match_denominator": int(entry["eligible"]),
            "objective_match_rate": 0.0 if entry["eligible"] else None,
            "independent_feasibility": dict(unavailable), "semantic_validation": dict(unavailable),
            "objective_match": {"status": "not_available", "level": "supplied_numeric_reference_match"},
            "formulation_validation": {"status": "not_available"}, "code_validation": {"status": "not_available"},
            "execution": {"status": "not_available"}, "candidate_primal": {"status": "not_available"},
            "case_binding": {"status": "not_available"}, "run_id": None, "run_status": "unknown",
            "run_error": None, "checker_error": None}

        def compare(oracle: dict[str, Any], public: dict[str, Any], observed: dict[str, Any]) -> None:
            root = case.public_problem.parent.parent
            policy = parse_reference_json(_verify_ref(root, manifest["policy_ref"]))
            key = entry["subset"] + ":" + entry["sample_id"]
            policy_review = next((item for item in policy["reviews"] if item["subset"] + ":" + item["sample_id"] == key), None)
            if policy_review != review or policy["tolerance"] != manifest["tolerance"] or entry["selected"] != (key in policy["selected"]):
                raise RunError("snapshot_hash_mismatch", "evaluation", "Frozen review or selection policy changed.")
            if review is not None:
                _review_policy(review, public["description"])
            record = oracle["record"]
            for file in manifest["source"]["files"]:
                raw = _verify_ref(root, {**file, "relative_path": "private/" + file["subset"] + ".jsonl"})
                if file["subset"] == entry["subset"]:
                    line = raw.splitlines()[entry["source_line"] - 1]
                    if hashlib.sha256(line).hexdigest() != entry["raw_record_sha256"] or parse_reference_json(line) != record:
                        raise RunError("snapshot_hash_mismatch", "evaluation", "Private reference differs from original record.")
            if (hashlib.sha256(public["description"].encode()).hexdigest() != entry["question_sha256"]
                    or record["Question"] != public["description"] or str(record["id"]) != entry["sample_id"]
                    or record["Type"] != entry["subset"] or not math.isfinite(float(record["Answer"]))):
                raise RunError("case_identity_mismatch", "evaluation", "Private reference belongs to another public question.")
            primal = observed["candidate_primal"]
            if not entry["eligible"] or primal["status"] != "available" or observed["case_binding"]["status"] != "pass":
                return
            matched = supplied_numeric_match(primal["reported_objective"], record["Answer"],
                review["rounding_policy"], policy["tolerance"])
            observed["objective_match"] = {"status": "pass" if matched else "fail", "level": "supplied_numeric_reference_match"}
            observed["objective_match_numerator"] = int(matched)
            observed["objective_match_rate"] = float(matched)

        return _evaluate_outcome(case, outcome, result, compare)
