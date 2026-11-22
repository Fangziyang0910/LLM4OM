"""AutoCO LangGraph workflow: Semantic -> Typed 4-Tuple -> Sandboxed Problem -> KG+Pilot Agent -> Metaheuristic Solve."""

from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from llm4om.methods import Method, presets
from llm4om.methods.autoco.knowledge import DEFAULT_KG, KG_AGENT_PROMPT, auto_problem_feature_ids, reconcile_features
from llm4om.methods.autoco.modeling import (
    FORMULATION_PROMPT,
    REVIEW_PROMPT,
    SEMANTIC_PROMPT,
    Formulation,
    FormulationReview,
    SemanticSpec,
    ask_schema,
)
from llm4om.methods.common import output_language, python_code_blocks
from llm4om.runtime import Context, ModelingState
from llm4om.sandbox.autoco.specs import ALGORITHM_SPECS, canonical_algorithm

_MARKER = "@@AUTOCO_JSON@@"

INSTANTIATE_PROBLEM_PROMPT = """
Compile the problem description and Typed 4-Tuple M = (P, X, F, C) into a Python module defining `def build_model(data) -> Problem:`.

API Contract (`from autoco import Problem, VarSpec`, `import numpy as np`):
- `data` is a `dict[str, str]` mapping each attached data file name to its text content (CSV or JSON). Parse it yourself when files are attached; when `data` is empty, take numbers from the problem description.
- `VarSpec(name, var_type, size, lb=0.0, ub=1.0, n_categories=2)` where `var_type` is one of:
  * `"binary"` (`{0, 1}`), `"permutation"` (strictly `0..size-1`; e.g. for `size = N + 1`, elements are `0..N` and the last element is `N`, NEVER `N + 1`), `"assignment"` (strictly `0..n_categories-1`), `"integer"` (`[lb, ub]`), `"continuous"` (`[lb, ub]`).
- `Problem(name, variables: list[VarSpec], evaluate: Callable, senses: list["min" | "max"], decode: Callable | None = None)`:
  * `evaluate(x)` receives a 1D `np.ndarray` if `len(variables) == 1`, else `dict[str, np.ndarray]` keyed by `VarSpec.name`.
  * `evaluate(x)` ALWAYS returns a 2-tuple `(objectives, violation)` in original objective sign/units (`senses` handles `"max"` automatically) with `violation >= 0.0` (`0.0` iff all hard constraints hold): `objectives` is a `float` when `len(senses) == 1`, or `np.array([f_1, ..., f_m], dtype=float)` matching `len(senses)` when `len(senses) > 1`.
  * When the prompt requests specific output fields or readable schedules/routes, define `decode(x) -> dict` mapping a single `x` (same input format as `evaluate(x)`) to a plain-Python JSON-serializable `dict`, and pass `decode=decode`.

Rules:
1. Implement ONLY the core variables `X` from `Formulation.variables` and their stated forward decoding semantics; never add auxiliary variables, read external files/network, or invoke external solvers.
2. Decode mandatory decision elements losslessly (never silently `continue`/skip unassigned items before delimiters in a way that yields artificial zero cost) and evaluate disjunctive/piecewise constraints directly via `min`/`max` rather than `Big-M` relaxations.
3. Precompute constant data/distance arrays ONCE outside `evaluate(x)`, use 0-based indexing carefully, guard divisions against zero, and keep `evaluate(x)` fast with NumPy.
4. Do NOT call `solve()` inside the code; the platform runs the selected algorithm inside the sandbox.
""".strip()


class State(ModelingState, total=False):
    semantic_md: str
    formulation_data: dict[str, Any]
    review_issues: list[str]
    revision_count: int
    base_code: str
    problem_meta: dict[str, Any]
    selection: dict[str, Any]
    algorithm_summary: str


class _QueryKnowledgeArgs(BaseModel):
    concepts: list[str] = Field(description="List of pfeat:*, afeat:*, or algorithm names to query.")


class _InspectSpecsArgs(BaseModel):
    algorithms: list[str] = Field(description="Candidate algorithm names to inspect.")


class _PilotCandidate(BaseModel):
    algorithm: str
    operators: dict[str, str] = Field(default_factory=dict)
    hyperparameters: dict[str, float] = Field(default_factory=dict)


class _PilotVerifyArgs(BaseModel):
    candidates: list[_PilotCandidate] = Field(description="1-2 competing configurations to benchmark briefly in the sandbox.")
    trial_seconds: float = Field(default=1.2, description="Seconds per candidate trial.")


