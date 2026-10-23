import { expect, test } from "vitest";
import { targetLabel } from "./target";
import type { Options } from "@/types";

const options: Options = { methods: [], providers: [], datasets: [], languages: [
  { id: "ortools", name: "OR-Tools", solver: "SCIP" },
  { id: "cvxpy", name: "CVXPY", solver: "AUTO" },
] };

test("one library label covers old pairs, native code and the backend actually used", () => {
  expect(targetLabel(options, { language: "pywraplp" })).toBe("OR-Tools · SCIP");
  expect(targetLabel(options, { language: "cvxpy_osqp" })).toBe("CVXPY · OSQP");
  expect(targetLabel(options, { language: "cvxpy", solver: "AUTO" }, "SCIP")).toBe("CVXPY · SCIP");
});
