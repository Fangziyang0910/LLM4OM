"""OptiTree inference over its pinned public modeling-thought hierarchy."""

import hashlib
import json
from importlib.resources import files
from typing import Any

from llm4om.contracts import RunError, parse_json
from llm4om.methods import MethodContext, MethodOutcome
from llm4om.or_llm_agent import ORLLMAgentFactory
from llm4om.prompt_methods import PromptSession, NATIVE_CODE_INSTRUCTION, json_reply


SOURCE: dict[str, Any] = {"upstream_url": "https://github.com/MIRALab-USTC/OptiTree",
    "upstream_commit": "2e70ecfd0a3c8e9c0c16d36d7d498a7344cfdec9",
    "variant_id": "optitree-fixed_ds_tree-public_inference/0.1.0",
    "adaptation": "original_prompts_no_example_answers_no_tree_training", "license": "MIT"}


class OptiTreeMethod:
    def __init__(self, config: dict[str, Any]) -> None:
        self.config = config

    async def run(self, problem: dict[str, Any], context: MethodContext,
                  *, checkpoint: dict[str, Any] | None = None) -> MethodOutcome:
        if checkpoint is not None:
            raise RunError("checkpoint_incompatible", "admission", "OptiTree has no internal continuation checkpoint.")
        session = PromptSession("optitree", SOURCE, problem, context)
        root = files("llm4om").joinpath("optitree_source")
        manifest = parse_json(root.joinpath("manifest.json").read_bytes())
        raw = {}
        for name, binding in manifest["files"].items():
            value = root.joinpath(name).read_bytes()
            if len(value) != binding["size_bytes"] or hashlib.sha256(value).hexdigest() != binding["sha256"]:
                raise RunError("source_hash_mismatch", "admission", "The fixed OptiTree resource bytes changed.")
            raw[name] = value
        templates = {item["id"]: item for item in (parse_json(line) for line in raw["thoughts.jsonl"].splitlines())}
        tree = parse_json(raw["tree.json"])
        node = 0
        path = [node]
        while tree.get(str(node)):
            children = tree[str(node)]
            root_step = node == 0
            choices = [templates[index]["problem_type"] for index in children] if root_step else [
                {"problem_type": templates[index]["problem_type"], "description": templates[index]["description"]} for index in children]
            reply = json_reply(await session.complete("classify", "Identify whether the public problem belongs to one of the "
                "listed child types of the current modeling category. Select only a listed type, or stop at the current type. "
                + ('Return JSON {matching_problem_type:string, belongs_to_problem_types:boolean}.' if root_step else
                   'Return JSON {matching_subtype:string, belongs_to_subtypes:boolean}.'),
                {**session.inputs, "current_type": templates[node]["problem_type"], "child_types": choices}))
            belongs = reply.get("belongs_to_problem_types" if root_step else "belongs_to_subtypes") if isinstance(reply, dict) else None
            if type(belongs) is not bool:
                raise RunError("invalid_tree_route", "formulation", "OptiTree needs an explicit boolean membership decision.")
            if not belongs:
                break
            name = reply.get("matching_problem_type" if root_step else "matching_subtype")
            matched = [index for index in children if templates[index]["problem_type"] == name]
            if len(matched) != 1 or matched[0] in path:
                raise RunError("invalid_tree_route", "formulation", "OptiTree selected an unknown, ambiguous or cyclic child type.")
            node = matched[0]
            path.append(node)
            session.record("tree-path.json", {"node_ids": path, "types": [templates[index]["problem_type"] for index in path]})
        # Upstream examples contain solved training instances; inference uses thoughts only.
        thought = {key: templates[node][key] for key in ("problem_type", "description", "reason_flow")}
        session.record("retrieved-thoughts.json", {"node_ids": path, "thought_template": thought,
            "source_sha256": manifest["files"]["thoughts.jsonl"]["sha256"]})
        answer = json_reply(await session.complete("reasoner", "Use the retrieved modeling thoughts to formulate the public "
            "problem. Include the full mathematical model, then its executable gurobipy implementation. " + NATIVE_CODE_INSTRUCTION
            .replace("Return only the Python code in one code block.", "Return JSON {formulation:string, code:string}."),
            {**session.inputs, "thought_template": thought}))
        if (not isinstance(answer, dict) or set(answer) != {"formulation", "code"}
                or any(not isinstance(answer[key], str) or not answer[key].strip() for key in answer)):
            raise RunError("invalid_method_reply", "formulation", "OptiTree requires a mathematical model and code.")
        code, execution_id = await session.debug_script(answer["code"], {**session.inputs, "formulation": answer["formulation"]},
            min(self.config["max_debug_attempts"], int(context.budget["max_repairs"])))
        return session.outcome({"mathematical_model": answer["formulation"], "retrieved_type": thought["problem_type"],
            "tree_path": path}, code, execution_id)


class OptiTreeFactory:
    def describe(self) -> dict[str, Any]:
        manifest = ORLLMAgentFactory().describe()
        manifest.update(plugin_id="llm4om.methods.optitree", display_name="OptiTree",
            description="Hierarchical public thought retrieval, problem-specific formulation and bounded code debugging.", source=SOURCE)
        return manifest

    def create(self, config: dict[str, Any]) -> OptiTreeMethod:
        return OptiTreeMethod({"max_debug_attempts": 2, **config})
