import { QueryClient } from "@tanstack/react-query";
import { beforeEach, expect, test, vi } from "vitest";
import { createSolutionChat, deleteRun, history, runMeta, startComparison, startRevision, startRun, startScenarios } from "@/features/runs/api";
import { errorText } from "@/format";
import { client } from "@/features/runs/sdk";
import type { Draft } from "@/types";
import type { RunMeta, RunSpec } from "@/features/runs/types";

vi.mock("@/features/runs/sdk", () => ({
  client: { threads: { create: vi.fn(), delete: vi.fn(), search: vi.fn(), get: vi.fn(), getState: vi.fn() }, runs: { create: vi.fn(), list: vi.fn() } },
}));

const threads = vi.mocked(client.threads);
const runs = vi.mocked(client.runs);
const draft = { description: "生产计划", data: {}, method: "direct", language: "pyomo", preset: null } as unknown as Draft;
const limited = Object.assign(new Error("This address started 3 runs in the last hour."), { status: 429 });

beforeEach(() => {
  vi.resetAllMocks();
  let count = 0;
  threads.create.mockImplementation(async () => ({ thread_id: `thread-${++count}` }) as never);
  threads.delete.mockResolvedValue(undefined as never);
  runs.list.mockResolvedValue([]);
});

test("library and backend reach the run independently", async () => {
  await startRun({ ...draft, language: "ortools", solver: "CP_SAT" }, undefined);
  expect(runs.create).toHaveBeenCalledWith("thread-1", "direct", expect.objectContaining({
    context: { language: "ortools", solver: "CP_SAT", preset: null, explain: true, locale: "zh" },
  }));
});

test("problem provenance is recorded as metadata and never enters modeling input", async () => {
  await startRun({ ...draft, origin: "requirements-thread" }, undefined);
  expect(threads.create).toHaveBeenCalledWith({ metadata: expect.objectContaining({ origin: "requirements-thread" }) });
  expect(runs.create.mock.calls[0][2]?.input).toEqual({ description: draft.description, data: draft.data });
});

test("a revision pins the source checkpoint and inherits its recorded choices and files", async () => {
  threads.search.mockResolvedValue([{ status: "idle", metadata: { title: "生产计划", method: "old", language: "old", group: "method-comparison" } }] as never);
  threads.getState.mockResolvedValue({ checkpoint: { checkpoint_id: "saved-checkpoint" }, values: {
    description: "原问题", data: { "data.csv": "a,b\n1,2" },
    spec: { method: "llmopt", language: "ortools", solver: "CP_SAT", preset: null, limits: { solve_time_limit: 15 },
      llm: { provider: "deepseek", model: "saved-model" } },
  } } as never);
  await startRevision("original-thread", " B 至少生产 3 件 ", []);
  expect(threads.create).toHaveBeenCalledWith({ metadata: expect.objectContaining({ method: "llmopt", language: "ortools",
    parent: { thread_id: "original-thread", checkpoint_id: "saved-checkpoint" } }) });
  expect(threads.create.mock.calls[0][0]?.metadata).not.toHaveProperty("group");
  expect(runs.create).toHaveBeenCalledWith("thread-1", "llmopt", expect.objectContaining({
    input: { description: "原问题", data: { "data.csv": "a,b\n1,2" }, change: "B 至少生产 3 件" },
    context: { language: "ortools", solver: "CP_SAT", preset: null, time_limit: 15, explain: true, locale: "zh" },
  }));
});

test("a revision cannot silently replace a deleted model preset", async () => {
  threads.search.mockResolvedValue([{ status: "idle", metadata: { title: "原方案" } }] as never);
  threads.getState.mockResolvedValue({ checkpoint: { checkpoint_id: "saved" }, values: { description: "原问题",
    spec: { method: "direct", language: "pyomo", preset: "deleted", llm: { provider: "deepseek", model: "old" } } } } as never);
  await expect(startRevision("source", "改预算", [])).rejects.toThrow("原预设已删除");
  expect(threads.create).not.toHaveBeenCalled();
});

