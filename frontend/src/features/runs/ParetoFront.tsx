import { lazy, Suspense, useLayoutEffect, useRef, useState } from "react";
import { ArrowDown, ArrowUp, Download, GitFork, Sparkles } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Plain, download } from "@/components/Content";
import { formatNumber } from "@/format";
import { t } from "@/i18n";
import { toCsv } from "@/lib/csv";
import { cn } from "@/lib/utils";
import { adjacentSolution, objectiveLabel } from "./pareto";
import type { Explanation, ParetoSolution, ParetoFront as ParetoFrontData } from "@/features/runs/types";

const TradeoffPlot = lazy(() => import("./TradeoffPlot"));

function DecisionDetails({ solution, decisions, objectives }: {
  solution: ParetoSolution; decisions?: Explanation["decisions"]; objectives: ParetoFrontData["objectives"];
}) {
  const variables = solution.variables ?? {};
  const labels = new Map((decisions ?? []).map(item => [item.variable, item]));
  const decoded = solution.decoded;
  const assignments = decoded && typeof decoded === "object" && "task_to_cluster" in decoded ? decoded.task_to_cluster : null;
  const tasks = assignments && typeof assignments === "object" && !Array.isArray(assignments)
    ? Object.entries(assignments).filter(([, cluster]) => typeof cluster === "string" || typeof cluster === "number") : [];
  const rows = tasks.length ? tasks.map(([task, cluster]) => ({
    id: task, label: t("任务 {id}", { id: task }), value: t("集群 {id}", { id: cluster }),
  })) : Object.entries(variables).filter(([name, value]) => labels.has(name) || (value != null && value !== 0)).slice(0, 60).map(([name, value]) => {
    const info = labels.get(name);
    return { id: name, label: info?.label || name, value: [value == null ? "—" : formatNumber(value), info?.unit].filter(Boolean).join(" ") };
  });
  return <>
    {rows.length > 0 && <dl className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
      {rows.map(row => <div key={row.id} className="flex items-baseline justify-between gap-2 border-b py-1">
        <dt>{row.label}</dt><dd className="font-medium tabular">{row.value}</dd>
      </div>)}
    </dl>}
    <details className="text-xs text-muted-foreground">
      <summary className="w-fit cursor-pointer py-1">{t("技术详情")}</summary>
      <Plain className="mt-2 max-h-56 overflow-auto">{JSON.stringify({ objectives, solution }, null, 2)}</Plain>
    </details>
  </>;
}

