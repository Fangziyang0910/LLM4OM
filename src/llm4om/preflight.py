"""Resolve and validate a supported run before a method receives resources."""

from dataclasses import dataclass
import time
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Any
from pathlib import Path
from llm4om.providers import credential_environment, provider_factory, MockProvider, OpenAICompatibleProvider, OpenAICompatibleFactory

import jsonschema

from llm4om.contracts import RunError, parse_json, validate_config
from llm4om.executors import worker_runtime, container_runtime, run_owned_process, DEFAULT_IMAGE
from llm4om.solvers import solver_packages
from llm4om.control import CancellationToken
from llm4om.plugins import MethodPlugin, discover_methods


@dataclass(frozen=True)
class AdmissionPlan:
    method: MethodPlugin
    snapshot: dict[str, Any]
    provider: MockProvider | OpenAICompatibleProvider | None
    deadline: float


def prepare_run(settings: dict[str, Any], *, offline: bool = False, config_dir: Path | None = None,
                deadline: float | None = None, cancellation: CancellationToken | None = None,
                expected: dict[str, Any] | None = None, identity_only: bool = False) -> AdmissionPlan:
    started = time.time()
    if cancellation is not None:
        cancellation.check()
    validate_config(settings)
    deadline = deadline if deadline is not None else started + settings["budget"]["wall_time_s"]
    if time.time() >= deadline:
        raise RunError("deadline_exhausted", "admission", "The absolute run deadline expired.")
    factory = provider_factory(settings["llm"]["provider_plugin_id"])
    if offline and settings["llm"]["provider_plugin_id"] != "llm4om.providers.mock":
        raise RunError("capability_mismatch", "admission", "Offline replay requires an explicitly configured Mock Provider.")
    provider = None
    if not identity_only:
        credential_path = (config_dir or Path.cwd()) / ".env"
        if not credential_path.exists():
            credential_path = Path.cwd() / ".env"
        environment = (dict(os.environ) if isinstance(factory, OpenAICompatibleFactory)
                       and os.environ.get(settings["llm"]["config"].get("credential_env", ""))
                       else credential_environment(credential_path) if isinstance(factory, OpenAICompatibleFactory) else None)
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
    method = method.resolve(settings["method"]["config"])
    execution_mode = settings["executor"]["plugin_id"].removeprefix("llm4om.executors.")
    capabilities = method.manifest["capabilities"]
    profile = capabilities.get("method_profile")
    if profile not in ("grounded_single_candidate/0.1.0", "factory_single_candidate/0.1.0", "native_single_candidate/0.1.0"):
        raise RunError("capability_mismatch", "admission", "Method profile is not supported.")
    if profile in ("factory_single_candidate/0.1.0", "native_single_candidate/0.1.0") and (offline or execution_mode != "container"):
        raise RunError("capability_mismatch", "admission", "Generated factories require container execution, including generation.")
    if profile == "grounded_single_candidate/0.1.0" and "compiler" not in settings:
        raise RunError("invalid_config", "admission", "Grounded LPIR requires its explicit compiler.")
    native = profile == "native_single_candidate/0.1.0"
    if settings["model_backend"]["plugin_id"] != ("llm4om.model_backends.gurobipy" if native else "llm4om.model_backends.pyomo_factory") or native and settings["solver"]["plugin_id"] != "llm4om.solvers.gurobi":
        raise RunError("capability_mismatch", "admission", "The output profile is incompatible with the selected Backend/Solver.")
    required = {"method_profile": profile,
                "input_artifact_kinds": ["public_problem"], "output_artifact_kinds": ["model_artifact"],
                "formulation_representations": ["five_element"], "code_representations": ["native_code" if native else "python_factory"],
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
    if expected is not None:
        if ({"manifest": method.manifest, "origin": method.origin} != expected["method"]
                or profile != expected["method_profile"]
                or any(expected["packages"].get(name) != value for name, value in packages.items())):
            raise RunError("checkpoint_incompatible", "admission", "Method profile, manifest or package identity changed.")
        for name, saved_version in expected["packages"].items():
            if execution_mode != "container" or name in method.manifest["dependencies"].get("python", []):
                try:
                    if version(name) != saved_version:
                        raise RunError("checkpoint_incompatible", "admission", "A saved resource package changed.")
                except PackageNotFoundError as error:
                    raise RunError("checkpoint_incompatible", "admission", "A saved resource package is absent.") from error
    if not offline and settings["budget"]["max_solver_calls"] < 1:
        raise RunError("budget_exhausted", "admission", "Real solving requires one Solver call slot.")
    worker = None
    local_runtime: dict[str, Any] = {}
    if not offline:
        if execution_mode == "container":
            if expected is not None:
                runtime = container_runtime(settings["executor"]["config"].get("image", DEFAULT_IMAGE),
                                            deadline=deadline, cancellation=cancellation)
                if runtime["image_id"] != expected["worker"]["image_id"]:
                    raise RunError("checkpoint_incompatible", "admission", "Worker image identity changed.")
                worker = expected["worker"]
            else:
                worker = worker_runtime(settings["executor"]["config"], deadline=deadline, cancellation=cancellation,
                                        solver_id=settings["solver"]["plugin_id"])
            packages.update(worker["packages"])
        else:
            if expected is not None:
                local_runtime = {"packages": expected["packages"], "solver_environment": expected.get("solver_environment")}
            else:
                solver_packages(settings["solver"]["plugin_id"])
                out, _, code = run_owned_process([sys.executable, "-m", "llm4om.worker", "--runtime", "--solver", settings["solver"]["plugin_id"]],
                                                b"", deadline=deadline, cancellation=cancellation or CancellationToken())
                payload = parse_json(out)
                if code != 0 or "runtime" not in payload:
                    runtime_error = payload.get("error", {})
                    raise RunError(runtime_error.get("code", "dependency_missing"), "admission", "The owned Solver runtime check failed.")
                local_runtime = payload["runtime"]
            packages.update(local_runtime["packages"])
    return AdmissionPlan(method, {"schema_version": "0.2.0", "mode": "offline_mock" if offline else execution_mode,
        "method": {"manifest": method.manifest, "origin": method.origin},
        "method_profile": profile, "method_cancellation": capabilities.get("cancellation", "unknown"), "code_origin": "method_generated" if profile in ("factory_single_candidate/0.1.0", "native_single_candidate/0.1.0") else "deterministic_compilation",
        "compiler_id": settings["compiler"]["plugin_id"] if profile == "grounded_single_candidate/0.1.0" else None, "model_backend_id": settings["model_backend"]["plugin_id"],
        "solver_id": settings["solver"]["plugin_id"], "executor_id": settings["executor"]["plugin_id"],
        "packages": packages, "solver_environment": (worker or local_runtime).get("solver_environment"), "worker": worker, "budget": settings["budget"], "allowed_problem_types": allowed_types, "provider": factory.describe(), "model": settings["llm"]["model"]}, provider, deadline)
