import type { Step } from "./types";

/**
 * A phase of the modeling process: one milestone (an intermediate result, a solve or an error) with the LLM calls
 * made since the previous milestone. LLM calls not yet followed by a milestone form a trailing "working" phase.
 */
export type Phase = {
  id: string;
  kind: "artifact" | "solve" | "error" | "working";
  step: Step | null;
  calls: Step[];
  seconds: number;
};

export function phases(steps: Step[]): Phase[] {
  const result: Phase[] = [];
  let calls: Step[] = [];
  const seconds = (items: Step[]) => items.reduce((total, item) => total + (item.seconds ?? 0), 0);
  for (const step of steps) {
    if (step.type === "llm") { calls.push(step); continue; }
    result.push({ id: step.id, kind: step.type, step, calls, seconds: seconds(calls) + (step.type === "solve" ? step.seconds ?? 0 : 0) });
    calls = [];
  }
  if (calls.length) result.push({ id: "working-" + calls[0].id, kind: "working", step: null, calls, seconds: seconds(calls) });
  return result;
}

/** What the LLM calls of a phase are doing now, or null when none is running. */
export function working(calls: Step[]): string | null {
  const running = calls.filter(call => call.running);
  if (!running.length) return null;
  if (running.length === 1) return roleName(running[0].title);
  const roles = [...new Set(running.map(call => roleName(call.title)))];
  return `${running.length} 个并行调用（${roles.slice(0, 3).join("、")}${roles.length > 3 ? "……" : ""}）`;
}

/** The name of an LLM call's role without its method prefix: "trival.code_agent" → "code agent". */
export const roleName = (role: string) => role.slice(role.lastIndexOf(".") + 1).replace(/_/g, " ");

/** The first readable line of Markdown, for a one-line preview. */
export function preview(markdown: string, length = 160): string {
  const text = markdown
    .replace(/```[\s\S]*?(```|$)/g, " ")
    .split("\n")
    .map(line => line.replace(/^#+\s*/, "").replace(/^[-*+>]\s+/, "").replace(/^\|.*\|$/, "").replace(/\*\*|__|[`$]/g, "").replace(/\\[()[\]]/g, "").trim())
    .filter(line => line && !/^[-:| ]+$/.test(line))
    .join(" · ");
  return text.length > length ? text.slice(0, length) + "…" : text;
}

/** Each formulation or code a method wrote, oldest first, with the step that wrote it. */
export type Version = { id: string; title: string; text: string; time: number };

export function versions(steps: Step[], key: "formulation" | "code", final?: string | null): Version[] {
  const found: Version[] = [];
  for (const step of steps) {
    const text = step.type === "artifact" ? step[key] : undefined;
    if (text && text !== found[found.length - 1]?.text) found.push({ id: step.id, title: step.title, text, time: step.time });
  }
  if (final && final !== found[found.length - 1]?.text) found.push({ id: "final", title: "最终结果", text: final, time: Infinity });
  return found;
}
