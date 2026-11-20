import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, TriangleAlert } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Diff } from "@/components/Content";
import { client } from "@/features/runs/sdk";
import { StatusBadge } from "@/features/runs/status";
import { variableChanges } from "@/features/runs/tables";
import { errorText, formatNumber } from "@/format";
import { t } from "@/i18n";
import type { RunValues, SourceRun } from "@/features/runs/types";

/** Compare with the exact checkpoint used to start this revision, even if the original thread is rerun later. */
export function ScenarioComparison({ source, values, active = false }: { source: SourceRun; values: RunValues; active?: boolean }) {
  const query = useQuery({ queryKey: ["source-run", source.thread_id, source.checkpoint_id],
    queryFn: () => client.threads.getState<RunValues>(source.thread_id, source.checkpoint_id), staleTime: Infinity, retry: false });
  const [limit, setLimit] = useState(200);
  if (query.error) return <Alert><TriangleAlert /><AlertDescription>
    {t("无法读取原方案，可能已被删除。当前方案仍可在“最优方案”标签页查看。")}
    <span className="text-xs">{errorText(query.error)}</span>
  </AlertDescription></Alert>;
  if (!query.data) return <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground"><Spinner />{t("正在加载原方案…")}</div>;

  const before = query.data.values as RunValues;
  const waitingForResult = active && !values.solve;
  const changes = waitingForResult ? [] : variableChanges(before.solve?.variables ?? {}, values.solve?.variables ?? {});
  const labels = new Map([...(before.explanation?.decisions ?? []), ...(values.explanation?.decisions ?? [])].map(item => [item.variable, item.label]));
  const previous = before.solve?.objective, current = values.solve?.objective;
  const difference = previous != null && current != null ? current - previous : null;
  const number = (value: number | undefined | null) => value == null ? "—" : formatNumber(value);
  const statusOf = (result: RunValues, isCurrent: boolean) =>
    isCurrent && active && !result.solve ? "running" : result.failure ? "failed" : result.solve?.status ?? (result.timing?.finished_at ? "success" : "interrupted");
  const scenarios: [string, RunValues, boolean][] = [[t("调整前（原方案）"), before, false], [t("调整后（新方案）"), values, true]];

  return <div className="flex min-w-0 flex-col gap-4">
    <Card className="gap-4 rounded-2xl border-border/80 py-5 shadow-2xs">
      <CardHeader className="flex flex-wrap items-center justify-between gap-2 px-5">
        <CardTitle className="text-sm font-semibold">{t("前后方案指标对比")}</CardTitle>
        <Button variant="outline" size="sm" className="rounded-lg" asChild><a href={`/run/${source.thread_id}${source.checkpoint_id ? `?checkpoint=${encodeURIComponent(source.checkpoint_id)}` : ""}`}>{t("查看原方案")}<ArrowUpRight /></a></Button>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4 px-5">
        {values.revision ? <div className="rounded-xl border border-primary/20 bg-primary/5 px-3.5 py-2.5 text-sm leading-relaxed whitespace-pre-wrap break-words">
          <span className="font-semibold text-primary">{t("本次调整条件")}：</span>{values.revision.instruction}</div> : null}
        <div className="grid gap-3 sm:grid-cols-3">
          {scenarios.map(([label, result, isCurrent]) => (
            <div key={label} className="flex min-w-0 flex-col gap-2 rounded-xl border border-border/70 bg-muted/15 p-3.5">
              <span className="text-xs font-medium text-muted-foreground">{label}</span>
              <StatusBadge status={statusOf(result, isCurrent)} />
              <span className="text-2xl font-bold tracking-tight tabular">{number(result.solve?.objective)}</span>
            </div>
          ))}
          <div className="flex flex-col gap-2 rounded-xl border border-primary/20 bg-primary/[0.04] p-3.5">
            <span className="text-xs font-medium text-muted-foreground">{t("目标值变化量（新 − 原）")}</span>
            <span className="text-2xl font-bold tracking-tight text-primary tabular">{difference != null && difference > 0 ? `+${number(difference)}` : number(difference)}</span>
            <span className="text-xs leading-relaxed text-muted-foreground">{t("当两次优化的目标单位一致时可直接比较增减。")}</span>
          </div>
        </div>
        <details className="min-w-0 rounded-xl border border-border/70 bg-muted/15 p-3.5">
          <summary className="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">{t("查看问题描述修改对照")}</summary>
          <div className="mt-3 min-w-0"><Diff before={before.description ?? ""} after={values.description ?? ""} /></div>
        </details>
      </CardContent>
    </Card>
    <Card className="gap-3 rounded-2xl border-border/80 py-5 shadow-2xs">
      <CardHeader className="px-5"><CardTitle className="text-sm font-semibold">{t("具体决策数值变化（共 {count} 项）", { count: changes.length })}</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3 px-5">
        {waitingForResult ? <p className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在计算最优方案，求解完成后将展示在这里…")}</p>
          : changes.length ? <Table className="text-[13px]" containerClassName="rounded-xl border border-border/80">
          <TableHeader className="bg-muted/40"><TableRow><TableHead>{t("决策项")}</TableHead><TableHead className="text-right">{t("原方案")}</TableHead>
            <TableHead className="text-right">{t("新方案")}</TableHead><TableHead className="text-right">{t("变化量")}</TableHead>
          </TableRow></TableHeader>
          <TableBody>{changes.slice(0, limit).map(item => {
            const delta = item.before != null && item.after != null ? item.after - item.before : null;
            return <TableRow key={item.name}>
              <TableCell className="min-w-32 max-w-64 font-medium whitespace-normal [overflow-wrap:anywhere]"><span>{labels.get(item.name) ?? item.name}</span>
                {labels.has(item.name) ? <span className="mt-0.5 block font-mono text-[11px] font-normal text-muted-foreground">{item.name}</span> : null}</TableCell>
              <TableCell className="text-right font-mono tabular">{number(item.before)}</TableCell>
              <TableCell className="text-right font-mono font-semibold tabular">{number(item.after)}</TableCell>
              <TableCell className="text-right font-mono text-primary tabular">{delta != null && delta > 0 ? `+${number(delta)}` : number(delta)}</TableCell>
            </TableRow>;
          })}</TableBody>
        </Table> : <p className="text-sm text-muted-foreground">{t("各同名决策项的取值未发生变化。")}</p>}
        {changes.length > limit ? <Button variant="link" size="sm" onClick={() => setLimit(limit + 200)}>{t("显示更多")}</Button> : null}
        <p className="text-xs leading-relaxed text-muted-foreground">{t("决策项按变量名自动对齐；新增或移除的项显示为“—”。")}</p>
      </CardContent>
    </Card>
  </div>;
}
