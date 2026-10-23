import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Columns3, RefreshCw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { history } from "@/features/runs/api";
import { targetLabel } from "@/features/runs/target";
import { STATUS, duration, errorText, formatNumber, formatTokens, tone } from "@/format";
import { t } from "@/i18n";
import { isRunEntry, type Entry } from "@/features/runs/types";
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
export function Compare({ group, options, onOpen }: { group: string; options: Options; onOpen: (id: string) => void }) {
  const query = useQuery({ queryKey: ["compare", group], queryFn: () => history({ group }),
    refetchInterval: current => current.state.data?.entries.some(entry => entry.state === "running") ? 3000 : false });
  const entries = (query.data?.entries ?? []).filter(isRunEntry)
    .reverse();  // in the order they started

  if (query.error) return <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm">
    <TriangleAlert className="size-6 text-destructive" /><p>{errorText(query.error)}</p>
    <Button variant="outline" size="sm" onClick={() => void query.refetch()}><RefreshCw />{t("重试")}</Button></div>;
  if (!query.data) return <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在读取对比……")}</div>;
  if (!entries.length) return <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">{t("这个对比没有运行，可能已被删除。")}</div>;
  if (entries[0].meta.scenario) return <ScenarioResults entries={entries} onOpen={onOpen} />;

  const methodName = (id: string) => options.methods.find(item => item.id === id)?.name ?? id;
  const running = entries.filter(entry => entry.state === "running").length;
  const result = agreement(entries);

  return <div className="h-full overflow-y-auto">
    <div className="flex min-w-0 flex-col gap-5 p-4 sm:p-6">
      <header className="flex flex-col gap-1.5">
        <span className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><Columns3 className="size-3.5" />{t("方法对比")}</span>
        <h1 className="break-words text-xl font-semibold tracking-tight">{entries[0].meta.title}</h1>
        <p className="text-sm text-muted-foreground">
          {t("{count} 个运行", { count: entries.length })}
          {running ? <> · {t("{count} 个进行中", { count: running })}</> : null}
          {result.solved >= 2 ? <> · {result.same ? <span className="text-success">{t("{count} 个有解的运行目标值一致", { count: result.solved })}</span>
            : <span className="text-warning">{t("目标值不一致：{low} 至 {high}", { low: formatNumber(result.low!), high: formatNumber(result.high!) })}</span>}</> : null}
        </p>
      </header>

        <Table className="text-[13px]" containerClassName="rounded-xl border bg-card shadow-xs">
          <TableHeader className="bg-muted/50"><TableRow>
            <TableHead>{t("建模方法")}</TableHead><TableHead>{t("代码写法")}</TableHead><TableHead>{t("预设模型")}</TableHead>
            <TableHead>{t("结果")}</TableHead><TableHead className="text-right">{t("目标值")}</TableHead>
            <TableHead className="text-right">{t("用时")}</TableHead><TableHead className="text-right">{t("LLM 调用")}</TableHead>
            <TableHead className="text-right">Token</TableHead><TableHead />
          </TableRow></TableHeader>
          <TableBody>{entries.map(entry => {
            const tokens = entry.usage ? entry.usage.input_tokens + entry.usage.output_tokens : null;
            return <TableRow key={entry.id} className="cursor-pointer" onClick={() => onOpen(entry.id)}>
              <TableCell className="font-medium">{methodName(entry.meta.method)}</TableCell>
              <TableCell>{targetLabel(options, entry.meta)}</TableCell>
              <TableCell className="max-w-48 truncate">{entry.meta.model ?? "—"}</TableCell>
              <TableCell><span className={cn("flex items-center gap-1.5", TONE[tone(entry.state)].text)} title={entry.failure ?? undefined}>
                <StatusIcon status={entry.state} className="size-3.5" />{(STATUS[entry.state] ?? entry.state)}</span>
                {entry.failure ? <p className="mt-1 max-w-64 text-xs whitespace-normal text-destructive">{entry.failure}</p> : null}</TableCell>
              <TableCell className="text-right font-mono tabular">
                {entry.objective != null && tone(entry.state) === "good"
                  ? formatNumber(entry.objective) : "—"}</TableCell>
              <TableCell className="text-right tabular text-muted-foreground">{entry.state === "running" ? "…" : entry.elapsed == null ? "—" : duration(entry.elapsed)}</TableCell>
              <TableCell className="text-right tabular text-muted-foreground">{entry.usage?.llm_calls ?? "—"}</TableCell>
              <TableCell className="text-right tabular text-muted-foreground">{tokens ? formatTokens(tokens) : "—"}</TableCell>
              <TableCell><Button variant="ghost" size="icon-xs" aria-label={t("打开运行")}><ArrowRight /></Button></TableCell>
            </TableRow>;
          })}</TableBody>
        </Table>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t("目标值相同不代表模型都对：几个方法可能犯同样的错。点击一行查看它的数学模型、代码和过程。")}
      </p>
    </div>
  </div>;
}
