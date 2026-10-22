import { beforeEach, expect, test, vi } from "vitest";
import { deleteRun, history, runMeta, startComparison, startRun } from "@/features/runs/api";
import { errorText } from "@/format";
import { client } from "@/features/runs/sdk";
import type { Draft } from "@/features/composer/types";
import type { RunMeta, RunSpec } from "@/features/runs/types";

vi.mock("@/features/runs/sdk", () => ({
  client: { threads: { create: vi.fn(), delete: vi.fn(), search: vi.fn() }, runs: { create: vi.fn() } },
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
