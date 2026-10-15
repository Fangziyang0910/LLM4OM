"""CoE expert routing, reduction and reflection over configured Solver feedback."""

import random
import json
from typing import Any

from llm4om.contracts import RunError, parse_json
from llm4om.methods import MethodContext, MethodOutcome
from llm4om.or_llm_agent import ORLLMAgentFactory
from llm4om.prompt_methods import PromptSession, json_reply

COMMIT = "afb89bf602690ea621f13a23c42722f20f653a43"
VARIANT = "coe-expert_reduce-public_reflection-configured_code/0.2.0"
SOURCE: dict[str, Any] = {"upstream_commit": COMMIT, "variant_id": VARIANT,
    "adaptation": "expert_routing_reduction_backward_feedback_configured_backend_solver"}
EXPERTS = ["Terminology Interpreter", "Parameter Extractor", "Modeling Expert", "Programming Example Provider",
    "Programming Expert", "Modeling Knowledge Supplement Expert", "Code Reviewer"]
TASKS = [
    "Explain up to three difficult optimization terms and how they apply to this problem.",
    "Extract the decisions, public parameters, objective and every LP/MILP condition. Preserve units and domains.",
    "Develop the mathematical model: decision variables and domains, objective and all constraints. Explain assumptions.",
    "Give a problem-specific implementation example using the configured code target and actual public values.",
    "Implement the model using the configured code target. Incorporate the previous expert comments.",
    "Supply missing modeling knowledge and implementation details needed to satisfy the original problem.",
    "Review the previous model and code for omitted requirements, incorrect domains, constants and execution errors.",
]