test("revisions, scenarios and discussions keep an explicit old checkpoint even during a later run", async () => {
  const source = { thread_id: "source", checkpoint_id: "old-checkpoint" };
  threads.search.mockImplementation(async query => query?.ids ? [{ status: "busy", metadata: { title: "new title", method: "new-method" } }] as never : []);
  threads.getState.mockImplementation(async (_, checkpoint) => ({ checkpoint: { checkpoint_id: checkpoint ?? "new-checkpoint" },
    values: { description: checkpoint ? "old problem" : "new problem", data: { "source.csv": "original data" },
      spec: { method: "direct", language: "pyomo", solver: "highs", preset: null, llm: { provider: "saved", model: "saved" } } },
  }) as never);
  await startRevision("source", "change", [], source);
  const scenarios = [{ name: "one", instruction: "first change" }, { name: "two", instruction: "second change" }];
  await startScenarios("source", scenarios, [], source);
  for (const call of runs.create.mock.calls) expect(call[2]?.input).toMatchObject({ description: "old problem", data: { "source.csv": "original data" } });
  await createSolutionChat(source);
  expect(threads.getState.mock.calls).toEqual([["source", "old-checkpoint"], ["source", "old-checkpoint"], ["source", "old-checkpoint"]]);
  for (const call of threads.create.mock.calls) expect(call[0]?.metadata).toMatchObject({ parent: source });
  expect(threads.create.mock.calls.at(-1)?.[0]?.supersteps).toEqual([
    { updates: [{ asNode: "discuss", values: { source, current: source, messages: [], plans: [] } }] },
  ]);
  await expect(createSolutionChat("source")).rejects.toThrow("请等待当前运行结束后再讨论方案");
});

test("a scenario batch freezes the baseline once and keeps successful starts when a later start is rejected", async () => {
  threads.search.mockResolvedValue([{ status: "idle", metadata: { title: "原方案" } }] as never);
  threads.getState.mockResolvedValue({ checkpoint: { checkpoint_id: "frozen" }, values: { description: "原问题", data: { "costs.csv": "a,b\n1,2" },
    spec: { method: "direct", language: "pyomo", solver: "highs", preset: null, llm: { provider: "deepseek", model: "saved" } } } } as never);
  runs.create.mockResolvedValueOnce({} as never).mockRejectedValueOnce(limited);
  const result = await startScenarios("source", [{ name: "容量 10", instruction: "容量改为 10" }, { name: "容量 12", instruction: "容量改为 12" }], []);
  expect(result).toMatchObject({ started: 1, error: limited });
  expect(threads.getState).toHaveBeenCalledOnce();
  expect(threads.create.mock.calls[0][0]?.metadata).toMatchObject({ parent: { thread_id: "source", checkpoint_id: "frozen" },
    scenario: { name: "容量 10", instruction: "容量改为 10" }, group: result.group });
  expect(runs.create.mock.calls[0][2]?.input).toEqual({ description: "原问题", data: { "costs.csv": "a,b\n1,2" }, change: "容量改为 10" });
  expect(threads.delete).toHaveBeenCalledWith("thread-2");
});

test("a rejected run start leaves no empty run behind", async () => {
  runs.create.mockRejectedValue(limited);
  await expect(startRun(draft, undefined)).rejects.toBe(limited);
  expect(threads.delete).toHaveBeenCalledWith("thread-1");
});

test.each([new TypeError("Failed to fetch"), Object.assign(new Error("Gateway timeout"), { status: 504 })])(
  "an uncertain start keeps the thread because the server may already be running it: %s", async error => {
    runs.create.mockRejectedValue(error);
    await expect(startRun(draft, undefined)).rejects.toBe(error);
    expect(threads.delete).not.toHaveBeenCalled();
  });

test.each([new TypeError("Failed to fetch"), Object.assign(new Error("Already running"), { status: 409 })])(
  "a lost response recovers the run that the server already accepted: %s", async error => {
    runs.create.mockRejectedValue(error);
    runs.list.mockResolvedValue([{ run_id: "accepted", status: "running" }] as never);
    await expect(startRun(draft, undefined)).resolves.toBe("thread-1");
    expect(threads.delete).not.toHaveBeenCalled();
  });

