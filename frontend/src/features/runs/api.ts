import { outcome } from "@/format";
import { t } from "@/i18n";
import type { Draft } from "@/features/composer/types";
import type { Entry, RunMeta, RunSpec, Usage } from "@/features/runs/types";
import type { Preset } from "@/types";

/** The LangGraph SDK client, loaded on first use. */
const sdk = () => import("@/features/runs/sdk").then(module => module.client);

/** Create a thread for the draft and start its run in the background; returns the thread id. */
export async function startRun(draft: Draft, preset: Preset | undefined, group: string | null = null): Promise<string> {
  if (draft.preset && !preset) throw new Error(t("原预设已删除，请重新选择预设模型。"));
  const title = draft.description.trim().split("\n")[0].slice(0, 120);
  const meta: RunMeta = { title, method: draft.method, language: draft.language, preset: preset?.id ?? null,
    ...(draft.solver ? { solver: draft.solver } : {}),
    provider: preset?.provider ?? null, model: preset?.name || preset?.model || null, ...(group ? { group } : {}) };
  const client = await sdk();
  const thread = await client.threads.create({ metadata: meta });
  try {
    await client.runs.create(thread.thread_id, draft.method, {
      input: { description: draft.description, data: draft.data },
      context: { language: draft.language, solver: draft.solver, preset: preset?.id ?? null },
      streamMode: ["custom"], streamResumable: true,
    });
  } catch (error) {
    // A rejected start (for example the hourly run limit) must not leave an empty run in the history.
    await client.threads.delete(thread.thread_id).catch(() => undefined);
    throw error;
  }
  return thread.thread_id;
}

/** Start one run of the same problem for each method and preset, as one comparison. If a start fails after others
 * started, those runs stay in the comparison and `error` says why the rest did not start. */
export async function startComparison(draft: Draft, runs: { method: string; preset: Preset | undefined }[]):
    Promise<{ group: string; started: number; error: unknown }> {
  // crypto.randomUUID needs HTTPS; the workbench is often opened over plain HTTP on the network.
  const group = Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");
  let started = 0;
  try {
    for (const item of runs) { await startRun({ ...draft, method: item.method }, item.preset, group); started++; }
  } catch (error) {
    if (!started) throw error;
    return { group, started, error };
  }
  return { group, started, error: null };
}

/** Merge `change` into a run's metadata: its note and tags. */
export async function updateMeta(threadId: string, change: Partial<Pick<RunMeta, "note" | "tags">>): Promise<void> {
  await (await sdk()).threads.update(threadId, { metadata: change });
}

/** Recorded configuration owns these fields; thread metadata also holds editable notes and legacy records. */
export function runMeta(metadata: RunMeta, spec?: RunSpec | null): RunMeta {
  return spec ? { ...metadata, method: spec.method, language: spec.language, solver: spec.solver, preset: spec.preset,
    provider: spec.llm.provider, model: spec.preset_name || spec.llm.model } : metadata;
}

export async function deleteRun(threadId: string): Promise<void> {
  try { await (await sdk()).threads.delete(threadId); }
  catch (error) {
    // A retry also clears progress left after the thread was already deleted.
    if (!(error instanceof Error && "status" in error && error.status === 404)) throw error;
  }
}

const PAGE_SIZE = 100;
export async function history(metadata?: Record<string, unknown>, offset = 0): Promise<{ entries: Entry[]; nextOffset: number | undefined }> {
  const threads = await (await sdk()).threads.search({ limit: PAGE_SIZE, offset, sortBy: "created_at", sortOrder: "desc", metadata,
    select: ["thread_id", "created_at", "updated_at", "status", "metadata"],
    extract: { objective: "values.solve.objective", solved: "values.solve.status", failure: "values.failure", usage: "values.usage",
      elapsed: "values.timing.elapsed", finished_at: "values.timing.finished_at", spec: "values.spec", actual_solver: "values.solve.solver" } });
  const entries = threads.filter(thread => thread.metadata?.title).map(thread => {
    const extracted = (thread as unknown as { extracted?: Record<string, unknown> }).extracted ?? {};
    // A thread is idle once its run finished; interrupted and error keep the run's own status.
    const state = outcome(thread.status === "busy", thread.status === "idle" ? "success" : thread.status, extracted.failure,
      extracted.solved as string | undefined);
    const spec = extracted.spec as RunSpec | undefined;
    const meta = runMeta(thread.metadata as RunMeta, spec);
    if (typeof extracted.actual_solver === "string") meta.solver = extracted.actual_solver;
    return { id: thread.thread_id, created: thread.created_at, updated: thread.updated_at, meta, state,
      objective: typeof extracted.objective === "number" ? extracted.objective : null,
      elapsed: extracted.finished_at && typeof extracted.elapsed === "number" ? extracted.elapsed : null,
      failure: typeof extracted.failure === "string" ? extracted.failure : null, usage: (extracted.usage as Usage | undefined) ?? null };
  });
  return { entries, nextOffset: threads.length === PAGE_SIZE ? offset + PAGE_SIZE : undefined };
}
