import type { ComponentType } from "react";
import { ArrowUpRight, Calculator, Check, ChevronRight, Cpu, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/features/runs/status";
import type { Explanation, Plan, SourceRun } from "@/features/runs/types";
import { sourceKey } from "@/features/runs/types";
import { formatNumber } from "@/format";
import { t } from "@/i18n";
import type { Options } from "@/types";

export type ComputedPlan = Plan & {
  status?: string | null; objective?: number | null; failure?: string | null; explanation?: Explanation | null;
  pareto?: { total: number; objectives: { name: string; sense: string }[]; knee?: (number | null)[] | null } | null;
  configuration?: { method?: string; language?: string; actual_solver?: string | null };
  /** The problem the plan was modeled from; a scenario's instruction is the change applied to it. */
  description?: string; variables?: Record<string, number | null>; total_variables?: number;
};

export type ToolArtifact = {
  type?: string;
  calculation?: { expression: string; result: number | number[]; matched_variables: number };
  selected_plan?: { name: string; source: SourceRun; status?: string | null; objective?: number | null; explanation?: Explanation | null };
  plans?: ComputedPlan[];
  query?: string; error?: string;
  results?: { title: string; url: string; snippet?: string; summary?: string; date?: string }[];
};

type ResultProps = { artifact?: ToolArtifact; options?: Options; onOpenPlan?: (source: SourceRun) => void; onCompare?: (group: string) => void };

const SHOWN_DECISIONS = 4;

/**
 * The decisions a plan card shows: the explanation's key decisions, else every value; nonzero values come first,
 * since an explanation may list every route or shift, most of them unused.
 */
export function planDecisions(plan: ComputedPlan): { shown: { label: string; value: string }[]; more: number } {
  const variables = plan.variables ?? {};
  const value = (number: number | null | undefined, unit = "") => number == null ? "—" : `${formatNumber(number)}${unit ? ` ${unit}` : ""}`;
  const explained = (plan.explanation?.decisions ?? []).filter(item => Object.hasOwn(variables, item.variable));
  const rows = explained.length ? explained.map(item => ({ label: item.label, number: variables[item.variable], unit: item.unit }))
    : Object.entries(variables).map(([name, number]) => ({ label: name, number, unit: "" }));
  const all = rows.sort((left, right) => Number(!left.number) - Number(!right.number))
    .map(row => ({ label: row.label, value: value(row.number, row.unit) }));
  const total = explained.length ? explained.length : Math.max(plan.total_variables ?? 0, all.length);
  return { shown: all.slice(0, SHOWN_DECISIONS), more: Math.max(0, total - SHOWN_DECISIONS) };
}

/** Method, library and actual solver of a computed plan, with the catalog's display names when known. */
export function configurationText(plan: ComputedPlan & { method?: string; language?: string }, options?: Options): string {
  const methodId = plan.configuration?.method ?? plan.method, languageId = plan.configuration?.language ?? plan.language;
  const method = options?.methods.find(item => item.id === methodId);
  const language = method?.builtin_solver || languageId === methodId ? null : options?.languages.find(item => item.id === languageId)?.name ?? languageId;
  return [method?.name ?? methodId, language, plan.configuration?.actual_solver].filter(Boolean).join(" · ");
}

function SelectedPlan({ artifact, onOpenPlan }: ResultProps) {
  const plan = artifact?.selected_plan;
  if (!plan) return null;
  return <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 rounded-xl border border-border/70 bg-muted/25 px-3 py-2 text-xs text-muted-foreground">
    <Check className="size-3.5 shrink-0 text-success" />
    {onOpenPlan ? <Button variant="link" size="xs" className="h-auto min-w-0 justify-start p-0 text-left font-medium whitespace-normal" onClick={() => onOpenPlan(plan.source)}>{t("已选择：{name}", { name: plan.name })}</Button>
      : <span className="min-w-0 break-words font-medium">{t("已选择：{name}", { name: plan.name })}</span>}
    {plan.status ? <StatusBadge status={plan.status} className="h-5 text-[11px]" /> : null}
    {plan.objective != null ? <span className="min-w-0 break-words tabular">{plan.explanation?.objective_label || t("目标值")}{" "}
      <strong className="font-semibold text-foreground tabular-nums">{formatNumber(plan.objective)}</strong>{plan.explanation?.objective_unit ? ` ${plan.explanation.objective_unit}` : ""}</span> : null}
  </div>;
}

function Calculation({ artifact }: ResultProps) {
  const calculation = artifact?.calculation;
  const values = calculation ? [calculation.result].flat() : [];
  const summary = values.slice(0, 4).map(formatNumber).join(", ") + (values.length > 4 ? ", …" : "");
  const exact = Array.isArray(calculation?.result) ? `[${values.map(String).join(", ")}]` : String(calculation?.result);
  return calculation ? <details className="group/calculation min-w-0 rounded-xl border border-border/80 bg-card text-xs shadow-2xs" aria-label={t("计算核对")}>
    <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl px-3.5 py-2.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <Calculator className="size-3.5 shrink-0 text-primary" /><span className="shrink-0 font-medium">{t("计算核对")}</span><strong className="ml-auto min-w-0 break-all text-right font-semibold text-foreground tabular-nums">{summary}</strong>
      <ChevronRight className="size-3.5 shrink-0 transition-transform group-open/calculation:rotate-90" />
    </summary>
    <div className="space-y-2 border-t border-border/60 p-3.5"><code className="block rounded-lg bg-muted/40 p-2 whitespace-pre-wrap break-all">{calculation.expression}</code>
      <p className="break-all font-mono font-medium tabular-nums">= {exact}</p>
      {calculation.matched_variables ? <p className="text-muted-foreground">{t("读取 {count} 个实际决策值", { count: calculation.matched_variables })}</p> : null}
    </div>
  </details> : null;
}

function Plans({ artifact, options, onOpenPlan, onCompare }: ResultProps) {
  const plans = artifact?.plans ?? [];
  if (!plans.length) return null;
  return <aside aria-label={t("本轮计算结果")} className="flex min-w-0 flex-col gap-2.5">
    {plans.map(plan => {
      const { shown, more } = plan.failure || plan.pareto?.total ? { shown: [], more: 0 } : planDecisions(plan);
      const configuration = configurationText(plan, options);
      // A scenario's instruction is its change; a new model's instruction is the whole problem the assistant wrote.
      const change = plan.description && plan.instruction !== plan.description ? plan.instruction : null;
      return <div key={sourceKey(plan.source)} className="min-w-0 rounded-2xl border border-border/80 bg-card p-4 text-xs shadow-xs transition-colors hover:border-primary/30">
        <div className="flex items-start justify-between gap-2"><p className="min-w-0 break-words text-sm font-semibold">{plan.name}</p>
          <StatusBadge status={plan.failure ? "failed" : plan.status ?? "unknown"} /></div>
        {change ? <p title={change} className="mt-1 line-clamp-2 break-words leading-relaxed text-muted-foreground">{t("调整：{change}", { change })}</p> : null}
        {plan.failure ? <p className="mt-2 break-words text-destructive">{plan.failure}</p> : plan.pareto?.total ? <div className="mt-2.5 space-y-1">
          <p className="break-words">{t("多目标 Pareto 前沿")} <strong className="text-sm font-bold text-foreground tabular-nums">{t("{count} 个 Pareto 解", { count: plan.pareto.total })}</strong></p>
          {plan.pareto.knee?.length ? <p className="text-muted-foreground tabular">{t("推荐折中解：")}{plan.pareto.objectives.map((obj, idx) =>
            `${obj.name} = ${plan.pareto!.knee?.[idx] == null ? "—" : formatNumber(plan.pareto!.knee![idx]!)}`).join(" · ")}</p> : null}
        </div> : plan.objective != null ? <p className="mt-2.5 flex flex-wrap items-baseline gap-x-1.5 break-words">
          <span className="text-muted-foreground">{plan.explanation?.objective_label || t("目标值")}</span>{" "}
          <strong className="text-lg font-bold text-foreground tabular-nums">{formatNumber(plan.objective)}</strong>
          {plan.explanation?.objective_unit ? <>{" "}<span className="text-muted-foreground">{plan.explanation.objective_unit}</span></> : null}</p> : null}
        {shown.length ? <dl aria-label={t("关键决策")} className="mt-2 grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 rounded-xl bg-muted/35 px-3 py-2">
          {shown.map(item => <div key={item.label} className="contents">
            <dt className="min-w-0 truncate text-muted-foreground" title={item.label}>{item.label}</dt>
            <dd className="text-right font-medium text-foreground tabular-nums">{item.value}</dd>
          </div>)}
          {more ? <dd className="col-span-2 text-muted-foreground">{t("另有 {count} 项决策", { count: more })}</dd> : null}
        </dl> : null}
        {!change && plan.instruction ? <details className="group/problem mt-2">
          <summary className="flex w-fit cursor-pointer list-none items-center gap-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <ChevronRight className="size-3.5 transition-transform group-open/problem:rotate-90" />{t("建模所用的题面")}</summary>
          <p className="mt-1.5 max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-lg bg-muted/35 px-3 py-2 leading-relaxed text-muted-foreground">{plan.instruction}</p>
        </details> : null}
        <div className="mt-3 flex min-w-0 flex-wrap items-center justify-between gap-x-3 gap-y-1.5 border-t border-border/60 pt-2.5">
          {configuration ? <span className="flex min-w-0 items-center gap-1.5 text-[11px] text-muted-foreground" title={t("建模方法 · 建模库 · 求解器")}>
            <Cpu className="size-3 shrink-0" /><span className="truncate">{configuration}</span></span> : <span />}
          {onOpenPlan ? <Button variant="link" size="xs" className="h-auto p-0 font-medium" onClick={() => onOpenPlan(plan.source)}>{t("查看计算方案")}<ArrowUpRight /></Button> : null}
        </div>
      </div>;
    })}
    {plans.length > 1 && plans[0].group && onCompare ? <Button variant="outline" size="sm" className="self-start rounded-lg" onClick={() => onCompare(plans[0].group!)}>{t("对比本轮方案")}</Button> : null}
  </aside>;
}

function Search({ artifact }: ResultProps) {
  const sources = (artifact?.results ?? []).filter(source => typeof source.title === "string" && /^https?:\/\//i.test(source.url) && URL.canParse(source.url));
  return <aside aria-label={t("搜索来源")} className="min-w-0 rounded-xl border border-border/80 bg-card text-xs shadow-2xs">
    <details className="group/sources" open={artifact?.error ? true : undefined}>
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl px-3.5 py-2.5 text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <Globe className="size-3.5 shrink-0 text-primary" /><span className="min-w-0 flex-1 truncate font-medium" title={artifact?.query}>{artifact?.query || t("联网搜索")}</span>
        <span className="shrink-0">{t("{count} 个来源", { count: sources.length })}</span><ChevronRight className="size-3.5 shrink-0 transition-transform group-open/sources:rotate-90" />
      </summary>
      <div className="border-t border-border/60 px-3.5 py-2.5">
        {artifact?.error ? <p role="alert" className="break-words text-destructive">{t(artifact.error)}</p>
          : sources.length ? <ul className="flex flex-col divide-y">{sources.map((source, index) => <li key={`${source.url}-${index}`} className="py-2 first:pt-0 last:pb-0">
            <a href={source.url} target="_blank" rel="noopener noreferrer" className="flex items-start gap-2 font-medium text-foreground hover:text-primary">
              <span className="min-w-0 break-words">{source.title}</span><ArrowUpRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
            </a>
            <p className="mt-1 truncate text-muted-foreground" title={source.url}>{new URL(source.url).hostname}{source.date ? ` · ${source.date.slice(0, 10)}` : ""}</p>
            {source.snippet || source.summary ? <p className="mt-1 break-words leading-5 text-muted-foreground">{source.snippet || source.summary}</p> : null}
          </li>)}</ul> : <p className="text-muted-foreground">{t("没有找到相关网页。")}</p>}
      </div>
    </details>
  </aside>;
}

export const resultViews: Readonly<Record<string, ComponentType<ResultProps>>> = {
  selected_plan: SelectedPlan, calculation: Calculation, plans: Plans, search: Search,
};

// Saved messages predating artifact types keep their original presentation.
const tools = new Map<string, { activity: string; result?: string }>([
  ["web_search", { activity: "正在检索参考资料…", result: "search" }],
  ["model_and_solve", { activity: "正在建模并求解…", result: "plans" }],
  ["modeling_capabilities", { activity: "正在匹配最佳求解策略…" }],
  ["solve_scenarios", { activity: "正在计算场景方案…", result: "plans" }],
  ["read_attachment", { activity: "正在核对附件原文…" }],
  ["lookup_variables", { activity: "正在读取方案决策明细…" }],
  ["calculate", { activity: "正在精确核对数值…", result: "calculation" }],
  ["select_plan", { activity: "正在切换当前讨论方案…", result: "selected_plan" }],
  ["update_draft", { activity: "正在同步更新需求描述…" }],
]);

export function activity(name: string): string {
  return t(tools.get(name)?.activity ?? "正在智能处理…");
}

export function resultType(artifact: ToolArtifact | undefined, toolName: string | undefined): string {
  return artifact?.type ?? tools.get(toolName ?? "")?.result ?? "";
}