test("a failed status check does not turn an uncertain start into a thread deletion", async () => {
  runs.create.mockRejectedValue(limited);
  runs.list.mockRejectedValue(new TypeError("Network unavailable"));
  await expect(startRun(draft, undefined)).rejects.toBe(limited);
  expect(threads.delete).not.toHaveBeenCalled();
});

test("a deleted preset cannot silently become the default on rerun", async () => {
  await expect(startRun({ ...draft, preset: "deleted" }, undefined)).rejects.toThrow("原预设已删除");
  expect(threads.create).not.toHaveBeenCalled();
});

test("deleting a run delegates its full lifecycle to the server", async () => {
  await deleteRun("thread");
  expect(threads.delete).toHaveBeenCalledWith("thread");
});

test("deletion can be retried after the server already removed the thread", async () => {
  threads.delete.mockRejectedValueOnce(Object.assign(new Error("gone"), { status: 404 }));
  await expect(deleteRun("thread")).resolves.toBeUndefined();
  threads.delete.mockRejectedValueOnce(limited);
  await expect(deleteRun("thread")).rejects.toBe(limited);
});

test("recorded configuration wins over editable metadata, preserving notes and legacy records", () => {
  const metadata = { title: "problem", method: "old", language: "old", note: "note", tags: ["tag"] } as RunMeta;
  const spec = { method: "direct", language: "pyomo", preset: "saved", llm: { provider: "provider", model: "model" } } as RunSpec;
  expect(runMeta(metadata, spec)).toEqual({ ...metadata, method: "direct", language: "pyomo", preset: "saved",
    provider: "provider", model: "model" });
  expect(runMeta(metadata)).toBe(metadata);
});

test("history pages use all server rows for offsets and keep execution time after edits", async () => {
  const thread = { thread_id: "one", created_at: "2026-01-01", updated_at: "2026-10-01", status: "idle",
    metadata: { title: "run" }, extracted: { timing: { elapsed: 12, finished_at: 12 }, solved: "optimal", objective: 1 } };
  threads.search.mockResolvedValueOnce([...Array.from({ length: 99 }, (_, index) => ({ ...thread, thread_id: String(index) })),
    { ...thread, metadata: {} }] as never).mockResolvedValueOnce([{ ...thread, thread_id: "earlier",
      extracted: { timing: { elapsed: 0.01 } } }] as never);
  const first = await history();
  const extract = (threads.search.mock.calls[0][0] as { extract?: Record<string, string> })?.extract ?? {};
  expect(Object.keys(extract).length).toBeLessThanOrEqual(10);
  expect(first.nextOffset).toBe(100);
  expect(first.entries).toHaveLength(99);
  expect(first.entries[0].elapsed).toBe(12);
  const next = await history(undefined, first.nextOffset);
  expect(threads.search).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 100, limit: 100 }));
  expect(next.nextOffset).toBeUndefined();
  expect(next.entries[0].id).toBe("earlier");
  expect(next.entries[0].elapsed).toBeNull();
});

test("a failed plan saved by an agent has a finished checkpoint without a native run", async () => {
  threads.search.mockResolvedValue([{ thread_id: "plan", status: "idle", metadata: { title: "scenario", method: "direct" },
    extracted: { timing: { finished_at: 1 }, failure: "Model generation failed" } }] as never);
  runs.list.mockResolvedValue([]);
  const { entries } = await history();
  expect(entries[0].state).toBe("failed");
});

