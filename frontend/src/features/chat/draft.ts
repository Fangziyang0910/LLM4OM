import { useCallback, useEffect, useRef, useState } from "react";
import { v7 } from "@langchain/core/utils/uuid";
import type { Message } from "@langchain/langgraph-sdk";
import { client } from "@/features/runs/sdk";

type Pending = { id: string; text: string };

/** Unsent messages stay in this browser tab and never enter the conversation history. */
export function useChatDraft(threadId: string, initial = "") {
  const key = `llm4om-message-${threadId}`;
  const [value, setValue] = useState(() => { try { return initial || sessionStorage.getItem(key) || ""; } catch { return initial; } });
  const pending = useRef<Pending | null>(null);
  if (pending.current === null) {
    try { pending.current = JSON.parse(sessionStorage.getItem(`${key}-pending`) ?? "null") as Pending | null; } catch { /* storage may be unavailable */ }
  }
  useEffect(() => {
    try { if (value) sessionStorage.setItem(key, value); else sessionStorage.removeItem(key); } catch { /* storage may be unavailable */ }
  }, [key, value]);
  const prepare = (text: string): Message => {
    const message: Message = { type: "human", id: v7(), content: text.trim() };
    pending.current = { id: message.id!, text };
    try { sessionStorage.setItem(`${key}-pending`, JSON.stringify(pending.current)); } catch { /* storage may be unavailable */ }
    return message;
  };
  const acknowledge = useCallback((messages?: Message[]) => {
    const sent = pending.current;
    if (!sent || !messages?.some(message => message.id === sent.id)) return;
    // Run creation precedes the input checkpoint; only a checkpoint confirms the question was saved.
    setValue(current => current === sent.text ? "" : current);
    pending.current = null;
    try { sessionStorage.removeItem(`${key}-pending`); } catch { /* storage may be unavailable */ }
  }, [key]);
  const savePending = async () => {
    const sent = pending.current;
    if (!sent) return;
    const message: Message = { type: "human", id: sent.id, content: sent.text.trim() };
    // Immediate cancellation can precede the graph's first input checkpoint.
    await client.threads.updateState(threadId, { values: { messages: [message] }, asNode: "discuss" });
    acknowledge([message]);
  };
  return { value, setValue, prepare, acknowledge, savePending };
}
