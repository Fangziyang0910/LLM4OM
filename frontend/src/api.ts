import { Client } from "@langchain/langgraph-sdk";
import type { Draft, Entry, RunMeta } from "./types";

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

export const STATUS: Record<string, string> = {
  pending: "排队中", running: "建模中", success: "已完成", error: "运行出错", timeout: "超时", interrupted: "已停止",
  failed: "未得到代码",
  optimal: "最优", feasible: "可行解", infeasible: "不可行", unbounded: "无界",
  infeasible_or_unbounded: "不可行或无界", time_limit: "达到时限", executed: "已执行",
};

/** The colour family of a status: good, bad, warn, live or idle. */
export function tone(state: string): "good" | "bad" | "warn" | "live" | "idle" {
  if (["optimal", "feasible", "success", "executed"].includes(state)) return "good";
  if (["failed", "error", "infeasible", "unbounded", "infeasible_or_unbounded"].includes(state)) return "bad";
  if (["time_limit", "timeout", "interrupted"].includes(state)) return "warn";
  if (["running", "pending"].includes(state)) return "live";
  return "idle";
}

/**
 * What a run came to, as a STATUS key: running, how the run ended when it did not succeed, "failed" without code,
 * or the solver status of the final code. `status` is the run status ("success" once the graph finished).
 */
export function outcome(active: boolean, status: string | undefined, failure: unknown, solveStatus: string | undefined): string {
  if (active) return "running";
  if (status !== "success") return status ?? "pending";
  return failure ? "failed" : solveStatus ?? "success";
}

export const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);

/** Create a thread for the draft and start its run in the background; returns the thread id. */
export async function startRun(draft: Draft): Promise<string> {
  const title = draft.description.trim().split("\n")[0].slice(0, 120);
  const meta: RunMeta = { title, method: draft.method, language: draft.language, provider: draft.provider, model: draft.model || null };
  const thread = await client.threads.create({ metadata: meta });
  await client.runs.create(thread.thread_id, draft.method, {
    input: { description: draft.description, data: draft.data },
    context: { language: draft.language, provider: draft.provider, model: draft.model || null },
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

export const formatNumber = (value: number) =>
  Number.isInteger(value) ? value.toLocaleString("en-US") : value.toLocaleString("en-US", { maximumSignificantDigits: 8 });

export const formatTokens = (count: number) => count < 1000 ? String(count) : `${(count / 1000).toFixed(count < 10000 ? 1 : 0)}k`;

export const duration = (seconds: number) =>
  seconds < 60 ? `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} 秒` : `${Math.floor(seconds / 60)} 分 ${Math.round(seconds % 60)} 秒`;
