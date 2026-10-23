import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { formatNumber } from "@/format";
import { t } from "@/i18n";
import type { Explanation as ExplanationData, Solve } from "@/features/runs/types";

/** The LLM supplies business labels; every displayed decision value comes from the solver. */
export function Explanation({ explanation, solve }: { explanation: ExplanationData; solve: Solve }) {
  const decisions = explanation.decisions.filter(item => Object.hasOwn(solve.variables, item.variable));
  return <Card className="gap-3 py-4 shadow-none">
    <CardHeader className="gap-2 px-4">
      <CardTitle className="text-sm">{t("方案解读")}</CardTitle>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{explanation.summary}</p>
    </CardHeader>
    <CardContent className="flex min-w-0 flex-col gap-3 px-4">
      {solve.objective != null ? <p className="text-sm font-medium">{explanation.objective_label || t("目标值")}：
        <span className="tabular">{formatNumber(solve.objective)}</span> {explanation.objective_unit}</p> : null}
      {decisions.length ? <div className="overflow-x-auto rounded-lg border">
        <Table className="text-[13px]"><TableHeader><TableRow>
          <TableHead>{t("决策")}</TableHead><TableHead className="text-right">{t("取值")}</TableHead><TableHead>{t("单位")}</TableHead>
        </TableRow></TableHeader><TableBody>{decisions.map(item => <TableRow key={item.variable}>
          <TableCell title={item.variable}>{item.label}</TableCell>
          <TableCell className="text-right font-mono tabular">{formatNumber(solve.variables[item.variable])}</TableCell>
          <TableCell>{item.unit || "—"}</TableCell>
        </TableRow>)}</TableBody></Table>
      </div> : null}
      {explanation.notes.length ? <ul className="list-disc space-y-1 pl-4 text-xs leading-relaxed text-muted-foreground">
        {explanation.notes.map((note, index) => <li key={index}>{note}</li>)}
      </ul> : null}
      <p className="text-xs text-muted-foreground">{t("解读数值来自实际求解结果；完整变量见下方。")}</p>
    </CardContent>
  </Card>;
}
