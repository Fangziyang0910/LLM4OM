import { Sparkles } from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatNumber } from "@/format";
import { t } from "@/i18n";
import type { Explanation as ExplanationData, Solve } from "@/features/runs/types";

/** The LLM supplies business labels; every displayed decision value comes from the solver. */
export function Explanation({ explanation, solve }: { explanation: ExplanationData; solve: Solve }) {
  const decisions = explanation.decisions.filter(item => Object.hasOwn(solve.variables, item.variable));
  return <section aria-label={t("方案解读")} className="flex max-w-3xl min-w-0 flex-col gap-4">
    <div className="flex flex-col gap-2">
      <h3 className="flex items-center gap-1.5 text-xs font-semibold text-primary"><Sparkles className="size-3.5" />{t("方案解读")}</h3>
      <p className="text-[15px] leading-relaxed whitespace-pre-wrap text-foreground">{explanation.summary}</p>
    </div>
    {decisions.length ? <Table className="text-[13px]" containerClassName="rounded-xl border border-border/80">
      <TableHeader className="bg-muted/40"><TableRow>
        <TableHead>{t("关键决策")}</TableHead><TableHead className="w-40 text-right">{t("建议取值")}</TableHead>
      </TableRow></TableHeader>
      <TableBody>{decisions.map(item => {
        const raw = solve.variables[item.variable];
        return <TableRow key={item.variable}>
          <TableCell title={item.variable} className="min-w-32 whitespace-normal [overflow-wrap:anywhere]">{item.label}</TableCell>
          <TableCell className="text-right whitespace-nowrap">
            <span className="font-mono font-semibold tabular">{raw == null ? "—" : formatNumber(raw)}</span>
            {item.unit ? <span className="ml-1 text-xs text-muted-foreground">{item.unit}</span> : null}
          </TableCell>
        </TableRow>;
      })}</TableBody>
    </Table> : null}
    {explanation.notes.length ? <ul className="list-disc space-y-1 pl-5 text-[13px] leading-relaxed text-muted-foreground">
      {explanation.notes.map((note, index) => <li key={index}>{note}</li>)}
    </ul> : null}
  </section>;
}
