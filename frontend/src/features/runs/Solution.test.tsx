import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { download } from "@/components/Content";
import { Solution } from "./Solution";

vi.mock("@/components/Content", () => ({ download: vi.fn(), Plain: ({ children }: { children: React.ReactNode }) => <pre>{children}</pre> }));
afterEach(cleanup);

test("large results are paged for display but searched and exported in full", () => {
  const variables = Object.fromEntries(Array.from({ length: 2001 }, (_, index) => [`x[${index}]`, 1]));
  render(<Solution solve={{ status: "optimal", objective: 2001, variables, output: "", error: null }} />);
  expect(screen.queryByTitle("x[2000]")).toBeNull();
  fireEvent.change(screen.getByLabelText("筛选变量"), { target: { value: "x[2000]" } });
  expect(screen.getByTitle("x[2000]")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("下载变量取值 CSV"));
  const csv = vi.mocked(download).mock.calls[0][1];
  expect(typeof csv).toBe("string");
  expect(String(csv).trimEnd().split("\n")).toHaveLength(2002);
  expect(csv).toContain('x[2000],1');
});

test("quoted customer names remain intact in matrix labels and CSV exports", () => {
  const variables = { "x['North, East',Monday]": 3, "x[West,Monday]": 0 };
  render(<Solution solve={{ status: "optimal", objective: 3, variables, output: "", error: null }} />);
  expect(screen.getByRole("columnheader", { name: "Monday" })).toBeTruthy();
  expect(screen.getByRole("rowheader", { name: "North, East" })).toBeTruthy();
  expect(screen.getByRole("rowheader", { name: "West" }).parentElement?.textContent).toContain("0");
  fireEvent.click(screen.getByLabelText("下载变量取值 CSV"));
  const csv = vi.mocked(download).mock.lastCall![1];
  expect(csv).toContain(`"x['North, East',Monday]",3`);
  expect(csv).toContain(`"x[West,Monday]",0`);
});

test("search finds zero values in grouped and list views and restores the zero filter when cleared", () => {
  render(<Solution solve={{ status: "optimal", objective: 12,
    variables: { production_A: 4, production_B: 0, "shipment[West]": 0 }, output: "", error: null }} />);
  expect(screen.queryByTitle("production_B")).toBeNull();
  fireEvent.change(screen.getByLabelText("筛选变量"), { target: { value: "production_B" } });
  expect(screen.getByTitle("production_B").parentElement?.textContent).toContain("0");
  expect(screen.queryByText("全部取值为 0。")).toBeNull();
  fireEvent.change(screen.getByLabelText("筛选变量"), { target: { value: "shipment" } });
  expect(screen.getByTitle("shipment[West]").parentElement?.textContent).toContain("0");
  fireEvent.click(screen.getByLabelText("全部列表"));
  expect(screen.getByRole("cell", { name: "shipment[West]" })).toBeTruthy();
  fireEvent.change(screen.getByLabelText("筛选变量"), { target: { value: "" } });
  expect(screen.queryByRole("cell", { name: "shipment[West]" })).toBeNull();
  expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("false");
  fireEvent.click(screen.getByRole("switch"));
  fireEvent.change(screen.getByLabelText("筛选变量"), { target: { value: "West" } });
  fireEvent.change(screen.getByLabelText("筛选变量"), { target: { value: "" } });
  expect(screen.getByRole("switch").getAttribute("aria-checked")).toBe("true");
  expect(screen.getByRole("cell", { name: "shipment[West]" })).toBeTruthy();
});
