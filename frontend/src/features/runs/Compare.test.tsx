import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { Compare } from "./Compare";
import { history } from "./api";

vi.mock("./api", () => ({ history: vi.fn() }));
afterEach(cleanup);

test("compares objective zero beside the strategy and expands the same run's settings", async () => {
  vi.mocked(history).mockResolvedValue({ entries: [{
    id: "run-0", created: "", updated: "", state: "optimal", objective: 0, failure: null, usage: null, elapsed: 5,
    meta: { title: "打印机", method: "OptiMUS 0.3", language: "pyomo", provider: null, model: "model-A" },
  }], nextOffset: undefined });
  const open = vi.fn();
  render(<QueryClientProvider client={new QueryClient()}><Compare group="test"
    options={{ methods: [], languages: [], providers: [], datasets: [] }} onOpen={open} /></QueryClientProvider>);
  const strategy = await screen.findByRole("button", { name: "打开方案：OptiMUS 0.3" });
  expect(within(strategy.closest("tr")!).getAllByRole("cell").slice(0, 3).map(cell => cell.textContent))
    .toEqual(["OptiMUS 0.3", "0", "最优"]);
  const details = screen.getByText("运行信息").closest("details")!;
  expect(details.open).toBe(false);
  fireEvent.click(screen.getByText("运行信息"));
  expect(details.open).toBe(true);
  expect(within(details).getByText("model-A")).toBeTruthy();
  expect(open).not.toHaveBeenCalled();
  fireEvent.click(strategy);
  expect(open).toHaveBeenCalledWith("run-0");
});