test("idle history uses the latest run for unfinished conversations and unsolved runs", async () => {
  const base = { created_at: "2026-01-01", updated_at: "2026-01-01", status: "idle" };
  threads.search.mockResolvedValueOnce([
    { ...base, thread_id: "stopped", metadata: { kind: "optimization", title: "stopped" }, extracted: { last_message_type: "human" } },
    { ...base, thread_id: "failed", metadata: { title: "failed" }, extracted: {} },
    { ...base, thread_id: "complete", metadata: { kind: "requirements", title: "complete" }, extracted: { last_message_type: "ai" } },
    { ...base, thread_id: "tool", metadata: { kind: "solution_chat", title: "tool" },
      extracted: { last_message_type: "ai", last_tool: "pending-tool" } },
    { ...base, thread_id: "explaining", metadata: { title: "explaining" }, extracted: { solved: "optimal" } },
    { ...base, thread_id: "queued", status: "busy", metadata: { kind: "optimization", title: "queued" }, extracted: {} },
  ] as never);
  runs.list.mockImplementation(async id => [{ status: id === "queued" ? "pending" : id === "failed" ? "error" : "interrupted" }] as never);
  const result = await history();
  expect(result.entries.map(item => [item.id, item.state])).toEqual([
    ["stopped", "interrupted"], ["failed", "error"], ["complete", "success"], ["tool", "interrupted"],
    ["explaining", "interrupted"], ["queued", "pending"],
  ]);
  expect(runs.list.mock.calls.map(([id]) => id)).toEqual(["stopped", "failed", "tool", "explaining", "queued"]);
});

test("a comparison cut short keeps the runs that started", async () => {
  runs.create.mockResolvedValueOnce({} as never).mockRejectedValue(limited);
  const result = await startComparison(draft, [{ method: "direct", preset: undefined }, { method: "coe", preset: undefined },
    { method: "optimus", preset: undefined }]);
  expect(result).toMatchObject({ started: 1, error: limited });
  expect(threads.delete).toHaveBeenCalledWith("thread-2");
  expect(threads.create).toHaveBeenCalledTimes(2);
});

test("a comparison whose first run cannot start fails", async () => {
  runs.create.mockRejectedValue(limited);
  await expect(startComparison(draft, [{ method: "direct", preset: undefined }])).rejects.toBe(limited);
});

test("an SDK error shows the server's detail alone", () => {
  expect(errorText(new Error('HTTP 429: {"detail":"Try again in 60 min."}'))).toBe("Try again in 60 min.");
  expect(errorText(new Error("HTTP 502: Bad Gateway"))).toBe("HTTP 502: Bad Gateway");
  expect(errorText({ error: "UpstreamFailed" })).toBe("UpstreamFailed");
});

test("blank Markdown headings still yield a visible title and deleted threads do not fail history()", async () => {
  await startRun({ ...draft, description: "# \n真实问题描述" }, undefined);
  expect(threads.create).toHaveBeenCalledWith({ metadata: expect.objectContaining({ title: "真实问题描述" }) });

  threads.search.mockResolvedValueOnce([
    { thread_id: "gone", created_at: "2026-01-01", updated_at: "2026-01-01", status: "idle", metadata: { title: "deleted" }, extracted: {} },
    { thread_id: "ok", created_at: "2026-01-01", updated_at: "2026-01-01", status: "idle", metadata: { title: "alive" },
      extracted: { timing: { started_at: 0, elapsed: 1, finished_at: 1 }, solved: "optimal", objective: 5 } },
  ] as never);
  runs.list.mockRejectedValueOnce(Object.assign(new Error("not found"), { status: 404 }));
  const page = await history();
  expect(page.entries.map(item => item.id)).toEqual(["ok"]);
});

test("unchanged idle drafts reuse an empty run lookup and still follow a run started elsewhere", async () => {
  const cache = new QueryClient();
  const draft = { thread_id: "draft", updated_at: "first", status: "idle", metadata: { title: "draft", kind: "requirements" } };
  threads.search.mockResolvedValue([draft] as never);
  runs.list.mockResolvedValue([]);
  await history(undefined, 0, cache);
  await history(undefined, 0, cache);
  expect(runs.list).toHaveBeenCalledTimes(1);
  threads.search.mockResolvedValue([{ ...draft, status: "busy" }] as never);
  runs.list.mockResolvedValue([{ status: "pending" }] as never);
  expect((await history(undefined, 0, cache)).entries[0].state).toBe("pending");
  threads.search.mockResolvedValue([{ ...draft, updated_at: "next" }] as never);
  runs.list.mockResolvedValue([{ status: "interrupted" }] as never);
  expect((await history(undefined, 0, cache)).entries[0].state).toBe("interrupted");
  expect(runs.list).toHaveBeenCalledTimes(3);
  cache.clear();
});
