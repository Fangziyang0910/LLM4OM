import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { client } from "@/features/runs/sdk";
import { useRun } from "@/features/runs/useRun";

vi.mock("@/features/runs/sdk", () => ({
  client: { threads: { get: vi.fn(), getState: vi.fn() }, runs: { list: vi.fn(), joinStream: vi.fn() }, store: { getItem: vi.fn() } },
}));

const threads = vi.mocked(client.threads);
const runs = vi.mocked(client.runs);

beforeEach(() => vi.resetAllMocks());

test("a cancelled run reads its saved artifacts without an event stream", async () => {
  threads.get.mockResolvedValue({ metadata: { title: "cancelled" }, values: { description: "problem" } } as never);
  runs.list.mockResolvedValue([{ run_id: "run", status: "interrupted" }] as never);
  vi.mocked(client.store.getItem).mockResolvedValue({ value: { formulation: "partial", code: "model code",
    steps: [{ id: "one", type: "artifact", title: "draft", content: "partial" }],
    timing: { started_at: 1, finished_at: 3, elapsed: 2 } } } as never);
  const { result } = renderHook(() => useRun("thread", vi.fn()));
  await waitFor(() => expect(result.current.values.code).toBe("model code"));
  expect(result.current.values.description).toBe("problem");
  expect(result.current.steps).toHaveLength(1);
  expect(result.current.values.timing?.elapsed).toBe(2);
  expect(runs.joinStream).not.toHaveBeenCalled();
});

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

test("a pinned plan reads its old result while the same thread's latest run stays independent", async () => {
  const source = { thread_id: "thread", checkpoint_id: "old" };
  threads.get.mockResolvedValue({ metadata: { title: "plan", method: "latest" },
    values: { code: "new code", solve: { objective: 99 } } } as never);
  threads.getState.mockResolvedValue({ values: { code: "old code", solve: { objective: 13 },
    spec: { method: "direct", llm: {} }, steps: [{ id: "saved", type: "artifact", content: "old" }] } } as never);
  runs.list.mockResolvedValue([{ run_id: "latest", status: "success" }] as never);
  const onFinished = vi.fn();
  const pinned = renderHook(() => useRun(source, onFinished));
  await waitFor(() => expect(pinned.result.current.values.solve?.objective).toBe(13));
  expect(threads.getState).toHaveBeenCalledWith("thread", "old");
  expect(pinned.result.current.values.code).toBe("old code");
  expect(pinned.result.current.meta?.method).toBe("direct");
  expect(pinned.result.current.steps.map(step => step.id)).toEqual(["saved"]);
  expect(pinned.result.current.run).toBeNull();
  expect(runs.list).not.toHaveBeenCalled();
  expect(runs.joinStream).not.toHaveBeenCalled();
  expect(client.store.getItem).not.toHaveBeenCalled();
  expect(onFinished).not.toHaveBeenCalled();
  pinned.unmount();
  const latest = renderHook(() => useRun("thread", onFinished));
  await waitFor(() => expect(latest.result.current.values.solve?.objective).toBe(99));
  expect(latest.result.current.values.code).toBe("new code");
  latest.unmount();
});

test("switching checkpoints in the same thread ignores the previous checkpoint's late response", async () => {
  let oldResponse!: (value: never) => void;
  threads.get.mockResolvedValue({ metadata: {} } as never);
  threads.getState.mockImplementation((_, checkpoint) => checkpoint === "old"
    ? new Promise(resolve => { oldResponse = resolve; })
    : Promise.resolve({ values: { solve: { objective: 42 } } } as never));
  const { result, rerender, unmount } = renderHook(({ checkpoint }) =>
    useRun({ thread_id: "thread", checkpoint_id: checkpoint }, vi.fn()), { initialProps: { checkpoint: "old" } });
  rerender({ checkpoint: "other" });
  await waitFor(() => expect(result.current.values.solve?.objective).toBe(42));
  oldResponse({ values: { solve: { objective: 13 } } } as never);
  await new Promise(resolve => setTimeout(resolve, 0));
  expect(result.current.values.solve?.objective).toBe(42);
  expect(runs.list).not.toHaveBeenCalled();
  unmount();
});

test("an unavailable checkpoint reports failure instead of falling back to the thread's latest result", async () => {
  threads.get.mockResolvedValue({ metadata: {}, values: { solve: { objective: 99 } } } as never);
  threads.getState.mockRejectedValue(new Error("Checkpoint not found"));
  const { result, unmount } = renderHook(() => useRun({ thread_id: "thread", checkpoint_id: "missing" }, vi.fn()));
  await waitFor(() => expect(result.current.error).toBe("Checkpoint not found"));
  expect(result.current.values.solve).toBeUndefined();
  expect(runs.list).not.toHaveBeenCalled();
  unmount();
});
