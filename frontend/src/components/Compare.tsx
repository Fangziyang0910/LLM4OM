import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Columns3, TriangleAlert } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { history } from "@/api";
import { STATUS, duration, errorText, formatNumber, formatTokens, tone } from "@/format";
import { t } from "@/i18n";
import type { Entry, Options } from "@/types";
import { StatusIcon, TONE } from "./status";

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
    refetchInterval: current => current.state.data?.some(entry => entry.state === "running") ? 3000 : false });
  const entries = [...(query.data ?? [])].reverse();  // in the order they started

  if (query.error) return <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm">
    <TriangleAlert className="size-6 text-destructive" /><p>{errorText(query.error)}</p></div>;
  if (!query.data) return <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在读取对比……")}</div>;
  if (!entries.length) return <div className="flex h-full items-center justify-center p-6 text-sm text-muted-foreground">{t("这个对比没有运行，可能已被删除。")}</div>;

  const methodName = (id: string) => options.methods.find(item => item.id === id)?.name ?? id;
  const language = (id: string) => options.languages.find(item => item.id === id);
  const running = entries.filter(entry => entry.state === "running").length;
  const result = agreement(entries);

  return <div className="h-full overflow-y-auto">
    <div className="mx-auto flex max-w-6xl flex-col gap-5 px-4 py-6 md:px-8 md:py-8">
      <header className="flex flex-col gap-1.5">
        <span className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><Columns3 className="size-3.5" />{t("方法对比")}</span>
        <h1 className="text-xl font-semibold tracking-tight">{entries[0].meta.title}</h1>
        <p className="text-sm text-muted-foreground">
          {t("{count} 个运行", { count: entries.length })}
          {running ? <> · {t("{count} 个进行中", { count: running })}</> : null}
          {result.solved >= 2 ? <> · {result.same ? <span className="text-success">{t("{count} 个有解的运行目标值一致", { count: result.solved })}</span>
            : <span className="text-warning">{t("目标值不一致：{low} 至 {high}", { low: formatNumber(result.low!), high: formatNumber(result.high!) })}</span>}</> : null}
        </p>
      </header>

      <div className="overflow-x-auto rounded-xl border bg-card shadow-xs">
        <Table className="text-[13px]">
          <TableHeader className="bg-muted/50"><TableRow>
            <TableHead>{t("建模方法")}</TableHead><TableHead>{t("代码写法")}</TableHead><TableHead>{t("预设模型")}</TableHead>
            <TableHead>{t("结果")}</TableHead><TableHead className="text-right">{t("目标值")}</TableHead>
            <TableHead className="text-right">{t("用时")}</TableHead><TableHead className="text-right">{t("LLM 调用")}</TableHead>
            <TableHead className="text-right">Token</TableHead><TableHead />
          </TableRow></TableHeader>
          <TableBody>{entries.map(entry => {
            const code = language(entry.meta.language);
            const seconds = (Date.parse(entry.updated) - Date.parse(entry.created)) / 1000;
            const tokens = entry.usage ? entry.usage.input_tokens + entry.usage.output_tokens : null;
            return <TableRow key={entry.id} className="cursor-pointer" onClick={() => onOpen(entry.id)}>
              <TableCell className="font-medium">{methodName(entry.meta.method)}</TableCell>
              <TableCell>{code ? <>{code.name}<span className="text-muted-foreground"> · {code.solver}</span></> : entry.meta.language}</TableCell>
              <TableCell className="max-w-48 truncate">{entry.meta.model ?? "—"}</TableCell>
              <TableCell><span className={cn("flex items-center gap-1.5", TONE[tone(entry.state)].text)} title={entry.failure ?? undefined}>
                <StatusIcon status={entry.state} className="size-3.5" />{(STATUS[entry.state] ?? entry.state)}</span></TableCell>
              <TableCell className="text-right font-mono tabular">
                {entry.objective != null && tone(entry.state) === "good"
                  ? formatNumber(entry.objective) : "—"}</TableCell>
              <TableCell className="text-right tabular text-muted-foreground">{entry.state === "running" ? "…" : duration(seconds)}</TableCell>
              <TableCell className="text-right tabular text-muted-foreground">{entry.usage?.llm_calls ?? "—"}</TableCell>
              <TableCell className="text-right tabular text-muted-foreground">{tokens ? formatTokens(tokens) : "—"}</TableCell>
              <TableCell><Button variant="ghost" size="icon-xs" aria-label={t("打开运行")}><ArrowRight /></Button></TableCell>
            </TableRow>;
          })}</TableBody>
        </Table>
      </div>
      <p className="text-xs leading-relaxed text-muted-foreground">
        {t("目标值相同不代表模型都对：几个方法可能犯同样的错。点击一行查看它的数学模型、代码和过程。")}
        {entries.some(entry => entry.failure) ? <> <Badge variant="outline" className="ml-1 font-normal">{t("悬停在失败的结果上可看原因")}</Badge></> : null}
      </p>
    </div>
  </div>;
}
