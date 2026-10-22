import { Client } from "@langchain/langgraph-sdk";
import { outcome } from "./format";
import type { Draft, Entry, Preset, RunMeta } from "./types";

/** The LangGraph server runs, streams and stores every run; this page is served by the same server. */
export const client = new Client({ apiUrl: location.origin });

// The platform's own routes. All requests are JSON; the server rejects other POST bodies.
export async function api<T>(path: string, body?: unknown, method = body === undefined ? "GET" : "POST"): Promise<T> {
  const response = await fetch(path, body === undefined ? { method } : {
    method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = value.detail;
    throw new Error(typeof detail === "string" ? detail : detail ? JSON.stringify(detail) : `请求失败（${response.status}）`);
  }
  return value as T;
}

/** Create a thread for the draft and start its run in the background; returns the thread id. */
export async function startRun(draft: Draft, preset: Preset | undefined): Promise<string> {
  const title = draft.description.trim().split("\n")[0].slice(0, 120);
  const meta: RunMeta = { title, method: draft.method, language: draft.language, preset: preset?.id ?? null,
    provider: preset?.provider ?? null, model: preset?.model ?? null };
  const thread = await client.threads.create({ metadata: meta });
  await client.runs.create(thread.thread_id, draft.method, {
    input: { description: draft.description, data: draft.data },
    context: { language: draft.language, preset: preset?.id ?? null },
    streamMode: ["custom"], streamResumable: true,
  });
  return thread.thread_id;
}

export async function history(): Promise<Entry[]> {
  const threads = await client.threads.search({ limit: 200, sortBy: "created_at", sortOrder: "desc",
    select: ["thread_id", "created_at", "status", "metadata"],
    extract: { objective: "values.solve.objective", solved: "values.solve.status", failure: "values.failure" } });
  return threads.filter(thread => thread.metadata?.title).map(thread => {
    const extracted = (thread as unknown as { extracted?: Record<string, unknown> }).extracted ?? {};
    // A thread is idle once its run finished; interrupted and error keep the run's own status.
    const state = outcome(thread.status === "busy", thread.status === "idle" ? "success" : thread.status, extracted.failure,
      extracted.solved as string | undefined);
    return { id: thread.thread_id, created: thread.created_at, meta: thread.metadata as unknown as RunMeta, state,
      objective: typeof extracted.objective === "number" ? extracted.objective : null };
  });
}
