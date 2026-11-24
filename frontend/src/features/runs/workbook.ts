import type { CellObject, Row, Sheet } from "write-excel-file/universal";
import { canHaveSolution, STATUS, uncheckedCvxpyLimit } from "@/format";
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
  columnSpan: 4, height: Math.min(409, Math.max(24, (value.split("\n").reduce((lines, line) => lines + Math.max(1, Math.ceil(line.length / 45)), 0)) * 18)),
})];
const chunkRows = (text: string): Row[] =>
  text.split("\n").flatMap(paragraph => (paragraph.match(/[\s\S]{1,450}/gu) || [""]).map(wide));

export function hasSolution(values?: RunValues): values is RunValues & { solve: Solve } {
  const solve = values?.solve;
  return !values?.failure && !!solve && !solve.error && canHaveSolution(solve.status) && !uncheckedCvxpyLimit(values?.spec, solve.status)
    && (solve.objective != null || Object.values(solve.variables).some(value => value != null) || !!solve.pareto?.solutions.length);
}

/** A business plan with every actual value, plus the problem and settings that produced it. */
function solutionWorkbook(meta: RunMeta, values: RunValues, options: Options, link?: string): Sheet<Blob>[] {
  if (!hasSolution(values)) {
    throw new Error(t("当前没有可导出的求解方案。"));
  }
  const { solve, explanation } = values;
  const labels = new Map(explanation?.decisions.map(item => [item.variable, item]));
  const plan: Row[] = [
    [cell(meta.title || t("求解方案"), { fontSize: 16, fontWeight: "bold", columnSpan: 4, height: 42 })],
    [cell(t("求解状态")), cell(STATUS[solve.status] ?? solve.status, { columnSpan: 3 })],
    [cell(explanation?.objective_label || t("目标值")),
      solve.objective == null ? null : cell(solve.objective, { fontWeight: "bold" }),
      cell(explanation?.objective_unit || "")],
  ];
  if (explanation) {
    plan.push([], ...chunkRows(explanation.summary), ...explanation.notes.flatMap(chunkRows));
  }
  plan.push([], [t("决策"), t("取值"), t("单位"), t("变量")].map(label => cell(label, header)));
  const stickyRowsCount = plan.length;
  for (const group of groupVariables(solve.variables)) {
    for (const variable of group.variables) {
      const label = labels.get(variable.name);
      plan.push([cell(label?.label || variable.name, { height: Math.min(409, Math.max(30, Math.ceil((label?.label || variable.name).length / 18) * 18)) }),
        variable.value == null ? cell("—", { align: "right" }) : cell(variable.value, { align: "right" }),
        cell(label?.unit || ""), cell(variable.name, { textColor: "#5B6474" })]);
    }
  }
  const problem: Row[] = [[cell(t("问题与条件"), { fontSize: 16, fontWeight: "bold", columnSpan: 4, height: 36 })]];
  const section = (title: string, text: string) => {
    problem.push([], [cell(title, { ...header, columnSpan: 4 })]);
    // Excel limits cell text and row height; short chunks preserve the complete problem without clipping.
    problem.push(...chunkRows(text));
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
  const sheets: Sheet<Blob>[] = [
    { sheet: t("求解方案"), data: plan, columns, stickyRowsCount, showGridLines: false },
    { sheet: t("问题与条件"), data: problem, columns, showGridLines: false },
  ];
  if (solve.pareto?.solutions.length) {
    const paretoRows: Row[] = [
      [cell(t("多目标 Pareto 前沿"), { fontSize: 16, fontWeight: "bold", columnSpan: solve.pareto.objectives.length + 2, height: 36 })],
      [],
      [t("方案编号"), t("推荐折中"), ...solve.pareto.objectives.map(obj => `${obj.name} (${obj.sense})`)].map(label => cell(label, header)),
      ...solve.pareto.solutions.map((sol, idx) => [
        cell(idx + 1, { align: "right" }),
        cell(sol.knee ? t("推荐折中") : ""),
        ...sol.objectives.map(val => val == null ? cell("—", { align: "right" }) : cell(val, { align: "right" })),
      ]),
    ];
    sheets.splice(1, 0, {
      sheet: t("Pareto 前沿"),
      data: paretoRows,
      columns: [{ width: 12 }, { width: 14 }, ...solve.pareto.objectives.map(() => ({ width: 20 }))],
      stickyRowsCount: 3,
      showGridLines: false,
    });
  }
  return sheets;
}

export async function exportSolution(meta: RunMeta, values: RunValues, options: Options, link?: string): Promise<Blob> {
  const { default: writeExcelFile } = await import("write-excel-file/universal");
  return writeExcelFile(solutionWorkbook(meta, values, options, link), { fontFamily: "Arial", fontSize: 11 }).toBlob();
}
