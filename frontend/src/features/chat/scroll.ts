import { useCallback, useRef } from "react";
import { useStickToBottom } from "use-stick-to-bottom";

export function useChatScroll() {
  const { scrollRef, contentRef, isAtBottom, scrollToBottom } = useStickToBottom({ initial: "instant", resize: "instant" });
  const viewport = useRef<ResizeObserver | null>(null);
  const log = useCallback((node: HTMLDivElement | null) => {
    viewport.current?.disconnect();
    scrollRef(node);
    if (!node) return;
    // The library observes message height; the viewport also changes when desktop panels resize.
    viewport.current = new ResizeObserver(() => { void scrollToBottom({ animation: "instant", preserveScrollPosition: true }); });
    viewport.current.observe(node);
  }, [scrollRef, scrollToBottom]);
  return { log, content: contentRef, follow: isAtBottom, followLatest: () => { void scrollToBottom("instant"); } };
}
