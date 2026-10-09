"""Resolve and validate a supported run before a method receives resources."""

from dataclasses import dataclass
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from pathlib import Path
from llm4om.providers import credential_environment, provider_factory, MockProvider, OpenAICompatibleProvider, OpenAICompatibleFactory

import jsonschema

from llm4om.contracts import RunError, validate_config
from llm4om.highs import runtime_versions
from llm4om.executors import worker_runtime
from llm4om.plugins import MethodPlugin, discover_methods


@dataclass(frozen=True)
class AdmissionPlan:
    method: MethodPlugin
    snapshot: dict[str, Any]
    provider: MockProvider | OpenAICompatibleProvider
    deadline: float


def prepare_run(settings: dict[str, Any], *, offline: bool = False, config_dir: Path | None = None) -> AdmissionPlan:
    started = time.time()
    validate_config(settings)
    factory = provider_factory(settings["llm"]["provider_plugin_id"])
    if offline and settings["llm"]["provider_plugin_id"] != "llm4om.providers.mock":
        raise RunError("capability_mismatch", "admission", "Offline replay requires an explicitly configured Mock Provider.")
    credential_path = (config_dir or Path.cwd()) / ".env"
    if not credential_path.exists():
        credential_path = Path.cwd() / ".env"
    environment = credential_environment(credential_path) if isinstance(factory, OpenAICompatibleFactory) else None
    provider = factory.create(settings["llm"]["config"], settings["llm"]["model"], environment=environment)
    inventory = discover_methods()
    method = inventory.get(("method", settings["method"]["plugin_id"]))
    if method is None:
        raise RunError("unknown_plugin", "admission", "The requested modeling method is not installed.")
    try:
        jsonschema.Draft202012Validator(method.manifest["config_schema"]).validate(settings["method"]["config"])
    except jsonschema.ValidationError as error:
        raise RunError("invalid_config", "admission", "Method config does not match its Manifest.",
                       details={"path": ["method", "config", *error.absolute_path]}) from error
    except (jsonschema.exceptions.RefResolutionError, RecursionError) as error:
        raise RunError("invalid_plugin_manifest", "admission", "Method configuration schema cannot be resolved or evaluated.",
                       details={"path": ["method", "config_schema"]}) from error
    execution_mode = settings["executor"]["plugin_id"].removeprefix("llm4om.executors.")
    capabilities = method.manifest["capabilities"]
    required = {"method_profile": "grounded_single_candidate/0.1.0",
                "input_artifact_kinds": ["public_problem"], "output_artifact_kinds": ["model_artifact"],
                "formulation_representations": ["five_element"], "code_representations": ["python_factory"],
                "model_backends": [settings["model_backend"]["plugin_id"]], "solvers": [settings["solver"]["plugin_id"]],
                "llm_features": ["text"], "oracle_requirements": []}
    if not offline:
        required["execution_modes"] = [settings["executor"]["plugin_id"].removeprefix("llm4om.executors.")]
    if not set(capabilities.get("llm_features", [])) <= set(factory.describe()["features"]):
        raise RunError("capability_mismatch", "admission", "Provider does not support the requested method features.")
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
    worker = None
    if not offline:
        if execution_mode == "container":
            worker = worker_runtime(settings["executor"]["config"], deadline=started + settings["budget"]["wall_time_s"])
            packages.update(worker["packages"])
        else:
            packages.update(runtime_versions())
    return AdmissionPlan(method, {"schema_version": "0.2.0", "mode": "offline_mock" if offline else execution_mode,
        "method": {"manifest": method.manifest, "origin": method.origin},
        "compiler_id": settings["compiler"]["plugin_id"], "model_backend_id": settings["model_backend"]["plugin_id"],
        "solver_id": settings["solver"]["plugin_id"], "executor_id": settings["executor"]["plugin_id"],
        "packages": packages, "worker": worker, "budget": settings["budget"], "allowed_problem_types": allowed_types, "provider": factory.describe(), "model": settings["llm"]["model"]}, provider, started + settings["budget"]["wall_time_s"])
