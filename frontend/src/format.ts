/** How statuses, numbers, durations and errors read in the page. */
import { t } from "./i18n";

const STATUS_TEXT: Record<string, string> = {
  pending: "排队中", running: "建模中", success: "已完成", error: "运行出错", timeout: "超时", interrupted: "已停止",
  failed: "未得到代码",
  optimal: "最优", feasible: "可行解", infeasible: "不可行", unbounded: "无界",
  infeasible_or_unbounded: "不可行或无界", time_limit: "达到时限", executed: "已执行",
};
export const STATUS: Record<string, string> = Object.fromEntries(Object.entries(STATUS_TEXT).map(([key, text]) => [key, t(text)]));

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

/** An error's message; for an SDK error ("HTTP 429: {\"detail\": ...}"), the server's detail alone. */
export function errorText(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error);
  const body = /^HTTP \d+: (\{.*\})$/s.exec(message)?.[1];
  try {
    const detail = body ? JSON.parse(body).detail : undefined;
    return typeof detail === "string" ? detail : message;
  } catch { return message; }
}

export const formatNumber = (value: number) =>
  Number.isInteger(value) ? value.toLocaleString("en-US") : value.toLocaleString("en-US", { maximumSignificantDigits: 8 });

export const formatTokens = (count: number) => count < 1000 ? String(count) : `${(count / 1000).toFixed(count < 10000 ? 1 : 0)}k`;

export const duration = (seconds: number) =>
  seconds < 60 ? t("{seconds} 秒", { seconds: seconds < 10 ? seconds.toFixed(1) : Math.round(seconds) })
    : t("{minutes} 分 {seconds} 秒", { minutes: Math.floor(seconds / 60), seconds: Math.round(seconds % 60) });
