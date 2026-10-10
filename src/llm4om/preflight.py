"""Resolve and validate a supported run before a method receives resources."""

from dataclasses import dataclass, field
from functools import partial
import time
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable
from pathlib import Path
from llm4om.providers import credential_environment, MockProvider, HTTPTextProvider, HTTPTextFactory

import jsonschema

from llm4om.contracts import RunError, parse_json, validate_config
from llm4om.executors import worker_runtime, container_runtime, run_owned_process, DEFAULT_IMAGE
from llm4om.solvers import solver_packages
from llm4om.control import CancellationToken
from llm4om.plugins import MethodPlugin, Plugin, discover_plugins, _quiet, _exception_details
from llm4om.compilers import ResolvedCompiler, resolve_compiler, compiler_identity


@dataclass(frozen=True)
class AdmissionPlan:
    method: MethodPlugin
    snapshot: dict[str, Any]
    provider: MockProvider | HTTPTextProvider | None
    deadline: float
    role_providers: dict[str, HTTPTextProvider] = field(default_factory=dict)
    compiler: ResolvedCompiler | None = None


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
    inventory = discover_plugins()
    provider_plugin = inventory.get(("llm_provider", settings["llm"]["provider_plugin_id"]))
    if provider_plugin is None:
        raise RunError("unknown_plugin", "admission", "Requested Provider is not installed.")
    factory = provider_plugin.factory
    if isinstance(factory, HTTPTextFactory):
        _call_provider(lambda: factory.validate(settings["llm"]["config"], settings["llm"]["model"]), provider_plugin)
    _validate_plugin_config(provider_plugin, settings["llm"]["config"], ["llm", "config"])
    role_models = settings["llm"].get("role_models", {})
    role_factories: dict[str, HTTPTextFactory] = {}
    selected_providers = [provider_plugin]
    for role, selection in role_models.items():
        role_plugin = inventory.get(("llm_provider", selection["provider_plugin_id"]))
        if role_plugin is None:
            raise RunError("unknown_plugin", "admission", "Requested role Provider is not installed.")
        selected_providers.append(role_plugin)
        role_factory = role_plugin.factory
        if not isinstance(factory, HTTPTextFactory) or not isinstance(role_factory, HTTPTextFactory) or offline:
            raise RunError("capability_mismatch", "admission", "Role routing requires declared online HTTP text Providers.")
        _call_provider(lambda: role_factory.validate(selection["config"], selection["model"]), role_plugin)
        _validate_plugin_config(role_plugin, selection["config"], ["llm", "role_models", role, "config"])
        role_factories[role] = role_factory
    packages = {}
    for selected in selected_providers:
        for name in selected.manifest["dependencies"].get("python", []):
            try:
                packages[name] = version(name)
            except PackageNotFoundError as error:
                raise RunError("dependency_missing", "admission", "A declared Provider dependency is not installed.",
                               details={"plugin_id": selected.manifest["plugin_id"], "distribution": name}) from error
    if offline and settings["llm"]["provider_plugin_id"] != "llm4om.providers.mock":
        raise RunError("capability_mismatch", "admission", "Offline replay requires an explicitly configured Mock Provider.")
    provider: MockProvider | HTTPTextProvider | None = None
    role_providers: dict[str, HTTPTextProvider] = {}
    if not identity_only:
        def environment(credential_name: str) -> dict[str, str]:
            if os.environ.get(credential_name):
                return dict(os.environ)
            credential_path = (config_dir or Path.cwd()) / ".env"
            if not credential_path.exists():
                credential_path = Path.cwd() / ".env"
            return credential_environment(credential_path)
        if isinstance(factory, HTTPTextFactory):
            default_credential_name = settings["llm"]["config"]["credential_env"]
            provider = _call_provider(lambda: (factory.restore(settings["llm"]["config"], settings["llm"]["model"], environment=lambda: environment(default_credential_name))
                        if expected is not None else factory.create(settings["llm"]["config"], settings["llm"]["model"], environment=environment(default_credential_name))), provider_plugin)
        else:
            provider = _call_provider(lambda: factory.create(settings["llm"]["config"], settings["llm"]["model"]), provider_plugin)
        for role, selected_factory in role_factories.items():
            selection = role_models[role]
            role_providers[role] = _call_provider(lambda: (selected_factory.restore(selection["config"], selection["model"],
                environment=partial(environment, selection["config"]["credential_env"]))
                if expected is not None else selected_factory.create(selection["config"], selection["model"], environment=environment(selection["config"]["credential_env"]))),
                inventory[("llm_provider", selection["provider_plugin_id"])])
    method = inventory.get(("method", settings["method"]["plugin_id"]))
    if not isinstance(method, MethodPlugin):
        raise RunError("unknown_plugin", "admission", "The requested modeling method is not installed.")
    _validate_plugin_config(method, settings["method"]["config"], ["method", "config"])
    method = method.resolve(settings["method"]["config"])
    execution_mode = settings["executor"]["plugin_id"].removeprefix("llm4om.executors.")
    capabilities = method.manifest["capabilities"]
    profile = capabilities.get("method_profile")
    if profile not in ("grounded_single_candidate/0.1.0", "grounded_candidates/0.1.0", "factory_single_candidate/0.1.0", "factory_candidates/0.1.0", "native_single_candidate/0.1.0", "native_candidates/0.1.0", "native_script/0.1.0", "native_script/0.2.0"):
        raise RunError("capability_mismatch", "admission", "Method profile is not supported.")
    if profile == "grounded_candidates/0.1.0" and offline:
        raise RunError("capability_mismatch", "admission", "Candidate assessment requires an actual Solver execution plan.")
    if profile in ("factory_single_candidate/0.1.0", "factory_candidates/0.1.0", "native_single_candidate/0.1.0", "native_candidates/0.1.0", "native_script/0.1.0", "native_script/0.2.0") and (offline or execution_mode != "container"):
        raise RunError("capability_mismatch", "admission", "Generated factories require container execution, including generation.")
    if profile in ("grounded_single_candidate/0.1.0", "grounded_candidates/0.1.0") and "compiler" not in settings:
        raise RunError("invalid_config", "admission", "Grounded LPIR requires its explicit compiler.")
    native = profile in ("native_single_candidate/0.1.0", "native_candidates/0.1.0", "native_script/0.1.0", "native_script/0.2.0")
    if settings["model_backend"]["plugin_id"] != ("llm4om.model_backends.gurobipy" if native else "llm4om.model_backends.pyomo_factory") or native and settings["solver"]["plugin_id"] != "llm4om.solvers.gurobi":
        raise RunError("capability_mismatch", "admission", "The output profile is incompatible with the selected Backend/Solver.")
    compiler = resolve_compiler(settings["compiler"], settings["model_backend"]["plugin_id"], inventory=inventory,
        expected=expected.get("compiler") if expected else None) if profile in ("grounded_single_candidate/0.1.0", "grounded_candidates/0.1.0") else None
    if compiler is not None:
        packages.update(compiler.binding["packages"])
    required = {"method_profile": profile,
                "input_artifact_kinds": ["public_problem"], "output_artifact_kinds": ["model_artifact"],
                "formulation_representations": [] if profile == "native_script/0.2.0" else ["native_formulation" if profile == "native_script/0.1.0" else "five_element"], "code_representations": ["native_script" if profile.startswith("native_script/") else "native_code" if native else "python_factory"],
                "model_backends": [settings["model_backend"]["plugin_id"]], "solvers": [settings["solver"]["plugin_id"]],
                "llm_features": ["text"], "oracle_requirements": []}
    if not offline:
        required["execution_modes"] = [settings["executor"]["plugin_id"].removeprefix("llm4om.executors.")]
    if not set(capabilities.get("llm_features", [])) <= set(provider_plugin.manifest["capabilities"].get("llm_features", [])):
        raise RunError("capability_mismatch", "admission", "Provider does not support the requested method features.")
    if any(not set(capabilities.get("llm_features", [])) <= set(selected.manifest["capabilities"].get("llm_features", [])) for selected in selected_providers[1:]):
        raise RunError("capability_mismatch", "admission", "Role Provider does not support the requested method features.")
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
    if compiler is not None and not set(allowed_types) <= set(compiler.binding["manifest"]["capabilities"]["problem_types"]):
        raise RunError("capability_mismatch", "admission", "Compiler cannot compile every configured problem type.",
                       details={"path": ["compiler", "capabilities", "problem_types"]})
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
                                        solver_id=settings["solver"]["plugin_id"],
                                        compiler_selection={"compiler": settings["compiler"], "target_backend": settings["model_backend"]["plugin_id"]} if compiler else None,
                                        expected_compiler=compiler_identity(compiler.binding) if compiler else None)
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
        "method_profile": profile, "method_cancellation": capabilities.get("cancellation", "unknown"), "code_origin": "method_generated" if profile in ("factory_single_candidate/0.1.0", "factory_candidates/0.1.0", "native_single_candidate/0.1.0", "native_candidates/0.1.0", "native_script/0.1.0", "native_script/0.2.0") else "deterministic_compilation",
        "compiler_id": settings["compiler"]["plugin_id"] if profile in ("grounded_single_candidate/0.1.0", "grounded_candidates/0.1.0") else None, "model_backend_id": settings["model_backend"]["plugin_id"],
        "compiler": compiler.binding if compiler else None,
        "solver_id": settings["solver"]["plugin_id"], "executor_id": settings["executor"]["plugin_id"],
        "packages": packages, "solver_environment": (worker or local_runtime).get("solver_environment"), "worker": worker, "budget": settings["budget"], "allowed_problem_types": allowed_types, "provider": provider_plugin.manifest,
        "provider_origin": provider_plugin.origin, "model": settings["llm"]["model"],
        **({"role_models": {role: {"provider": inventory[("llm_provider", selection["provider_plugin_id"])].manifest,
            "origin": inventory[("llm_provider", selection["provider_plugin_id"])].origin, "model": selection["model"],
            "config": selection["config"]} for role, selection in role_models.items()},
            "model_comparison": "heterogeneous_role_models" if any(selection["model"] != settings["llm"]["model"]
                for selection in role_models.values()) else "same_requested_model_roles",
            "role_resource_comparison": "different_role_resources" if any(
                any(selection[key] != settings["llm"][key] for key in ("provider_plugin_id", "model", "config"))
                for selection in role_models.values()) else "same_role_resources"} if role_models else {})}, provider, deadline, role_providers, compiler)


