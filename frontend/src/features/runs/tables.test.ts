import { describe, expect, it } from "vitest";
import { asMatrix, groupVariables, parseDelimited, variableChanges } from "@/features/runs/tables";

describe("groupVariables", () => {
  it("groups indexed variables by base name and lays two-index groups out as a matrix", () => {
    const groups = groupVariables({ "x[W2,C1]": 0, "x[W1,C10]": 5, "x[W1,C2]": 3, "y[1]": 1, "total": 9 });
    expect(groups.map(group => [group.base, group.dims])).toEqual([["x", 2], ["y", 1], ["", 0]]);
    const matrix = asMatrix(groups[0])!;
    expect(matrix.rows).toEqual(["W1", "W2"]);
    expect(matrix.columns).toEqual(["C1", "C2", "C10"]);
    expect([matrix.cell("W1", "C10"), matrix.cell("W2", "C1"), matrix.cell("W2", "C2")]).toEqual([5, 0, undefined]);
  });

  it("reads quoted and parenthesised indices and refuses mixed groups as matrices", () => {
    const groups = groupVariables({ "x('a', 'b')": 1, "x[c]": 2 });
    expect(groups[0].variables.map(variable => variable.indices)).toEqual([["a", "b"], ["c"]]);
    expect(asMatrix(groups[0])).toBeNull();
  });
});

describe("parseDelimited", () => {
  it("parses a CSV with quotes and a trailing empty cell", () => {
    expect(parseDelimited('from,C1,supply\nW1,"4,5",120\ndemand,80,\n')).toEqual([["from", "C1", "supply"], ["W1", "4,5", "120"], ["demand", "80", ""]]);
  });

  it("returns null for text that is not a rectangular table", () => {
    expect(parseDelimited("just a note")).toBeNull();
    expect(parseDelimited("a,b\n1,2,3\n")).toBeNull();
  });
});
it("compares actual variable values without turning missing values into zero", () => {
  expect(variableChanges({ a: 3, b: 0, same: 2 }, { a: 2, c: 0, same: 2 })).toEqual([
    { name: "a", before: 3, after: 2 }, { name: "b", before: 0, after: undefined },
    { name: "c", before: undefined, after: 0 },
  ]);
  expect(variableChanges({}, { constructor: 0 })).toEqual([{ name: "constructor", before: undefined, after: 0 }]);
});
