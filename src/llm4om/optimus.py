"""Fixed OptiMUS0.3 main, EC=true/RAG=None, using shared public resources."""

import asyncio
import hashlib
import json
import os
import signal
import sys
import time
from typing import Any

from llm4om.contracts import RunError, parse_json
from llm4om.methods import DirectFactory, MethodContext, MethodOutcome, ModelProposal, ScriptCodeProposal

COMMIT = "e182e9ef5841605c2a7e87467021fd83522b6484"
VARIANT = "optimus0.3-source_main-ec_true-rag_none-external_chat"
INLINE_VARIANT = "optimus0.3-source_main-inline_public-ec_true-rag_none-external_chat"


class OptimusMethod:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        resources = context.resources
        if resources is None:
            raise RunError("capability_mismatch", "admission", "OptiMUS requires mediated script/artifact resources.")
        if self.config["rag_mode"] is not None:
            raise RunError("rag_resources_unavailable", "admission", "Requested RAG has no admitted rights-cleared compatible corpus/index/embedding resources.")
        inline = self.config.get("public_input_mode", "provided_json") == "inline_public"
        variant = INLINE_VARIANT if inline else VARIANT
        identity = {"schema_version": "0.1.0", "source_commit": COMMIT, "variant": variant,
                    "problem_sha256": context.problem_sha256, "config": self.config}
        if checkpoint is not None and checkpoint != identity:
            raise RunError("checkpoint_incompatible", "admission", "OptiMUS replay checkpoint identity changed.")
        context.cancellation.check()
        description = problem["description"]
        if inline:
            params_raw, labels_raw = b"{}", b"{}"
            public_data = {key: raw.decode("utf-8") for key, raw in context.data.items()}
            if public_data:
                assembled = "\nPublic problem data (original bytes as text):\n" + json.dumps(public_data, ensure_ascii=False)
                if len(description.encode()) + len(assembled.encode()) > 16 * 1024 * 1024:
                    raise RunError("data_view_limit", "admission",
                                   "Aggregated public data exceeds the fixed source driver input limit.")
                description += assembled
            description += "\nNo external parameter declarations are supplied. Use the public description and data values directly; data.json has no parameter entries."
        else:
            try:
                params_raw = context.data[self.config["params_data_id"]]
                labels_raw = context.data[self.config["labels_data_id"]]
            except KeyError as error:
                raise RunError("invalid_method_input", "admission", "Explicit public parameter and label data are required.") from error
        resources.record("public-input-projection.json", json.dumps({"schema_version": "0.1.0", "public_input_mode": "inline_public" if inline else "provided_json",
            "variant_id": variant, "description_sha256": hashlib.sha256(description.encode()).hexdigest(),
            "data_sha256": {key: hashlib.sha256(raw).hexdigest() for key, raw in context.data.items()},
            "parameter_declarations": "empty_inline_literals" if inline else "provided_public_json"}, ensure_ascii=False).encode())
        params, labels = parse_json(params_raw), parse_json(labels_raw)
        if any(not isinstance(value, dict) or not {"value", "shape", "definition"} <= value.keys() for value in params.values()):
            raise RunError("invalid_method_input", "admission", "Supplied parameters require value, shape and definition.")
        if not isinstance(labels, dict):
            raise RunError("invalid_method_input", "admission", "Labels must be an explicit public object.")
        if context.save_checkpoint is not None:
            context.save_checkpoint(identity)
        bindings = [{"data_id": item["data_id"], "sha256": item["sha256"]} for item in problem["data_refs"]]
        calls = 0
        executions: dict[str, str] = {}
        roles = []
        revisions: list[dict[str, Any]] = []
        files: dict[str, bytes] = {}
        selected = None
        source_selected = None
        last_executed = None
        deadline = context.deadline if context.deadline is not None else time.time() + context.budget["wall_time_s"]
        process = await asyncio.create_subprocess_exec(sys.executable, "-I", "-m", "llm4om.optimus_runtime", str(os.getpid()),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True, limit=16 * 1024 * 1024,
            env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"})
        assert process.stdin is not None and process.stdout is not None
        writer = process.stdin
        async def send(value: dict[str, Any]) -> None:
            writer.write(json.dumps(value, allow_nan=False).encode() + b"\n")
            await writer.drain()
        try:
            await send({"files": {"params.json": params_raw.decode(), "labels.json": labels_raw.decode(),
                                  "desc.txt": description}})
            while True:
                context.cancellation.check()
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise RunError("deadline_exhausted", "formulation", "The original run deadline stops source processing.")
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), min(0.1, remaining))
                except asyncio.TimeoutError:
                    continue
                if not line:
                    raise RunError("source_driver_failed", "formulation", "Bounded source driver ended without a completed state.")
                message = parse_json(line)
                operation = message["operation"]
                reply: Any = None
                if operation == "complete":
                    if message["role"] == "execute_code.execute_and_debug" and len(executions) > context.budget["max_repairs"]:
                        raise RunError("budget_exhausted", "code", "The shared repair limit stops source debugging.")
                    calls += 1
                    progress = {"type": "modeling_step", "schema_version": "0.1.0",
                        "step_id": f"source-{calls:06d}", "label": message["role"], "actor": message["role"],
                        "phase": "code" if any(word in message["role"] for word in ("code", "debug")) else "formulation"}
                    resources.emit({**progress, "status": "running"})
                    response = await context.llm.complete({"request_id": f"source-{calls:06d}",
                        "messages": message["messages"], "role": message["role"]})
                    resources.emit({**progress, "status": "completed"})
                    roles.append({"role": message["role"], "source_model": message["model"], "call_id": response.call_id,
                        "prompt_sha256": hashlib.sha256(message["messages"][0]["content"].encode()).hexdigest(),
                        "response_sha256": response.source_sha256, "evidence_origin": response.evidence_origin})
                    reply = response.text
                elif operation == "record":
                    files[message["name"]] = message["value"].encode()
                    reply = resources.record(message["name"], files[message["name"]])
                    if message["name"].endswith(".py"):
                        revisions.append({"revision_id": message["name"], "source_ref": reply,
                            "parent_revision_id": revisions[-1]["revision_id"] if revisions else None,
                            "execution_id": None})
                        resources.record("revisions.json", json.dumps({"schema_version": "0.1.0", "revisions": revisions}).encode())
                    if message["name"].startswith("state_"):
                        resources.emit({"stage": "formulation", "source_state": message["name"], "artifact_ref": reply})
                elif operation == "execute":
                    filename = message["filename"]
                    execution_id = "source-" + filename.removesuffix(".py")
                    executions[filename] = execution_id
                    source = message["source"]
                    reply = await resources.execute(execution_id, ScriptCodeProposal(source,
                        hashlib.sha256(source.encode()).hexdigest(), bindings, files["data.json"]))
                    revisions[-1]["execution_id"] = execution_id
                    resources.record("revisions.json", json.dumps({"schema_version": "0.1.0", "revisions": revisions}).encode())
                elif operation == "done":
                    source_selected, last_executed = message["selected"], message["last_executed"]
                    selected = source_selected or last_executed
                    break
                elif operation == "failed":
                    raise RunError("source_stage_failed", "formulation", "Fixed source stage could not parse or construct its output.",
                                   details={"source_exception": message["exception"]})
                else:
                    raise RunError("source_driver_failed", "formulation", "Source requested an unknown resource operation.")
                await send({"value": reply})
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            cleanup = asyncio.create_task(process.communicate())
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                await cleanup
                raise
            resources.record("source-calls.json", json.dumps({"schema_version": "0.1.0", "calls": roles}).encode())
        report = parse_json(files["fidelity-report.json"])
        if report["status"] != "match":
            raise RunError("source_fidelity_mismatch", "formulation", "Fixed main reference differs on the same public resource tape.")
        if selected is None:
            return MethodOutcome("failed", None, None)
        source = files[selected]
        state = parse_json(files["state_6_code.json"])
        provenance = {"origin": "source_native", "upstream_commit": COMMIT, "variant_id": variant,
                      "public_input_mode": "inline_public" if inline else "provided_json",
                      "source_model": "gpt-4o", "actual_model": "configured_shared_gateway",
                      "paper_coverage": "fixed_source_main_not_entire_paper_algorithm", "rag_mode": None,
                      "error_correction": True, "max_source_executions": 3,
                      "source_selected": source_selected, "last_executed": last_executed,
                      "call_ids": [item["call_id"] for item in roles]}
        resources.record("source-selection.json", json.dumps(provenance).encode())
        resources.emit({"stage": "selection", "source_selected": source_selected, "last_executed": last_executed,
                        "selected_execution_id": executions[selected]})
        formulation = {"schema_version": "0.3.0", "formulation_id": "optimus-formulation-001",
            "problem_id": problem["problem_id"], "problem_revision": problem["revision"],
            "representation_kind": "native_formulation", "representation": {"schema": "optimus0.3-state/0.1.0", "state": state},
            "structured_ir_ref": None, "data_bindings": bindings, "provenance": provenance}
        artifact = {"schema_version": "0.2.0", "artifact_id": "optimus-artifact-001",
            "problem_ref": {"sha256": context.problem_sha256}, "formulation_ref": {}, "code_ref": None,
            "data_bindings": bindings, "assumptions": [], "requirement_traces": [], "diagnostics": [],
            "warnings": [], "optional_views": [], "provenance": provenance,
            "stage_status": {"formulation": {"status": "available", "reason": None},
                             "code": {"status": "pending", "reason": "Raw native script contract must be checked."}}}
        return MethodOutcome("candidate_selected", "001", ModelProposal(artifact, formulation,
            code=ScriptCodeProposal(source.decode(), hashlib.sha256(source).hexdigest(), bindings, files["data.json"]),
            execution_id=executions[selected]))


