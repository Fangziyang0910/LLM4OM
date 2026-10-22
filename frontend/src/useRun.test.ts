import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { client } from "./sdk";
import { useRun } from "./useRun";

vi.mock("./sdk", () => ({
  client: { threads: { get: vi.fn(), getState: vi.fn() }, runs: { list: vi.fn(), joinStream: vi.fn() } },
}));

const threads = vi.mocked(client.threads);
const runs = vi.mocked(client.runs);

beforeEach(() => vi.resetAllMocks());

/** A running run whose stream breaks after the run reached `finalStatus`. */
function disconnect(finalStatus: string) {
  const run = { run_id: "run", status: "running" };
  threads.get.mockResolvedValue({ metadata: {}, values: {} } as never);
  runs.list.mockImplementation(async () => [{ ...run }] as never);
  runs.joinStream.mockImplementation(() => ({
    [Symbol.asyncIterator]: async function* () {
      run.status = finalStatus;
      yield* [];
      throw new Error("SSE retries exhausted");
    },
  }) as never);
}

test("a broken stream still reads the completed run", async () => {
  disconnect("success");
  const onFinished = vi.fn();
  const { result } = renderHook(() => useRun("thread", onFinished));
  await waitFor(() => expect(onFinished).toHaveBeenCalledOnce());
  expect(result.current.run?.status).toBe("success");
  expect(result.current.error).toBeNull();
  expect(result.current.streaming).toBe(false);
  expect(threads.get).toHaveBeenCalledTimes(2);
});

test("a broken stream reports an active run as disconnected", async () => {
  disconnect("running");
  const { result } = renderHook(() => useRun("thread", vi.fn()));
  await waitFor(() => expect(result.current.error).toBe("SSE retries exhausted"));
  expect(result.current.run?.status).toBe("running");
  expect(threads.get).toHaveBeenCalledTimes(2);
});

test("leaving a run ignores its late state response", async () => {
  let resolve!: (value: unknown) => void;
  threads.get.mockReturnValue(new Promise(done => { resolve = done }) as never);
  runs.list.mockResolvedValue([{ run_id: "old", status: "running" }] as never);
  const onFinished = vi.fn();
  const { result, unmount } = renderHook(() => useRun("old-thread", onFinished));
  unmount();
  resolve({ metadata: { title: "old-thread" }, values: { code: "stale" } });
  await new Promise(done => setTimeout(done, 0));
  expect(result.current.meta).toBeNull();
  expect(result.current.run).toBeNull();
  expect(onFinished).not.toHaveBeenCalled();
});
