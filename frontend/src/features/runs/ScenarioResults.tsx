import { useQueries, useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Columns3 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { client } from "@/features/runs/sdk";
import { StatusBadge } from "@/features/runs/status";
import { hasSolution } from "@/features/runs/workbook";
import { errorText, formatNumber, savedRunState } from "@/format";
import { t } from "@/i18n";
import type { Entry, RunMeta, RunValues, SourceRun } from "@/features/runs/types";

/** Alternative business conditions share a frozen baseline, not a claim that their objective values must agree. */
export function ScenarioResults({ entries, onOpen }: { entries: Entry<RunMeta>[]; onOpen: (run: string | SourceRun) => void }) {
  const source = entries[0].meta.parent;
  const baseline = useQuery({ queryKey: ["source-run", source?.thread_id, source?.checkpoint_id], enabled: !!source,
    queryFn: () => client.threads.getState<RunValues>(source!.thread_id, source!.checkpoint_id), staleTime: Infinity, retry: false });
  const queries = useQueries({ queries: entries.map(entry => ({ queryKey: ["scenario-result", entry.id, entry.updated],
    queryFn: () => client.threads.getState<RunValues>(entry.id), enabled: !["running", "pending"].includes(entry.state), staleTime: Infinity, retry: false })) });
  const previous = baseline.data?.values as RunValues | undefined;
  const records = entries.map((entry, i) => ({ name: entry.meta.scenario?.name || entry.meta.title, id: entry.id,
    instruction: entry.meta.scenario?.instruction, values: queries[i].data?.values as RunValues | undefined,
    state: entry.state, error: queries[i].error }));
  const plans = [...(previous ? [{ name: t("原方案"), id: source!.thread_id, source, instruction: "", values: previous,
    state: savedRunState(previous), error: null }] : []), ...records];
  const solvedPlans = plans.filter(plan => hasSolution(plan.values?.solve));
  const reference = solvedPlans[0]?.values?.solve?.variables;
  const names = [...new Set(solvedPlans.flatMap(plan => Object.keys(plan.values!.solve!.variables)))];
  const changed = reference
    ? names.filter(name => {
      const refVal = Object.hasOwn(reference, name) ? reference[name] : undefined;
      return solvedPlans.some(plan => {
        const vars = plan.values!.solve!.variables;
        const val = Object.hasOwn(vars, name) ? vars[name] : undefined;
        return val !== refVal;
      });
    })
    : [];
  const shown = (changed.length ? changed : names).slice(0, 20);
  return <div className="h-full overflow-y-auto"><div className="mx-auto flex max-w-6xl min-w-0 flex-col gap-5 p-4 sm:p-6">
    <header className="animate-fade-up flex flex-col gap-2">
      <span className="inline-flex w-fit items-center gap-1.5 rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-medium text-primary">
        <Columns3 className="size-3.5" />{t("多场景方案对比")}
      </span>
      <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{t("不同业务假设下的方案对比")}</h1>
      <p className="text-sm text-muted-foreground">{t("以原方案为基准，独立计算并对比各假设场景下的最优结果与关键决策变化。")}</p>
    </header>
    {baseline.error ? <p role="alert" className="text-sm text-muted-foreground">{t("原方案暂不可读，已生成的各场景结果仍可正常查看。")}</p> : null}
    <Table containerClassName="rounded-2xl border border-border/80 bg-card shadow-xs"><TableHeader className="bg-muted/40"><TableRow><TableHead>{t("业务场景")}</TableHead><TableHead>{t("假设条件变化")}</TableHead>
      <TableHead>{t("状态")}</TableHead><TableHead className="text-right">{t("最优目标值")}</TableHead><TableHead /></TableRow></TableHeader>
      <TableBody>{plans.map(plan => <TableRow key={plan.id} className="hover:bg-muted/30">
        <TableCell className="min-w-28 max-w-64 font-medium whitespace-normal [overflow-wrap:anywhere]">{plan.name}</TableCell>
        <TableCell className="min-w-48 max-w-96 text-xs leading-5 text-muted-foreground whitespace-normal">{plan.instruction || t("原始基准条件")}</TableCell>
        <TableCell><StatusBadge status={plan.state} />{plan.error ? <p role="alert" className="mt-1 text-xs text-destructive">{errorText(plan.error)}</p> : null}</TableCell>
        <TableCell className="text-right">{(() => {
          const pareto = plan.values?.solve?.pareto?.solutions.length ? plan.values.solve.pareto : null;
          if (pareto) {
            const knee = pareto.solutions.find(item => item.knee) ?? pareto.solutions[0];
            return <>
              <span className="font-mono font-semibold tabular">{t("{count} 个 Pareto 解", { count: pareto.total })}</span>
              {knee ? <p className="mt-1 text-xs text-muted-foreground tabular">{pareto.objectives.map((obj, idx) =>
                `${obj.name} = ${knee.objectives[idx] == null ? "—" : formatNumber(knee.objectives[idx]!)}`).join(" · ")}</p> : null}
            </>;
          }
          return <>
            <span className="font-mono font-semibold tabular">{hasSolution(plan.values?.solve) && plan.values?.solve?.objective != null ? formatNumber(plan.values.solve.objective) : ["running", "pending"].includes(plan.state) ? "…" : "—"}</span>
            {plan.values?.explanation ? <p className="mt-1 text-xs text-muted-foreground">{plan.values.explanation.objective_label} {plan.values.explanation.objective_unit}</p> : null}
          </>;
        })()}</TableCell>
        <TableCell className="text-right"><Button variant="ghost" size="icon-sm" aria-label={t("打开方案：{name}", { name: plan.name })} onClick={() => onOpen("source" in plan && plan.source ? plan.source : plan.id)}><ArrowUpRight /></Button></TableCell>
      </TableRow>)}</TableBody>
    </Table>
    {entries.some(entry => ["running", "pending"].includes(entry.state)) ? <p role="status" className="flex items-center gap-2 text-sm text-muted-foreground"><Spinner />{t("部分场景正在计算中，完成后将自动更新…")}</p> : null}
    {shown.length ? <section className="flex flex-col gap-3"><h2 className="text-sm font-semibold">{t("关键决策横向对比")}</h2>
      <Table containerClassName="rounded-2xl border border-border/80 bg-card shadow-xs"><TableHeader className="bg-muted/40"><TableRow>
        <TableHead>{t("决策项")}</TableHead>{plans.map(plan => <TableHead key={plan.id} className="min-w-28 max-w-64 text-right whitespace-normal [overflow-wrap:anywhere]">{plan.name}</TableHead>)}
      </TableRow></TableHeader><TableBody>{shown.map(name => <TableRow key={name}><TableCell className="font-mono text-xs">{name}</TableCell>
        {plans.map(plan => {
          const variables = plan.values?.solve?.variables;
          const raw = hasSolution(plan.values?.solve) && variables && Object.hasOwn(variables, name) ? variables[name] : null;
          return <TableCell key={plan.id} className="text-right font-mono tabular">
            {raw == null ? "—" : formatNumber(raw)}</TableCell>;
        })}
      </TableRow>)}</TableBody></Table>
      <p className="text-xs leading-5 text-muted-foreground">{t("优先展示发生变化的前 20 项决策，点击右上角箭头可进入单场景查看全部明细。")}</p>
    </section> : null}
  </div></div>;
}
