import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { useChatDraft } from "./draft";

const updateState = vi.hoisted(() => vi.fn().mockResolvedValue({}));
vi.mock("@/features/runs/sdk", () => ({ client: { threads: { updateState } } }));
afterEach(() => { cleanup(); sessionStorage.clear(); vi.clearAllMocks(); });

test("a prepared message stays in the draft until its own persisted message ID is acknowledged", () => {
  const { result } = renderHook(() => useChatDraft("chat"));
  act(() => result.current.setValue("  帮我排班  "));
  const question = result.current.prepare(result.current.value);
  expect(question.content).toBe("帮我排班");
  expect(question.id).toBeTruthy();
  expect(result.current.value).toBe("  帮我排班  ");
  act(() => result.current.acknowledge([{ type: "human", id: "older-question", content: "帮我排班" }]));
  expect(result.current.value).toBe("  帮我排班  ");
  act(() => result.current.acknowledge([question]));
  expect(result.current.value).toBe("");
});

test("receipt acknowledgment survives reload and never clears a newer draft", () => {
  const first = renderHook(() => useChatDraft("chat"));
  act(() => first.result.current.setValue("已提交的问题"));
  const question = first.result.current.prepare(first.result.current.value);
  act(() => first.result.current.setValue("下一轮的新草稿"));
  first.unmount();
  const reopened = renderHook(() => useChatDraft("chat"));
  expect(reopened.result.current.value).toBe("下一轮的新草稿");
  act(() => reopened.result.current.acknowledge([question]));
  expect(reopened.result.current.value).toBe("下一轮的新草稿");
  expect(sessionStorage.getItem("llm4om-message-chat-pending")).toBeNull();
});

test("immediate stop saves the unconfirmed question with its same ID and keeps the next draft", async () => {
  const { result } = renderHook(() => useChatDraft("chat"));
  act(() => result.current.setValue("已提交的问题"));
  const question = result.current.prepare(result.current.value);
  act(() => result.current.setValue("下一轮的新草稿"));
  await act(() => result.current.savePending());
  expect(updateState).toHaveBeenCalledWith("chat", { values: { messages: [question] }, asNode: "discuss" });
  expect(result.current.value).toBe("下一轮的新草稿");
  await act(() => result.current.savePending());
  expect(updateState).toHaveBeenCalledOnce();
});

test("a rejected question save keeps both the pending question and the newer draft", async () => {
  const { result } = renderHook(() => useChatDraft("chat"));
  act(() => result.current.setValue("已提交的问题"));
  const question = result.current.prepare(result.current.value);
  act(() => result.current.setValue("下一轮的新草稿"));
  updateState.mockRejectedValueOnce(new Error("save rejected"));
  await expect(result.current.savePending()).rejects.toThrow("save rejected");
  expect(result.current.value).toBe("下一轮的新草稿");
  expect(JSON.parse(sessionStorage.getItem("llm4om-message-chat-pending")!).id).toBe(question.id);
});
