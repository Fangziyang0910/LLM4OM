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
export function ScenarioComparison({ source, values }: { source: SourceRun; values: RunValues }) {
  const query = useQuery({ queryKey: ["source-run", source.thread_id, source.checkpoint_id],
    queryFn: () => client.threads.getState<RunValues>(source.thread_id, source.checkpoint_id), staleTime: Infinity, retry: false });
  const [limit, setLimit] = useState(200);
  if (query.error) return <Alert><TriangleAlert /><AlertDescription>
    {t("无法读取原方案，可能已被删除。当前方案仍可在“解”中查看。")}
    <span className="text-xs">{errorText(query.error)}</span>
  </AlertDescription></Alert>;
  if (!query.data) return <div className="flex items-center gap-2 p-4 text-sm text-muted-foreground"><Spinner />{t("正在读取原方案……")}</div>;

  const before = query.data.values as RunValues;
  const changes = variableChanges(before.solve?.variables ?? {}, values.solve?.variables ?? {});
  const labels = new Map([...(before.explanation?.decisions ?? []), ...(values.explanation?.decisions ?? [])].map(item => [item.variable, item.label]));
  const previous = before.solve?.objective, current = values.solve?.objective;
  const difference = previous != null && current != null ? current - previous : null;
  const number = (value: number | undefined | null) => value == null ? "—" : formatNumber(value);
  const scenarios: [string, RunValues][] = [[t("原方案"), before], [t("新方案"), values]];

  return <div className="flex min-w-0 flex-col gap-4">
    <Card className="gap-3 py-4 shadow-none">
      <CardHeader className="flex flex-wrap items-center justify-between gap-2 px-4">
        <CardTitle className="text-sm">{t("方案对比")}</CardTitle>
        <Button variant="outline" size="sm" asChild><a href={`/run/${source.thread_id}`}>{t("打开原运行")}<ArrowUpRight /></a></Button>
      </CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-4 px-4">
        {values.revision ? <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">
          <span className="font-medium">{t("调整要求")}：</span>{values.revision.instruction}</p> : null}
        <div className="grid gap-3 sm:grid-cols-3">
          {scenarios.map(([label, result]) => {
            return <div key={label} className="flex min-w-0 flex-col gap-2 rounded-lg border p-3">
              <span className="text-xs text-muted-foreground">{label}</span>
              <StatusBadge status={result.failure ? "failed" : result.solve?.status ?? "unknown"} />
              <span className="text-xl font-semibold tabular">{number(result.solve?.objective)}</span>
            </div>;
          })}
          <div className="flex flex-col gap-2 rounded-lg border p-3">
            <span className="text-xs text-muted-foreground">{t("目标值差（新 − 原）")}</span>
            <span className="text-xl font-semibold tabular">{number(difference)}</span>
            <span className="text-xs leading-relaxed text-muted-foreground">{t("目标含义与单位相同时，数值才可直接比较。")}</span>
          </div>
        </div>
        <details className="min-w-0 rounded-lg border p-3">
          <summary className="cursor-pointer text-sm font-medium">{t("查看题面变化")}</summary>
          <div className="mt-3 min-w-0"><Diff before={before.description ?? ""} after={values.description ?? ""} /></div>
        </details>
      </CardContent>
    </Card>
    <Card className="gap-3 py-4 shadow-none">
      <CardHeader className="px-4"><CardTitle className="text-sm">{t("决策变化（{count} 项）", { count: changes.length })}</CardTitle></CardHeader>
      <CardContent className="flex min-w-0 flex-col gap-3 px-4">
        {changes.length ? <div className="overflow-x-auto rounded-lg border"><Table className="text-[13px]">
          <TableHeader><TableRow><TableHead>{t("决策")}</TableHead><TableHead className="text-right">{t("原值")}</TableHead>
            <TableHead className="text-right">{t("新值")}</TableHead><TableHead className="text-right">{t("差值")}</TableHead>
          </TableRow></TableHeader>
          <TableBody>{changes.slice(0, limit).map(item => <TableRow key={item.name}>
            <TableCell className="max-w-64 break-all"><span>{labels.get(item.name) ?? item.name}</span>
              {labels.has(item.name) ? <span className="mt-0.5 block text-xs text-muted-foreground">{item.name}</span> : null}</TableCell>
            <TableCell className="text-right font-mono tabular">{number(item.before)}</TableCell>
            <TableCell className="text-right font-mono tabular">{number(item.after)}</TableCell>
            <TableCell className="text-right font-mono tabular">{number(item.before != null && item.after != null ? item.after - item.before : null)}</TableCell>
          </TableRow>)}</TableBody>
        </Table></div> : <p className="text-sm text-muted-foreground">{t("没有同名决策变量的取值变化。")}</p>}
        {changes.length > limit ? <Button variant="link" size="sm" onClick={() => setLimit(limit + 200)}>{t("显示更多")}</Button> : null}
        <p className="text-xs leading-relaxed text-muted-foreground">{t("变量按名称对应；新增或移除的变量显示为“—”，不当作零值。")}</p>
      </CardContent>
    </Card>
  </div>;
}
