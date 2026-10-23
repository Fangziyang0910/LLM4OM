import { useEffect, useState } from "react";

/** Unsent messages stay in this browser tab and never enter the conversation history. */
export function useChatDraft(threadId: string) {
  const key = `llm4om-message-${threadId}`;
  const [value, setValue] = useState(() => { try { return sessionStorage.getItem(key) ?? ""; } catch { return ""; } });
  useEffect(() => {
    try { if (value) sessionStorage.setItem(key, value); else sessionStorage.removeItem(key); } catch { /* storage may be unavailable */ }
  }, [key, value]);
  return [value, setValue] as const;
}
