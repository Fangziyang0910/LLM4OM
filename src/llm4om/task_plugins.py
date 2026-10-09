"""Task/Evaluator factories and frozen selections for privileged dataset operations."""

from copy import deepcopy
import hashlib
import json
from importlib.metadata import version, PackageNotFoundError
from pathlib import Path
import tempfile
from typing import Any, Callable, TypeVar, cast
import jsonschema
from llm4om.contracts import RunError, read_config, parse_reference_json, validate_problem, reject_additional_refs, public_path
from llm4om.storage import _atomic
from llm4om.plugins import Plugin, discover_plugins, _quiet, _exception_details
from llm4om.tasks import TaskAdapter, Evaluator, EvaluationCase

T = TypeVar("T")


class _BuiltinFactory:
    def __init__(self, plugin_id: str, kind: str, implementation: type[Any], capabilities: dict[str, Any]) -> None:
        self.plugin_id, self.kind, self.implementation, self.capabilities = plugin_id, kind, implementation, capabilities

    def describe(self) -> dict[str, Any]:
        return {"schema_version": "0.2.0", "plugin_id": self.plugin_id, "kind": self.kind,
            "plugin_version": "0.1.0", "contract_range": ">=0.2.0,<0.3.0",
            "display_name": self.implementation.__name__, "description": "Frozen local-source import or privileged post-run evaluation.",
            "capabilities": deepcopy(self.capabilities), "config_schema": {"type": "object", "additionalProperties": False},
            "dependencies": {"python": []}, "source": None}

    def create(self, config: dict[str, Any]) -> Any:
        if config:
            raise RunError("invalid_config", "admission", "This built-in uses its explicit source/protocol configuration.")
        return self.implementation()


def builtin_factories() -> tuple[_BuiltinFactory, ...]:
    from llm4om.tasks import NL4OptAdapter, PROTOCOL as nl4opt_protocol
    from llm4om.evaluation import NL4OptEvaluator
    from llm4om.mamo import MAMOAdapter, MAMOEvaluator, PROTOCOL as mamo_protocol
    from llm4om.nlp4lp import NLP4LPAdapter, NLP4LPEvaluator, PROTOCOL as nlp4lp_protocol
    from llm4om.checker_tasks import CheckerFixtureAdapter, IndependentCheckerEvaluator, PROTOCOL as checker_protocol
    factories = []
    for name, adapter, evaluator, protocol, levels in (
        ("nl4opt", NL4OptAdapter, NL4OptEvaluator, nl4opt_protocol, ["structural"]),
        ("mamo", MAMOAdapter, MAMOEvaluator, mamo_protocol, ["structural", "objective_match"]),
        ("nlp4lp", NLP4LPAdapter, NLP4LPEvaluator, nlp4lp_protocol, ["structural", "objective_match"]),
        ("checker_fixture", CheckerFixtureAdapter, IndependentCheckerEvaluator, checker_protocol,
         ["structural", "objective_match", "independent_feasibility", "verified_solution", "property_checks"]),
    ):
        evaluator_id = "llm4om.evaluators." + name
        common = {"problem_types": ["lp", "milp"], "protocol_ids": [protocol]}
        factories.append(_BuiltinFactory("llm4om.tasks." + name, "task_adapter", adapter,
            {**common, "input_artifact_kinds": ["task_source"], "output_artifact_kinds": ["evaluation_manifest"],
             "task_profile": "frozen_task/0.1.0", "oracle_separation": "separate_public_private/0.1.0",
             "default_evaluator_id": evaluator_id}))
        factories.append(_BuiltinFactory(evaluator_id, "evaluator", evaluator,
            {**common, "input_artifact_kinds": ["evaluation_case", "run_bundle"], "output_artifact_kinds": ["evaluation_result"],
             "evaluator_profile": "frozen_evaluation/0.1.0", "evidence_levels": levels,
             "oracle_requirements": ["task_private"]}))
    return tuple(factories)


def _call(plugin: Plugin, operation: Callable[[], T], stage: str) -> T:
    try:
        with _quiet():
            return operation()
    except RunError as error:
        raise RunError(error.code, error.stage, "Task/Evaluator operation rejected its input or environment.",
                       details={"plugin_id": plugin.manifest["plugin_id"], **_exception_details(error)}) from error
    except (Exception, SystemExit) as error:
        raise RunError("plugin_operation_error", stage, "The installed Task/Evaluator operation failed.",
                       details={"plugin_id": plugin.manifest["plugin_id"], **_exception_details(error)}) from error


