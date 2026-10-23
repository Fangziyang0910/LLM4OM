import type { CellObject, Row, Sheet } from "write-excel-file/universal";
import { STATUS } from "@/format";
import { t } from "@/i18n";
import { groupVariables } from "@/features/runs/tables";
import { targetLabel } from "@/features/runs/target";
import type { RunMeta, RunValues, Solve } from "@/features/runs/types";
import type { Options } from "@/types";

const header = { fontWeight: "bold", backgroundColor: "#4824D8", textColor: "#FFFFFF", height: 28 } as const;
const cell = (value: string | number, style: Partial<CellObject> = {}): CellObject => ({
  value, type: typeof value === "number" ? Number : String,
  format: typeof value === "number" ? Number.isInteger(value) ? "#,##0" : "General" : undefined,
  wrap: true, alignVertical: "center", ...style,
});
const wide = (value: string): Row => [cell(value, {
  columnSpan: 4, height: Math.max(24, (value.split("\n").reduce((lines, line) => lines + Math.max(1, Math.ceil(line.length / 45)), 0)) * 18),
})];

export function hasSolution(solve: Solve | null | undefined): solve is Solve {
  return !!solve && !solve.error && ["optimal", "feasible", "locally_optimal", "time_limit", "iteration_limit"].includes(solve.status)
    && (solve.objective != null || Object.keys(solve.variables).length > 0);
}

/** A business plan with every actual value, plus the problem and settings that produced it. */
export function solutionWorkbook(meta: RunMeta, values: RunValues, options: Options, link?: string): Sheet<Blob>[] {
  const solve = values.solve;
  if (!hasSolution(solve)) {
    throw new Error(t("当前没有可导出的求解方案。"));
  }
  const explanation = values.explanation;
  const labels = new Map(explanation?.decisions.map(item => [item.variable, item]));
  const plan: Row[] = [
    [cell(meta.title || t("求解方案"), { fontSize: 16, fontWeight: "bold", columnSpan: 4, height: 42 })],
    [cell(t("求解状态")), cell(STATUS[solve.status] ?? solve.status, { columnSpan: 3 })],
    [cell(explanation?.objective_label || t("目标值")),
      solve.objective == null ? null : cell(solve.objective, { fontWeight: "bold" }),
      cell(explanation?.objective_unit || "")],
  ];
  if (explanation) {
    plan.push([], wide(explanation.summary), ...explanation.notes.map(wide));
  }
  plan.push([], [t("决策"), t("取值"), t("单位"), t("变量")].map(label => cell(label, header)));
  const stickyRowsCount = plan.length;
  for (const group of groupVariables(solve.variables)) {
    for (const variable of group.variables) {
      const label = labels.get(variable.name);
      plan.push([cell(label?.label || variable.name, { height: Math.max(30, Math.ceil((label?.label || variable.name).length / 18) * 18) }),
        cell(variable.value, { align: "right" }),
        cell(label?.unit || ""), cell(variable.name, { textColor: "#5B6474" })]);
    }
  }
  const problem: Row[] = [[cell(t("问题与条件"), { fontSize: 16, fontWeight: "bold", columnSpan: 4, height: 36 })]];
  const section = (title: string, text: string) => {
    problem.push([], [cell(title, { ...header, columnSpan: 4 })]);
    // Excel limits cell text and row height; short chunks preserve the complete problem without clipping.
    for (const paragraph of text.split("\n")) {
      for (const chunk of paragraph.match(/[\s\S]{1,450}/gu) || [""]) problem.push(wide(chunk));
    }
  };
  section(t("问题描述"), values.description || "");
  if (values.revision) {
    section(t("调整要求"), values.revision.instruction);
    section(t("原问题"), values.revision.description);
  }
  if (Object.keys(values.data || {}).length) section(t("数据文件"), Object.keys(values.data!).join("\n"));
  const method = options.methods.find(item => item.id === meta.method);
  section(t("运行配置"), [
    `${t("建模方法")}：${method?.name || meta.method}`,
    `${t("建模求解器")}：${targetLabel(options, meta, solve.solver)}`,
    `${t("预设模型")}：${values.spec?.preset_name || meta.model || "—"}`,
    ...(link ? [`${t("链接")}：${link}`] : []),
  ].join("\n"));
  if (meta.note) section(t("备注"), meta.note);
  const columns = [{ width: 40 }, { width: 20 }, { width: 12 }, { width: 34 }];
  return [{ sheet: t("求解方案"), data: plan, columns, stickyRowsCount, showGridLines: false },
    { sheet: t("问题与条件"), data: problem, columns, showGridLines: false }];
}

export async function exportSolution(meta: RunMeta, values: RunValues, options: Options, link?: string): Promise<Blob> {
  const { default: writeExcelFile } = await import("write-excel-file/universal");
  return writeExcelFile(solutionWorkbook(meta, values, options, link), { fontFamily: "Arial", fontSize: 11 }).toBlob();
}
