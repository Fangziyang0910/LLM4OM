import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, test } from "vitest";
import { Explanation } from "./Explanation";

afterEach(cleanup);

test("business values are taken from the solver, including zero decisions", () => {
  render(<Explanation explanation={{ summary: "按表中数量生产。", objective_label: "总利润", objective_unit: "元",
    decisions: [{ variable: "A", label: "生产 A", unit: "件" }, { variable: "B", label: "生产 B", unit: "件" }],
    notes: ["采用非负整数数量。"], total_variables: 2 }}
    solve={{ status: "optimal", objective: 13, variables: { A: 0, B: 2 }, output: "", error: null }} />);
  expect(screen.getByText(/总利润/).textContent).toContain("13");
  const rows = screen.getAllByRole("row");
  expect(rows[1].textContent).toBe("生产 A0件");
  expect(rows[2].textContent).toBe("生产 B2件");
});
