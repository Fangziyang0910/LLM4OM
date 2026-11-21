import { describe, expect, it } from "vitest";
import { asMatrix, groupVariables, parseDelimited, variableChanges } from "@/features/runs/tables";

describe("groupVariables", () => {
  it.each([
    [`x['North, East',Monday]`, ["North, East", "Monday"]],
    [`x["O'Brien, East",Monday]`, ["O'Brien, East", "Monday"]],
    [`x[' North, East ', Monday]`, [" North, East ", "Monday"]],
    [`x[O'Brien,Monday]`, ["O'Brien", "Monday"]],
    [String.raw`x['Both \' and " here, East',Monday]`, [`Both ' and " here, East`, "Monday"]],
    [String.raw`x['West\\East, North',Monday]`, [String.raw`West\East, North`, "Monday"]],
    [`x("North, East", 'Monday, Tuesday')`, ["North, East", "Monday, Tuesday"]],
  ])("preserves string indices in %s", (name, indices) => {
    expect(groupVariables({ [name]: 3 })[0].variables[0]).toEqual({ name, indices, value: 3 });
  });

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

  it("keeps quoted customer names as one matrix dimension and retains zero values", () => {
    const groups = groupVariables({ "x['North, East',Monday]": 3, "x['North, East',Tuesday]": 0, "x[West,Monday]": 2 });
    expect(groups[0].dims).toBe(2);
    const matrix = asMatrix(groups[0])!;
    expect(matrix.rows).toEqual(["North, East", "West"]);
    expect(matrix.columns).toEqual(["Monday", "Tuesday"]);
    expect([matrix.cell("North, East", "Monday"), matrix.cell("North, East", "Tuesday"), matrix.cell("West", "Tuesday")]).toEqual([3, 0, undefined]);
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

it("parses chained and dotted indexed names, rejects malformed brackets, sorts tuples elementwise, and rejects matrix collisions", () => {
  expect(groupVariables({ "x[1)": 2, "foo()": 2 })).toEqual([{
    base: "", dims: 0, variables: [{ name: "foo()", indices: [], value: 2 }, { name: "x[1)", indices: [], value: 2 }],
  }]);
  const groups = groupVariables({ "stage[0].flow[A,B]": 5, "x[0][1]": 3, "m[1,10]": 1, "m[11,0]": 2 });
  const stageGroup = groups.find(g => g.base === "stage[0].flow")!;
  expect(stageGroup.variables[0].indices).toEqual(["A", "B"]);
  const xGroup = groups.find(g => g.base === "x")!;
  expect(xGroup.variables[0].indices).toEqual(["0", "1"]);
  const mGroup = groups.find(g => g.base === "m")!;
  expect(mGroup.variables.map(v => v.indices)).toEqual([["1", "10"], ["11", "0"]]);
  const colliding = groupVariables({ "c[a,b]": 1, "c['a','b']": 2 })[0];
  expect(asMatrix(colliding)).toBeNull();
});
