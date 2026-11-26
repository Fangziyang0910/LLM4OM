import { Fragment } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CircleCheck, Columns3, RefreshCw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { history } from "@/features/runs/api";
import { targetLabel } from "@/features/runs/target";
import { canHaveSolution, STATUS, duration, errorText, formatNumber, tone } from "@/format";
import { t } from "@/i18n";
import { isRunEntry, type Entry, type SourceRun } from "@/features/runs/types";
import type { Options } from "@/types";
import { StatusIcon, TONE } from "@/features/runs/status";
import { ScenarioResults } from "./ScenarioResults";

/** Whether single-objective solved runs agree on the objective value, up to a relative 1e-6. */
function agreement(entries: Entry[]): { solved: number; same: boolean; low: number | null; high: number | null; pareto: number } {
  const pareto = entries.filter(entry => canHaveSolution(entry.state) && !!entry.paretoTotal && entry.paretoTotal > 0).length;
  const values = entries
    .filter(entry => canHaveSolution(entry.state) && (!entry.paretoTotal || entry.paretoTotal <= 0) && entry.objective != null)
    .map(entry => entry.objective!);
  if (!values.length) return { solved: 0, same: false, low: null, high: null, pareto };
  const low = Math.min(...values), high = Math.max(...values);
  return { solved: values.length, same: high - low <= 1e-6 * Math.max(1, Math.abs(high)), low, high, pareto };
}

/** The runs of one comparison side by side: the same problem, one row per method and preset. */
export function Compare({ group, options, onOpen }: { group: string; options: Options; onOpen: (run: string | SourceRun) => void }) {
  const query = useQuery({ queryKey: ["compare", group], queryFn: () => history({ group }),
    refetchInterval: current => current.state.data?.entries.some(entry => ["running", "pending"].includes(entry.state)) ? 3000 : false });
  const entries = (query.data?.entries ?? []).filter(isRunEntry)
    .reverse();  // in the order they started

  if (query.error) return <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-sm">
    <TriangleAlert className="size-6 text-destructive" /><p>{errorText(query.error)}</p>
    <Button variant="outline" size="sm" onClick={() => void query.refetch()}><RefreshCw />{t("重试")}</Button></div>;
  if (!query.data) return <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在加载对比结果…")}</div>;
  if (!entries.length) return <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">{t("暂无对比记录，可能已被删除。")}</div>;
  if (entries[0].meta.scenario) return <ScenarioResults entries={entries} onOpen={onOpen} />;

  const methodName = (id: string) => options.methods.find(item => item.id === id)?.name ?? id;
  const running = entries.filter(entry => ["running", "pending"].includes(entry.state)).length;
  const result = agreement(entries);

  return <div className="h-full overflow-y-auto">
    <div className="mx-auto flex max-w-6xl min-w-0 flex-col gap-5 p-4 sm:p-6">
      <header className="animate-fade-up flex flex-col gap-2">
        <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
          <Columns3 className="size-3.5" />{t("多策略求解对比")}
        </span>
        <h1 className="break-words text-xl font-semibold tracking-tight sm:text-2xl">{entries[0].meta.title}</h1>
        <p className="text-sm text-muted-foreground">
          {t("共 {count} 组求解方案", { count: entries.length })}
          {running ? <> · {t("{count} 组正在计算", { count: running })}</> : null}
        </p>
      </header>

      {result.solved >= 2 ? <div className={cn(
        "flex items-center gap-3 rounded-2xl border p-3.5 text-sm",
        result.same ? "border-success/25 bg-success/5 text-foreground" : "border-warning/30 bg-warning/5 text-foreground"
      )}>
        {result.same ? <CircleCheck className="size-5 shrink-0 text-success" /> : <TriangleAlert className="size-5 shrink-0 text-warning" />}
        <p>
          {result.same
            ? t("{count} 个方案的目标值在数值容差内一致（约 {value}）。", { count: result.solved, value: formatNumber(result.low!) })
            : t("不同方案求得的目标值存在差异（范围：{low} 至 {high}），建议点开具体方案核对约束条件。", { low: formatNumber(result.low!), high: formatNumber(result.high!) })}
        </p>
      </div> : null}

      <Table className="text-[13px]" containerClassName="rounded-2xl border border-border/80 bg-card shadow-xs">
        <TableHeader className="bg-muted/40"><TableRow>
          <TableHead>{t("求解策略")}</TableHead><TableHead className="text-right">{t("目标值")}</TableHead><TableHead>{t("状态")}</TableHead>
          <TableHead className="hidden md:table-cell">{t("求解引擎")}</TableHead><TableHead className="hidden md:table-cell">{t("AI 模型")}</TableHead>
          <TableHead className="hidden text-right md:table-cell">{t("耗时")}</TableHead>
        </TableRow></TableHeader>
        <TableBody>{entries.map(entry => {
          const engine = targetLabel(options, entry.meta);
          const elapsed = entry.state === "running" ? "…" : entry.elapsed == null ? "—" : duration(entry.elapsed);
          return <Fragment key={entry.id}>
            <TableRow className="cursor-pointer max-md:border-b-0" onClick={() => onOpen(entry.id)}>
              <TableCell className="font-medium whitespace-normal">
                <button type="button" className="inline-flex items-center gap-1 text-left hover:underline"
                  aria-label={t("打开方案：{method}", { method: methodName(entry.meta.method) })}>
                  {methodName(entry.meta.method)}<ArrowRight className="size-3 shrink-0 text-muted-foreground" />
                </button>
              </TableCell>
              <TableCell className="text-right font-mono font-semibold whitespace-normal tabular">
                {entry.paretoTotal && entry.paretoTotal > 0 && canHaveSolution(entry.state)
                  ? t("{count} 个 Pareto 解", { count: entry.paretoTotal })
                  : entry.objective != null && canHaveSolution(entry.state) ? formatNumber(entry.objective) : "—"}
              </TableCell>
              <TableCell><span className={cn("flex items-center gap-1.5 font-medium whitespace-normal", TONE[tone(entry.state)].text)} title={entry.failure ?? undefined}>
                <StatusIcon status={entry.state} className="size-3.5 shrink-0" />{STATUS[entry.state] ?? entry.state}</span>
                {entry.failure ? <p className="mt-1 max-w-64 text-xs whitespace-normal text-destructive">{entry.failure}</p> : null}</TableCell>
              <TableCell className="hidden text-muted-foreground md:table-cell">{engine}</TableCell>
              <TableCell className="hidden max-w-48 truncate text-muted-foreground md:table-cell">{entry.meta.model ?? "—"}</TableCell>
              <TableCell className="hidden text-right tabular text-muted-foreground md:table-cell">{elapsed}</TableCell>
            </TableRow>
            <TableRow className="md:hidden"><TableCell colSpan={3} className="pt-0 text-xs whitespace-normal text-muted-foreground">
              <details><summary className="w-fit cursor-pointer py-1">{t("运行信息")}</summary>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 py-1">
                  <dt>{t("求解引擎")}</dt><dd>{engine}</dd>
                  <dt>{t("AI 模型")}</dt><dd className="break-all">{entry.meta.model ?? "—"}</dd>
                  <dt>{t("耗时")}</dt><dd>{elapsed}</dd>
                </dl>
              </details>
            </TableCell></TableRow>
          </Fragment>;
        })}</TableBody>
      </Table>
    </div>
  </div>;
}
