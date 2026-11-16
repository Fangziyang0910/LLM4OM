import { useQuery } from "@tanstack/react-query";
import { ArrowRight, CircleCheck, Columns3, RefreshCw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { history } from "@/features/runs/api";
import { targetLabel } from "@/features/runs/target";
import { STATUS, duration, errorText, formatNumber, tone } from "@/format";
import { t } from "@/i18n";
import { isRunEntry, type Entry, type SourceRun } from "@/features/runs/types";
import type { Options } from "@/types";
import { StatusIcon, TONE } from "@/features/runs/status";
import { ScenarioResults } from "./ScenarioResults";

/** Whether the solved runs agree on the objective value, up to a relative 1e-6. */
export function agreement(entries: Entry[]): { solved: number; same: boolean; low: number | null; high: number | null } {
  const values = entries.filter(entry => tone(entry.state) === "good" && entry.objective != null).map(entry => entry.objective!);
  if (!values.length) return { solved: 0, same: false, low: null, high: null };
  const low = Math.min(...values), high = Math.max(...values);
  return { solved: values.length, same: high - low <= 1e-6 * Math.max(1, Math.abs(high)), low, high };
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
            ? t("交叉验证一致：{count} 组已求得最优解的方案目标值完全相同（{value}）。", { count: result.solved, value: formatNumber(result.low!) })
            : t("不同方案求得的目标值存在差异（范围：{low} 至 {high}），建议点开具体方案核对约束条件。", { low: formatNumber(result.low!), high: formatNumber(result.high!) })}
        </p>
      </div> : null}

      <Table className="text-[13px]" containerClassName="rounded-2xl border border-border/80 bg-card shadow-xs">
        <TableHeader className="bg-muted/40"><TableRow>
          <TableHead>{t("求解策略")}</TableHead><TableHead>{t("求解引擎")}</TableHead><TableHead>{t("AI 模型")}</TableHead>
          <TableHead>{t("状态")}</TableHead><TableHead className="text-right">{t("最优目标值")}</TableHead>
          <TableHead className="text-right">{t("耗时")}</TableHead><TableHead />
        </TableRow></TableHeader>
        <TableBody>{entries.map(entry => (
          <TableRow key={entry.id} className="cursor-pointer transition-colors hover:bg-muted/40" onClick={() => onOpen(entry.id)}>
            <TableCell className="font-medium">{methodName(entry.meta.method)}</TableCell>
            <TableCell className="text-muted-foreground">{targetLabel(options, entry.meta)}</TableCell>
            <TableCell className="max-w-48 truncate text-muted-foreground">{entry.meta.model ?? "—"}</TableCell>
            <TableCell><span className={cn("flex items-center gap-1.5 font-medium", TONE[tone(entry.state)].text)} title={entry.failure ?? undefined}>
              <StatusIcon status={entry.state} className="size-3.5" />{(STATUS[entry.state] ?? entry.state)}</span>
              {entry.failure ? <p className="mt-1 max-w-64 text-xs whitespace-normal text-destructive">{entry.failure}</p> : null}</TableCell>
            <TableCell className="text-right font-mono font-semibold tabular">
              {entry.objective != null && tone(entry.state) === "good"
                ? formatNumber(entry.objective) : "—"}</TableCell>
            <TableCell className="text-right tabular text-muted-foreground">{entry.state === "running" ? "…" : entry.elapsed == null ? "—" : duration(entry.elapsed)}</TableCell>
            <TableCell className="text-right"><Button variant="ghost" size="icon-xs" aria-label={t("打开运行")}><ArrowRight /></Button></TableCell>
          </TableRow>
        ))}</TableBody>
      </Table>
    </div>
  </div>;
}
