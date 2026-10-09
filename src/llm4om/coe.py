"""CoE transitions with independently authored prompts and native invocation."""

import ast
import hashlib
import json
import random
import re
from typing import Any

from llm4om.contracts import RunError, parse_json
from llm4om.methods import DirectFactory, MethodContext, MethodOutcome, ModelProposal, ScriptCodeProposal

COMMIT = "afb89bf602690ea621f13a23c42722f20f653a43"
VARIANT = "coe-fixed_transitions-original_prompts-single_import-native_function"
EXPERTS = ["Terminology Interpreter", "Parameter Extractor", "Modeling Expert", "Programming Example Provider",
           "Programming Expert", "Modeling Knowledge Supplement Expert", "Code Reviewer"]
TASKS = [
    "Explain at most three difficult optimization terms. Return JSON term/interpretation records.",
    "Extract decisions, parameters, objective and non-strict LP/MILP constraints from the public problem.",
    "Describe the mathematical model. Return JSON string fields VARIABLES, CONSTRAINS and OBJECTIVE.",
    "Develop a problem-specific Python example from the supplied public function interface and comments.",
    "Implement the supplied function interface using gurobipy for a linear LP/MILP. Put imports outside the function and omit tests.",
    "Develop Python optimization code from the supplied interface and previous comments.",
    "Review the previous code for correctness, runtime errors and efficiency. Explain concrete corrections.",
]


def _extract(text: str) -> str:
    blocks = re.findall(r"```(?:[A-Za-z0-9_+-]+)?[^\S\n]*\n(.*?)```", text, re.S)
    return text if not blocks else blocks[0] if len(blocks) == 1 else "\n".join(block for block in blocks if "pip" not in block)


def _parse(text: str) -> Any:
    candidates = [text, _extract(text)]
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character in "[{":
            try:
                value, _ = decoder.raw_decode(text[index:])
                json.dumps(value, allow_nan=False)
                return value
            except (ValueError, TypeError):
                pass
    for candidate in candidates:
        for parser in (json.loads, ast.literal_eval):
            try:
                value = parser(candidate)
                json.dumps(value, allow_nan=False)
                return value
            except (ValueError, SyntaxError, TypeError, RecursionError):
                pass
    raise RunError("invalid_coe_reply", "formulation", "CoE could not parse the expected public reply.")


def _comments(pool: list[tuple[str, str]]) -> str:
    return "\n".join(name + ":\n```\n" + value + "\n```" for name, value in pool) or "No expert comments yet."


def _invocation(source: str, entry: str, arguments: dict[str, Any], reflection: bool) -> str:
    # ponytail: a single source import is intentional; record the upstream reload difference.
    footer = "\nimport inspect as _coe_inspect\nimport json as _coe_json\n"
    if reflection:
        footer += "_coe_names = sorted(name for name, value in globals().items() if name.startswith('prob_') and _coe_inspect.isfunction(value))\n"
        footer += "if not _coe_names: raise NotImplementedError('CoE requires a prob_* function for public reflection.')\n"
        footer += "_coe_function = globals()[_coe_names[0]]\n"
    else:
        footer += "_coe_function = globals()[" + repr(entry) + "]\n"
    footer += "_coe_function(**_coe_json.loads(" + repr(json.dumps(arguments, allow_nan=False)) + "))\n"
    return source + footer