class OptimusFactory:
    def describe(self) -> dict[str, Any]:
        manifest = DirectFactory().describe()
        manifest.update(plugin_id="llm4om.methods.optimus", display_name="OptiMUS0.3 fixed source main (EC, no RAG)",
            description="Complete fixed-source clause formulation, code assembly and script-debug workflow.",
            source={"upstream_commit": COMMIT, "variant_id": VARIANT, "license": "MIT",
                    "paper_url": "https://arxiv.org/abs/2407.19633", "paper_version": "v3",
                    "citation_key": "ahmaditeshnizi2024optimus03", "source_model": "gpt-4o",
                    "adaptation": "fixed_source_main_external_chat_resource_bridges"},
            config_schema={"type": "object", "properties": {"rag_mode": {"enum": [None, "problem_description", "constraint_or_objective", "problem_labels"]},
                "params_data_id": {"type": "string", "minLength": 1}, "labels_data_id": {"type": "string", "minLength": 1}},
                "required": ["rag_mode", "params_data_id", "labels_data_id"], "additionalProperties": False})
        manifest["capabilities"].update(method_profile="native_script/0.1.0", data_access="full", formulation_representations=["native_formulation"],
            code_representations=["native_script"], model_backends=["llm4om.model_backends.gurobipy"],
            solvers=["llm4om.solvers.gurobi"], execution_modes=["container"])
        return manifest

    def resolve_capabilities(self, config: dict[str, Any]) -> dict[str, Any]:
        if config["rag_mode"] is not None:
            raise RunError("rag_resources_unavailable", "admission", "RAG requires admitted compatible corpus/index/embedding resources and explicit rights/provenance.")
        capabilities: dict[str, Any] = self.describe()["capabilities"]
        return capabilities

    def create(self, config: dict[str, Any]) -> OptimusMethod:
        return OptimusMethod(config)


class OptimusInlineFactory(OptimusFactory):
    def describe(self) -> dict[str, Any]:
        manifest = super().describe()
        manifest.update(plugin_id="llm4om.methods.optimus_inline", display_name="OptiMUS0.3 inline-public input variant",
            description="Fixed main workflow with empty parameter declarations and all public values in description; no hidden labels.")
        manifest["source"].update(variant_id=INLINE_VARIANT,
            adaptation="fixed_source_main_empty_parameter_declarations_inline_public_values")
        manifest["config_schema"] = {"type": "object", "additionalProperties": False, "required": ["rag_mode"],
            "properties": {"rag_mode": {"const": None}}}
        return manifest

    def create(self, config: dict[str, Any]) -> OptimusMethod:
        return OptimusMethod({**config, "public_input_mode": "inline_public"})
