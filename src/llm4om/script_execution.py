"""Run-owned native script execution and reuse of trusted collector evidence."""

from dataclasses import asdict
from copy import deepcopy
import hashlib
import json
import re
import time
from typing import Any

from llm4om.contracts import RunError, parse_json, validate_bindings, validate_worker_response
from llm4om.methods import ScriptCodeProposal
from llm4om.preflight import AdmissionPlan
from llm4om.run_records import load_run_record
from llm4om.storage import RunStore


class ScriptExecutions:
    def __init__(self, store: RunStore, public: dict[str, Any], settings: dict[str, Any], plan: AdmissionPlan) -> None:
        self.store, self.public, self.settings, self.plan = store, public, settings, plan

    async def execute(self, execution_id: str, code: ScriptCodeProposal) -> dict[str, Any]:
        # The event-loop thread owns checkpoints and ledger updates throughout execution.
        return self._execute(execution_id, code)


    def reuse(self, execution_id: str, code: ScriptCodeProposal) -> dict[str, Any]:
        if execution_id not in self.store.state.get("method_executions", {}):
            raise RunError("invalid_method_outcome", "execution", "Selected script has no admitted execution record.")
        return self._execute(execution_id, code)


    def _execute(self, execution_id: str, code: ScriptCodeProposal) -> dict[str, Any]:
        store, plan = self.store, self.plan
        store.cancellation.check()
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,80}", execution_id)
                or not isinstance(code, ScriptCodeProposal) or code.schema_version != "0.1.0"
                or code.representation_kind != "native_script" or not code.source
                or hashlib.sha256(code.source.encode()).hexdigest() != code.source_sha256):
            raise RunError("invalid_script_proposal", "execution", "Invalid raw script identity or source bytes.")
        validate_bindings({"data_bindings": code.data_bindings}, self.public)
        if len(code.data_json) > 8 * 1024 * 1024 or len(code.source.encode()) > 8 * 1024 * 1024:
            raise RunError("invalid_script_proposal", "execution", "Script or derived data exceeds its byte limit.")
        parse_json(code.data_json)
        identity = {"source_sha256": code.source_sha256, "data_sha256": hashlib.sha256(code.data_json).hexdigest(),
                    "data_bindings": code.data_bindings, "admission": store.state["admission"]}
        identity = parse_json(json.dumps(identity, allow_nan=False).encode())
        records = store.state.setdefault("method_executions", {})
        prior = records.get(execution_id)
        path = "method/executions/" + execution_id + "/"
        if prior is not None:
            if prior["identity"] != identity:
                raise RunError("checkpoint_incompatible", "execution", "Script execution ID was rebound to different inputs or resources.")
            ref = prior.get("result_ref")
            if ref is None:
                receipts = store.interrupted_publications.get(path + "result.json", [])
                ref = receipts[-1] if receipts else None
            if ref is None:
                raise RunError("execution_outcome_unknown", "execution", "An admitted script execution has no completed evidence; it will not be repeated.")
            result = load_run_record(self.store, ref)
            if (result["identity"] != identity or result["execution_id"] != execution_id
                    or result["solver_call"] != prior["solver_call"]):
                raise RunError("checkpoint_incompatible", "execution", "Script execution receipt identity differs.")
            if prior.get("result_ref") is None:
                store.accept_publications()
                prior["result_ref"] = ref
                store.checkpoint()
            store.emit("method_execution_reused", execution_id=execution_id)
            return deepcopy(result)
        if plan.snapshot["method_profile"] not in ("native_script/0.1.0", "native_script/0.2.0"):
            raise RunError("capability_mismatch", "execution", "The admitted method has no raw-script execution profile.")
        ledger = store.state["ledger"]
        remaining = plan.deadline - time.time()
        if remaining <= 0:
            raise RunError("deadline_exhausted", "execution", "No run deadline remains.")
        if ledger["solver_calls"] + 2 > self.settings["budget"]["max_solver_calls"]:
            raise RunError("budget_exhausted", "execution", "Script and independent collector require two available Solver slots.")
        limits = dict(self.settings["executor"]["config"])
        limits["wall_time_s"] = min(limits["wall_time_s"], remaining)
        byte_limit = min(limits.get("output_limit_bytes", 1048576), 8 * 1024 * 1024)
        source_ref = store.write(path + "code.py", code.source.encode(), execution_id + "-source")
        data_ref = store.write(path + "data.json", code.data_json, execution_id + "-data")
        ledger["solver_calls"] += 1
        ledger["script_executions"] = ledger.get("script_executions", 0) + 1
        ledger["source_optimize_calls"] = None
        ledger["source_optimize_measurement"] = "untrusted_hook_observations_only"
        records[execution_id] = {"identity": identity, "result_ref": None, "solver_call": ledger["solver_calls"]}
        store.checkpoint()
        request = {"schema_version": "0.1.0", "source_sha256": code.source_sha256, "data_json": code.data_json.decode(),
                   "wall_time_s": limits["wall_time_s"], "output_limit_bytes": byte_limit}
        if plan.executor is None:
            raise RunError("executor_unavailable", "execution", "Script execution needs its admitted Executor.")
        execution = plan.executor.run(["python", "-I", "-m", "llm4om.script_worker", "/input/request.json"],
            {"request.json": json.dumps(request, allow_nan=False).encode(), "model.py": code.source.encode()}, limits,
            image=plan.snapshot["worker"]["image_id"], deadline=plan.deadline, cancellation=store.cancellation)
        execution_details = asdict(execution)
        execution_details["stdout"] = execution.stdout.decode(errors="replace")
        execution_details["stderr"] = execution.stderr.decode(errors="replace")
        worker_ref = store.json(path + "worker.json", execution_details, execution_id + "-worker")
        if execution.status != "completed" or execution.exit_code != 0:
            raise RunError("run_cancelled" if execution.status == "cancelled" else "execution_" + execution.status,
                           "execution", "Raw-script Worker did not return a complete record.")
        payload = parse_json(execution.stdout)
        if payload.get("schema_version") != "0.1.0" or payload.get("source_sha256") != code.source_sha256:
            raise RunError("worker_protocol_error", "execution", "Raw script Worker returned another source identity.")
        source = payload["source"]
        if (set(source) != {"status", "exit_code", "stdout", "stderr"}
                or type(source["exit_code"]) is not int or source["status"] not in {"completed", "timeout", "output_limit"}
                or not isinstance(source["stdout"], str) or not isinstance(source["stderr"], str)):
            raise RunError("worker_protocol_error", "execution", "Invalid source exit diagnostics.")
        capture = payload["capture"]
        capture_ref = store.json(path + "capture.json", payload, execution_id + "-capture")
        ledger["capture_attempts"] = ledger.get("capture_attempts", 0) + (capture["optimize_calls"] if capture else 0)
        ledger["hook_optimize_observations"] = ledger.get("hook_optimize_observations", 0) + (capture["optimize_calls"] if capture else 0)
        solve_ref = None
        collector_ref = None
        collector_error: str | None = "capture_missing_or_unsupported"
        if capture and capture["model_count"] == 1 and capture["optimize_calls"] == 1 and capture["transport"] is not None and capture["error"] is None:
            ledger["solver_calls"] += 1
            ledger["collector_calls"] = ledger.get("collector_calls", 0) + 1
            store.checkpoint()
            remaining = plan.deadline - time.time()
            options = dict(self.settings["solver"].get("options", {}))
            options["time_limit_s"] = min(options.get("time_limit_s", remaining), remaining)
            collection = {"schema_version": "0.1.0", "transport": capture["transport"],
                "source_sha256": code.source_sha256, "solver_options": options,
                "allowed_problem_types": plan.snapshot["allowed_problem_types"],
                "execution": {"model_backend": self.settings["model_backend"], "solver": self.settings["solver"], "allowed_problem_types": plan.snapshot["allowed_problem_types"]},
                "execution_identity": plan.execution.identity() if plan.execution else None}
            try:
                collected = plan.executor.run(["python", "-I", "-m", "llm4om.worker", "--collect-native", "/input/capture.json",
                        "--solver", self.settings["solver"]["plugin_id"]],
                    {"capture.json": json.dumps(collection, allow_nan=False).encode()}, limits,
                    image=plan.snapshot["worker"]["image_id"], deadline=plan.deadline, cancellation=store.cancellation)
                if collected.status != "completed" or collected.exit_code != 0:
                    raise RunError("run_cancelled" if collected.status == "cancelled" else "collector_failed", "execution", "Independent collector did not complete.")
                trusted = parse_json(collected.stdout)
                expected = {name: value for name, value in plan.snapshot["worker"].items()
                            if name in ("python", "llm4om", "packages", "solver_environment")}
                validate_worker_response(trusted, expected, solver_id=self.settings["solver"]["plugin_id"],
                                         model_backend=self.settings["model_backend"]["plugin_id"], result_profile=plan.execution.result_profile if plan.execution else None)
                collector_ref = store.json(path + "collector.json", trusted, execution_id + "-collector")
                if "error" in trusted:
                    raise RunError(trusted["error"]["code"], "execution", "Independent collector rejected the model.")
                solve = trusted["result"]
                variables = solve.pop("variables")
                solve.update(schema_version="0.2.0", evidence_origin="trusted_container_worker")
                solve["solution_ref"] = store.json(path + "solution.json", {"schema_version": "0.2.0", "variables": variables,
                    "evidence_origin": "trusted_container_worker"}, execution_id + "-solution") if variables is not None else None
                solve_ref = store.json(path + "solve-result.json", solve, execution_id + "-solve")
                collector_error = None
            except RunError as error:
                if error.code == "run_cancelled":
                    raise
                collector_error = error.code
        result = {"schema_version": "0.1.0", "execution_id": execution_id, "identity": identity,
                  "mode": "container", "status": "completed" if source["status"] == "completed" and source["exit_code"] == 0 and collector_error is None else "failed",
                  "solver_call": records[execution_id]["solver_call"], "source_ref": source_ref, "data_ref": data_ref,
                  "worker_ref": worker_ref, "capture_ref": capture_ref, "collector_ref": collector_ref,
                  "source": source, "solve_result_ref": solve_ref, "collector_error": collector_error}
        result_ref = store.json(path + "result.json", result, execution_id)
        records[execution_id]["result_ref"] = result_ref
        store.checkpoint()
        store.emit("method_execution_finished", execution_id=execution_id, result_ref=result_ref)
        return deepcopy(result)
