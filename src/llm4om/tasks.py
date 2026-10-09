"""Frozen task snapshots; only public ProblemSpec files enter modeling."""

import hashlib
import json
import re
import shutil
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import jsonschema

from llm4om.contracts import RunError, parse_reference_json, read_config, validate_problem, public_path
from llm4om.storage import RunStore


PROTOCOL = "llm4om.eval.nl4opt-raw-v0.1"
COMMIT = "49f1e0d66b7fdcd33305a7f281c2a7c13f5620ea"
SPLIT_HASHES = {
    "train": "120ff6881c723296c458ef34f3840b5f14d174c6c30dd7002711f59e7e262380",
    "dev": "6538ce1fe76861f89879672a6c9a02c8f41156952256f3cfde82c2808ba320ee",
    "test": "2a4a20a11935aacc99068ee4207d5265f15c0b387d4720c548c196d8ff2fcf5b",
}
MIT_LICENSE = """MIT License

Copyright (c) 2022 Huawei Technologies

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

RECORD_TYPES = {"document": "string", "vars": "array", "var_mentions": "array", "params": "array",
                "var_mention_to_first_var": "object", "first_var_to_mentions": "object",
                "obj_declaration": "object", "const_declarations": "array", "spans": "array",
                "tokens": "array", "_input_hash": "integer", "order_mapping": "object"}


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    public_problem: Path
    oracle_ref: Path
    manifest: bytes
    entry: bytes


class TaskAdapter(Protocol):
    def import_source(self, config: Path, output: Path, settings: dict[str, Any]) -> Path: ...
    def iter_cases(self, config: Path) -> Iterator[EvaluationCase]: ...
    def load_case(self, config: Path, case_id: str) -> EvaluationCase: ...


class Evaluator(Protocol):
    def evaluate(self, case: EvaluationCase, outcome: Path) -> dict[str, Any]: ...


def _json(value: dict[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def _validate_source(settings: dict[str, Any]) -> None:
    if settings["source_kind"] not in {"official", "fixture", "fork"} or settings["split"] not in SPLIT_HASHES:
        raise RunError("source_identity_mismatch", "import", "Unsupported source kind or split.")
    official = settings["source_kind"] == "official"
    if ((official and (settings["dataset_id"] != "nl4opt" or settings["source_version"] != COMMIT
                      or settings["sha256"] != SPLIT_HASHES[settings["split"]]))
            or (not official and (settings["dataset_id"] == "nl4opt" or settings["source_version"] == COMMIT))):
        raise RunError("source_identity_mismatch", "import", "Fixture/fork identity must differ from the fixed official source.")


def import_dataset(config: Path, output: Path) -> Path:
    """Freeze a supported local task source through its declared adapter."""
    from llm4om.task_plugins import import_registered_task
    return import_registered_task(config, output)


def _import_nl4opt(config: Path, output: Path, settings: dict[str, Any]) -> Path:
    """Validate a complete local split before atomically accepting a new snapshot."""
    schema = {"type": "object", "additionalProperties": False,
              "required": ["schema_version", "dataset_id", "source_kind", "source_version", "split", "path", "sha256"],
              "properties": {"schema_version": {"const": "0.1.0"},
                  "dataset_id": {"type": "string", "pattern": "^[a-zA-Z0-9_-]+$"},
                  "source_kind": {"enum": ["official", "fixture", "fork"]},
                  "source_version": {"type": "string", "minLength": 1},
                  "split": {"enum": ["train", "dev", "test"]}, "path": {"type": "string", "minLength": 1},
                  "sha256": {"type": "string", "pattern": "^[a-f0-9]{64}$"}}}
    try:
        jsonschema.Draft202012Validator(schema).validate(settings)
    except jsonschema.ValidationError as error:
        raise RunError("invalid_task_config", "import", "Unsupported NL4Opt import configuration.") from error
    _validate_source(settings)
    official = settings["source_kind"] == "official"
    raw = public_path(config.parent, settings["path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != settings["sha256"]:
        raise RunError("source_hash_mismatch", "import", "Split bytes do not match the configured source hash.")
    if not raw or not raw.endswith(b"\n") or b"\r" in raw:
        raise RunError("invalid_source", "import", "Expected nonempty UTF-8 JSONL with LF record terminators.")
    records = []
    seen: set[str] = set()
    record_schema: dict[str, Any] = {"type": "object", "required": list(RECORD_TYPES), "additionalProperties": False,
                     "properties": {key: {"type": kind} for key, kind in RECORD_TYPES.items()}}
    for key in ("vars", "var_mentions", "params"):
        record_schema["properties"][key]["items"] = {"type": "string"}
    for key in ("const_declarations", "spans", "tokens"):
        record_schema["properties"][key]["items"] = {"type": "object"}
    for key, kind in (("var_mention_to_first_var", "string"), ("order_mapping", "integer")):
        record_schema["properties"][key]["additionalProperties"] = {"type": kind}
    record_schema["properties"]["first_var_to_mentions"]["additionalProperties"] = {
        "type": "array", "items": {"type": "string"}}
    validator = jsonschema.Draft202012Validator(record_schema)
    for line_number, line in enumerate(raw.split(b"\n")[:-1], 1):
        value = parse_reference_json(line)
        if len(value) != 1:
            raise RunError("invalid_source", "import", f"Line {line_number}: expected one sample ID.")
        sample_id, record = next(iter(value.items()))
        if not re.fullmatch(r"-?(0|[1-9][0-9]*)", sample_id) or sample_id in seen:
            raise RunError("duplicate_or_invalid_id", "import", f"Line {line_number}: invalid or duplicate sample ID.")
        try:
            validator.validate(record)
            if not record["document"].strip() or record["_input_hash"] != int(sample_id):
                raise ValueError("Invalid document or upstream ID.")
        except (jsonschema.ValidationError, ValueError) as error:
            raise RunError("invalid_source", "import", f"Line {line_number}: unsupported NL4Opt record schema.") from error
        seen.add(sample_id)
        records.append((sample_id, record, line_number, hashlib.sha256(line).hexdigest()))
    if output.exists():
        raise RunError("snapshot_exists", "import", "Frozen snapshots cannot be overwritten.")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".nl4opt-", dir=output.parent))
    store: RunStore | None = None
    try:
        # Task snapshots are write-once and retain the public/ layout.
        store = RunStore(staging, versioned=False)
        private = store.path / "private"
        private.mkdir(mode=0o700)
        entries = []
        source = {key: settings[key] for key in ("dataset_id", "source_kind", "source_version", "split", "sha256")}
        if official:
            store.write("LICENSE", MIT_LICENSE.encode(), "source-license")
            source["license_reference"] = f"https://github.com/nl4opt/nl4opt-competition/blob/{COMMIT}/LICENSE"
        source.update(source_path=f"generation_data/{settings['split']}.jsonl", license="MIT" if official else "unspecified")
        for sample_id, record, line_number, record_hash in records:
            case_id = f"{settings['dataset_id']}:{settings['source_version']}:{settings['split']}:{sample_id}"
            problem = {"schema_version": "0.2.0", "problem_id": case_id, "revision": record_hash,
                       "description": record["document"], "language": "en", "problem_type_hint": "unknown",
                       "requirements": [], "assumptions": [], "data_refs": [],
                       "source": {key: value for key, value in source.items() if key != "source_path"}}
            validate_problem(problem)
            public_ref = store.json(f"public/{sample_id}.json", problem, case_id)
            public_ref["namespace"] = "task_public"
            annotations = {"schema_version": "0.1.0", "reference_quality": "incomplete_declarations",
                           "variable_domains": "not_available", "reference_objective": None,
                           "annotations": {key: value for key, value in record.items() if key != "document"}}
            oracle_raw = _json(annotations)
            (private / f"{sample_id}.json").write_bytes(oracle_raw)
            (private / f"{sample_id}.json").chmod(0o600)
            entries.append({"case_id": case_id, "sample_id": sample_id, "source_line": line_number,
                            "raw_record_sha256": record_hash, "public_ref": public_ref,
                            "oracle_ref": {"relative_path": f"private/{sample_id}.json",
                                           "sha256": hashlib.sha256(oracle_raw).hexdigest(), "size_bytes": len(oracle_raw),
                                           "namespace": "task_private", "schema_version": "0.1.0"},
                            "selected": True, "eligible": False,
                            "exclusion_reason": "no_reference_objective_or_variable_domains",
                            "reference_quality": "incomplete_declarations"})
        manifest = {"schema_version": "0.1.0", "adapter_id": "llm4om.tasks.nl4opt", "source": source,
                    "projection_revision": "original-document-v0.1", "protocol_id": PROTOCOL,
                    "domain_policy": "unspecified", "normalization_policy": "none",
                    "N_selected": len(entries), "N_eligible": 0, "cases": entries}
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


class FrozenTaskAdapter:
    def iter_cases(self, config: Path) -> Iterator[EvaluationCase]:
        """Read and verify a frozen snapshot, never expose it to a MethodContext."""
        for case in self._cases(config):
            entry = parse_reference_json(case.entry)
            if entry["selected"] is not True:
                continue
            for name, path in (("public_ref", case.public_problem), ("oracle_ref", case.oracle_ref)):
                ref = entry[name]
                content = path.read_bytes()
                if len(content) != ref["size_bytes"] or hashlib.sha256(content).hexdigest() != ref["sha256"]:
                    raise RunError("snapshot_hash_mismatch", "evaluation", "Frozen case bytes changed.")
            yield case

    def load_case(self, config: Path, case_id: str) -> EvaluationCase:
        """Load frozen metadata; the Evaluator records material read/validation failures."""
        case = next((case for case in self._cases(config) if case.case_id == case_id), None)
        if case is None:
            raise RunError("unknown_case", "evaluation", "Case ID is absent from the frozen manifest.")
        return case

    def _cases(self, config: Path) -> Iterator[EvaluationCase]:
        raise NotImplementedError


class NL4OptAdapter(FrozenTaskAdapter):
    def import_source(self, config: Path, output: Path, settings: dict[str, Any]) -> Path:
        source = dict(settings)
        source.pop("adapter_id", None)
        return _import_nl4opt(config, output, source)

    def _cases(self, config: Path) -> Iterator[EvaluationCase]:
        raw = config.read_bytes()
        manifest = parse_reference_json(raw)
        if (manifest.get("schema_version") != "0.1.0" or manifest.get("protocol_id") != PROTOCOL
                or manifest.get("adapter_id") != "llm4om.tasks.nl4opt"
                or manifest.get("N_eligible") != 0 or manifest.get("domain_policy") != "unspecified"
                or manifest.get("projection_revision") != "original-document-v0.1"
                or manifest.get("normalization_policy") != "none"
                or manifest.get("N_selected") != len(manifest.get("cases", []))):
            raise RunError("invalid_manifest", "evaluation", "Unsupported frozen NL4Opt manifest.")
        try:
            _validate_source(manifest["source"])
        except (KeyError, TypeError) as error:
            raise RunError("invalid_manifest", "evaluation", "Manifest source identity is incomplete.") from error
        seen = set()
        for entry in manifest["cases"]:
            if entry["case_id"] in seen or entry["eligible"] is not False:
                raise RunError("invalid_manifest", "evaluation", "Duplicate cases or fabricated eligibility.")
            seen.add(entry["case_id"])
            expected_id = ":".join(str(manifest["source"][key]) for key in ("dataset_id", "source_version", "split")) + ":" + entry["sample_id"]
            if (entry["case_id"] != expected_id or entry["selected"] is not True
                    or entry["reference_quality"] != "incomplete_declarations"
                    or entry["exclusion_reason"] != "no_reference_objective_or_variable_domains"):
                raise RunError("invalid_manifest", "evaluation", "Case identity or raw reference eligibility changed.")
            paths = []
            for name in ("public_ref", "oracle_ref"):
                ref = entry[name]
                path = public_path(config.parent, ref["relative_path"], require_file=False)
                paths.append(path)
            yield EvaluationCase(entry["case_id"], paths[0], paths[1], raw, _json(entry))