def _select(inventory: dict[tuple[str, str], Plugin], kind: str, plugin_id: str,
            config: dict[str, Any], *, expected: dict[str, Any] | None = None) -> tuple[Plugin, dict[str, Any], Any]:
    if not isinstance(plugin_id, str) or not isinstance(config, dict):
        raise RunError("invalid_config", "admission", "Task/Evaluator selection needs a string ID and object config.")
    plugin = inventory.get((kind, plugin_id))
    if plugin is None:
        raise RunError("checkpoint_incompatible" if expected else "unknown_plugin", "admission", "Requested Task/Evaluator is not installed.")
    try:
        jsonschema.Draft202012Validator(plugin.manifest["config_schema"]).validate(config)
        json.dumps(config, allow_nan=False)
    except (jsonschema.ValidationError, TypeError, ValueError) as error:
        raise RunError("invalid_config", "admission", "Task/Evaluator config does not match its Manifest.") from error
    except (jsonschema.exceptions.RefResolutionError, RecursionError) as error:
        raise RunError("invalid_plugin_manifest", "admission", "Task/Evaluator configuration schema cannot be evaluated.") from error
    packages = {}
    for name in plugin.manifest["dependencies"].get("python", []):
        try:
            packages[name] = version(name)
        except PackageNotFoundError as error:
            raise RunError("dependency_missing", "admission", "A declared Task/Evaluator dependency is absent.") from error
    binding = {"manifest": plugin.manifest, "origin": plugin.origin, "config": deepcopy(config), "packages": packages}
    if expected is not None and binding != expected:
        raise RunError("checkpoint_incompatible", "evaluation", "Frozen Task/Evaluator identity changed before construction.")
    instance = _call(plugin, lambda: plugin.factory.create(deepcopy(config)), "admission")
    required = ("import_source", "iter_cases", "load_case") if kind == "task_adapter" else ("evaluate",)
    if any(not callable(getattr(instance, name, None)) for name in required):
        raise RunError("invalid_plugin_manifest", "admission", "Factory does not implement its declared Task/Evaluator profile.")
    return plugin, binding, instance


def _runtime() -> dict[str, str]:
    from llm4om.application import _sdk_sha256
    return {"sdk_version": version("llm4om"), "sdk_sha256": _sdk_sha256()}


def _prepare_task(settings: dict[str, Any]) -> tuple[Plugin, TaskAdapter, dict[str, Any]]:
    inventory = discover_plugins()
    task_plugin, task_binding, adapter = _select(inventory, "task_adapter", settings.get("adapter_id", "llm4om.tasks.nl4opt"), settings.pop("adapter_config", {}))
    evaluation = settings.pop("evaluation", {"evaluator_plugin_id": task_plugin.manifest["capabilities"]["default_evaluator_id"], "config": {}})
    if not isinstance(evaluation, dict) or set(evaluation) != {"evaluator_plugin_id", "config"}:
        raise RunError("invalid_config", "admission", "Evaluation selection needs explicit evaluator_plugin_id and config.")
    evaluator_plugin, evaluator_binding, _ = _select(inventory, "evaluator", evaluation["evaluator_plugin_id"], evaluation["config"])
    if not set(task_plugin.manifest["capabilities"]["protocol_ids"]) & set(evaluator_plugin.manifest["capabilities"]["protocol_ids"]):
        raise RunError("capability_mismatch", "admission", "Task and Evaluator have no shared declared protocol.")
    return task_plugin, cast(TaskAdapter, adapter), {"schema_version": "0.1.0", "runtime": _runtime(), "task_adapter": task_binding, "evaluator": evaluator_binding}


def prepare_task(config: Path) -> dict[str, Any]:
    """Check installed selections without reading or importing task source material."""
    return _prepare_task(read_config(config))[2]


