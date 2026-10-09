"""Resolve and validate a supported run before a method receives resources."""

from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import Any

import jsonschema

from llm4om.contracts import RunError, validate_config
from llm4om.highs import runtime_versions
from llm4om.plugins import MethodPlugin, discover_methods


@dataclass(frozen=True)
class AdmissionPlan:
    method: MethodPlugin
    snapshot: dict[str, Any]


def prepare_run(settings: dict[str, Any], *, offline: bool = False) -> AdmissionPlan:
    validate_config(settings)
    inventory = discover_methods()
    method = inventory.get(("method", settings["method"]["plugin_id"]))
    if method is None:
        raise RunError("unknown_plugin", "admission", "The requested modeling method is not installed.")
    try:
        jsonschema.Draft202012Validator(method.manifest["config_schema"]).validate(settings["method"]["config"])
    except jsonschema.ValidationError as error:
        raise RunError("invalid_config", "admission", "Method config does not match its Manifest.",
                       details={"path": ["method", "config", *error.absolute_path]}) from error
    if not offline and settings["executor"]["plugin_id"] != "llm4om.executors.trusted_local":
        raise RunError("offline_required", "admission", "Select trusted_local or offline mode; container execution is not implemented.")
    capabilities = method.manifest["capabilities"]
    required = {"method_profile": "grounded_single_candidate/0.1.0",
                "input_artifact_kinds": ["public_problem"], "output_artifact_kinds": ["model_artifact"],
                "formulation_representations": ["five_element"], "code_representations": ["python_factory"],
                "model_backends": [settings["model_backend"]["plugin_id"]], "solvers": [settings["solver"]["plugin_id"]],
                "llm_features": ["text"], "oracle_requirements": []}
    if not offline:
        required["execution_modes"] = [settings["executor"]["plugin_id"].removeprefix("llm4om.executors.")]
    for field, value in required.items():
        declared = capabilities.get(field)
        compatible = (isinstance(declared, list) and set(value) <= set(declared)) if field in {
            "input_artifact_kinds", "output_artifact_kinds", "model_backends", "solvers", "execution_modes"} else declared == value
        if not compatible:
            raise RunError("capability_mismatch", "admission", "A method capability is unknown or incompatible with this profile.",
                           details={"path": ["method", "capabilities", field]})
    allowed_types = settings.get("allowed_problem_types", ["lp", "milp"])
    if not set(allowed_types) <= set(capabilities["problem_types"]):
        raise RunError("capability_mismatch", "admission", "Method cannot produce every configured problem type.",
                       details={"path": ["method", "capabilities", "problem_types"]})
    packages = {}
    for name in method.manifest["dependencies"].get("python", []):
        try:
            packages[name] = version(name)
        except PackageNotFoundError as error:
            raise RunError("dependency_missing", "admission", "A declared method dependency is not installed.",
                           details={"distribution": name}) from error
    if not offline and settings["budget"]["max_solver_calls"] < 1:
        raise RunError("budget_exhausted", "admission", "Real solving requires one Solver call slot.")
    if not offline:
        packages.update(runtime_versions())
    return AdmissionPlan(method, {"schema_version": "0.2.0", "mode": "offline_mock" if offline else "trusted_local",
        "method": {"manifest": method.manifest, "origin": method.origin},
        "compiler_id": settings["compiler"]["plugin_id"], "model_backend_id": settings["model_backend"]["plugin_id"],
        "solver_id": settings["solver"]["plugin_id"], "executor_id": settings["executor"]["plugin_id"],
        "packages": packages, "budget": settings["budget"], "allowed_problem_types": allowed_types})
