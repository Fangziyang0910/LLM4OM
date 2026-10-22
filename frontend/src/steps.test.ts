import { expect, test } from "vitest";
import { phases } from "./steps";
import type { Step } from "./types";

const step = (id: string, type: Step["type"], title: string, node?: string): Step =>
  ({ id, time: 0, type, title, content: "", node });

test("each phase holds the calls made since the previous milestone", () => {
  const items = phases([step("1", "llm", "generate"), step("2", "artifact", "Model", "generate"),
    step("3", "solve", "Solve"), step("4", "llm", "repair")]);
  expect(items.map(item => [item.kind, item.calls.map(call => call.id)])).toEqual(
    [["artifact", ["1"]], ["solve", []], ["working", ["4"]]]);
});

test("parallel nodes keep their own calls", () => {
  const items = phases([step("a", "llm", "trival.constraint_expert"), step("b", "llm", "trival.objective_expert"),
    step("c", "artifact", "Objective", "objective_expert"), step("d", "artifact", "Constraints", "constraint_expert")]);
  expect(items.map(item => item.calls.map(call => call.id))).toEqual([["b"], ["a"]]);
});
