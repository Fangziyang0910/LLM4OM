import { useEffect, useRef, useState } from "react";

/** Follow the rendered height, including formulas and opened cards; scrolling up always leaves the reader in control. */
export function useChatScroll() {
  const log = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const following = useRef(true);
  const [follow, setFollow] = useState(true);
  useEffect(() => {
    const pane = log.current, body = content.current;
    if (!pane || !body) return;
    let frame = 0, previousTop = pane.scrollTop;
    const update = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        if (following.current) { pane.scrollTop = pane.scrollHeight; previousTop = pane.scrollTop; }
      });
    };
    const onScroll = () => {
      if (pane.scrollTop < previousTop - 1) { following.current = false; cancelAnimationFrame(frame); }
      else if (pane.scrollHeight - pane.scrollTop - pane.clientHeight < 40) following.current = true;
      previousTop = pane.scrollTop;
      setFollow(following.current);
    };
    const observer = new ResizeObserver(update);
    observer.observe(body);
    observer.observe(pane);
    pane.addEventListener("scroll", onScroll, { passive: true });
    update();
    return () => { observer.disconnect(); cancelAnimationFrame(frame); pane.removeEventListener("scroll", onScroll); };
  }, []);
  const followLatest = () => {
    following.current = true;
    setFollow(true);
    if (log.current) log.current.scrollTop = log.current.scrollHeight;
  };
  return { log, content, follow, followLatest };
}