class _CommitConfigArgs(BaseModel):
    algorithm: str
    operators: dict[str, str] = Field(default_factory=dict)
    hyperparameters: dict[str, float] = Field(default_factory=dict)
    rationale: str = ""


def _extract_code(text: str) -> str:
    matches = python_code_blocks(text, allow_unclosed=True)
    if matches:
        return matches[-1].group(2).strip() + "\n"
    return text.strip() + "\n"


def _parse_marker_json(output: str) -> dict[str, Any] | None:
    for line in reversed(output.splitlines()):
        if line.startswith(_MARKER):
            return json.loads(line[len(_MARKER):])
    return None


def _smoke_script(code: str, data: dict[str, str]) -> str:
    return (
        "import json\n"
        "from autoco.runner import smoke_test_problem\n"
        f"code = {code!r}\n"
        f"data = {json.dumps(data, ensure_ascii=False)}\n"
        "meta = smoke_test_problem(code, data)\n"
        f"print({_MARKER!r} + json.dumps(meta, ensure_ascii=False))\n"
    )


def _pilot_script(code: str, data: dict[str, str], candidates: list[dict[str, Any]], trial_sec: float) -> str:
    return (
        "import json\n"
        "from autoco.runner import pilot_trial\n"
        f"code = {code!r}\n"
        f"data = {json.dumps(data, ensure_ascii=False)}\n"
        f"candidates = {json.dumps(candidates, ensure_ascii=False)}\n"
        f"trials = pilot_trial(code, data, candidates, {float(trial_sec)!r})\n"
        f"print({_MARKER!r} + json.dumps({{'trials': trials}}, ensure_ascii=False))\n"
    )


def _strip_invalid_calls(reply: AIMessage) -> tuple[AIMessage, list[dict[str, Any]]]:
    invalid = list(getattr(reply, "invalid_tool_calls", None) or [])
    if not invalid:
        return reply, []
    extra = {key: value for key, value in reply.additional_kwargs.items() if key != "tool_calls"}
    content = reply.text or ("" if reply.tool_calls else "[malformed tool call]")
    return reply.model_copy(update={"content": content, "invalid_tool_calls": [], "additional_kwargs": extra}), invalid


def _compose_final_code(base_code: str, selection: dict[str, Any], formulation: Formulation) -> str:
    config = {
        "algorithm": selection["algorithm"],
        "operators": selection.get("operators") or {},
        "hyperparameters": selection.get("hyperparameters") or {},
        "seed": presets.AUTOCO.seed,
        "objective_names": [obj.name for obj in formulation.objectives],
    }
    return base_code.rstrip() + "\n\nAUTOCO_CONFIG = " + json.dumps(config, ensure_ascii=False, indent=2) + "\n"


def _format_selection_markdown(selection: dict[str, Any], trace: list[dict[str, Any]]) -> str:
    lines = [
        f"### Selected Algorithm: `{selection['algorithm']}`",
        "",
        f"- **Operators**: `{json.dumps(selection.get('operators') or {}, ensure_ascii=False)}`",
        f"- **Hyperparameters**: `{json.dumps(selection.get('hyperparameters') or {}, ensure_ascii=False)}`",
    ]
    if selection.get("pilot_sec"):
        lines.append(f"- **Sandbox Pilot Time**: {selection['pilot_sec']:.2f}s")
    if selection.get("rationale"):
        lines.append(f"\n**Rationale**: {selection['rationale']}")
    pilot_trials = [entry["trials"] for entry in trace if entry.get("tool") == "pilot_verify" and entry.get("trials")]
    if pilot_trials:
        lines.append("\n#### Sandbox Pilot Trials")
        for batch in pilot_trials:
            for item in batch:
                if "error" in item:
                    lines.append(f"- `{item.get('algorithm')}`: error ({item['error']})")
                else:
                    lines.append(
                        f"- `{item.get('algorithm')}`: feasible={item.get('feasible')}, "
                        f"best_obj={item.get('best_objective')}, evals={item.get('n_evals')} "
                        f"({item.get('evals_per_sec')}/s)"
                    )
    return "\n".join(lines)


