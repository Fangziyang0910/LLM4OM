import { beforeEach, expect, test, vi } from "vitest";
import { deleteRun, history, runMeta, startComparison, startRevision, startRun, startScenarios } from "@/features/runs/api";
import { errorText } from "@/format";
import { client } from "@/features/runs/sdk";
import type { Draft } from "@/features/composer/types";
import type { RunMeta, RunSpec } from "@/features/runs/types";

vi.mock("@/features/runs/sdk", () => ({
  client: { threads: { create: vi.fn(), delete: vi.fn(), search: vi.fn(), get: vi.fn(), getState: vi.fn() }, runs: { create: vi.fn() } },
}));

const threads = vi.mocked(client.threads);
const runs = vi.mocked(client.runs);
const draft = { description: "生产计划", data: {}, method: "direct", language: "pyomo", preset: null } as unknown as Draft;
const limited = new Error("This address started 3 runs in the last hour.");

beforeEach(() => {
  vi.resetAllMocks();
  let count = 0;
  threads.create.mockImplementation(async () => ({ thread_id: `thread-${++count}` }) as never);
  threads.delete.mockResolvedValue(undefined as never);
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
  threads.get.mockResolvedValue({ status: "idle", metadata: { title: "生产计划", method: "old", language: "old", group: "method-comparison" } } as never);
  threads.getState.mockResolvedValue({ checkpoint: { checkpoint_id: "saved-checkpoint" }, values: {
    description: "原问题", data: { "data.csv": "a,b\n1,2" },
    spec: { method: "feedback_repair", language: "ortools", solver: "CP_SAT", preset: null,
      llm: { provider: "deepseek", model: "saved-model" } },
  } } as never);
  await startRevision("original-thread", " B 至少生产 3 件 ", []);
  expect(threads.create).toHaveBeenCalledWith({ metadata: expect.objectContaining({ method: "feedback_repair", language: "ortools",
    parent: { thread_id: "original-thread", checkpoint_id: "saved-checkpoint" } }) });
  expect(threads.create.mock.calls[0][0]?.metadata).not.toHaveProperty("group");
  expect(runs.create).toHaveBeenCalledWith("thread-1", "feedback_repair", expect.objectContaining({
    input: { description: "原问题", data: { "data.csv": "a,b\n1,2" }, change: "B 至少生产 3 件" },
    context: { language: "ortools", solver: "CP_SAT", preset: null, explain: true, locale: "zh" },
  }));
});

test("a revision cannot silently replace a deleted model preset", async () => {
  threads.get.mockResolvedValue({ status: "idle", metadata: { title: "原方案" } } as never);
  threads.getState.mockResolvedValue({ checkpoint: { checkpoint_id: "saved" }, values: { description: "原问题",
    spec: { method: "direct", language: "pyomo", preset: "deleted", llm: { provider: "deepseek", model: "old" } } } } as never);
  await expect(startRevision("source", "改预算", [])).rejects.toThrow("原预设已删除");
  expect(threads.create).not.toHaveBeenCalled();
});

test("a scenario batch freezes the baseline once and keeps successful starts when a later start is rejected", async () => {
  threads.get.mockResolvedValue({ status: "idle", metadata: { title: "原方案" } } as never);
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
    metadata: { title: "run" }, extracted: { elapsed: 12, finished_at: 12, solved: "optimal", objective: 1 } };
  threads.search.mockResolvedValueOnce([...Array.from({ length: 99 }, (_, index) => ({ ...thread, thread_id: String(index) })),
    { ...thread, metadata: {} }] as never).mockResolvedValueOnce([{ ...thread, thread_id: "earlier",
      extracted: { elapsed: 0.01 } }] as never);
  const first = await history();
  expect(first.nextOffset).toBe(100);
  expect(first.entries).toHaveLength(99);
  expect(first.entries[0].elapsed).toBe(12);
  const next = await history(undefined, first.nextOffset);
  expect(threads.search).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 100, limit: 100 }));
  expect(next.nextOffset).toBeUndefined();
  expect(next.entries[0].id).toBe("earlier");
  expect(next.entries[0].elapsed).toBeNull();
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
});
