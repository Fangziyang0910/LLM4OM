// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import readXlsxFile from "read-excel-file/node";
import { exportSolution } from "@/features/runs/workbook";
import type { RunValues } from "@/features/runs/types";
import type { Options } from "@/types";

vi.mock("@/i18n", () => ({ locale: "zh", dateLocale: "zh-CN", t: (text: string) => text }));

const options = { methods: [{ id: "direct", name: "Direct" }],
  languages: [{ id: "pyomo", name: "Pyomo", solver: "HiGHS" }], providers: [], datasets: [] } as unknown as Options;
const meta = { title: "生产计划", method: "direct", language: "pyomo", provider: null, model: "m1" };

describe("business solution workbook", () => {
  it("round-trips business labels, typed actual values including zero, and the complete problem", async () => {
    const description = "A".repeat(449) + "😀" + "切割与加工资源。".repeat(5000);
    const values: RunValues = {
      description, data: { "capacity.csv": "capacity\n8" },
      revision: { description: "原题面", instruction: "B 至少生产 3 件" },
      explanation: { summary: "按表中数量生产。", objective_label: "总利润", objective_unit: "元",
        decisions: [{ variable: "x[A]", label: "A 产品数量", unit: "件" }], notes: [], total_variables: 3 },
      solve: { status: "optimal", objective: 12, variables: { "x[A]": 2, "x[B]": 0, "=1+1": 0.123456789123 }, output: "", error: null },
    };
    const blob = await exportSolution(meta, values, options, "http://localhost/run/example");
    const sheets = await readXlsxFile(Buffer.from(await blob.arrayBuffer()));
    expect(sheets.map(sheet => sheet.sheet)).toEqual(["求解方案", "问题与条件"]);
    expect(sheets[0].data).toContainEqual(["总利润", 12, "元", null]);
    expect(sheets[0].data).toContainEqual(["A 产品数量", 2, "件", "x[A]"]);
    expect(sheets[0].data).toContainEqual(["x[B]", 0, null, "x[B]"]);
    expect(sheets[0].data).toContainEqual(["=1+1", 0.123456789123, null, "=1+1"]);
    const rows = sheets[1].data;
    const start = rows.findIndex(row => row[0] === "问题描述") + 1;
    const end = rows.findIndex(row => row[0] === "调整要求");
    expect(rows.slice(start, end).map(row => row[0] || "").join("")).toBe(description);
    expect(rows.flat()).toContain("B 至少生产 3 件");
    expect(rows.flat()).toContain("原题面");
    expect(rows.flat()).toContain("capacity.csv");
    expect(rows.flat()).toContain("链接：http://localhost/run/example");
  });

  it("exports all values when no business explanation is available", async () => {
    const variables = Object.fromEntries(Array.from({ length: 501 }, (_, i) => [`x[${i}]`, i]));
    const blob = await exportSolution(meta, { solve: { status: "feasible", objective: 0, variables, output: "", error: null } }, options);
    const [plan] = await readXlsxFile(Buffer.from(await blob.arrayBuffer()));
    expect(plan.data).toContainEqual(["x[0]", 0, null, "x[0]"]);
    expect(plan.data).toContainEqual(["x[500]", 500, null, "x[500]"]);
    expect(plan.data.filter(row => typeof row[1] === "number")).toHaveLength(502);
  });

  it.each(["infeasible", "unbounded", "locally_infeasible", "error"])("does not export a %s model as an execution plan even if it has numeric artifacts", async status => {
    await expect(exportSolution(meta, { solve: { status, objective: 1e30, variables: { A: 1e30 }, output: "", error: null } }, options))
      .rejects.toThrow("当前没有可导出的求解方案。");
  });
});
