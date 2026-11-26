import { t } from "@/i18n";
import type { ParetoObjective } from "./types";

export function objectiveLabel(objective: ParetoObjective): string {
  let name = objective.label || objective.name;
  if (!objective.label) {
    if (name === "total_electricity_cost") name = t("总电费");
    else if (name === "total_fault_risk") name = t("总故障风险");
    else if (/^[a-z][a-z0-9]*(_[a-z0-9]+)+$/i.test(name)) name = name.replaceAll("_", " ");
  }
  return objective.unit ? `${name} (${objective.unit})` : name;
}

/** Both the plot and table select from the displayed representatives in the same order. */
export function adjacentSolution(key: string, current: number, count: number): number | undefined {
  switch (key) {
    case "Home": return 0;
    case "End": return count - 1;
    case "ArrowUp":
    case "ArrowLeft": return Math.max(0, current - 1);
    case "ArrowDown":
    case "ArrowRight": return Math.min(count - 1, current + 1);
  }
}
