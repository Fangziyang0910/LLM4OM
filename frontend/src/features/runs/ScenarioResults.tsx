import { useQueries, useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Columns3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { client } from "@/features/runs/sdk";
import { StatusBadge } from "@/features/runs/status";
import { hasSolution } from "@/features/runs/workbook";
import { errorText, formatNumber } from "@/format";
import { t } from "@/i18n";
import type { Entry, RunMeta, RunValues } from "@/features/runs/types";

/** Alternative business conditions share a frozen baseline, not a claim that their objective values must agree. */
export function ScenarioResults({ entries, onOpen }: { entries: Entry<RunMeta>[]; onOpen: (id: string) => void }) {
  const source = entries[0].meta.parent;
  const baseline = useQuery({ queryKey: ["source-run", source?.thread_id, source?.checkpoint_id], enabled: !!source,
    queryFn: () => client.threads.getState<RunValues>(source!.thread_id, source!.checkpoint_id), staleTime: Infinity, retry: false });
  const queries = useQueries({ queries: entries.map(entry => ({ queryKey: ["scenario-result", entry.id, entry.updated],
    queryFn: () => client.threads.getState<RunValues>(entry.id), enabled: entry.state !== "running", staleTime: Infinity, retry: false })) });
  const previous = baseline.data?.values as RunValues | undefined;
  const records = entries.map((entry, i) => ({ name: entry.meta.scenario?.name || entry.meta.title, id: entry.id,
    instruction: entry.meta.scenario?.instruction, values: queries[i].data?.values as RunValues | undefined,
    state: entry.state, error: queries[i].error }));
  const plans = [...(previous ? [{ name: t("原方案"), id: source!.thread_id, instruction: "", values: previous,
    state: previous.failure ? "failed" : previous.solve?.status ?? "unknown", error: null }] : []), ...records];
  const names = [...new Set(plans.flatMap(plan => hasSolution(plan.values?.solve) ? Object.keys(plan.values!.solve!.variables) : []))];
  const changed = names.filter(name => plans.some(plan => plan.values?.solve?.variables[name] !== previous?.solve?.variables[name]));
  const shown = (changed.length ? changed : names).slice(0, 20);
  return <div className="h-full overflow-y-auto"><div className="flex min-w-0 flex-col gap-5 p-4 sm:p-6">
    <header className="flex flex-col gap-2"><span className="flex items-center gap-2 text-xs font-medium text-muted-foreground"><Columns3 className="size-4" />{t("业务场景对比")}</span>
      <h1 className="text-xl font-semibold">{t("比较不同条件下的实际方案")}</h1>
      <p className="text-sm text-muted-foreground">{t("各场景独立重新建模，原方案作为固定基准。点击场景可查看完整题面、模型、数据和求解结果。")}</p>
    </header>
    {baseline.error ? <p role="alert" className="text-sm text-muted-foreground">{t("原方案暂不可读，已生成的场景仍可查看。")}</p> : null}
      <Table containerClassName="rounded-xl border bg-card"><TableHeader className="bg-muted/50"><TableRow><TableHead>{t("业务场景")}</TableHead><TableHead>{t("调整要求")}</TableHead>
        <TableHead>{t("结果")}</TableHead><TableHead className="text-right">{t("目标值")}</TableHead><TableHead /></TableRow></TableHeader>
        <TableBody>{plans.map(plan => <TableRow key={plan.id}>
          <TableCell className="min-w-28 max-w-64 font-medium whitespace-normal [overflow-wrap:anywhere]">{plan.name}</TableCell>
          <TableCell className="min-w-48 max-w-96 text-xs leading-5 whitespace-normal">{plan.instruction || t("原始条件")}</TableCell>
          <TableCell><StatusBadge status={plan.state} />{plan.error ? <p role="alert" className="mt-1 text-xs text-destructive">{errorText(plan.error)}</p> : null}</TableCell>
          <TableCell className="text-right"><span className="font-mono tabular">{hasSolution(plan.values?.solve) && plan.values?.solve?.objective != null ? formatNumber(plan.values.solve.objective) : plan.state === "running" ? "…" : "—"}</span>
            {plan.values?.explanation ? <p className="mt-1 text-xs text-muted-foreground">{plan.values.explanation.objective_label} {plan.values.explanation.objective_unit}</p> : null}</TableCell>
          <TableCell><Button variant="ghost" size="icon-sm" aria-label={t("打开方案：{name}", { name: plan.name })} onClick={() => onOpen(plan.id)}><ArrowUpRight /></Button></TableCell>
        </TableRow>)}</TableBody>
      </Table>
    {entries.some(entry => entry.state === "running") ? <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner />{t("场景正在计算，结果会自动更新。")}</p> : null}
    {shown.length ? <section className="flex flex-col gap-3"><h2 className="text-sm font-semibold">{t("关键决策对比")}</h2>
      <Table containerClassName="rounded-xl border bg-card"><TableHeader className="bg-muted/50"><TableRow>
        <TableHead>{t("决策变量")}</TableHead>{plans.map(plan => <TableHead key={plan.id} className="min-w-28 max-w-64 text-right whitespace-normal [overflow-wrap:anywhere]">{plan.name}</TableHead>)}
      </TableRow></TableHeader><TableBody>{shown.map(name => <TableRow key={name}><TableCell className="font-mono text-xs">{name}</TableCell>
        {plans.map(plan => { const variables = plan.values?.solve?.variables; return <TableCell key={plan.id} className="text-right font-mono tabular">
          {hasSolution(plan.values?.solve) && variables && Object.hasOwn(variables, name) ? formatNumber(variables[name]) : "—"}</TableCell>; })}
      </TableRow>)}</TableBody></Table>
      <p className="text-xs leading-5 text-muted-foreground">{t("优先显示发生变化的前 20 个变量，完整结果可打开各方案查看。变量按原名称对应，缺失值显示为 —，不会当作零值。")}</p>
    </section> : null}
    <p className="text-xs leading-5 text-muted-foreground">{t("目标含义与单位相同时，数值才可直接比较。")}</p>
  </div></div>;
}
