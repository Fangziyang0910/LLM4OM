import type { Options } from "@/types";
import type { RunMeta } from "./types";

/** Render saved targets without interpreting old library/backend pairs as new libraries. */
export function targetLabel(options: Options, meta: Pick<RunMeta, "language" | "solver">, actualSolver?: string | null): string {
  const legacy = /^cvxpy_(osqp|scs|mosek)$/.exec(meta.language);
  const id = legacy ? "cvxpy" : meta.language === "pywraplp" ? "ortools" : meta.language;
  const library = options.languages.find(item => item.id === id);
  const solver = actualSolver ?? meta.solver ?? legacy?.[1].toUpperCase() ?? library?.solver;
  return [library?.name ?? id, solver === "AUTO" ? undefined : solver].filter(Boolean).join(" · ");
}
