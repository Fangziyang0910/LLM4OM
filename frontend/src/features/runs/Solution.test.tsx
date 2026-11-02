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
