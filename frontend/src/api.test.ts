import { beforeEach, expect, test, vi } from "vitest";
import { startComparison, startRun } from "./api";
import { errorText } from "./format";
import { client } from "./sdk";
import type { Draft } from "./types";

vi.mock("./sdk", () => ({
  client: { threads: { create: vi.fn(), delete: vi.fn() }, runs: { create: vi.fn() } },
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