export function ParetoFront({ pareto, decisions, runKey }: {
  pareto: ParetoFrontData; decisions?: Explanation["decisions"]; runKey?: string;
}) {
  const storageKey = runKey && `llm4om-pareto-${runKey}`;
  const [selected, setSelected] = useState(() => {
    try {
      const saved = storageKey && sessionStorage.getItem(storageKey);
      if (saved && /^\d+$/.test(saved)) return Number(saved);
    } catch { /* storage may be unavailable */ }
    return -1;
  });
  const table = useRef<HTMLTableElement>(null);
  const activeIndex = selected >= 0 && selected < pareto.solutions.length
    ? selected : Math.max(0, pareto.solutions.findIndex(item => item.knee));
  const active = pareto.solutions[activeIndex];
  const select = (index: number) => {
    setSelected(index);
    try { if (storageKey) sessionStorage.setItem(storageKey, String(index)); } catch { /* storage may be unavailable */ }
  };
  useLayoutEffect(() => {
    const element = table.current;
    const container = element?.parentElement;
    const row = element?.tBodies[0]?.rows[activeIndex];
    if (!element || !container || !row) return;
    const reveal = () => {
      if (!container.clientHeight) return;
      const bounds = container.getBoundingClientRect();
      const top = bounds.top + container.clientTop + (element.tHead?.offsetHeight ?? 0);
      const bottom = bounds.top + container.clientTop + container.clientHeight;
      const rect = row.getBoundingClientRect();
      if (rect.top < top) container.scrollTop += rect.top - top;
      else if (rect.bottom > bottom) container.scrollTop += rect.bottom - bottom;
    };
    reveal();
    // The mobile conversation keeps this pane mounted while it is hidden.
    const observer = new ResizeObserver(reveal);
    observer.observe(container);
    return () => observer.disconnect();
  }, [activeIndex, active]);
  if (!active) return null;

  const exportCsv = () => {
    const headers = [
      "index",
      "knee",
      ...pareto.objectives.map(obj => `${obj.name} (${obj.sense})`),
    ];
    const rows = pareto.solutions.map((sol, idx) => [
      idx + 1,
      sol.knee ? "yes" : "",
      ...sol.objectives.map(val => val ?? ""),
    ]);
    download("pareto_front.csv", toCsv([headers, ...rows]));
  };

  return <Card className="gap-4 rounded-2xl border-primary/20 bg-gradient-to-br from-primary/[0.03] via-card to-card py-4 shadow-xs">
    <CardHeader className="flex flex-wrap items-center gap-2 px-5">
      <CardTitle className="flex items-center gap-2 text-sm font-semibold">
        <span className="grid size-6 place-items-center rounded-lg bg-primary/10 text-primary">
          <GitFork className="size-3.5" />
        </span>
        {t("多目标 Pareto 前沿")}
      </CardTitle>
      <Badge variant="secondary" className="h-5 font-normal tabular">
        {t("共 {total} 个非支配解", { total: pareto.total })}
      </Badge>
      {pareto.total > pareto.solutions.length ? <span className="text-xs text-muted-foreground">
        {t("已展示 {shown} 个代表解", { shown: pareto.solutions.length })}
      </span> : null}
      <Button variant="ghost" size="sm" className="ml-auto rounded-lg text-muted-foreground" aria-label={t("导出 Pareto CSV")} onClick={exportCsv}>
        <Download />{t("导出 Pareto CSV")}
      </Button>
      <p className="w-full text-xs text-muted-foreground">
        {t("点击散点或表格行选择方案，也可用方向键切换。")}
      </p>
    </CardHeader>
    <CardContent className="flex min-w-0 flex-col gap-3.5 px-5">
      <Suspense fallback={null}><TradeoffPlot objectives={pareto.objectives} solutions={pareto.solutions} activeIndex={activeIndex} onSelect={select} /></Suspense>
      <div aria-live="polite" aria-atomic="true" className="flex flex-wrap items-baseline gap-x-4 gap-y-1 rounded-lg bg-primary/5 px-3 py-2 text-sm">
        <strong>{t("已选方案 #{index}", { index: activeIndex + 1 })}</strong>
        {pareto.objectives.map((obj, i) => <span key={i}>{objectiveLabel(obj)} <b className="tabular">{active.objectives[i] == null ? "—" : formatNumber(active.objectives[i])}</b></span>)}
      </div>
      <Table ref={table} role="grid" aria-label={t("多目标 Pareto 前沿")} className="text-[13px]" containerClassName="max-h-80 rounded-xl border border-border/80 bg-background/80">
        <TableHeader className="sticky top-0 z-10 bg-muted/80 backdrop-blur-xs">
          <TableRow>
            <TableHead className="h-9 w-28">{t("方案编号")}</TableHead>
            {pareto.objectives.map((obj, idx) => <TableHead key={`${obj.name}-${idx}`} className="h-9 text-right">
              <span className="inline-flex items-center justify-end gap-1 font-medium">
                <span>{objectiveLabel(obj)}</span>
                <span className="inline-flex items-center rounded bg-muted px-1 py-0.5 font-mono text-[10px] font-normal text-muted-foreground">
                  {obj.sense === "max" ? <ArrowUp className="mr-0.5 size-2.5" /> : <ArrowDown className="mr-0.5 size-2.5" />}
                  {obj.sense}
                </span>
              </span>
            </TableHead>)}
          </TableRow>
        </TableHeader>
        <TableBody>
          {pareto.solutions.map((sol, idx) => {
            const isSelected = idx === activeIndex;
            return <TableRow
              key={idx}
              tabIndex={isSelected ? 0 : -1}
              onClick={() => select(idx)}
              onKeyDown={event => {
                const next = adjacentSolution(event.key, idx, pareto.solutions.length);
                if (next === undefined) return;
                event.preventDefault();
                select(next);
                table.current?.tBodies[0]?.rows[next]?.focus({ preventScroll: true });
              }}
              aria-selected={isSelected}
              className={cn(
                "cursor-pointer transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                isSelected ? "bg-primary/10 hover:bg-primary/12" : sol.knee ? "bg-primary/[0.04] hover:bg-primary/[0.08]" : "hover:bg-muted/40",
              )}
            >
              <TableCell className="py-2 font-mono text-xs">
                <span className="inline-flex items-center gap-1.5">
                  <span className={cn("font-semibold", isSelected && "text-primary")}>#{idx + 1}</span>
                  {sol.knee ? <Badge variant="secondary" className="h-4.5 gap-0.5 px-1.5 text-[10px] font-medium text-primary">
                    <Sparkles className="size-2.5" />{t("推荐折中")}
                  </Badge> : null}
                </span>
              </TableCell>
              {pareto.objectives.map((_, objIdx) => {
                const val = sol.objectives[objIdx];
                return <TableCell key={objIdx} className={cn("py-2 text-right font-mono tabular", isSelected && "font-semibold")}>
                  {val == null ? "—" : formatNumber(val)}
                </TableCell>;
              })}
            </TableRow>;
          })}
        </TableBody>
      </Table>

      <section className="grid gap-2 rounded-xl border border-border/70 bg-muted/20 p-3">
        <h3 className="text-sm font-medium">{t("方案 #{index} 决策明细", { index: activeIndex + 1 })}</h3>
        <DecisionDetails solution={active} decisions={decisions} objectives={pareto.objectives} />
      </section>
    </CardContent>
  </Card>;
}
