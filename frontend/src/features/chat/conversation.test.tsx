import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useStream } from "@langchain/langgraph-sdk/react";
import type { Message } from "@langchain/langgraph-sdk";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { clearChatDraft } from "@/features/runs/api";
import { client } from "@/features/runs/sdk";
import { useChatDraft, useConversation } from "./conversation";

vi.mock("@/features/runs/sdk", () => ({ client: {
  threads: { get: vi.fn(), search: vi.fn(), update: vi.fn(), create: vi.fn(), updateState: vi.fn() },
  runs: { create: vi.fn(), cancel: vi.fn(), list: vi.fn() },
} }));
vi.mock("@langchain/langgraph-sdk/react", () => ({ useStream: vi.fn() }));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

const threads = vi.mocked(client.threads), runs = vi.mocked(client.runs);
const stream = { messages: [] as Message[], values: {}, isLoading: false, isThreadLoading: false,
  error: undefined, submit: vi.fn(), stop: vi.fn(), joinStream: vi.fn(), switchThread: vi.fn() };
const callbacks = () => vi.mocked(useStream).mock.calls.at(-1)![0];
const question = () => stream.submit.mock.calls.at(-1)![0].messages[0] as Message;

beforeEach(() => {
  vi.resetAllMocks();
  sessionStorage.clear();
  stream.messages = [];
  stream.isLoading = false;
  stream.isThreadLoading = false;
  vi.mocked(useStream).mockReturnValue(stream as never);
  threads.get.mockResolvedValue({ metadata: {}, values: { messages: [] } } as never);
  threads.search.mockResolvedValue([{ metadata: {} }] as never);
  threads.create.mockResolvedValue({ thread_id: "created" } as never);
  threads.updateState.mockResolvedValue({} as never);
  runs.create.mockResolvedValue({ run_id: "first-run" } as never);
  runs.list.mockResolvedValue([]);
});
afterEach(cleanup);

function conversation(threadId: string | null = "chat") {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderHook(() => useConversation({ assistantId: "optimization", threadId: threadId ?? undefined }), {
    wrapper: ({ children }) => <QueryClientProvider client={query}>{children}</QueryClientProvider>,
  });
}

test("a prepared message stays in the draft until its own persisted message ID is acknowledged, and clearChatDraft clears both keys", () => {
  const { result } = renderHook(() => useChatDraft("chat"));
  act(() => result.current.setValue("  帮我排班  "));
  const prepared = result.current.prepare(result.current.value);
  expect(prepared.content).toBe("帮我排班");
  expect(prepared.id).toBeTruthy();
  expect(result.current.value).toBe("  帮我排班  ");
  act(() => result.current.acknowledge([{ type: "human", id: "older-question", content: "帮我排班" }]));
  expect(result.current.value).toBe("  帮我排班  ");
  clearChatDraft("chat");
  expect(sessionStorage.getItem("llm4om-message-chat")).toBeNull();
  expect(sessionStorage.getItem("llm4om-message-chat-pending")).toBeNull();
  act(() => result.current.acknowledge([prepared]));
  expect(result.current.value).toBe("");
});

test("receipt acknowledgment survives reload and never clears a newer draft", () => {
  const first = renderHook(() => useChatDraft("chat"));
  act(() => first.result.current.setValue("已提交的问题"));
  const prepared = first.result.current.prepare(first.result.current.value);
  act(() => first.result.current.setValue("下一轮的新草稿"));
  first.unmount();
  const reopened = renderHook(() => useChatDraft("chat"));
  expect(reopened.result.current.value).toBe("下一轮的新草稿");
  act(() => reopened.result.current.acknowledge([prepared]));
  expect(reopened.result.current.value).toBe("下一轮的新草稿");
  expect(sessionStorage.getItem("llm4om-message-chat-pending")).toBeNull();
});

test("reopening fetches a full snapshot only to confirm a pending message", async () => {
  const first = conversation();
  await waitFor(() => expect(first.result.current.busy).toBe(false));
  expect(threads.get).not.toHaveBeenCalled();
  first.unmount();
  sessionStorage.setItem("llm4om-message-chat", "submitted");
  sessionStorage.setItem("llm4om-message-chat-pending", JSON.stringify({ id: "written", text: "submitted" }));
  threads.get.mockResolvedValue({ metadata: {}, values: { messages: [{ type: "human", id: "written", content: "submitted" }] } } as never);
  const reopened = conversation();
  await waitFor(() => expect(reopened.result.current.input).toBe(""));
  expect(threads.get).toHaveBeenCalledOnce();
  expect(sessionStorage.getItem("llm4om-message-chat-pending")).toBeNull();
});

test("a rejected question save keeps both the pending question and the newer draft", async () => {
  const { result } = renderHook(() => useChatDraft("chat"));
  act(() => result.current.setValue("已提交的问题"));
  const prepared = result.current.prepare(result.current.value);
  act(() => result.current.setValue("下一轮的新草稿"));
  threads.updateState.mockRejectedValueOnce(new Error("save rejected"));
  await expect(result.current.savePending()).rejects.toThrow("save rejected");
  expect(result.current.value).toBe("下一轮的新草稿");
  expect(JSON.parse(sessionStorage.getItem("llm4om-message-chat-pending")!).id).toBe(prepared.id);
});

