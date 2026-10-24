import { useSyncExternalStore } from "react";

const DESKTOP = "(min-width: 1024px)";
export function useDesktop(): boolean {
  return useSyncExternalStore(change => {
    const query = matchMedia(DESKTOP);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, () => matchMedia(DESKTOP).matches);
}
