import { useSyncExternalStore } from "react";

const DESKTOP = "(min-width: 1024px)";

function subscribe(change: () => void) {
  const query = matchMedia(DESKTOP);
  query.addEventListener("change", change);
  return () => query.removeEventListener("change", change);
}

function getSnapshot() {
  return matchMedia(DESKTOP).matches;
}

export function useDesktop(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot);
}