def import_registered_task(config: Path, output: Path) -> Path:
    settings = read_config(config)
    if output.exists() or output.is_symlink():
        raise RunError("snapshot_exists", "import", "Frozen snapshots cannot be overwritten.")
    task_plugin, adapter, binding = _prepare_task(settings)
    evaluator_manifest = binding["evaluator"]["manifest"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".task-registry-", dir=output.parent) as directory:
        staging = Path(directory).resolve() / "snapshot"
        manifest_path = _call(task_plugin, lambda: adapter.import_source(config, staging, settings), "import")
        if not isinstance(manifest_path, Path) or manifest_path.resolve() != (staging / "manifest.json").resolve():
            raise RunError("invalid_manifest", "import", "Adapter must publish its manifest inside the assigned staging directory.")
        manifest = parse_reference_json(manifest_path.read_bytes())
        protocol = manifest.get("protocol_id")
        if manifest.get("adapter_id") != task_plugin.manifest["plugin_id"] or any(protocol not in item["capabilities"]["protocol_ids"] for item in (task_plugin.manifest, evaluator_manifest)):
            raise RunError("capability_mismatch", "import", "Imported manifest differs from the declared Task/Evaluator protocol.")
        cases = _call(task_plugin, lambda: list(adapter.iter_cases(manifest_path)), "import")
        if any(not isinstance(case, EvaluationCase) for case in cases):
            raise RunError("invalid_manifest", "import", "Task iterator must return EvaluationCase records.")
        entries = manifest.get("cases")
        if not isinstance(entries, list) or any(not isinstance(entry, dict) or not isinstance(entry.get("case_id"), str)
                or type(entry.get("selected")) is not bool or type(entry.get("eligible")) is not bool for entry in entries):
            raise RunError("invalid_manifest", "import", "Case census needs unique IDs and explicit selection/eligibility.")
        selected = [entry for entry in entries if entry["selected"]]
        eligible = manifest.get("N_eligible", manifest.get("N_independent_eligible"))
        if (len({entry["case_id"] for entry in entries}) != len(entries)
                or type(manifest.get("N_selected")) is not int or manifest["N_selected"] != len(selected)
                or type(eligible) is not int or eligible != sum(entry["eligible"] for entry in selected)
                or len(cases) != len(selected) or {case.case_id for case in cases} != {entry["case_id"] for entry in selected}):
            raise RunError("invalid_manifest", "import", "Frozen census differs from actual selected unique cases.")
        for case in cases:
            if not case.public_problem.resolve().is_relative_to(staging / "public") or not case.oracle_ref.resolve().is_relative_to(staging / "private"):
                raise RunError("private_input", "import", "Task public/private projections must stay in separate assigned directories.")
            validate_problem(parse_reference_json(case.public_problem.read_bytes()))
            _validate_case(case, manifest_path, manifest, case.case_id)
        manifest["plugin_bindings"] = binding
        raw = (json.dumps(manifest, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
        _atomic(manifest_path, raw)
        _atomic(staging / "private/import-seal.json", (json.dumps({"schema_version": "0.1.0", "manifest_sha256": hashlib.sha256(raw).hexdigest()}) + "\n").encode())
        staging.rename(output)
    return output.resolve() / "manifest.json"


def load_registered_case(manifest_path: Path, case_id: str) -> tuple[Plugin, Evaluator, EvaluationCase, dict[str, Any]]:
    manifest = parse_reference_json(manifest_path.read_bytes())
    if not isinstance(manifest.get("adapter_id"), str):
        raise RunError("invalid_manifest", "evaluation", "Frozen manifest needs a Task adapter ID.")
    inventory = discover_plugins()
    saved = manifest.get("plugin_bindings")
    seal = manifest_path.parent / "private/import-seal.json"
    if saved is not None or seal.exists():
        try:
            expected = parse_reference_json(seal.read_bytes())
            if expected != {"schema_version": "0.1.0", "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}:
                raise ValueError("Frozen manifest changed.")
        except (OSError, ValueError) as error:
            raise RunError("checkpoint_incompatible", "evaluation", "Imported manifest differs from its private seal.") from error
    if saved is None:
        task_id = str(manifest["adapter_id"])
        plugin = inventory.get(("task_adapter", task_id))
        if plugin is None or plugin.origin["kind"] != "builtin":
            raise RunError("checkpoint_incompatible", "evaluation", "Unbound legacy manifests are only accepted for explicit built-in Task profiles.")
        _, task_binding, adapter = _select(inventory, "task_adapter", task_id, {})
        evaluator_plugin, evaluator_binding, evaluator = _select(inventory, "evaluator", plugin.manifest["capabilities"]["default_evaluator_id"], {})
        status = "legacy_unbound"
    else:
        if saved.get("schema_version") != "0.1.0" or saved.get("runtime") != _runtime():
            raise RunError("checkpoint_incompatible", "evaluation", "Frozen import runtime identity changed.")
        task = saved["task_adapter"]
        evaluation = saved["evaluator"]
        _, task_binding, adapter = _select(inventory, "task_adapter", task["manifest"]["plugin_id"], task["config"], expected=task)
        evaluator_plugin, evaluator_binding, evaluator = _select(inventory, "evaluator", evaluation["manifest"]["plugin_id"], evaluation["config"], expected=evaluation)
        if task_binding != task or evaluator_binding != evaluation:
            raise RunError("checkpoint_incompatible", "evaluation", "Frozen Task/Evaluator package, Manifest or config identity changed.")
        status = "frozen"
    case = _call(inventory[("task_adapter", manifest["adapter_id"])], lambda: cast(TaskAdapter, adapter).load_case(manifest_path, case_id), "evaluation")
    _validate_case(case, manifest_path, manifest, case_id)
    identity = {"binding_status": status, "runtime": _runtime(), "task_adapter": {key: value for key, value in task_binding.items() if key != "config"},
                "evaluator": {key: value for key, value in evaluator_binding.items() if key != "config"}}
    return evaluator_plugin, cast(Evaluator, evaluator), case, identity


def _validate_case(case: EvaluationCase, path: Path, manifest: dict[str, Any], case_id: str) -> None:
    try:
        entry = parse_reference_json(case.entry)
        if not isinstance(case, EvaluationCase) or case.case_id != case_id or entry not in manifest["cases"] or entry["case_id"] != case_id or case.manifest != path.read_bytes():
            raise ValueError("Returned case differs from its frozen metadata.")
        for field, actual, directory, namespace in (("public_ref", case.public_problem, "public", "task_public"), ("oracle_ref", case.oracle_ref, "private", "task_private")):
            expected = public_path(path.parent, entry[field]["relative_path"], require_file=False)
            if expected != actual.resolve() or not expected.is_relative_to((path.parent / directory).resolve()) or entry[field]["namespace"] != namespace:
                raise ValueError("Case projections differ from their assigned references.")
    except (Exception, SystemExit) as error:
        raise RunError("invalid_case", "evaluation", "Task returned an invalid public/private case binding.") from error


def validate_evaluation_result(result: dict[str, Any], case: EvaluationCase, plugin: Plugin, outcome: Path) -> None:
    fields = set((
        "schema_version protocol_id case_id manifest_sha256 source projection_revision domain_policy normalization_policy "
        "raw_record_sha256 reference_quality reference_diagnostic reference_counts data_binding_policy variable_mapping "
        "selected eligible exclusion_reason tolerance N_selected N_eligible N_evaluated "
        "objective_match_numerator objective_match_denominator objective_match_rate independent_feasibility objective_match "
        "semantic_validation formulation_validation code_validation execution candidate_primal case_binding run_id run_status "
        "run_error checker_error N_verified_eligible verified_eligible original_objective original_objective_quality "
        "reported_objective_match objective_consistency verified_solution verified_solution_numerator verified_solution_denominator "
        "verified_solution_rate independent_feasibility_numerator independent_feasibility_denominator independent_feasibility_rate "
        "property_checks decision_mapping checker_identity"
    ).split())
    try:
        json.dumps(result, allow_nan=False)
        _public_result(result, outcome)
        manifest, entry = parse_reference_json(case.manifest), parse_reference_json(case.entry)
        if (not isinstance(result, dict) or set(result) - fields or result.get("schema_version") not in {"0.1.0", "0.2.0"}
                or result.get("case_id") != case.case_id or result.get("protocol_id") != manifest["protocol_id"]
                or result.get("manifest_sha256") != hashlib.sha256(case.manifest).hexdigest()
                or result.get("eligible") is not entry["eligible"] or result.get("N_selected") != manifest["N_selected"]
                or type(result.get("N_selected")) is not int or type(result.get("N_evaluated")) is not int
                or result.get("N_evaluated") != 1
                or result.get("N_eligible") != manifest.get("N_eligible", manifest.get("N_independent_eligible", 0))
                or type(result.get("N_eligible")) is not int or result.get("source") != manifest["source"]):
            raise ValueError("Invalid evaluation binding or public fields.")
        try:
            bundle = parse_reference_json((outcome / "bundle.json").read_bytes())
        except (OSError, ValueError):
            if result.get("checker_error") is None:
                raise ValueError("Missing outcome requires an explicit evaluation error.")
        else:
            if bundle.get("schema_version") == "0.2.0" and {"run_id", "status"} <= bundle.keys():
                if result.get("run_id") != bundle["run_id"] or result.get("run_status") != bundle["status"]:
                    raise ValueError("Result belongs to another actual run.")
            elif result.get("checker_error") is None:
                raise ValueError("Result belongs to another actual run.")
        levels = plugin.manifest["capabilities"]["evidence_levels"]
        for field, capability in {"formulation_validation": "structural", "code_validation": "structural",
            "objective_match": "objective_match", "independent_feasibility": "independent_feasibility",
            "verified_solution": "verified_solution", "semantic_validation": "semantic_validation", "property_checks": "property_checks"}.items():
            if result.get(field, {}).get("status") in {"pass", "fail", "complete"} and capability not in levels:
                raise ValueError("Evaluator claims undeclared evidence.")
        for prefix, eligibility in (("objective_match", "eligible"), ("independent_feasibility", "eligible"), ("verified_solution", "verified_eligible")):
            numerator, denominator, rate = (result.get(prefix + suffix) for suffix in ("_numerator", "_denominator", "_rate"))
            if any(prefix + suffix in result for suffix in ("_numerator", "_denominator")):
                if (type(numerator) is not int or type(denominator) is not int or not 0 <= numerator <= denominator
                        or denominator != int(entry.get(eligibility, False))
                        or (rate is not None and type(rate) not in {float, int})
                        or rate != (numerator / denominator if denominator else None)):
                    raise ValueError("Invalid frozen denominator or rate.")
                if (result.get(prefix, {}).get("status") == "pass") != (numerator == 1):
                    raise ValueError("Metric status contradicts its success count.")
    except (Exception, SystemExit) as error:
        raise RunError("invalid_evaluation_result", "evaluation", "Evaluator returned invalid bound public evidence.") from error


def _public_result(value: Any, outcome: Path) -> None:
    if isinstance(value, dict):
        forbidden = {"oracle", "oracle_ref", "reference_objective", "reference_value", "reference_solution", "reference_code", "ground_truth", "private_sentinel", "raw_oracle", "annotations"}
        if set(value) & forbidden:
            raise ValueError("Privileged evaluation fields cannot be exported.")
        if "relative_path" in value or "namespace" in value:
            from llm4om.evaluation import _verify_ref
            bundle = parse_reference_json((outcome / "bundle.json").read_bytes())
            if value.get("namespace") != "run_public" or value not in bundle["artifacts"]:
                raise ValueError("Only actual public run diagnostic references can be exported.")
            _verify_ref(outcome, value)
        for child in value.values():
            _public_result(child, outcome)
    elif isinstance(value, list):
        for child in value:
            _public_result(child, outcome)


def evaluation_error(case: EvaluationCase, outcome: Path, plugin: Plugin, error: RunError) -> dict[str, Any]:
    from llm4om.evaluation import evaluate_outcome
    manifest, entry = parse_reference_json(case.manifest), parse_reference_json(case.entry)
    unavailable = {"status": "not_available"}
    result: dict[str, Any] = {"schema_version": "0.2.0", "protocol_id": manifest["protocol_id"], "case_id": case.case_id,
        "manifest_sha256": hashlib.sha256(case.manifest).hexdigest(), "source": manifest["source"],
        "projection_revision": manifest["projection_revision"], "eligible": entry["eligible"],
        "N_selected": manifest["N_selected"], "N_eligible": manifest.get("N_eligible", manifest.get("N_independent_eligible", 0)),
        "N_evaluated": 1, "objective_match": {"status": "error"}, "independent_feasibility": dict(unavailable),
        "semantic_validation": dict(unavailable), "formulation_validation": dict(unavailable), "code_validation": dict(unavailable),
        "execution": dict(unavailable), "candidate_primal": dict(unavailable), "case_binding": dict(unavailable),
        "run_id": None, "run_status": "unknown", "run_error": None, "checker_error": None}
    for prefix, eligibility in (("objective_match", "eligible"), ("independent_feasibility", "eligible"), ("verified_solution", "verified_eligible")):
        if prefix in plugin.manifest["capabilities"]["evidence_levels"]:
            denominator = int(entry.get(eligibility, False))
            result.update({prefix: {"status": "error"}, prefix + "_numerator": 0, prefix + "_denominator": denominator,
                           prefix + "_rate": 0.0 if denominator else None})
    evaluate_outcome(case, outcome, result)
    result["checker_error"] = {"code": "evaluator_error", "message": "Registered evaluator failed; frozen eligibility is retained.",
                               "diagnostic": error.details}
    return result
