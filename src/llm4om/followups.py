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


async def revise_problem(context: Context, description: str, instruction: str) -> str:
    reply = await context.llm("revise_problem").ainvoke([
        SystemMessage("Revise an optimization problem according to the user's change request. "
                      "Return only the complete revised problem in Markdown, in the original language. "
                      "Preserve all requirements, units, data-file references and objectives not changed by the request. "
                      "Replace superseded requirements rather than appending contradictory ones. "
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
    language = "简体中文" if locale == "zh" else "English"
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
                      "by the supplied material; do not list unspecified features. "
                      "A feasible or locally optimal solution is not a proven global optimum.\n"
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
