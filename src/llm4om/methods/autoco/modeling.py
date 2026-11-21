"""Two-stage compact combinatorial modeling for AutoCO: Semantic Grounding -> Typed 4-Tuple Formulation."""

from __future__ import annotations

import json
from typing import Literal, TypeVar

import json_repair
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field, ValidationError

from llm4om.methods.common import strip_json_fence
from llm4om.runtime import Context

T = TypeVar("T", bound=BaseModel)

VarType = Literal["binary", "integer", "continuous", "permutation", "assignment"]
Sense = Literal["min", "max"]
ScaleLevel = Literal["small", "medium", "large"]
ObjectiveForm = Literal["linear", "quadratic", "nonlinear", "minmax"]
ConstraintCategory = Literal["bound", "capacity", "precedence", "conflict", "equality", "nonlinear"]


class SemanticSpec(BaseModel):
    parameters: list[str] = Field(description="Known sets, dimensions, and input data in plain language.")
    objectives: list[str] = Field(description="Optimization goal(s), direction(s), and cost/benefit meaning.")
    constraints: list[str] = Field(description="All hard rules, limits, and structural requirements.")
    assumptions: list[str] = Field(
        default_factory=list,
        description="Conventions resolving genuine modeling ambiguities; empty list if unambiguous.",
    )

    def to_markdown(self) -> str:
        parts = [
            "## Parameters\n" + "\n".join(f"- {x}" for x in self.parameters),
            "## Objectives\n" + "\n".join(f"- {x}" for x in self.objectives),
            "## Constraints\n" + "\n".join(f"- {x}" for x in self.constraints),
        ]
        if self.assumptions:
            parts.append("## Assumptions\n" + "\n".join(f"- {x}" for x in self.assumptions))
        return "\n\n".join(parts)


class ParameterSpec(BaseModel):
    name: str
    description: str
    value: str


class VariableSpec(BaseModel):
    name: str
    var_type: VarType
    domain: str
    shape: str
    description: str


class ObjectiveSpec(BaseModel):
    name: str
    sense: Sense
    form: ObjectiveForm
    expr: str
    description: str


class ConstraintSpec(BaseModel):
    name: str
    category: ConstraintCategory
    expr: str
    description: str


class Formulation(BaseModel):
    """Typed 4-Tuple M = (P, X, F, C) carrying both math expressions and intrinsic problem features."""

    scale_level: ScaleLevel
    parameters: list[ParameterSpec]
    variables: list[VariableSpec]
    objectives: list[ObjectiveSpec] = Field(min_length=1)
    constraints: list[ConstraintSpec] = Field(default_factory=list)

    def features(self) -> dict[str, object]:
        var_types = list(dict.fromkeys(v.var_type for v in self.variables))
        obj_forms = list(dict.fromkeys(o.form for o in self.objectives))
        con_cats = list(dict.fromkeys(c.category for c in self.constraints)) or ["unconstrained"]
        return {
            "scale_level": self.scale_level,
            "objective_mode": "multi" if len(self.objectives) > 1 else "single",
            "objective_forms": obj_forms,
            "variable_types": var_types,
            "is_mixed_variables": len(self.variables) > 1,
            "constraint_categories": con_cats,
        }

    def to_markdown(self) -> str:
        lines = [f"## Parameters (scale: {self.scale_level})"]
        lines += [f"- `{p.name}` = {p.value}: {p.description}" for p in self.parameters]
        lines.append("\n## Variables")
        lines += [
            f"- `{v.name}` ({v.var_type}, domain `{v.domain}`, shape `{v.shape}`): {v.description}"
            for v in self.variables
        ]
        lines.append("\n## Objectives")
        lines += [f"- **{o.sense}** `{o.name}` ({o.form}): `{o.expr}` — {o.description}" for o in self.objectives]
        lines.append("\n## Constraints")
        lines += (
            [f"- `{c.name}` ({c.category}): `{c.expr}` — {c.description}" for c in self.constraints]
            if self.constraints
            else ["- (unconstrained)"]
        )
        return "\n".join(lines)


class FormulationReview(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)


SEMANTIC_PROMPT = """
Extract the plain-language semantic specification of the optimization problem:
1. Stay purely at the semantic level (no decision variables, equations, or solver hints).
2. Default to a SINGLE optimization objective in `objectives` unless the problem explicitly asks to optimize multiple conflicting goals simultaneously; NEVER turn resource limits (e.g. distance/time/capacity budgets) or `Print the following fields` diagnostics into extra objectives.
3. Capture all sets/parameters and hard constraints faithfully; populate `assumptions` ONLY if genuine textual ambiguity affects the math model, else `[]`.
""".strip()

