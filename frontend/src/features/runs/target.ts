import type { Options } from "@/types";
import type { RunMeta } from "./types";

/** Normalize legacy library/backend pairs (`cvxpy_osqp`, `pywraplp`) into `{ language, solver }`. */
export function normalizeTarget(language?: string, solver?: string): { language: string; solver?: string } {
  const legacy = /^cvxpy_(osqp|scs|mosek)$/.exec(language ?? "");
  return {
    language: legacy ? "cvxpy" : language === "pywraplp" ? "ortools" : language || "pyomo",
    solver: solver ?? legacy?.[1].toUpperCase(),
  };
}

/** Render saved targets without interpreting old library/backend pairs as new libraries. */
export function targetLabel(options: Options, meta: Pick<RunMeta, "language" | "solver">, actualSolver?: string | null): string {
  const normalized = normalizeTarget(meta.language, meta.solver);
  const library = options.languages.find(item => item.id === normalized.language);
  const solver = actualSolver ?? normalized.solver ?? library?.solver;
  return [library?.name ?? normalized.language, solver === "AUTO" ? undefined : solver].filter(Boolean).join(" · ");
}