class CoEMethod:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        if checkpoint is not None:
            raise RunError("checkpoint_incompatible", "admission", "CoE has no internal continuation checkpoint.")
        session = PromptSession("coe", SOURCE, problem, context)
        inputs = dict(session.inputs)
        contract_id = self.config["public_contract_data_id"]
        if contract_id is not None:
            if contract_id not in context.data:
                raise RunError("public_contract_unavailable", "admission", "The declared public input contract is missing.")
            contract = parse_json(context.data[contract_id])
            if (set(contract) != {"code_example", "entry_point", "input"} or not isinstance(contract["code_example"], str)
                    or not isinstance(contract["input"], dict) or not isinstance(contract["entry_point"], str)
                    or not contract["entry_point"].isidentifier() or any(not key.isidentifier() for key in contract["input"])):
                raise RunError("invalid_public_contract", "admission", "Public input contracts need a starter, entry point and keyword arguments.")
            inputs["public_contract"] = contract
        session.record("public-interface.json", {"public_contract_data_id": contract_id,
            "code_target": dict(context.code_target) if context.code_target else None})
        rng = random.Random(self.config["seed"])
        routes: list[dict[str, Any]] = []
        trials: list[dict[str, Any]] = []
        feedback: list[tuple[str, str]] = []
        reflection = self.config["enable_reflection"]
        trial_limit = min(self.config["max_trials"], int(context.budget["max_repairs"]) + 1) if reflection else 1
        parent = None
        for trial in range(1, trial_limit + 1):
            pool: list[tuple[str, str]] = []
            stack: list[str] = []
            for step in range(min(self.config["max_collaborate_nums"], len(EXPERTS))):
                remaining = [name for name in EXPERTS if name not in stack]
                route = await session.complete("conductor", "Choose the next expert by its full name, according to the "
                    "problem and the work still needed. Prefer a remaining expert. Do not solve the problem yourself.",
                    {**inputs, "experts": dict(zip(EXPERTS, TASKS)), "already_commented": stack,
                        "remaining": remaining, "feedback": feedback}, phase="coordination")
                matches = [name for name in remaining if name in route]
                if not matches:
                    matches = [name for name in EXPERTS if name in route]
                expert = matches[0] if matches else rng.choice(remaining or EXPERTS)
                routes.append({"trial": trial, "step": step + 1, "expert": expert,
                    "selection": "name_match" if matches else "seeded_fallback"})
                instruction = TASKS[EXPERTS.index(expert)]
                if expert in EXPERTS[3:5]:
                    instruction += " " + session.code_instruction
                elif expert in EXPERTS[5:]:
                    instruction += " Code target for your analysis: " + json.dumps(dict(context.code_target or {}))
                comment = await session.complete(expert, instruction, {**inputs, "comments": pool, "feedback": feedback},
                    phase="formulation" if expert in EXPERTS[:3] else "code")
                pool.append((expert, comment))
                stack.append(expert)
                session.record("routes.json", {"seed": self.config["seed"], "routes": routes})
            answer = json_reply(await session.complete("reducer", "Combine the expert comments into one complete "
                "mathematical model and corresponding implementation. Resolve inconsistent comments against the original "
                "problem. The configured code target overrides any API or entry point in examples or public starter code. "
                + session.code_instruction.replace("Return only the Python source in one code block.",
                    "Return JSON {formulation:string,code:string}."),
                {**inputs, "comments": pool, "feedback": feedback}, phase="coordination"))
            if (set(answer) != {"formulation", "code"} or any(not isinstance(answer[key], str)
                    or not answer[key].strip() for key in answer)):
                raise RunError("invalid_method_reply", "code", "CoE requires a final mathematical model and code.")
            check_id = f"{trial:03d}"
            session.resources.record(f"trial-{trial:03d}-code.py", answer["code"].encode())
            session.record(f"trial-{trial:03d}-comments.json", {"comments": pool})
            checked = await session.resources.check(check_id,
                session.proposal({"mathematical_model": answer["formulation"]}, answer["code"]), parent_id=parent,
                change_reason="CoE expert reflection from public execution feedback." if parent else None)
            trials.append({"trial": trial, "check_id": check_id, "diagnostics": checked["diagnostics"],
                "termination": checked["termination"]})
            session.record("trials.json", {"trials": trials})
            if not checked["diagnostics"] and checked["solve_result_ref"] is not None:
                session.record("selection.json", {"check_id": check_id, "public_check": "passed"})
                return session.resources.select(check_id, rule="first_executable_reducer",
                    reason="Expert reduction passed isolated construction and configured Solver execution.")
            if trial == trial_limit:
                raise RunError("method_debug_exhausted", "code", "CoE exhausted its public-feedback trials.")
            remaining_slots = session.resources.remaining_budget()
            if not remaining_slots["checks"] or not remaining_slots["solver_calls"]:
                raise RunError("budget_exhausted", "code", "No public check or Solver slot remains for expert reflection.")
            feedback = [("execution", str(checked))]
            backward = []
            while stack:
                expert = stack.pop()
                old_comment = pool.pop()
                raw = await session.complete(expert + ".backward", "Use the public execution diagnostics to identify "
                    "whether your contribution caused the failure. Return JSON {is_caused_by_you:boolean,reason:string,"
                    "refined_result:string}. Refine your contribution without relaxing the public requirements.",
                    {**inputs, "previous_reply": old_comment[1], "feedback": feedback}, phase="coordination")
                try:
                    revised = json_reply(raw)
                    if (set(revised) != {"is_caused_by_you", "reason", "refined_result"}
                            or type(revised["is_caused_by_you"]) is not bool
                            or any(not isinstance(revised[key], str) for key in ("reason", "refined_result"))):
                        raise RunError("invalid_method_reply", "code", "Invalid expert reflection.")
                except RunError:
                    feedback.append((expert, raw))
                    backward.append({"expert": expert, "parsed": False})
                    continue
                backward.append({"expert": expert, **revised})
                feedback.append((expert, revised["refined_result"] if revised["is_caused_by_you"] else revised["reason"]))
                if revised["is_caused_by_you"]:
                    break
            session.record(f"trial-{trial:03d}-backward.json", {"backward": backward, "feedback": feedback})
            parent = check_id
        raise AssertionError("Bounded CoE trials must return or raise.")


class CoEFactory:
    def describe(self) -> dict[str, Any]:
        manifest = ORLLMAgentFactory().describe()
        manifest.update(plugin_id="llm4om.methods.coe", display_name="CoE",
            description="Dynamic expert collaboration, reduction and bounded reflection with configured Backend/Solver.",
            source=SOURCE, config_schema={"type": "object", "additionalProperties": False, "properties": {
                "public_contract_data_id": {"type": ["string", "null"], "minLength": 1},
                "max_collaborate_nums": {"type": "integer", "minimum": 1, "maximum": 100},
                "enable_reflection": {"type": "boolean"}, "max_trials": {"type": "integer", "minimum": 1, "maximum": 100},
                "seed": {"type": "integer", "minimum": 0}}})
        return manifest

    def create(self, config: dict[str, Any]) -> CoEMethod:
        return CoEMethod({"public_contract_data_id": None, "max_collaborate_nums": 3,
            "enable_reflection": False, "max_trials": 3, "seed": 0, **config})
