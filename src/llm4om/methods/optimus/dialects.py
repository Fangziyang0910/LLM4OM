"""Inject native examples into OptiMUS component prompts; the method's reasoning stays unchanged."""

from llm4om.methods.optimus import prompts as P
from llm4om.model_code import ModelCode


def constraint_prompt(code: ModelCode) -> str:
    return (P.TARGET_CODE__PROMPT_CONSTRAINTS_CODE
            .replace("    model.addConstr(SalesVolumes[i] <= MaxProductionVolumes[i])",
                     "    " + code.constraint("SalesVolumes[i] <= MaxProductionVolumes[i]"))
            .replace("Gurobi does not support a <= x <= b syntax", "Use separate constraints for lower and upper bounds"))


def objective_prompt(code: ModelCode) -> str:
    return P.TARGET_CODE__PROMPT_OBJECTIVE_CODE.replace(
        "model.setObjective(quicksum(price[i] * x[i] for i in range(N)), GRB.MAXIMIZE)",
        code.objective("quicksum(price[i] * x[i] for i in range(N))", "max"))
