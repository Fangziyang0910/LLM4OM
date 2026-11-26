import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";
import { download } from "@/components/Content";
import { ParetoFront } from "./ParetoFront";
import type { ParetoFront as Data } from "./types";

vi.mock("@/components/Content", () => ({ download: vi.fn(), Plain: ({ children }: { children: React.ReactNode }) => <pre>{children}</pre> }));
vi.stubGlobal("ResizeObserver", class { observe = vi.fn(); disconnect = vi.fn(); });
afterEach(() => { cleanup(); sessionStorage.clear(); });

const pareto: Data = {
  objectives: [{ name: "total_electricity_cost", sense: "min" }, { name: "risk", label: "模型风险", unit: "分", sense: "min" }],
  total: 2,
  solutions: [
    { objectives: [0.25, 2.25], variables: { x: 0 }, decoded: { task_to_cluster: { "0": 0, "1": 3 } } },
    { objectives: [1, 1], knee: true, variables: { x: 1 } },
  ],
};

test("the table and plot select the same plan, with model labels, real zeros and raw CSV fields", async () => {
  const labeled = { ...pareto, solutions: pareto.solutions.map(solution => ({ ...solution, decoded: undefined })) };
  render(<ParetoFront pareto={labeled} decisions={[{ variable: "x", label: "分配集群", unit: "号" }]} />);
  const plot = await screen.findByRole("group", { name: "目标权衡图" }, { timeout: 5000 });
  expect(screen.getByText("已选方案 #2")).toBeTruthy();
  fireEvent.keyDown(plot, { key: "Home" });
  expect(screen.getByText("已选方案 #1").parentElement?.textContent).toContain("总电费 0.25模型风险 (分) 2.25");
  expect(screen.getByText("分配集群").parentElement?.textContent).toBe("分配集群0 号");
  expect(screen.getByText("技术详情").closest("details")?.open).toBe(false);
  fireEvent.keyDown(screen.getByRole("row", { selected: true }), { key: "ArrowDown" });
  expect(document.activeElement).toBe(screen.getByRole("row", { selected: true }));
  expect(screen.getByText("方案 #2 决策明细")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("导出 Pareto CSV"));
  expect(vi.mocked(download).mock.lastCall?.[1]).toContain("total_electricity_cost (min),risk (min)");
  expect(vi.mocked(download).mock.lastCall?.[1]).toContain("2,yes,1,1");
});

test("selection survives a remount for this saved run and is isolated across checkpoints", () => {
  const show = (runKey: string) => render(<ParetoFront key={runKey} runKey={runKey} pareto={pareto} />);
  const first = show("run:checkpoint-1");
  fireEvent.click(screen.getByText("#1"));
  expect(screen.getByText("任务 0").parentElement?.textContent).toBe("任务 0集群 0");
  first.unmount();
  const second = show("run:checkpoint-2");
  expect(screen.getByText("已选方案 #2")).toBeTruthy();
  second.unmount();
  show("run:checkpoint-1");
  expect(screen.getByText("已选方案 #1")).toBeTruthy();
});
