import { normalizeTarget } from "@/features/runs/target";
import type { Draft } from "@/types";

export const DRAFT_KEY = "llm4om-draft";

export function initialDraft(): Draft {
  let saved: Partial<Draft> = {};
  try { saved = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "{}") ?? {}; } catch { /* storage may be unavailable */ }
  const target = normalizeTarget(saved.language, saved.solver);
  return { description: saved.description ?? "", data: saved.data ?? {}, method: saved.method ?? "direct",
    language: target.language, preset: saved.preset ?? null, solver: target.solver, time_limit: saved.time_limit,
    origin: saved.origin, comparing: saved.comparing ?? false, methods: saved.methods ?? [], presets: saved.presets ?? [] };
}