test.each(["checkpoint", "finish"])("only persisted %s confirmation acknowledges a message and preserves a later draft", async receipt => {
  const { result, rerender } = conversation();
  await waitFor(() => expect(result.current.busy).toBe(false));
  act(() => result.current.setInput("question"));
  await act(() => result.current.send());
  const message = question();
  await act(async () => { result.current.thread.reload(); });
  await waitFor(() => expect(threads.search.mock.calls.length).toBeGreaterThan(1));
  expect(threads.get).not.toHaveBeenCalled();
  stream.messages = [message]; // The SDK may show an optimistic message before the input checkpoint exists.
  rerender();
  expect(result.current.input).toBe("question");
  act(() => callbacks().onCheckpointEvent?.({ values: { messages: [message] } } as never, { namespace: ["nested"] }));
  expect(sessionStorage.getItem("llm4om-message-chat-pending")).not.toBeNull();
  act(() => result.current.setInput("next draft"));
  act(() => {
    if (receipt === "checkpoint") callbacks().onCheckpointEvent?.({ values: { messages: [message] } } as never, { namespace: [] });
    else callbacks().onFinish?.({ values: { messages: [message] } } as never, undefined);
  });
  expect(result.current.input).toBe("next draft");
  expect(sessionStorage.getItem("llm4om-message-chat-pending")).toBeNull();
});

test("retry sends the original message ID without submitting or clearing the next draft", async () => {
  const previous: Message = { type: "human", id: "persisted-question", content: "old question" };
  stream.messages = [previous];
  const { result } = conversation();
  await waitFor(() => expect(result.current.busy).toBe(false));
  act(() => result.current.setInput("next draft"));
  await act(() => result.current.send({ retry: true }));
  expect(question()).toBe(previous);
  expect(stream.submit.mock.calls[0][1].optimisticValues).toBeUndefined();
  expect(result.current.input).toBe("next draft");
  expect(sessionStorage.getItem("llm4om-message-chat-pending")).toBeNull();
});

test("immediate stop waits for cancellation, persists the original question and then stops locally", async () => {
  const order: string[] = [];
  runs.cancel.mockImplementation(async () => { order.push("cancel"); });
  threads.updateState.mockImplementation(async () => { order.push("save"); return {} as never; });
  stream.stop.mockImplementation(async () => { order.push("stop"); });
  const { result } = conversation();
  await waitFor(() => expect(result.current.busy).toBe(false));
  act(() => result.current.setInput("question"));
  await act(() => result.current.send());
  const message = question();
  act(() => callbacks().onMetadataEvent?.({ run_id: "active" } as never));
  act(() => result.current.setInput("next draft"));
  await act(async () => { expect(await result.current.stop()).toBe(true); });
  expect(order).toEqual(["cancel", "save", "stop"]);
  expect(runs.cancel).toHaveBeenCalledWith("chat", "active", true);
  expect(threads.updateState).toHaveBeenCalledWith("chat", { values: { messages: [message] }, asNode: "discuss" });
  expect(result.current.input).toBe("next draft");
});

test.each(["cancel", "save"])("a %s failure keeps the draft and prevents local stop until a successful retry", async failure => {
  const { result } = conversation();
  await waitFor(() => expect(result.current.busy).toBe(false));
  act(() => result.current.setInput("question"));
  await act(() => result.current.send());
  act(() => callbacks().onMetadataEvent?.({ run_id: "active" } as never));
  if (failure === "cancel") runs.cancel.mockRejectedValueOnce(new Error("cancel failed"));
  else threads.updateState.mockRejectedValueOnce(new Error("save failed"));
  await act(async () => { expect(await result.current.stop()).toBe(false); });
  expect(stream.stop).not.toHaveBeenCalled();
  expect(result.current.input).toBe("question");
  await act(async () => { expect(await result.current.stop()).toBe(true); });
  expect(stream.stop).toHaveBeenCalledOnce();
  expect(runs.cancel).toHaveBeenCalledTimes(failure === "cancel" ? 2 : 1);
  expect(result.current.input).toBe("");
});

test("a later turn replaces the previous run reference before cancellation", async () => {
  const { result } = conversation();
  await waitFor(() => expect(result.current.busy).toBe(false));
  await act(() => result.current.reconnect("old-run"));
  expect(stream.joinStream).toHaveBeenCalledWith("old-run", "-1");
  act(() => result.current.setInput("next question"));
  await act(() => result.current.send());
  act(() => callbacks().onMetadataEvent?.({ run_id: "new-run" } as never));
  await act(() => result.current.stop());
  expect(runs.cancel).toHaveBeenCalledExactlyOnceWith("chat", "new-run", true);
  expect(runs.create).not.toHaveBeenCalled();
});

test("a new conversation persists its message before starting a run and survives a rejected run start", async () => {
  runs.create.mockRejectedValueOnce(new Error("start rejected"));
  const { result } = conversation(null);
  act(() => result.current.setInput("first question"));
  let created: string | undefined;
  await act(async () => { created = await result.current.startThread({ values: { description: "draft" } }); });
  expect(created).toBe("created");
  const saved = threads.create.mock.calls[0][0]?.supersteps?.[0].updates[0].values as { messages: Message[] };
  expect(saved.messages[0].content).toBe("first question");
  expect(runs.create).toHaveBeenCalledWith("created", "optimization", expect.objectContaining({ input: { messages: saved.messages } }));
  expect(result.current.input).toBe("");
  expect(threads.create.mock.invocationCallOrder[0]).toBeLessThan(runs.create.mock.invocationCallOrder[0]);
});
