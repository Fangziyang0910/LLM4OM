"""Fixed NLP4LP public descriptions/parameters and private source references."""

import hashlib
import json
import math
from collections.abc import Iterator
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any

import jsonschema

from llm4om.contracts import RunError, parse_json, parse_reference_json, public_path, validate_problem
from llm4om.storage import RunStore
from llm4om.tasks import _json, FrozenTaskAdapter, EvaluationCase
from llm4om.task_policy import review_schema, _review_policy, _review_shape, supplied_numeric_match
from llm4om.evaluation import evaluate_outcome, _verify_ref

COMMIT = "f0f2abb5d4fa01812ab2c818dd350f6c34041d15"
TRAIN_HASH = "84dbed2b8f27c10f94718c93bdc9608d606dffc56139021a859ee1e45bc0619f"
SOURCE_MANIFEST_HASH = "a0a78906086b644156f079db1fdef9d10c6f8855a42ced9ab751e0fd1db49c66"
PROTOCOL = "llm4om.eval.nlp4lp-supplied-v0.1"
REVIEW_SCHEMA = review_schema(("train",), with_data=True)
PUBLIC_FIELDS = {"description": "description.txt", "parameters": "parameters.json", "type": "metadata.json"}
PRIVATE_FIELDS = {"optimus_code": "optimus-code.py", "problem_info": "problem_info.json", "solution": "solution.json"}


def _same_json(left: Any, right: Any) -> bool:
    # Retain scalar types: Python equality alone would equate integer1 with float1.0/boolTrue.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def _solution(raw: str | None) -> tuple[dict[str, Any] | None, str, str | None]:
    if raw is None:
        return None, "missing_solution", "source_does_not_supply_solution"
    try:
        value = parse_reference_json(raw.encode())
        if (set(value) != {"objective", "variables"} or type(value["objective"]) not in (int, float)
                or not math.isfinite(value["objective"]) or not isinstance(value["variables"], dict)):
            raise ValueError("Unsupported supplied solution schema.")
        def numeric(item: Any) -> bool:
            if isinstance(item, (dict, list)):
                return all(numeric(child) for child in (item.values() if isinstance(item, dict) else item))
            return type(item) in (int, float) and math.isfinite(item)
        if not numeric(value["variables"]):
            raise ValueError("Invalid supplied numeric vector.")
        return value, "available_unverified", None
    except (ValueError, OverflowError):
        return None, "invalid_solution", "invalid_solution_json_or_schema"


