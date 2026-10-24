"""Platform operations around modeling: revise the problem and explain an actual solution."""

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

from llm4om.runtime import Context

MAX_EXPLAINED_VARIABLES = 100


class Decision(BaseModel):
    variable: str = Field(description="Exact variable name from the supplied solution")
    label: str = Field(description="Business meaning of this decision, without its numeric value")
    unit: str = ""


class Explanation(BaseModel):
    summary: str = Field(min_length=1, description="A short qualitative explanation of the proposed plan")
    objective_label: str = Field(description="Business meaning of the objective, without its numeric value")
    objective_unit: str = ""
    decisions: list[Decision] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list, max_length=3, description="Up to three key requirements actually used")


class ConflictReason(BaseModel):
    constraint_ids: list[int] = Field(min_length=1, description="One-based IDs of the supplied conflicting constraints")
    explanation: str = Field(min_length=1, description="Business meaning of this conflict, in plain language")


class Adjustment(BaseModel):
    title: str = Field(min_length=1, description="Short name of a candidate change to the user's requirements")
    instruction: str = Field(min_length=1, description="A complete change request with explicit new requirements, no missing values")


class InfeasibilityExplanation(BaseModel):
    summary: str = Field(min_length=1, description="Why the computed model cannot meet these requirements together")
    conflicts: list[ConflictReason] = Field(min_length=1, max_length=5)
    adjustments: list[Adjustment] = Field(default_factory=list, max_length=1,
                                           description="At most one concrete change with the strongest basis; preserve explicitly fixed requirements")


async def revise_problem(context: Context, description: str, instruction: str) -> str:
    reply = await context.llm("revise_problem").ainvoke([
        SystemMessage("Revise an optimization problem according to the user's change request. "
                      "Return only the complete revised problem in Markdown, in the original language. "
                      "Preserve all requirements, units, data-file references and objectives not changed by the request. "
                      "Replace superseded requirements rather than appending contradictory ones. "
                      "When replacing a numeric parameter, preserve its physical meaning and constraint direction: "
                      "changing available capacity from 8 to 15 changes usage <= 8 to usage <= 15, never to usage >= 15. "
                      "An increase in capacity does not impose a minimum production target or make capacity a free decision. "
                      "Do not solve the problem, write code, invent missing data or silently relax constraints. "
                      "The attached files stay unchanged; express requested exceptions explicitly in the problem."),
        HumanMessage(json.dumps({"original_problem": description, "change_request": instruction,
                                 "data_files": list(context.data)}, ensure_ascii=False)),
    ])
    if not reply.text.strip():
        raise ValueError("The change request did not produce a revised problem.")
    return reply.text.strip()


async def explain_result(context: Context, problem: str, formulation: str | None,
                         code: str | None, solve: dict[str, Any], locale: str) -> dict[str, Any]:
    variables = solve.get("variables") or {}
    nonzero = {name: value for name, value in variables.items() if value != 0}
    shown = dict(list((nonzero or variables).items())[:MAX_EXPLAINED_VARIABLES])
    parser = PydanticOutputParser(pydantic_object=Explanation)
    language = "Simplified Chinese" if locale == "zh" else "English"
    reply = await context.llm("explain_result").ainvoke([
        SystemMessage("Explain a computed optimization solution for an ordinary user. "
                      f"Write ALL user-facing strings (summary, labels, units and notes) in {language}, "
                      "regardless of the language used by the mathematical model or code. Keep variable keys exact. "
                      "Use one or two short sentences for the summary, short business labels, and at most three notes. "
                      "Use only the supplied problem, mathematical model, code and actual solver result. "
                      "Identify the business meanings and units of the objective and the supplied decision variables. "
                      "The platform fills in the numeric values: do not put solution values in prose or labels. "
                      "Use qualitative prose; do not invent resource utilization, remaining capacity, optimality "
                      "proofs or sensitivity claims. Mention only key requirements actually supported "
                      "by the supplied material; notes contain only business requirements from the problem. "
                      "Do not add generic disclaimers, proof caveats, unspecified features or tool limitations. "
                      "The platform displays solver status separately. Respect that status: optimal means the solver "
                      "proved optimality for this model; feasible or locally_optimal does not mean a global optimum.\n"
                      + parser.get_format_instructions()),
        HumanMessage(json.dumps({"problem": problem, "formulation": formulation, "code": code,
                                 "status": solve["status"], "objective": solve.get("objective"),
                                 "variables": shown, "total_variables": len(variables)}, ensure_ascii=False)),
    ])
    explanation = parser.parse(reply.text)
    names = [decision.variable for decision in explanation.decisions]
    if any(name not in shown for name in names) or len(names) != len(set(names)):
        raise ValueError("The explanation must reference distinct variables from the actual solution.")
    return {**explanation.model_dump(), "total_variables": len(variables)}


async def explain_infeasibility(context: Context, problem: str, formulation: str | None,
                                code: str | None, solve: dict[str, Any], locale: str) -> dict[str, Any]:
    diagnosis = solve["diagnosis"]
    items = diagnosis["items"]
    parser = PydanticOutputParser(pydantic_object=InfeasibilityExplanation)
    language = "Simplified Chinese" if locale == "zh" else "English"
    reply = await context.llm("explain_infeasibility").ainvoke([
        SystemMessage("Explain an infeasible optimization model for an ordinary user using the actual solver diagnosis. "
                      f"Write all user-facing strings in {language}. Explain the conflicting business requirements "
                      "in short, concrete sentences and cite their supplied constraint IDs. Use the problem, formulation "
                      "and code to map constraints to their business meaning. The diagnosis concerns this computed model; "
                      "it does not prove that the model correctly represents the user's problem. "
                      "The constraint list may be truncated: explain only what the supplied evidence supports. "
                      "Offer at most ONE practical change with the strongest basis in the diagnosis, as a standalone "
                      "user instruction. Preserve unrelated requirements and requirements explicitly declared fixed: "
                      "for example, if the user says not to change a contract, do not lower its required quantities. "
                      "Give an explicit new bound when one is needed. You may derive a candidate bound by simple arithmetic "
                      "from the supplied constraints; describe a hypothetical change, not currently available resources. "
                      "Choose one exact scenario value for a fixed parameter. For example, write 'set the capacity upper "
                      "bound to 15 (usage <= 15)', not 'capacity at least 15' or a range of unspecified values. "
                      "Do not change physical consumption coefficients, units or factual data just to remove a conflict. "
                      "Do not give vague instructions to recheck data, negotiate unspecified values or make capacity sufficient. "
                      "Do not change code or silently relax a requirement. These are candidates for a new solve, not verified "
                      "feasible repairs. Do not claim a minimum change or invent business facts. "
                      "Omit candidates unless their concrete new requirements have a clear basis in the supplied material.\n"
                      + parser.get_format_instructions()),
        HumanMessage(json.dumps({"problem": problem, "formulation": formulation, "code": code,
                                 "tool": diagnosis["tool"], "total_constraints": diagnosis["total"],
                                 "constraints": {str(i): item for i, item in enumerate(items, 1)}}, ensure_ascii=False)),
    ])
    explanation = parser.parse(reply.text)
    if any(not 1 <= index <= len(items) for conflict in explanation.conflicts for index in conflict.constraint_ids):
        raise ValueError("The explanation must reference constraints from the actual solver diagnosis.")
    return {"summary": explanation.summary,
            "conflicts": [{"explanation": conflict.explanation,
                           "constraints": [items[index - 1] for index in dict.fromkeys(conflict.constraint_ids)]}
                          for conflict in explanation.conflicts],
            "adjustments": [item.model_dump() for item in explanation.adjustments]}
