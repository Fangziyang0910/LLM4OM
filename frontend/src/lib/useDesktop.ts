import { useCallback, useMemo, useSyncExternalStore } from "react";

export function useDesktop(minWidth = "1024px"): boolean {
  const query = useMemo(() => matchMedia(`(min-width: ${minWidth})`), [minWidth]);
  const subscribe = useCallback((change: () => void) => {
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, [query]);
  return useSyncExternalStore(subscribe, () => query.matches);
}