def import_nlp4lp(config: Path, output: Path, settings: dict[str, Any]) -> Path:
    """Check authorized local release bytes before publishing public/private projections."""
    schema = {"type": "object", "additionalProperties": False, "required": [
        "schema_version", "adapter_id", "dataset_id", "source_kind", "source_version", "release_root",
        "sha256", "reviews", "selected", "tolerance"], "properties": {
        "schema_version": {"const": "0.2.0"}, "adapter_id": {"const": "llm4om.tasks.nlp4lp"},
        "dataset_id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]+$"},
        "source_kind": {"enum": ["official", "fixture", "fork"]}, "source_version": {"type": "string", "minLength": 1},
        "release_root": {"type": "string", "minLength": 1}, "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
        "reviews": {"type": "array", "items": REVIEW_SCHEMA},
        "selected": {"anyOf": [{"type": "null"}, {"type": "array", "minItems": 1, "uniqueItems": True,
            "items": {"type": "string", "pattern": "^[1-9][0-9]*$"}}]},
        "tolerance": {"type": "object", "additionalProperties": False, "required": ["abs_tol", "rel_tol"],
            "properties": {key: {"type": "number", "minimum": 0, "maximum": 1} for key in ("abs_tol", "rel_tol")}}}}
    try:
        jsonschema.Draft202012Validator(schema).validate(settings)
    except jsonschema.ValidationError as error:
        raise RunError("invalid_task_config", "import", "Invalid NLP4LP import configuration.") from error
    official = settings["source_kind"] == "official"
    if ((official and (settings["dataset_id"] != "nlp4lp" or settings["source_version"] != COMMIT or settings["sha256"] != TRAIN_HASH))
            or (not official and (settings["dataset_id"] == "nlp4lp" or settings["source_version"] == COMMIT))):
        raise RunError("source_identity_mismatch", "import", "Official NLP4LP and fixture/fork identities must differ.")
    release = public_path(config.parent, settings["release_root"], require_file=False)
    files: dict[str, bytes] = {}
    if official:
        manifest_raw = Path(__file__).with_name("nlp4lp_source.json").read_bytes()
        if hashlib.sha256(manifest_raw).hexdigest() != SOURCE_MANIFEST_HASH:
            raise RunError("source_hash_mismatch", "import", "Fixed release hash manifest changed.")
        for entry in json.loads(manifest_raw):
            raw = public_path(release, entry["path"]).read_bytes()
            if len(raw) != entry["bytes"] or hashlib.sha256(raw).hexdigest() != entry["sha256"]:
                raise RunError("source_hash_mismatch", "import", "A fixed NLP4LP release file changed.")
            files[entry["path"]] = raw
    raw_train = public_path(release, "train.jsonl").read_bytes()
    card = public_path(release, "README.md").read_bytes()
    if hashlib.sha256(raw_train).hexdigest() != settings["sha256"]:
        raise RunError("source_hash_mismatch", "import", "NLP4LP aggregate bytes changed.")
    if not raw_train or not raw_train.endswith(b"\n") or b"\r" in raw_train or len(raw_train) > 32 * 1024 * 1024:
        raise RunError("invalid_source", "import", "Expected bounded UTF-8 LF JSONL.")
    records, seen = [], set()
    counts = {"available_unverified": 0, "missing_solution": 0, "invalid_solution": 0}
    for line_number, line in enumerate(raw_train.split(b"\n")[:-1], 1):
        record = parse_reference_json(line)
        if (set(record) != {"id", "type", "description", "parameters", "optimus_code", "problem_info", "solution", "keywords", "parametrized_description"}
                or not isinstance(record["id"], str) or not re.fullmatch(r"[1-9][0-9]*", record["id"]) or record["id"] in seen
                or record["type"] not in ("easy", "hard", "case study")
                or any(not isinstance(record[key], str) for key in ("description", "parameters", "optimus_code"))
                or not record["description"].strip()
                or any(record[key] is not None and not isinstance(record[key], str) for key in ("problem_info", "solution", "parametrized_description"))
                or record["keywords"] is not None and (not isinstance(record["keywords"], list) or any(not isinstance(item, str) for item in record["keywords"]))):
            raise RunError("invalid_source", "import", "Malformed or duplicate NLP4LP public record.")
        seen.add(record["id"])
        parameters = parse_json(record["parameters"].encode())
        consistency = {}
        case_files = {}
        for field, name in {**PUBLIC_FIELDS, **PRIVATE_FIELDS}.items():
            source_path = f"data/{record['id']}/{name}"
            path = public_path(release, source_path, require_file=False)
            case_raw = path.read_bytes() if path.exists() else None
            expected = record[field]
            if case_raw is None:
                same, status = expected is None, "both_absent"
            elif field in ("parameters", "problem_info", "solution"):
                try:
                    same = _same_json(parse_reference_json(expected.encode()), parse_reference_json(case_raw)) if expected is not None else False
                    status = "semantic_equal_directory_bytes_retained"
                except ValueError:
                    same = isinstance(expected, str) and expected.encode() == case_raw
                    status = "invalid_raw_equal" if same else "mismatch"
            else:
                same = _same_json(parse_reference_json(case_raw), {"type": expected}) if field == "type" else expected is not None and expected.encode() == case_raw
                status = "exact_equal"
            if not same:
                raise RunError("ambiguous_source", "import", "Aggregate and per-instance source differ.")
            consistency[field] = status
            if case_raw is not None:
                case_files[name] = case_raw
                files[source_path] = case_raw
        if not _same_json(parameters, parse_json(case_files["parameters.json"])):
            raise RunError("ambiguous_source", "import", "Public parameter values/types differ.")
        _, quality, diagnostic = _solution(record["solution"])
        counts[quality] += 1
        records.append((record, line_number, hashlib.sha256(line).hexdigest(), case_files, consistency, quality, diagnostic))
    if official and (seen != {str(i) for i in range(1, 362)} or counts != {"available_unverified": 322, "missing_solution": 37, "invalid_solution": 2}):
        raise RunError("source_identity_mismatch", "import", "Fixed NLP4LP counts/IDs changed.")
    public_inputs = {record["id"]: (record["description"], hashlib.sha256(case_files["parameters.json"]).hexdigest())
                     for record, _, _, case_files, _, _, _ in records}
    reviews = {}
    selected = set(settings["selected"] if settings["selected"] is not None else seen)
    try:
        if not selected <= seen:
            raise ValueError("Unknown selected case.")
        for review in settings["reviews"]:
            key = review["sample_id"]
            if key in reviews or key not in public_inputs:
                raise ValueError("Unknown or duplicate review.")
            question, data_hash = public_inputs[key]
            _review_policy(review, question, ("train",), data_sha256=data_hash)
            reviews[key] = review
    except (ValueError, jsonschema.ValidationError) as error:
        raise RunError("invalid_public_review", "import", "Review/selection must bind exact public description and parameter bytes.") from error
    if output.exists():
        raise RunError("snapshot_exists", "import", "Frozen snapshots cannot be overwritten.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".nlp4lp-", dir=output.parent))
    store: RunStore | None = None
    try:
        store = RunStore(staging, versioned=False)
        private = store.path / "private"
        private.mkdir(mode=0o700)
        (private / "train.jsonl").write_bytes(raw_train)
        (private / "train.jsonl").chmod(0o600)
        source = {key: settings[key] for key in ("dataset_id", "source_kind", "source_version", "sha256")}
        source.update(split="train", records=len(records), license="CC-BY-NC-4.0" if official else "unspecified",
            source_card_sha256=hashlib.sha256(card).hexdigest(), source_card_url=f"https://huggingface.co/datasets/udell-lab/NLP4LP/blob/{COMMIT}/README.md" if official else None)
        store.write("SOURCE_CARD.md", card, "source-card")
        store.write("ATTRIBUTION.txt", ("NLP4LP, udell-lab. Source " + settings["source_version"] + "\n"
            "Original source card and research-use statements govern dataset projections separately from SDK code.\n"
            "Modification: original description/concrete parameter projections; private references; frozen evaluation policy.\n").encode(), "source-attribution")
        policy_ref = store.json("evaluation-policy.json", {"schema_version": "0.1.0", "selected": sorted(selected), "reviews": settings["reviews"], "tolerance": settings["tolerance"]}, "evaluation-policy")
        policy_ref["namespace"] = "task_public"
        entries = []
        for record, line_number, record_hash, case_files, consistency, quality, diagnostic in records:
            sample_id = record["id"]
            review = reviews.get(sample_id)
            eligible = sample_id in selected and quality == "available_unverified" and review is not None and review["classification"] in ("lp", "milp")
            case_id = f"{settings['dataset_id']}:{settings['source_version']}:train:{sample_id}"
            params_ref = store.write(f"public/params-{sample_id}.json", case_files["parameters.json"], sample_id + "-parameters")
            params_ref["namespace"] = "task_public"
            problem = {"schema_version": "0.3.0", "problem_id": case_id, "revision": record_hash,
                "description": record["description"], "language": "en",
                "problem_type_hint": review["classification"] if review is not None and review["classification"] in ("lp", "milp") else "unknown", "requirements": [],
                "assumptions": [], "data_refs": [{"data_id": "parameters", "path": f"params-{sample_id}.json", "format": "json",
                    "sha256": params_ref["sha256"], "schema": {"type": "object"}}], "source": {**source, "sample_id": sample_id, "difficulty": record["type"]}}
            validate_problem(problem)
            public_ref = store.json(f"public/{sample_id}.json", problem, case_id)
            public_ref["namespace"] = "task_public"
            oracle = _json({"schema_version": "0.1.0", "record": record})
            (private / f"{sample_id}.json").write_bytes(oracle)
            (private / f"{sample_id}.json").chmod(0o600)
            folder = private / sample_id
            folder.mkdir(mode=0o700)
            file_refs = []
            for name, raw in case_files.items():
                (folder / name).write_bytes(raw)
                (folder / name).chmod(0o600)
                file_refs.append({"relative_path": f"private/{sample_id}/{name}", "sha256": hashlib.sha256(raw).hexdigest(), "size_bytes": len(raw)})
            entries.append({"case_id": case_id, "sample_id": sample_id, "subset": "train", "difficulty": record["type"],
                "source_line": line_number, "raw_record_sha256": record_hash, "question_sha256": hashlib.sha256(record["description"].encode()).hexdigest(),
                "public_ref": public_ref, "data_ref": params_ref, "oracle_ref": {"relative_path": f"private/{sample_id}.json",
                    "sha256": hashlib.sha256(oracle).hexdigest(), "size_bytes": len(oracle), "namespace": "task_private", "schema_version": "0.1.0"},
                "private_source_refs": file_refs, "consistency": consistency, "reference_quality": quality,
                "reference_diagnostic": diagnostic, "selected": sample_id in selected, "eligible": eligible, "review": review,
                "exclusion_reason": None if eligible else "not_selected" if sample_id not in selected else
                    diagnostic or (review["reason"] if review is not None else "public_math_review_required")})
        store.json("manifest.json", {"schema_version": "0.2.0", "adapter_id": "llm4om.tasks.nlp4lp", "protocol_id": PROTOCOL,
            "source": source, "projection_revision": "original-description-concrete-json-v0.1", "N_imported": len(entries),
            "N_selected": len(selected), "N_eligible": sum(entry["eligible"] for entry in entries), "reference_counts": counts, "policy_ref": policy_ref,
            "tolerance": settings["tolerance"], "cases": entries}, "manifest")
        saved = store.path
        store.close()
        store = None
        saved.rename(output)
    finally:
        if store is not None:
            store.close()
        shutil.rmtree(staging)
    return output.resolve() / "manifest.json"


class NLP4LPAdapter(FrozenTaskAdapter):
    def import_source(self, config: Path, output: Path, settings: dict[str, Any]) -> Path:
        return import_nlp4lp(config, output, settings)

    def iter_cases(self, config: Path) -> Iterator[EvaluationCase]:
        for case in super().iter_cases(config):
            entry = parse_reference_json(case.entry)
            _verify_ref(config.parent, entry["data_ref"])
            if entry["review"] is not None:
                try:
                    _review_policy(entry["review"], parse_json(case.public_problem.read_bytes())["description"],
                                   ("train",), data_sha256=entry["data_ref"]["sha256"])
                except (ValueError, jsonschema.ValidationError) as error:
                    raise RunError("invalid_public_review", "evaluation", "Review must bind exact public description/data.") from error
            yield case

    def _cases(self, config: Path) -> Iterator[EvaluationCase]:
        raw = config.read_bytes()
        manifest = parse_reference_json(raw)
        try:
            if (manifest["schema_version"] != "0.2.0" or manifest["adapter_id"] != "llm4om.tasks.nlp4lp"
                    or manifest["protocol_id"] != PROTOCOL or manifest["projection_revision"] != "original-description-concrete-json-v0.1"
                    or manifest["N_imported"] != len(manifest["cases"])
                    or manifest["N_selected"] != sum(entry["selected"] for entry in manifest["cases"])
                    or manifest["N_eligible"] != sum(entry["eligible"] for entry in manifest["cases"])):
                raise ValueError("Invalid frozen protocol/counts.")
            source = manifest["source"]
            official = source["source_kind"] == "official"
            if (source["source_kind"] not in ("official", "fixture", "fork")
                    or official and (source["dataset_id"] != "nlp4lp" or source["source_version"] != COMMIT
                                     or source["sha256"] != TRAIN_HASH or manifest["N_imported"] != 361)
                    or not official and (source["dataset_id"] == "nlp4lp" or source["source_version"] == COMMIT)):
                raise ValueError("Invalid source identity.")
            counts = {key: sum(entry["reference_quality"] == key for entry in manifest["cases"])
                      for key in ("available_unverified", "missing_solution", "invalid_solution")}
            if counts != manifest["reference_counts"] or sum(counts.values()) != manifest["N_imported"]:
                raise ValueError("Reference availability counts changed.")
            if official and counts != {"available_unverified": 322, "missing_solution": 37, "invalid_solution": 2}:
                raise ValueError("Official reference counts changed.")
            pending, seen = [], set()
            for entry in manifest["cases"]:
                if entry["review"] is not None:
                    _review_shape(entry["review"], ("train",), with_data=True)
                sample_id = entry["sample_id"]
                expected_id = f"{source['dataset_id']}:{source['source_version']}:train:{sample_id}"
                supported = entry["review"] is not None and entry["review"]["classification"] in ("lp", "milp")
                expected_eligible = entry["selected"] and supported and entry["reference_quality"] == "available_unverified"
                exclusion = None if expected_eligible else "not_selected" if not entry["selected"] else (
                    entry["reference_diagnostic"] or (entry["review"]["reason"] if entry["review"] is not None else "public_math_review_required"))
                if (not isinstance(sample_id, str) or not re.fullmatch(r"[1-9][0-9]*", sample_id) or sample_id in seen
                        or entry["case_id"] != expected_id or entry["subset"] != "train"
                        or type(entry["selected"]) is not bool or type(entry["eligible"]) is not bool
                        or entry["eligible"] != expected_eligible or entry["exclusion_reason"] != exclusion
                        or type(entry["source_line"]) is not int or entry["source_line"] < 1):
                    raise ValueError("Invalid frozen case identity/eligibility.")
                seen.add(sample_id)
                paths = [public_path(config.parent, entry[key]["relative_path"], require_file=False)
                         for key in ("public_ref", "oracle_ref")]
                pending.append(EvaluationCase(expected_id, paths[0], paths[1], raw, _json(entry)))
            if official and seen != {str(i) for i in range(1, 362)}:
                raise ValueError("Official sample IDs changed.")
            yield from pending
        except (KeyError, TypeError, ValueError, jsonschema.ValidationError) as error:
            raise RunError("invalid_manifest", "evaluation", "Unsupported frozen NLP4LP manifest.") from error


class NLP4LPEvaluator:
    def evaluate(self, case: EvaluationCase, outcome: Path) -> dict[str, Any]:
        """Grade only an independently selected supplied objective, never execute reference code."""
        manifest, entry = parse_reference_json(case.manifest), parse_reference_json(case.entry)
        if manifest.get("protocol_id") != PROTOCOL or entry not in manifest["cases"] or entry["case_id"] != case.case_id:
            raise RunError("invalid_case", "evaluation", "Case must belong to its NLP4LP snapshot.")
        review = entry["review"]
        unavailable = {"status": "not_available", "reason": "Supplied solution/vector has no independent model, checker or optimum certificate."}
        result: dict[str, Any] = {"schema_version": "0.2.0", "protocol_id": PROTOCOL, "case_id": case.case_id,
            "manifest_sha256": hashlib.sha256(case.manifest).hexdigest(), "source": manifest["source"],
            "projection_revision": manifest["projection_revision"], "raw_record_sha256": entry["raw_record_sha256"],
            "reference_quality": entry["reference_quality"], "reference_diagnostic": entry["reference_diagnostic"],
            "reference_counts": manifest["reference_counts"], "selected": entry["selected"], "eligible": entry["eligible"],
            "exclusion_reason": entry["exclusion_reason"], "domain_policy": review["domain_policy"] if review else None,
            "normalization_policy": review["rounding_policy"] if review else None,
            "data_binding_policy": review["data_binding_policy"] if review else None, "tolerance": manifest["tolerance"],
            "N_selected": manifest["N_selected"], "N_eligible": manifest["N_eligible"], "N_evaluated": 1,
            "objective_match_numerator": 0, "objective_match_denominator": int(entry["eligible"]),
            "objective_match_rate": 0.0 if entry["eligible"] else None,
            "independent_feasibility": dict(unavailable), "semantic_validation": dict(unavailable),
            "variable_mapping": {"status": "not_available", "reason": "No independently verified candidate-to-source vector mapping was declared."},
            "objective_match": {"status": "not_available", "level": "supplied_objective_reference_match"},
            "formulation_validation": {"status": "not_available"}, "code_validation": {"status": "not_available"},
            "execution": {"status": "not_available"}, "candidate_primal": {"status": "not_available"},
            "case_binding": {"status": "not_available"}, "run_id": None, "run_status": "unknown", "run_error": None, "checker_error": None}

        def compare(oracle: dict[str, Any], public: dict[str, Any], observed: dict[str, Any]) -> None:
            root = case.public_problem.parent.parent
            data = _verify_ref(root, entry["data_ref"])
            policy = parse_reference_json(_verify_ref(root, manifest["policy_ref"]))
            policy_review = next((item for item in policy["reviews"] if item["sample_id"] == entry["sample_id"]), None)
            if (policy_review != review or policy["tolerance"] != manifest["tolerance"]
                    or entry["selected"] != (entry["sample_id"] in policy["selected"])):
                raise RunError("snapshot_hash_mismatch", "evaluation", "Frozen selection/review changed.")
            if review is not None:
                _review_policy(review, public["description"], ("train",), data_sha256=entry["data_ref"]["sha256"])
            for ref in entry["private_source_refs"]:
                _verify_ref(root, ref)
            aggregate = _verify_ref(root, {"relative_path": "private/train.jsonl", "sha256": manifest["source"]["sha256"],
                "size_bytes": (root / "private/train.jsonl").stat().st_size})
            line = aggregate.splitlines()[entry["source_line"] - 1]
            record = oracle["record"]
            if (hashlib.sha256(line).hexdigest() != entry["raw_record_sha256"] or parse_reference_json(line) != record
                    or record["id"] != entry["sample_id"] or record["description"] != public["description"]
                    or not _same_json(parse_reference_json(record["parameters"].encode()), parse_json(data))):
                raise RunError("case_identity_mismatch", "evaluation", "Supplied reference belongs to another public input.")
            solution, quality, diagnostic = _solution(record["solution"])
            if quality != entry["reference_quality"] or diagnostic != entry["reference_diagnostic"]:
                raise RunError("snapshot_hash_mismatch", "evaluation", "Reference availability changed.")
            primal = observed["candidate_primal"]
            if not entry["eligible"] or solution is None or primal["status"] != "available" or observed["case_binding"]["status"] != "pass":
                return
            matched = supplied_numeric_match(primal["reported_objective"], solution["objective"],
                review["rounding_policy"], policy["tolerance"])
            observed["objective_match"] = {"status": "pass" if matched else "fail", "level": "supplied_objective_reference_match"}
            observed["objective_match_numerator"] = int(matched)
            observed["objective_match_rate"] = float(matched)

        return evaluate_outcome(case, outcome, result, compare)
