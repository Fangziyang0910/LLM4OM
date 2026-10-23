import { isRunEntry, type Entry } from "./types";

export type HistoryGroup = { entry: Entry; related: Entry[]; created: string };

/** Group only recorded relationships; equal titles do not establish the same problem. */
export function groupHistory(entries: Entry[]): HistoryGroup[] {
  const parents = new Map<string, string>();
  const root = (id: string): string => {
    const parent = parents.get(id);
    if (!parent) { parents.set(id, id); return id; }
    if (parent === id) return id;
    const found = root(parent); parents.set(id, found); return found;
  };
  const join = (a: string, b: string) => { parents.set(root(a), root(b)); };
  for (const entry of entries) {
    root(entry.id);
    if ("parent" in entry.meta && entry.meta.parent) join(entry.id, entry.meta.parent.thread_id);
    if ("origin" in entry.meta && entry.meta.origin) join(entry.id, entry.meta.origin);
    if (isRunEntry(entry) && entry.meta.conversation) join(entry.id, entry.meta.conversation);
    if (isRunEntry(entry) && entry.meta.group) join(entry.id, `group:${entry.meta.group}`);
  }
  const groups = new Map<string, Entry[]>();
  for (const entry of entries) {
    const id = root(entry.id);
    if (!groups.has(id)) groups.set(id, []);
    groups.get(id)!.push(entry);
  }
  return [...groups.values()].map(items => {
    const ordered = [...items].sort((a, b) => Number(b.meta.kind === "optimization") - Number(a.meta.kind === "optimization")
      || Number(isRunEntry(b)) - Number(isRunEntry(a)) || a.created.localeCompare(b.created));
    return { entry: ordered[0], related: items.filter(item => item !== ordered[0]),
      created: items.reduce((latest, item) => item.created > latest ? item.created : latest, items[0].created) };
  }).sort((a, b) => b.created.localeCompare(a.created));
}
