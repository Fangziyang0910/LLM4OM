"""Resolve and validate a supported run before a method receives resources."""

from dataclasses import dataclass, field
from functools import partial
import time
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Callable
from pathlib import Path
from urllib.error import HTTPError
from llm4om.providers import credential_environment, MockProvider, HTTPTextProvider, HTTPTextFactory

import jsonschema

from llm4om.contracts import RunError, parse_json, validate_config
from llm4om.executors import worker_runtime, container_runtime, run_owned_process, DEFAULT_IMAGE
from llm4om.control import CancellationToken
from llm4om.plugins import MethodPlugin, Plugin, discover_plugins, _quiet, _exception_details
from llm4om.compilers import ResolvedCompiler, resolve_compiler, compiler_identity
from llm4om.execution_plugins import ExecutionResources, resolve_execution_resources
from llm4om.data_loaders import ResolvedDataLoader, resolve_data_loader
from llm4om.reporters import ResolvedReporter, resolve_reporters
from llm4om.executor_registry import ResolvedExecutor, resolve_executor
from llm4om.store_registry import resolve_store


@dataclass(frozen=True)
class AdmissionPlan:
    method: MethodPlugin
    snapshot: dict[str, Any]
    provider: MockProvider | HTTPTextProvider | None
    deadline: float
    role_providers: dict[str, HTTPTextProvider] = field(default_factory=dict)
    compiler: ResolvedCompiler | None = None
    execution: ExecutionResources | None = None
    data_loader: ResolvedDataLoader | None = None
    reporters: tuple[ResolvedReporter, ...] = ()
    executor: ResolvedExecutor | None = None


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
    executor = resolve_executor(settings["executor"], inventory=inventory,
        expected=expected.get("executor") if expected else None)
    if executor.mode == "container":
        missing = {"network", "cpu_limit", "memory_limit_mb", "wall_time_s"} - set(settings["executor"]["config"])
        if missing:
            raise RunError("invalid_config", "admission", "Container Executors must declare their runtime limits.",
                details={"missing": sorted(missing)})
    store = resolve_store(settings["store"], inventory=inventory,
        expected=expected.get("store") if expected else None)
    reporters = resolve_reporters(settings.get("reporters", []), "run", inventory=inventory,
        expected=expected.get("reporters") if expected is not None else None)
    data_loader = resolve_data_loader(settings, inventory=inventory, expected=expected.get("data_loader") if expected else None)
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
        if not isinstance(role, str) or not 1 <= len(role.strip()) <= 128:
            raise RunError("invalid_config", "admission", "Role names must be nonempty bounded strings.")
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
    packages = dict(data_loader.binding["packages"])
    packages.update(executor.binding["packages"])
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
    execution_mode = executor.mode
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
    allowed_types = settings.get("allowed_problem_types", ["lp", "milp"])
    execution = resolve_execution_resources(settings["model_backend"], settings["solver"], allowed_types, inventory=inventory,
        expected=expected.get("execution") if expected else None, check_dependencies=not offline and execution_mode != "container")
    factory = profile in ("factory_single_candidate/0.1.0", "factory_candidates/0.1.0")
    if factory:
        native = execution.backend_binding["manifest"]["capabilities"]["handle_profile"] == "gurobipy_linear/0.1.0"
    if not factory and execution.backend_binding["manifest"]["capabilities"]["handle_profile"] != ("gurobipy_linear/0.1.0" if native else "pyomo_linear/0.1.0"):
        raise RunError("capability_mismatch", "admission", "The output profile is incompatible with the selected Backend/Solver.")
    if ("native_code" if native else "python_factory") not in execution.backend_binding["manifest"]["capabilities"]["input_artifact_kinds"]:
        raise RunError("capability_mismatch", "admission", "Backend does not accept this Code representation.")
    compiler = resolve_compiler(settings["compiler"], settings["model_backend"]["plugin_id"], inventory=inventory,
        expected=expected.get("compiler") if expected else None) if profile in ("grounded_single_candidate/0.1.0", "grounded_candidates/0.1.0") else None
    if compiler is not None:
        packages.update(compiler.binding["packages"])
    required = {"method_profile": profile,
                "input_artifact_kinds": ["public_problem"], "output_artifact_kinds": ["model_artifact"],
                "formulation_representations": [] if factory or profile == "native_script/0.2.0" else ["native_formulation" if profile == "native_script/0.1.0" else "five_element"], "code_representations": ["native_script" if profile.startswith("native_script/") else "native_code" if native else "python_factory"],
                "model_backends": [settings["model_backend"]["plugin_id"]], "solvers": [settings["solver"]["plugin_id"]],
                "llm_features": ["text"], "oracle_requirements": []}
    if not offline:
        required["execution_modes"] = [execution_mode]
    if factory and not capabilities.get("formulation_representations"):
        raise RunError("capability_mismatch", "admission", "Factory methods must declare a Formulation representation.")
    if not set(capabilities.get("llm_features", [])) <= set(provider_plugin.manifest["capabilities"].get("llm_features", [])):
        raise RunError("capability_mismatch", "admission", "Provider does not support the requested method features.")
    if any(not set(capabilities.get("llm_features", [])) <= set(selected.manifest["capabilities"].get("llm_features", [])) for selected in selected_providers[1:]):
        raise RunError("capability_mismatch", "admission", "Role Provider does not support the requested method features.")
    for field, value in required.items():
        declared = capabilities.get(field)
        if field in {"model_backends", "solvers"}:
            kind = "model_backend" if field == "model_backends" else "solver_backend"
            capability = "handle_profile" if kind == "model_backend" else "result_profile"
            selected_binding = execution.backend_binding if kind == "model_backend" else execution.solver_binding
            compatible = isinstance(declared, list) and any((kind, key) in inventory and
                inventory[(kind, key)].manifest["capabilities"][capability] == selected_binding["manifest"]["capabilities"][capability]
                for key in declared)
        else:
            compatible = (isinstance(declared, list) and set(value) <= set(declared)) if field in {
            "input_artifact_kinds", "output_artifact_kinds", "formulation_representations", "code_representations", "model_backends", "solvers", "execution_modes"} else declared == value
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
            if execution_mode != "container" or name in method.manifest["dependencies"].get("python", []) or name in executor.binding["packages"]:
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
                worker = worker_runtime(settings["executor"]["config"], deadline=deadline, cancellation=cancellation, runner=executor.run,
                                        solver_id=settings["solver"]["plugin_id"],
                                        compiler_selection={"compiler": settings["compiler"], "target_backend": settings["model_backend"]["plugin_id"]} if compiler else None,
                                        expected_compiler=compiler_identity(compiler.binding) if compiler else None,
                                        execution_selection={"model_backend": settings["model_backend"], "solver": settings["solver"], "allowed_problem_types": allowed_types},
                                        expected_execution=execution.identity(), result_profile=execution.result_profile)
            packages.update(worker["packages"])
        else:
            if expected is not None:
                local_runtime = {"packages": expected["packages"], "solver_environment": expected.get("solver_environment")}
            else:
                import json
                out, _, code = executor.run([sys.executable, "-m", "llm4om.worker", "--runtime", "--runtime-stdin"],
                    json.dumps({"model_backend": settings["model_backend"], "solver": settings["solver"], "allowed_problem_types": allowed_types}, allow_nan=False).encode(),
                    deadline=deadline, cancellation=cancellation or CancellationToken())
                payload = parse_json(out)
                if code != 0 or "runtime" not in payload:
                    runtime_error = payload.get("error", {})
                    raise RunError(runtime_error.get("code", "dependency_missing"), "admission", "The owned Solver runtime check failed.")
                local_runtime = payload["runtime"]
                if payload.get("execution_identity") != execution.identity():
                    raise RunError("execution_plugin_unavailable", "admission", "Owned Worker execution adapters differ from the selected identities.")
            packages.update(local_runtime["packages"])
    return AdmissionPlan(method, {"schema_version": "0.2.0", "mode": "offline_mock" if offline else execution_mode,
        "method": {"manifest": method.manifest, "origin": method.origin},
        "method_profile": profile, "method_cancellation": capabilities.get("cancellation", "unknown"), "code_origin": "method_generated" if profile in ("factory_single_candidate/0.1.0", "factory_candidates/0.1.0", "native_single_candidate/0.1.0", "native_candidates/0.1.0", "native_script/0.1.0", "native_script/0.2.0") else "deterministic_compilation",
        "compiler_id": settings["compiler"]["plugin_id"] if profile in ("grounded_single_candidate/0.1.0", "grounded_candidates/0.1.0") else None, "model_backend_id": settings["model_backend"]["plugin_id"],
        "compiler": compiler.binding if compiler else None,
        "data_loader": data_loader.binding, "data_view": data_loader.limits,
        "execution": {"model_backend": execution.backend_binding, "solver": execution.solver_binding},
        "solver_id": settings["solver"]["plugin_id"], "executor_id": settings["executor"]["plugin_id"], "executor": executor.binding,
        "store": store.binding,
        "packages": packages, "reporters": [reporter.binding for reporter in reporters], "solver_environment": (worker or local_runtime).get("solver_environment"), "worker": worker, "budget": settings["budget"], "allowed_problem_types": allowed_types, "provider": provider_plugin.manifest,
        "provider_origin": provider_plugin.origin, "model": settings["llm"]["model"],
        **({"role_models": {role: {"provider": inventory[("llm_provider", selection["provider_plugin_id"])].manifest,
            "origin": inventory[("llm_provider", selection["provider_plugin_id"])].origin, "model": selection["model"],
            "config": selection["config"]} for role, selection in role_models.items()},
            "model_comparison": "heterogeneous_role_models" if any(selection["model"] != settings["llm"]["model"]
                for selection in role_models.values()) else "same_requested_model_roles",
            "role_resource_comparison": "different_role_resources" if any(
                any(selection[key] != settings["llm"][key] for key in ("provider_plugin_id", "model", "config"))
            for selection in role_models.values()) else "same_role_resources"} if role_models else {})}, provider, deadline, role_providers, compiler, execution, data_loader, tuple(reporters), executor)


