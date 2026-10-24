import type { ComponentType } from "react";
import { ArrowUpRight, Calculator, Check, ChevronRight, Globe } from "lucide-react";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/features/runs/status";
import type { Explanation, Plan } from "@/features/runs/types";
import { formatNumber } from "@/format";
import { t } from "@/i18n";

type ComputedPlan = Plan & {
  status?: string | null; objective?: number | null; failure?: string | null; explanation?: Explanation | null;
  configuration?: { method?: string; language?: string; actual_solver?: string | null };
};

export type ToolArtifact = {
  type?: string;
  calculation?: { expression: string; result: number; matched_variables: number };
  selected_plan?: { name: string; source: { thread_id: string } };
  plans?: ComputedPlan[];
  query?: string; error?: string;
  results?: { title: string; url: string; snippet?: string; summary?: string; date?: string }[];
};

type ResultProps = { artifact?: ToolArtifact; onOpenPlan?: (id: string) => void; onCompare?: (group: string) => void };

function DraftResult() {
  return <p className="flex items-center gap-1.5 pl-9 text-xs text-muted-foreground"><Check className="size-3.5 text-success" />{t("需求稿已整理")}</p>;
}

function SelectedPlan({ artifact, onOpenPlan }: ResultProps) {
  const plan = artifact?.selected_plan;
  return plan ? <div className="ml-9 flex items-center gap-2 text-xs text-muted-foreground"><Check className="size-3.5 shrink-0 text-success" />
    {onOpenPlan ? <Button variant="link" size="xs" className="h-auto min-w-0 justify-start p-0 text-left whitespace-normal" onClick={() => onOpenPlan(plan.source.thread_id)}>{t("已选择：{name}", { name: plan.name })}</Button>
      : <span>{t("已选择：{name}", { name: plan.name })}</span>}
  </div> : null;
}

function Calculation({ artifact }: ResultProps) {
  const calculation = artifact?.calculation;
  return calculation ? <details className="group/calculation ml-9 rounded-xl border bg-card text-xs" aria-label={t("计算核对")}>
    <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl px-3 py-2.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <Calculator className="size-3.5 shrink-0" /><span>{t("计算核对")}</span><strong className="ml-auto break-all font-medium text-foreground tabular-nums">{formatNumber(calculation.result)}</strong>
      <ChevronRight className="size-3.5 shrink-0 transition-transform group-open/calculation:rotate-90" />
    </summary>
    <div className="space-y-2 border-t p-3"><code className="block whitespace-pre-wrap break-all">{calculation.expression}</code>
      <p className="break-all font-mono tabular-nums">= {String(calculation.result)}</p>
      {calculation.matched_variables ? <p className="text-muted-foreground">{t("读取 {count} 个实际决策值", { count: calculation.matched_variables })}</p> : null}
    </div>
  </details> : null;
}

function Plans({ artifact, onOpenPlan, onCompare }: ResultProps) {
  const plans = artifact?.plans ?? [];
  if (!plans.length) return null;
  return <aside aria-label={t("本轮计算结果")} className="ml-9 flex flex-col gap-2">
    {plans.map(plan => <div key={plan.source.thread_id} className="rounded-xl border bg-card p-3 text-xs">
      <div className="flex items-start justify-between gap-2"><p className="min-w-0 break-words font-medium">{plan.name}</p>
        <StatusBadge status={plan.failure ? "failed" : plan.status ?? "unknown"} /></div>
      <p className="mt-1 line-clamp-2 break-words text-muted-foreground" title={plan.instruction}>{plan.instruction}</p>
      {plan.configuration ? <p className="mt-1 text-muted-foreground">{[plan.configuration.method, plan.configuration.language, plan.configuration.actual_solver].filter(Boolean).join(" · ")}</p> : null}
      {plan.objective != null ? <p className="mt-2">{plan.explanation?.objective_label || t("目标值")} <strong className="text-sm tabular-nums">{formatNumber(plan.objective)}</strong> {plan.explanation?.objective_unit}</p> : null}
      {onOpenPlan ? <Button variant="link" size="xs" className="mt-2 h-auto p-0" onClick={() => onOpenPlan(plan.source.thread_id)}>{t("查看计算方案")}<ArrowUpRight /></Button> : null}
    </div>)}
    {plans.length > 1 && plans[0].group && onCompare ? <Button variant="outline" size="sm" onClick={() => onCompare(plans[0].group!)}>{t("对比本轮方案")}</Button> : null}
  </aside>;
}

function Search({ artifact }: ResultProps) {
  const sources = (artifact?.results ?? []).filter(source => typeof source.title === "string" && /^https?:\/\//i.test(source.url) && URL.canParse(source.url));
  return <aside aria-label={t("搜索来源")} className="ml-9 rounded-xl border bg-card text-xs">
    <details className="group/sources" open={artifact?.error ? true : undefined}>
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl px-3 py-2.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
        <Globe className="size-3.5 shrink-0" /><span className="min-w-0 flex-1 truncate" title={artifact?.query}>{artifact?.query || t("联网搜索")}</span>
        <span className="shrink-0">{t("{count} 个来源", { count: sources.length })}</span><ChevronRight className="size-3.5 shrink-0 transition-transform group-open/sources:rotate-90" />
      </summary>
      <div className="border-t px-3 py-2">
        {artifact?.error ? <p role="alert" className="break-words text-destructive">{t(artifact.error)}</p>
          : sources.length ? <ul className="flex flex-col divide-y">{sources.map((source, index) => <li key={`${source.url}-${index}`} className="py-2 first:pt-0 last:pb-0">
            <a href={source.url} target="_blank" rel="noopener noreferrer" className="flex items-start gap-2 font-medium text-foreground hover:text-primary">
              <span className="line-clamp-2 min-w-0 break-words">{source.title}</span><ArrowUpRight className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
            </a>
            <p className="mt-1 truncate text-muted-foreground">{new URL(source.url).hostname}{source.date ? ` · ${source.date.slice(0, 10)}` : ""}</p>
            {source.snippet || source.summary ? <p className="mt-1 line-clamp-3 break-words leading-5 text-muted-foreground">{source.snippet || source.summary}</p> : null}
          </li>)}</ul> : <p className="text-muted-foreground">{t("没有找到相关网页。")}</p>}
      </div>
    </details>
  </aside>;
}

export const resultViews: Readonly<Record<string, ComponentType<ResultProps>>> = {
  draft: DraftResult, selected_plan: SelectedPlan, calculation: Calculation, plans: Plans, search: Search,
};

// Saved messages predating artifact types keep their original presentation.
const tools = new Map<string, { activity: string; result?: string }>([
  ["web_search", { activity: "正在联网搜索……", result: "search" }],
  ["model_and_solve", { activity: "正在建模求解……", result: "plans" }],
  ["modeling_capabilities", { activity: "正在查看可用建模能力……" }],
  ["solve_scenarios", { activity: "正在重新建模求解……", result: "plans" }],
  ["lookup_variables", { activity: "正在读取实际方案……" }],
  ["calculate", { activity: "正在计算核对……", result: "calculation" }],
  ["select_plan", { activity: "正在切换讨论方案……", result: "selected_plan" }],
  ["update_draft", { activity: "正在更新需求稿……", result: "draft" }],
]);

export function activity(name: string): string {
  return t(tools.get(name)?.activity ?? "正在执行工具……");
}

export function resultType(artifact: ToolArtifact | undefined, toolName: string | undefined): string {
  return artifact?.type ?? tools.get(toolName ?? "")?.result ?? "";
}
