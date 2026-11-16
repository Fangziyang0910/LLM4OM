import { Sparkles } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatNumber } from "@/format";
import { t } from "@/i18n";
import type { Explanation as ExplanationData, Solve } from "@/features/runs/types";

/** The LLM supplies business labels; every displayed decision value comes from the solver. */
export function Explanation({ explanation, solve }: { explanation: ExplanationData; solve: Solve }) {
  const decisions = explanation.decisions.filter(item => Object.hasOwn(solve.variables, item.variable));
  return <Card className="gap-4 rounded-2xl border-primary/20 bg-gradient-to-br from-primary/[0.04] via-card to-card py-5 shadow-xs">
    <CardHeader className="gap-2.5 px-5">
      <CardTitle className="flex items-center gap-2 text-sm font-semibold text-primary">
        <span className="grid size-6 place-items-center rounded-lg bg-primary/10"><Sparkles className="size-3.5" /></span>
        {t("方案解读")}
      </CardTitle>
      <p className="text-sm leading-relaxed text-foreground/95 whitespace-pre-wrap">{explanation.summary}</p>
    </CardHeader>
    <CardContent className="flex min-w-0 flex-col gap-3.5 px-5">
      {decisions.length ? <Table className="text-[13px]" containerClassName="rounded-xl border border-border/80 bg-background/80">
        <TableHeader className="bg-muted/40"><TableRow>
          <TableHead>{t("关键决策")}</TableHead><TableHead className="text-right">{t("建议取值")}</TableHead><TableHead>{t("单位")}</TableHead>
        </TableRow></TableHeader>
        <TableBody>{decisions.map(item => <TableRow key={item.variable}>
          <TableCell title={item.variable} className="min-w-32 font-medium whitespace-normal [overflow-wrap:anywhere]">{item.label}</TableCell>
          <TableCell className="text-right font-mono font-semibold tabular">{formatNumber(solve.variables[item.variable])}</TableCell>
          <TableCell className="text-muted-foreground">{item.unit || "—"}</TableCell>
        </TableRow>)}</TableBody>
      </Table> : null}
      {explanation.notes.length ? <ul className="list-disc space-y-1 rounded-xl bg-muted/30 px-4 py-2.5 pl-7 text-xs leading-relaxed text-muted-foreground">
        {explanation.notes.map((note, index) => <li key={index}>{note}</li>)}
      </ul> : null}
    </CardContent>
  </Card>;
}
