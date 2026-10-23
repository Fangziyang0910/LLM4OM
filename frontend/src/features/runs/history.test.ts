import { expect, test } from "vitest";
import { groupHistory } from "./history";
import type { Entry } from "./types";

const entry = (id: string, meta: Partial<Entry["meta"]> = {}, time = 0): Entry => ({
  id, created: new Date(1_700_000_000_000 + time * 1000).toISOString(), updated: "", state: "optimal", objective: 13,
  failure: null, usage: null, elapsed: null,
  meta: { title: "相同题名", method: "direct", language: "pyomo", provider: null, model: null, ...meta } as Entry["meta"],
});
const source = (thread_id: string) => ({ thread_id, checkpoint_id: "saved" });

test("identical text never groups unrelated problems", () => {
  expect(groupHistory([entry("a"), entry("b")])).toHaveLength(2);
});

test("a problem joins its requirements, copied runs, discussions and revised plans by recorded references", () => {
  const groups = groupHistory([entry("revised", { parent: source("run") }, 4),
    entry("chat", { kind: "solution_chat", parent: source("run") }, 3),
    entry("copy", { origin: "run" }, 2), entry("run", { origin: "requirements" }, 1),
    entry("requirements", { kind: "requirements" })]);
  expect(groups).toHaveLength(1);
  expect(groups[0].entry.id).toBe("run");
  expect(groups[0].related.map(item => item.id)).toEqual(["revised", "chat", "copy", "requirements"]);
  expect(groups[0].created).toBe(entry("revised", {}, 4).created);
});

test("comparison siblings join even while their source is deleted or on another history page", () => {
  const a = entry("a", { group: "comparison", parent: source("older") }, 1);
  const b = entry("b", { group: "comparison", parent: source("older") }, 2);
  expect(groupHistory([b, a])).toEqual([{ entry: a, related: [b], created: b.created }]);
  const original = entry("older");
  const groups = groupHistory([b, a, original]);
  expect(groups[0].entry).toBe(original);
  expect(groups[0].related).toEqual([b, a]);
});