def check_model_connectivity(plan: AdmissionPlan) -> dict[str, Any]:
    """Explicit bounded metadata checks; admission itself remains network-free."""
    deadline = min(plan.deadline, time.time() + 20)
    checks = []
    providers = {"default": plan.provider, **plan.role_providers}
    for role, provider in providers.items():
        item: dict[str, Any] = {"role": role, "provider": getattr(provider, "plugin_id", None),
            "model": getattr(provider, "model", None), "status": "not_supported", "http_attempts": 0}
        if isinstance(provider, MockProvider):
            item["status"] = "not_applicable"
        elif isinstance(provider, HTTPTextProvider) and provider.connectivity_profile == "models_get/0.1.0":
            timeout = min(provider.timeout_s, 10, deadline - time.time())
            if timeout <= 0:
                item["status"] = "not_checked"
            else:
                started = time.monotonic()
                item["http_attempts"] = 1
                try:
                    item.update(provider.check_connectivity(timeout))
                except HTTPError as error:
                    item.update(status="not_supported" if error.code in {404, 405} else "failed", http_status=error.code)
                    error.close()
                except (RunError, TimeoutError) as error:
                    item.update(status="failed", diagnostic=error.code if isinstance(error, RunError) else "provider_timeout")
                    if isinstance(error, RunError) and error.details and error.details.get("connection_diagnostic"):
                        item["connection_diagnostic"] = error.details["connection_diagnostic"]
                item["duration_s"] = time.monotonic() - started
        checks.append(item)
    states = {item["status"] for item in checks}
    status = ("passed" if states <= {"reachable", "not_applicable"} and "reachable" in states else
              "not_applicable" if states == {"not_applicable"} else
              "failed" if "failed" in states else "not_available")
    return {"status": status, "checks": checks, "generation_requests": 0}


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