class CoEMethod:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        if checkpoint is not None:
            raise RunError("checkpoint_incompatible", "admission", "CoE has no internal continuation checkpoint.")
        resources = context.resources
        if resources is None:
            raise RunError("resource_unavailable", "admission", "CoE requires public artifact/execution resources.")
        contract_id = self.config["public_contract_data_id"]
        if contract_id is not None and contract_id not in context.data:
            raise RunError("public_contract_unavailable", "admission", "CoE needs a declared public function contract.")
        contract = parse_json(context.data[contract_id]) if contract_id is not None else {
            "entry_point": "prob_problem", "input": {},
            "code_example": "def prob_problem():\n    # Build a gurobipy LP/MILP from the public description and data.json public_data.\n    pass\n"}
        if (set(contract) != {"code_example", "entry_point", "input"} or not isinstance(contract["code_example"], str)
                or not contract["code_example"] or not isinstance(contract["input"], dict)
                or not isinstance(contract["entry_point"], str) or not contract["entry_point"].isidentifier()):
            raise RunError("invalid_public_contract", "admission", "CoE requires a starter, function name and public keyword arguments.")
        for key in contract["input"]:
            if not key.isidentifier():
                raise RunError("invalid_public_contract", "admission", "Public keyword argument names must be identifiers.")
        bindings = [{"data_id": ref["data_id"], "sha256": ref["sha256"]} for ref in problem["data_refs"]]
        public_data = {key: value.decode("utf-8") for key, value in context.data.items()}
        description = problem["description"] + "\nPublic data:\n" + json.dumps({
            "arguments": contract["input"], "data": {key: value for key, value in public_data.items() if key != contract_id}}, ensure_ascii=False)
        if contract_id is None:
            description += "\nPublic entry point: prob_problem(), with no arguments."
        resources.record("public-interface.json", json.dumps({"schema_version": "0.1.0", "contract": contract,
            "origin": "original_default_interface" if contract_id is None else "declared_public_data",
            "public_contract_data_id": contract_id}, ensure_ascii=False, allow_nan=False).encode())
        calls: list[dict[str, Any]] = []
        routes: list[dict[str, Any]] = []
        trials: list[dict[str, Any]] = []
        previous: dict[str, str] = {}
        rng = random.Random(self.config["seed"])
        reflection = self.config["enable_reflection"]
        limit = min(self.config["max_collaborate_nums"], len(EXPERTS))
        trial_limit = self.config["max_trials"] if reflection else 1

        def record(name: str, value: Any) -> None:
            resources.record(name, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())

        fidelity: dict[str, Any] = {"schema_version": "0.1.0", "upstream_commit": COMMIT, "variant_id": VARIANT,
            "workflow": {"status": "source_derived_transition_implementation", "reference_execution": "not_available",
                "reference_basis": "fixed_source_investigation_and_independent_public_transition_tapes"},
            "prompts": {"status": "changed", "origin": "independently_authored"},
            "inputs": {"status": "changed", "problem_sha256": context.problem_sha256, "data_bindings": bindings,
                "starter": "original_default_interface" if contract_id is None else "declared_public_data"},
            "model": {"status": "changed", "actual": "configured_shared_external_gateway", "source": "gpt-3.5-turbo"},
            "execution": {"status": "changed", "import_count": 1, "source_import_count": 2,
                "collector": "independent_fresh_gurobi", "final_instance": "declared_original_arguments",
                "missing_function_detection": "public_driver_stderr_marker_untrusted_diagnostic"},
            "controls": {"status": "changed", "routing_seed": self.config["seed"], "sampling_caps": "configured_gateway",
                "source_conductor_output_cap": 10}, "selection": {"status": "not_available"}, "paper_benchmark_reproduction": False}
        record("fidelity-report.json", fidelity)

        async def complete(role: str, instruction: str, inputs: dict[str, Any]) -> str:
            context.cancellation.check()
            content = instruction + "\nPublic inputs:\n" + json.dumps(inputs, ensure_ascii=False, allow_nan=False)
            reply = await context.llm.complete({"request_id": "coe-" + str(len(calls) + 1), "role": "coe." + role,
                "messages": [{"role": "user", "content": content}]})
            calls.append({"role": role, "call_id": reply.call_id, "prompt_sha256": hashlib.sha256(content.encode()).hexdigest(),
                "response_sha256": reply.source_sha256, "evidence_origin": reply.evidence_origin})
            record("calls.json", {"schema_version": "0.1.0", "calls": calls})
            return reply.text

        selected: ScriptCodeProposal | None = None
        execution_id = ""
        public_check = "not_requested"
        for trial in range(1, trial_limit + 1):
            if trial > 1 and trial - 1 > context.budget["max_repairs"]:
                raise RunError("budget_exhausted", "code", "The shared repair limit stops further CoE trials.")
            pool: list[tuple[str, str]] = []
            stack: list[str] = []
            for step in range(limit):
                remaining = [name for name in EXPERTS if name not in stack]
                routing_descriptions = ["Explain unfamiliar terms.", "Write optimization Python.", "Formulate LP/MILP.",
                    "Provide a Python example.", "Write optimization Python.", "Write optimization Python.", "Write optimization Python."]
                route = await complete("conductor", "Choose one participating expert by its full name.", {
                    "description": description, "experts": dict(zip(EXPERTS, routing_descriptions)), "already_commented": stack,
                    "remaining": remaining, "total_collaboration": limit, "remaining_collaboration": limit - step})
                matches = [name for name in remaining if name in route]
                origin = "name_match_remaining"
                if not matches:
                    matches = [name for name in EXPERTS if name in route]
                    origin = "name_match_all"
                expert = matches[0] if matches else rng.choice(remaining or EXPERTS)
                routes.append({"trial": trial, "step": step + 1, "expert": expert, "selection": origin if matches else "seeded_fallback"})
                inputs: dict[str, Any] = {"description": description}
                if expert == EXPERTS[0]:
                    inputs["knowledge"] = None
                else:
                    inputs["comments"] = _comments(pool)
                if expert in EXPERTS[3:6]:
                    inputs["code_example"] = contract["code_example"]
                raw = await complete(expert, TASKS[EXPERTS.index(expert)], inputs)
                previous[expert] = raw
                comment = raw
                if expert == EXPERTS[0]:
                    try:
                        interpreted = _parse(raw)
                        if isinstance(interpreted, list):
                            comment = "\n".join(str(item["term"]) + ": " + str(item["interpretation"]) for item in interpreted)
                    except (RunError, KeyError, TypeError):
                        pass
                if expert == EXPERTS[2]:
                    comment = comment.replace(" < ", " \\leq ").replace(" > ", " \\geq ")
                pool.append((expert, comment))
                stack.append(expert)
                record("routes.json", {"schema_version": "0.1.0", "seed": self.config["seed"], "routes": routes})
            answer = await complete("reducer", "Combine expert comments into final LP/MILP gurobipy function code with imports and no tests.",
                {"description": description, "comments": _comments(pool)})
            source = _extract(answer)
            prefix = f"trial-{trial:03d}"
            resources.record(prefix + "-reply.txt", answer.encode())
            resources.record(prefix + "-code.py", source.encode())
            record(prefix + "-comments.json", {"schema_version": "0.1.0", "comments": pool})
            arguments = contract["input"]
            if reflection:
                generated = _parse(await complete("public_evaluator", "Create one public test input as JSON {input:{keyword: value}}; do not give expected answers.",
                    {"description": description, "code_example": contract["code_example"]}))
                if isinstance(generated, list) and generated:
                    generated = generated[0]
                if not isinstance(generated, dict) or not isinstance(generated.get("input"), dict):
                    raise RunError("invalid_coe_test", "code", "CoE public test generation requires keyword arguments.")
                arguments = generated["input"]
            invoked = _invocation(source, contract["entry_point"], arguments, reflection)
            data = json.dumps({"public_data": public_data, "arguments": arguments}, ensure_ascii=False, allow_nan=False).encode()
            selected = ScriptCodeProposal(invoked, hashlib.sha256(invoked.encode()).hexdigest(), bindings, data)
            execution_id = "coe-" + prefix
            execution = await resources.execute(execution_id, selected)
            passed = execution["source"]["status"] == "completed" and execution["source"]["exit_code"] == 0
            trials.append({"trial": trial, "execution_id": execution_id, "original_code_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "source_public_pass": passed, "collector_error": execution.get("collector_error")})
            record("trials.json", {"schema_version": "0.1.0", "trials": trials})
            if reflection and "NotImplementedError: CoE requires a prob_* function for public reflection." in execution["source"]["stderr"]:
                raise RunError("public_function_unavailable", "execution", "CoE public reflection did not find its required prob_* function.")
            if not reflection or passed:
                public_check = "passed" if reflection else "not_requested"
                break
            public_check = "failed_trials_exhausted"
            feedback = [("public_evaluator", execution["source"]["stderr"])]
            backward = []
            while stack:
                expert = stack.pop()
                old_comment = pool.pop()
                raw = await complete(expert + ".backward", "Explain whether you caused the execution failure. Return is_caused_by_you, reason and refined_result.",
                    {"description": description, "previous_reply": previous[expert], "feedback": _comments(feedback)})
                try:
                    value = _parse(raw)
                    if not isinstance(value, dict):
                        raise TypeError("Expected a feedback object.")
                    caused, reason, refined = value["is_caused_by_you"], value["reason"], value["refined_result"]
                except (RunError, KeyError, TypeError):
                    feedback.append((expert, raw))
                    backward.append({"expert": expert, "parsed": False})
                    continue
                backward.append({"expert": expert, "parsed": True, "caused": bool(caused), "refined_result": refined})
                if caused:
                    pool.append((old_comment[0], str(refined)))
                    stack.append(expert)
                    break
                feedback.append((expert, str(reason)))
            record(prefix + "-backward.json", {"schema_version": "0.1.0", "backward": backward, "comments_after": pool})
        assert selected is not None
        if reflection:
            invoked = _invocation(source, contract["entry_point"], contract["input"], False)
            data = json.dumps({"public_data": public_data, "arguments": contract["input"]}, ensure_ascii=False, allow_nan=False).encode()
            selected = ScriptCodeProposal(invoked, hashlib.sha256(invoked.encode()).hexdigest(), bindings, data)
            execution_id = "coe-final-original"
            await resources.execute(execution_id, selected)
        provenance = {"origin": "original_coe_adaptation", "upstream_commit": COMMIT, "variant_id": VARIANT,
            "public_check": public_check, "call_ids": [item["call_id"] for item in calls], "selected_execution_id": execution_id,
            "prompt_fidelity": "independently_authored_changed", "execution_fidelity": "single_import_function_driver_changed",
            "model_fidelity": "configured_external_model_changed", "sampling_and_caps": "configured_gateway_changed",
            "final_binding": "declared_original_public_arguments", "trial_inputs": "public_generated_tests_not_original_solve"}
        record("selection.json", provenance)
        fidelity["selection"] = {"status": "last_reducer", "public_check": public_check, "selected_execution_id": execution_id}
        record("fidelity-report.json", fidelity)
        resources.emit({"stage": "selection", "selected_execution_id": execution_id, "public_check": public_check})
        artifact = {"schema_version": "0.2.0", "artifact_id": "coe-artifact-001", "problem_ref": {"sha256": context.problem_sha256},
            "formulation_ref": None, "code_ref": None, "data_bindings": bindings, "assumptions": [], "requirement_traces": [],
            "diagnostics": [], "warnings": ["public_reflection_exhausted"] if public_check == "failed_trials_exhausted" else [],
            "optional_views": [], "provenance": provenance,
            "stage_status": {"formulation": {"status": "not_available", "reason": "Optional expert comments are not a final mathematical Formulation."},
                "code": {"status": "pending", "reason": "Native invocation must be checked."}}}
        return MethodOutcome("candidate_selected", "001", ModelProposal(artifact, None, code=selected, execution_id=execution_id))


class CoEFactory:
    def describe(self) -> dict[str, Any]:
        manifest = DirectFactory().describe()
        manifest.update(plugin_id="llm4om.methods.coe", display_name="CoE expert workflow (original prompt/native invocation variant)",
            description="Dynamic expert collaboration, reducer and optional public reflection with source reset/selection transitions.",
            source={"upstream_commit": COMMIT, "variant_id": VARIANT, "adaptation": "independently_authored_prompts_and_native_driver",
                "license": "original_platform_implementation_no_upstream_vendoring"},
            config_schema={"type": "object", "additionalProperties": False,
                "properties": {"public_contract_data_id": {"type": ["string", "null"], "minLength": 1},
                    "max_collaborate_nums": {"type": "integer", "minimum": 1, "maximum": 100}, "enable_reflection": {"type": "boolean"},
                    "max_trials": {"type": "integer", "minimum": 1, "maximum": 100}, "seed": {"type": "integer", "minimum": 0}}})
        manifest["capabilities"].update(method_profile="native_script/0.2.0", formulation_representations=[], code_representations=["native_script"],
            model_backends=["llm4om.model_backends.gurobipy"], solvers=["llm4om.solvers.gurobi"], execution_modes=["container"], supports_checkpoint=False)
        return manifest

    def create(self, config: dict[str, Any]) -> CoEMethod:
        return CoEMethod({"public_contract_data_id": None, "max_collaborate_nums": 3,
            "enable_reflection": False, "max_trials": 3, "seed": 0, **config})
