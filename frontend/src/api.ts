import { outcome } from "./format";
import { t } from "./i18n";
import type { Draft, Entry, Preset, RunMeta, Usage } from "./types";

/** The LangGraph SDK client, loaded on first use. */
const sdk = () => import("./sdk").then(module => module.client);

// The platform's own routes. All requests are JSON; the server rejects other POST bodies.
export async function api<T>(path: string, body?: unknown, method = body === undefined ? "GET" : "POST"): Promise<T> {
  const response = await fetch(path, body === undefined ? { method } : {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = value.detail;
    throw new Error(typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : t("请求失败（{status}）", { status: response.status }));
  }
  return value as T;
}

/** Create a thread for the draft and start its run in the background; returns the thread id. */
export async function startRun(draft: Draft, preset: Preset | undefined, group: string | null = null): Promise<string> {
  const title = draft.description.trim().split("\n")[0].slice(0, 120);
  const meta: RunMeta = { title, method: draft.method, language: draft.language, preset: preset?.id ?? null,
    provider: preset?.provider ?? null, model: preset?.model ?? null, ...(group ? { group } : {}) };
  const client = await sdk();
  const thread = await client.threads.create({ metadata: meta });
  try {
    await client.runs.create(thread.thread_id, draft.method, {
      input: { description: draft.description, data: draft.data },
      context: { language: draft.language, preset: preset?.id ?? null },
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
export async function updateMeta(threadId: string, change: Partial<RunMeta>): Promise<void> {
  await (await sdk()).threads.update(threadId, { metadata: change });
}

export async function deleteRun(threadId: string): Promise<void> {
  await (await sdk()).threads.delete(threadId);
}

export async function history(metadata?: Record<string, unknown>): Promise<Entry[]> {
  const threads = await (await sdk()).threads.search({ limit: 200, sortBy: "created_at", sortOrder: "desc", metadata,
    select: ["thread_id", "created_at", "updated_at", "status", "metadata"],
    extract: { objective: "values.solve.objective", solved: "values.solve.status", failure: "values.failure", usage: "values.usage" } });
  return threads.filter(thread => thread.metadata?.title).map(thread => {
    const extracted = (thread as unknown as { extracted?: Record<string, unknown> }).extracted ?? {};
    // A thread is idle once its run finished; interrupted and error keep the run's own status.
    const state = outcome(thread.status === "busy", thread.status === "idle" ? "success" : thread.status, extracted.failure,
      extracted.solved as string | undefined);
    return { id: thread.thread_id, created: thread.created_at, updated: thread.updated_at, meta: thread.metadata as unknown as RunMeta, state,
      objective: typeof extracted.objective === "number" ? extracted.objective : null,
      failure: typeof extracted.failure === "string" ? extracted.failure : null, usage: (extracted.usage as Usage | undefined) ?? null };
  });
}