def _validate_plugin_config(plugin: Plugin, config: dict[str, Any], path: list[str]) -> None:
    try:
        jsonschema.Draft202012Validator(plugin.manifest["config_schema"]).validate(config)
    except jsonschema.ValidationError as error:
        raise RunError("invalid_config", "admission", "Plugin config does not match its Manifest.",
                       details={"path": [*path, *error.absolute_path]}) from error
    except (jsonschema.exceptions.RefResolutionError, RecursionError) as error:
        raise RunError("invalid_plugin_manifest", "admission", "Plugin configuration schema cannot be evaluated.",
                       details={"path": [*path[:-1], "config_schema"]}) from error


def _call_provider(operation: Callable[[], Any], plugin: Plugin) -> Any:
    try:
        with _quiet():
            return operation()
    except RunError as error:
        raise RunError(error.code, error.stage, "Provider configuration or environment check failed.",
                       details={"plugin_id": plugin.manifest["plugin_id"], **_exception_details(error)}) from error
    except (Exception, SystemExit) as error:
        code = "dependency_missing" if isinstance(error, (ImportError, OSError)) else "invalid_config"
        raise RunError(code, "admission", "Cannot construct or validate the configured Provider.",
                       details={"plugin_id": plugin.manifest["plugin_id"], **_exception_details(error)}) from error
