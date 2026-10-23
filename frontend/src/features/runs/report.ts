import { STATUS, formatNumber } from "@/format";
import { locale, t } from "@/i18n";
import type { Options } from "@/types";
import type { RunMeta, RunValues } from "@/features/runs/types";
import { targetLabel } from "./target";

const MAX_DATA = 4000;  // characters of each data file in the report
const COLON = locale === "zh" ? "：" : ": ";
const fence = (text: string, lang = "") => {
  const ticks = "`".repeat(Math.max(3, ...[...text.matchAll(/`+/g)].map(match => match[0].length + 1)));
  return `${ticks}${lang}\n${text.trimEnd()}\n${ticks}`;
};

/** One run as a Markdown report: settings, problem and data, formulation, code, solution and counts. */
export function report(meta: RunMeta, values: RunValues, options: Options, link?: string): string {
  const method = options.methods.find(item => item.id === meta.method);
  const solve = values.solve;
  const usage = values.usage;
  const parts = [`# ${meta.title}`, [
    `- ${t("建模方法")}${COLON}${method?.name ?? meta.method}`,
    `- ${t("建模求解器")}${COLON}${targetLabel(options, meta, solve?.solver)}`,
    `- ${t("预设模型")}${COLON}${meta.model ?? "—"}`,
    ...(usage ? [`- ${t("调用")}${COLON}${t("{calls} 次 LLM 调用，{solves} 次求解，{tokens} token", {
      calls: usage.llm_calls, solves: usage.solves, tokens: (usage.input_tokens + usage.output_tokens).toLocaleString() })}`] : []),
    ...(meta.tags?.length ? [`- ${t("标签")}${COLON}${meta.tags.join(", ")}`] : []),
    ...(link ? [`- ${t("链接")}${COLON}${link}`] : []),
  ].join("\n")];
  if (meta.note) parts.push(`## ${t("备注")}\n\n${meta.note}`);
  if (values.spec) parts.push(`## ${t("运行配置")}\n\n${fence(JSON.stringify(values.spec, null, 2), "json")}`);
  parts.push(`## ${t("问题描述")}\n\n${(values.description ?? "").trim()}`);
  if (values.revision) {
    parts.push(`## ${t("调整要求")}\n\n${values.revision.instruction}`);
    parts.push(`### ${t("原问题")}\n\n${values.revision.description}`);
  }
  for (const [name, content] of Object.entries(values.data ?? {})) {
    const shown = content.length > MAX_DATA ? content.slice(0, MAX_DATA) + `\n… (${t("共 {count} 字符", { count: content.length })})` : content;
    parts.push(`### ${t("数据文件")} \`${name}\`\n\n${fence(shown)}`);
  }
  if (values.failure) parts.push(`## ${t("失败原因")}\n\n${values.failure}`);
  if (values.formulation) parts.push(`## ${t("数学模型")}\n\n${values.formulation.trim()}`);
  if (values.code) parts.push(`## ${t("求解代码")}\n\n${fence(values.code, "python")}`);
  if (solve) {
    if (values.explanation) {
      const explanation = values.explanation;
      const decisions = explanation.decisions.map(item => `- ${item.label}${COLON}${formatNumber(solve.variables[item.variable])} ${item.unit}`);
      const objective = solve.objective == null ? "" : `${explanation.objective_label}${COLON}${formatNumber(solve.objective)} ${explanation.objective_unit}`;
      parts.push([`## ${t("方案解读")}`, explanation.summary, objective, decisions.join("\n"),
        explanation.notes.map(note => `- ${note}`).join("\n")].filter(Boolean).join("\n\n"));
    }
    const lines = [`- ${t("求解状态")}${COLON}${(STATUS[solve.status] ?? solve.status)}`];
    if (solve.objective != null) lines.push(`- ${t("目标值")}${COLON}${formatNumber(solve.objective)}`);
    const nonzero = Object.entries(solve.variables).filter(([, value]) => value !== 0);
    let text = `## ${t("求解结果")}\n\n${lines.join("\n")}`;
    if (nonzero.length) {
      text += `\n\n${t("非零变量（{count} / {total}）", { count: nonzero.length, total: Object.keys(solve.variables).length })}${COLON}\n\n`
        + `| ${t("变量")} | ${t("取值")} |\n|---|---:|\n` + nonzero.slice(0, 500).map(([name, value]) => `| \`${name}\` | ${formatNumber(value)} |`).join("\n");
      if (nonzero.length > 500) text += `\n\n${t("报告只列出前 500 个非零变量；完整结果可下载 CSV。")}`;
    }
    if (solve.diagnosis?.items.length) {
      text += `\n\n${t("冲突的约束（{tool}）", { tool: solve.diagnosis.tool })}${COLON}\n\n` + solve.diagnosis.items.map(item => `- \`${item}\``).join("\n");
    }
    if (solve.error) text += `\n\n${fence(solve.error)}`;
    parts.push(text);
  }
  return parts.join("\n\n") + "\n";
}