async def semantic_grounding(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    semantic = await ask_schema(runtime.context, "semantic_grounding", SEMANTIC_PROMPT, state["problem"], SemanticSpec)
    return {"semantic_md": semantic.to_markdown(), "revision_count": 0, "review_issues": []}


async def formulate(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context_text = f"## Problem Description\n{state['problem']}\n\n## Semantic Specification\n{state['semantic_md']}"
    issues = state.get("review_issues") or []
    if issues and state.get("formulation_data"):
        current_json = json.dumps(state["formulation_data"], ensure_ascii=False, indent=2)
        prompt = (
            f"{context_text}\n\n## Current Formulation\n{current_json}\n\n"
            "## Issues to Fix\n" + "\n".join(f"- {issue}" for issue in issues)
        )
    else:
        prompt = context_text
    form = await ask_schema(runtime.context, "formulate", FORMULATION_PROMPT, prompt, Formulation)
    return {
        "formulation": form.to_markdown(),
        "formulation_data": form.model_dump(),
        "review_issues": [],
    }


async def review_formulation(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    if state.get("revision_count", 0) >= presets.AUTOCO.max_modeling_revisions:
        return {"review_issues": []}
    context_text = (
        f"## Problem Description\n{state['problem']}\n\n## Semantic Specification\n{state['semantic_md']}\n\n"
        f"## Candidate Formulation\n{state['formulation']}"
    )
    review = await ask_schema(runtime.context, "review_formulation", REVIEW_PROMPT, context_text, FormulationReview)
    if review.passed or not review.issues:
        return {"review_issues": []}
    return {"review_issues": review.issues, "revision_count": state.get("revision_count", 0) + 1}


def after_review(state: State) -> str:
    return "formulate" if state.get("review_issues") else "instantiate"


async def instantiate(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    base_prompt = (
        f"## Problem Description\n{state['problem']}\n\n"
        f"## Typed 4-Tuple Formulation\n{state['formulation']}\n\n"
        "Return ONLY Python code defining `def build_model(data) -> Problem:` inside ```python ... ```."
    )
    prompt = base_prompt
    last_error = ""
    last_code = ""
    attempts = max(1, presets.AUTOCO.max_instantiate_attempts)
    for _ in range(attempts):
        reply = await context.llm("instantiate").ainvoke([
            SystemMessage(INSTANTIATE_PROBLEM_PROMPT + output_language(context)),
            HumanMessage(prompt),
        ])
        code = _extract_code(reply.text)
        last_code = code
        check = await context.run_script(_smoke_script(code, context.data))
        meta = _parse_marker_json(check.output) if check.executed else None
        if check.executed and isinstance(meta, dict) and meta.get("ok"):
            return {"base_code": code, "code": code, "problem_meta": meta}
        last_error = check.error or check.output.strip() or "Smoke test returned no metadata."
        prompt = f"{base_prompt}\n\n## Previous Code\n```python\n{code}\n```\n\n## Error to Fix\n{last_error}"
    return {
        "base_code": last_code,
        "code": last_code or None,
        "failure": f"Failed to instantiate a valid AutoCO Problem after {attempts} attempts:\n{last_error}",
    }


def after_instantiate(state: State) -> str:
    return END if state.get("failure") else "select_algorithm"


def _kg_tools(allow_pilot: bool) -> list[StructuredTool]:
    noop = lambda **kwargs: kwargs  # noqa: E731
    tools = [
        StructuredTool.from_function(
            noop,
            name="query_knowledge",
            args_schema=_QueryKnowledgeArgs,
            description="Query Problem-Feature <-> Algorithm-Feature relations (SUITS, CONFLICTS_WITH, SYNERGIZES_WITH) and matching pool components.",
        ),
        StructuredTool.from_function(
            noop,
            name="inspect_solver_specs",
            args_schema=_InspectSpecsArgs,
            description="Inspect mechanism features, valid operator slots, and default hyperparameters of candidate algorithms.",
        ),
        StructuredTool.from_function(
            noop,
            name="commit_configuration",
            args_schema=_CommitConfigArgs,
            description="Validate feature conflicts & syntax and commit final (algorithm, operators, hyperparameters).",
        ),
    ]
    if allow_pilot:
        tools.insert(
            2,
            StructuredTool.from_function(
                noop,
                name="pilot_verify",
                args_schema=_PilotVerifyArgs,
                description="Run short empirical trials in the sandbox on 1-2 competing configurations to check feasibility, turnover speed, and stagnation.",
            ),
        )
    return tools


def _fallback_algorithm(feats: dict[str, object]) -> str:
    if int(feats.get("n_objectives", 1)) >= 3:  # type: ignore[arg-type]
        return "NSGA-III"
    if feats.get("objective_mode") == "multi":
        return "MOEA/D"
    if set(feats.get("variable_types", [])) <= {"continuous"}:  # type: ignore[arg-type]
        return "CMA-ES"
    return "LNS"


async def select_algorithm(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    formulation = Formulation.model_validate(state["formulation_data"])
    time_limit = float(context.recorder.limits.solve_time_limit)
    feats = reconcile_features(formulation, state.get("problem_meta"), time_limit=time_limit)
    auto_pfeats = auto_problem_feature_ids(feats)
    kg = DEFAULT_KG

    allow_pilot = bool(presets.AUTOCO.enable_pilot and time_limit >= 5.0 and state.get("base_code"))
    max_pilot_budget = min(4.0, max(1.2, 0.08 * time_limit)) if allow_pilot else 0.0
    pilot_spent = 0.0
    tools = _kg_tools(allow_pilot)
    bound = context.llm("kg_agent").bind_tools(tools)

    messages: list[BaseMessage] = [
        SystemMessage(KG_AGENT_PROMPT + output_language(context)),
        HumanMessage(
            f"## Main Solve Budget: {time_limit:.1f}s (Pilot budget cap: {max_pilot_budget:.1f}s)\n\n"
            f"## Explicit Problem Features\n{json.dumps(feats, ensure_ascii=False, indent=2)}\n"
            f"Base `pfeat:*` tags: {auto_pfeats}\n"
            f"Available KG feature catalog: {json.dumps(kg.concept_catalog(), ensure_ascii=False)}\n\n"
            f"## Typed 4-Tuple Formulation\n{formulation.to_markdown()}"
        ),
    ]

    trace: list[dict[str, Any]] = []
    active_pfeats: set[str] = set(auto_pfeats)
    warned_once = False
    last_proposed: dict[str, Any] | None = None
    committed: dict[str, Any] | None = None
    max_steps = max(1, presets.AUTOCO.max_kg_steps)

    for step in range(max_steps):
        reply, invalid = _strip_invalid_calls(await bound.ainvoke(messages))
        if not reply.tool_calls and not invalid:
            messages.append(reply if reply.text else reply.model_copy(update={"content": "[empty response]"}))
            messages.append(
                HumanMessage(
                    "Call one of the available tools (`query_knowledge`, `inspect_solver_specs`, "
                    + ("`pilot_verify`, " if allow_pilot else "")
                    + "`commit_configuration`) to proceed."
                )
            )
            continue
        messages.append(reply)
        for idx, call in enumerate(reply.tool_calls):
            call_id = call.get("id") or f"call_{step}_{idx}"
            fn = call["name"]
            args = call.get("args") if isinstance(call.get("args"), dict) else {}
            if fn == "query_knowledge":
                c_list = [str(x) for x in (args.get("concepts") or [])]
                active_pfeats.update(c for c in kg.resolve_concepts(c_list) if c.startswith("pfeat:"))
                res: Any = kg.query_knowledge(c_list, features=feats)
                trace.append({"step": step + 1, "tool": fn, "concepts": c_list})
            elif fn == "inspect_solver_specs":
                a_list = [str(x) for x in (args.get("algorithms") or [])]
                res = kg.inspect_solver_specs(a_list, feats)
                trace.append({"step": step + 1, "tool": fn, "algorithms": a_list})
            elif fn == "pilot_verify":
                cands = [dict(c) for c in (args.get("candidates") or [])[:2] if isinstance(c, dict)]
                rem_pilot = max_pilot_budget - pilot_spent
                if not allow_pilot or rem_pilot < 0.4 or not cands:
                    res = {"note": "Pilot budget exhausted or unavailable; proceed to commit_configuration."}
                    trace.append({"step": step + 1, "tool": fn, "skipped": True})
                else:
                    req_s = float(args.get("trial_seconds", 1.2))
                    per_s = max(0.5, min(req_s, min(1.8, rem_pilot / len(cands))))
                    t0 = time.perf_counter()
                    pilot_res = await context.run_script(_pilot_script(state["base_code"], context.data, cands, per_s))
                    pilot_spent += time.perf_counter() - t0
                    parsed = _parse_marker_json(pilot_res.output) if pilot_res.executed else None
                    if isinstance(parsed, dict) and isinstance(parsed.get("trials"), list):
                        trials = parsed["trials"]
                    else:
                        trials = [{"error": pilot_res.error or pilot_res.output.strip() or "Pilot trial failed."}]
                    res = {
                        "trial_seconds_each": round(per_s, 2),
                        "remaining_pilot_budget": round(max(0.0, max_pilot_budget - pilot_spent), 2),
                        "trials": trials,
                    }
                    trace.append({"step": step + 1, "tool": fn, "trials": trials})
            elif fn == "commit_configuration":
                alg = str(args.get("algorithm", "GA"))
                ops = {str(k): str(v) for k, v in (args.get("operators") or {}).items()}
                hps = {str(k): float(v) for k, v in (args.get("hyperparameters") or {}).items() if v is not None}
                last_proposed = {
                    "algorithm": canonical_algorithm(alg),
                    "operators": ops,
                    "hyperparameters": hps,
                    "rationale": str(args.get("rationale", "")),
                    "pilot_sec": round(pilot_spent, 3),
                }
                ok, hard_errs, warnings = kg.validate_configuration(alg, ops, hps, feats, active_pfeats)
                if ok and (not warnings or warned_once or step >= max_steps - 1):
                    trace.append({"step": step + 1, "tool": fn, "accepted": True, "warnings": warnings})
                    committed = last_proposed
                    messages.append(ToolMessage(json.dumps({"accepted": True}, ensure_ascii=False), tool_call_id=call_id, name=fn))
                    break
                if ok and warnings:
                    warned_once = True
                res = {
                    "accepted": False,
                    "hard_errors": hard_errs,
                    "feature_conflict_warnings": warnings,
                    "hint": "Resolve hard_errors or feature_conflict_warnings (re-committing confirms intentional override if hard_errors is empty).",
                }
                trace.append({"step": step + 1, "tool": fn, "accepted": False, "hard_errors": hard_errs, "warnings": warnings})
            else:
                res = {"error": f"Unknown tool {fn}"}
            messages.append(ToolMessage(json.dumps(res, ensure_ascii=False), tool_call_id=call_id, name=fn))
        if committed is not None:
            break
        if invalid:
            errors = "; ".join(str(bad.get("error") or "invalid JSON arguments") for bad in invalid)
            messages.append(HumanMessage(f"Malformed tool call ({errors}). Retry with valid JSON arguments."))

    if committed is None and last_proposed is not None:
        ok, _, _ = kg.validate_configuration(
            str(last_proposed["algorithm"]), last_proposed["operators"], last_proposed["hyperparameters"], feats
        )
        if ok:
            committed = last_proposed
    if committed is None:
        committed = {
            "algorithm": _fallback_algorithm(feats),
            "operators": {},
            "hyperparameters": {},
            "rationale": "Fallback valid configuration selected from problem features.",
            "pilot_sec": round(pilot_spent, 3),
        }

    final_code = _compose_final_code(state["base_code"], committed, formulation)
    return {
        "selection": committed,
        "algorithm_summary": _format_selection_markdown(committed, trace),
        "code": final_code,
    }


async def solve_problem(state: State, runtime: Runtime[Context]) -> dict[str, Any]:
    context = runtime.context
    selection = state["selection"]
    alg = canonical_algorithm(str(selection.get("algorithm", "AUTO")))
    if alg not in ALGORITHM_SPECS:
        alg = "AUTO"
    total_budget = float(context.recorder.limits.solve_time_limit)
    pilot_sec = float(selection.get("pilot_sec", 0.0))
    rem_budget = max(2.0, total_budget - min(pilot_sec, 0.2 * total_budget)) if total_budget >= 5.0 else total_budget
    result = await context.solve(
        state["code"],
        title=f"AutoCO 求解（{alg}）",
        language="autoco",
        solver=alg,
        time_limit=rem_budget,
    )
    return {"solve": result}


def autoco_graph():
    graph = StateGraph(State, context_schema=Context)
    for node in (semantic_grounding, formulate, review_formulation, instantiate, select_algorithm, solve_problem):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "semantic_grounding")
    graph.add_edge("semantic_grounding", "formulate")
    graph.add_edge("formulate", "review_formulation")
    graph.add_conditional_edges("review_formulation", after_review, ["formulate", "instantiate"])
    graph.add_conditional_edges("instantiate", after_instantiate, ["select_algorithm", END])
    graph.add_edge("select_algorithm", "solve_problem")
    graph.add_edge("solve_problem", END)
    return graph.compile(name="autoco")


AUTOCO = Method(
    "autoco",
    "AutoCO",
    "面向组合与黑盒优化的两阶段紧凑建模、特征知识图谱与沙箱试跑选配，并调用内置 12 类智能优化算法求解。",
    autoco_graph,
    titles={
        "semantic_grounding": "语义分析",
        "formulate": "四元组建模",
        "review_formulation": "模型自审",
        "instantiate": "编写问题代码",
        "select_algorithm": "知识图谱选配算法",
        "solve_problem": "智能优化求解",
    },
    hidden=frozenset({"formulation_data", "review_issues", "revision_count", "base_code", "problem_meta", "selection"}),
    languages=frozenset(),
    builtin_solver=True,
    parameters=lambda: asdict(presets.AUTOCO),
)