FORMULATION_PROMPT = """
Construct a Typed 4-Tuple formulation M = (P, X, F, C) oriented toward metaheuristic/evolutionary search.

Principles:
1. Intrinsic Degrees of Freedom (`X`) — Strictly 0-Based 1D Encodings:
   - Include ONLY independent 1D search decisions in `variables` (`X`) using the 5 canonical types: `permutation` (strictly 0-based `{0..S-1}`), `assignment` (strictly 0-based `{0..K-1}`), `binary` (`{0, 1}`), `integer` (`[lb, ub]`), `continuous` (`[lb, ub]`).
   - NEVER introduce 2D binary arc/assignment matrices (`shape` `(N, M)` or `(N, N)` one-hot encoding single-choice mappings or routes), `Big-M` variables, or derived state variables (event/arrival/completion timestamps, cumulative loads, group-used flags). Compute sequential states and counts via forward recurrences directly in `F` and `C`.
2. Feasible-by-Construction Domain Topology (`X`):
   - Match domain topology to structural constraints so random/mutated candidates stay out of dead space:
     * Sequence & optional-prefix routing: WHEN visiting order matters, use 0-based `permutation` with `K - 1` delimiters to split `N` items (`0..N-1`) into `K` ordered segments `0..K-1` (`size = N + K - 1`, delimiters `N..N+K-2`, where segment `0` precedes the first delimiter — NEVER use `K` markers that drop items before the first marker), or visit an ordered optional prefix before stopping (`size = N + 1`, stop delimiter `N`, NEVER `N + 1`), or map `val // M` for repeated operations.
     * Many-to-one mapping, unordered grouping & active-subset selection: represent "each of `N` items chooses 1 of `K` options/bins/groups/colors" (whenever within-group order does NOT affect cost or constraints) as a 1D `assignment` (`shape` `(N,)`, domain `0..K-1`), NEVER as a delimiter permutation. When simultaneously choosing `p` active options out of `M` AND assigning `N` items only to active options, encode active selection as `permutation(M)` (taking prefix `[:p]`) and item mapping as `assignment(N)` over relative indices `{0..p-1}` (NEVER `binary(M)` + `assignment(N)` or `0..M-1`).
   - Keep every `description` field brief (1-2 concise sentences) stating the exact decoding semantics.
3. Parameters (`P`): define sets and input data clearly; tag `scale_level` (`small` <= 30, `medium` 31..200, `large` > 200).
4. Objectives (`F`): match true optimization goal(s) (1 objective unless explicitly multi-objective); tag `sense` (`min`/`max`) and `form` (`linear`, `quadratic`, `minmax`, `nonlinear`).
5. Constraints (`C`): include ONLY remaining constraints not already guaranteed by `X`'s encoding; tag `category` (`bound`, `capacity`, `precedence`, `conflict`, `equality`, `nonlinear`), or `[]` if unconstrained given `X`. Since `C` is evaluated procedurally in Python rather than by a linear solver, NEVER write `Big-M` disjunctive linearizations or auxiliary selector binaries in `C` — express logical OR / disjunctive / piecewise conditions directly via closed-form `min`/`max` expressions.
""".strip()

REVIEW_PROMPT = """
Audit M = (P, X, F, C) for semantic fidelity and metaheuristic search compactness:
1. Objectives & constraints match the problem faithfully without turning resource budgets or `Print` fields into extra objectives.
2. `variables` (`X`) are strictly 1D intrinsic search decisions — REJECT if ANY variable is:
   - a 2D binary assignment/routing matrix (`(N, M)` or `(N, N)`) instead of a 1D `assignment` or `permutation` vector;
   - a derived state/timestamp/indicator computable from `X`;
   - a 1-based discrete domain (`{1..S}`) instead of 0-based `{0..S-1}`, or a plain `permutation(N)` that forces visiting optional nodes (must use `permutation(N + 1)` with delimiter `N`), or a delimiter decoding that silently drops items appearing before the first delimiter;
   - an unlinked master-slave pair (`binary(M)` + `binary`/`assignment`) instead of `permutation(M)` prefix `[:p]` + relative `assignment(N)` in `{0..p-1}`.
3. All symbols and forward decoding recurrences in `F` and `C` are well-defined over `P` and `X`, with NO `Big-M` disjunctive linearizations or unmodeled selector binaries inside `C` (disjunctions must use native `min`/`max` form).
Set `passed = true` (`issues = []`) iff all checks pass; otherwise list 1-3 concrete fixes.
""".strip()


def _parse_model(text: str, schema: type[T]) -> T:
    raw = strip_json_fence(text)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = json_repair.loads(raw)
    return schema.model_validate(parsed)


async def ask_schema(context: Context, role: str, system_prompt: str, user_prompt: str, schema: type[T]) -> T:
    """Query `context.llm(role)` for a JSON object matching `schema`, retrying up to 3 times on parse errors."""
    parser = PydanticOutputParser(pydantic_object=schema)
    messages: list[BaseMessage] = [
        SystemMessage(system_prompt + "\n\nReturn ONLY a valid JSON object matching this schema:\n" + parser.get_format_instructions()),
        HumanMessage(user_prompt),
    ]
    llm = context.llm(role)
    for attempt in range(3):
        reply = await llm.ainvoke(messages)
        try:
            return _parse_model(reply.text, schema)
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError) as exc:
            if attempt == 2:
                raise ValueError(f"Could not parse {schema.__name__} JSON after 3 attempts: {exc}") from exc
            messages.append(reply)
            messages.append(HumanMessage(f"Invalid JSON for {schema.__name__} ({exc}). Return ONLY valid JSON matching the schema."))
    raise RuntimeError("Unreachable")
