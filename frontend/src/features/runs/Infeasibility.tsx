import { ArrowRight, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { t } from "@/i18n";
import type { Infeasibility as InfeasibilityData } from "@/features/runs/types";

export function Infeasibility({ explanation, onAdjust }: {
  explanation: InfeasibilityData; onAdjust?: (instruction: string) => void;
}) {
  return <Card className="gap-4 rounded-2xl border-destructive/25 bg-gradient-to-br from-destructive/[0.04] via-card to-card py-5 shadow-xs">
    <CardHeader className="gap-2.5 px-5">
      <CardTitle className="flex items-center gap-2 text-sm font-semibold text-destructive">
        <span className="grid size-6 place-items-center rounded-lg bg-destructive/10"><TriangleAlert className="size-3.5" /></span>
        {t("为什么当前条件无解")}
      </CardTitle>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{explanation.summary}</p>
    </CardHeader>
    <CardContent className="flex min-w-0 flex-col gap-4 px-5">
      {explanation.conflicts.map((conflict, index) => <div key={index} className="flex flex-col gap-2 rounded-xl border border-destructive/20 bg-background/80 p-3.5">
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{conflict.explanation}</p>
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer hover:text-foreground">{t("查看对应数学约束")}</summary>
          <ul className="mt-2 space-y-1 rounded-lg bg-muted/40 p-2.5 font-mono break-all">{conflict.constraints.map(item => <li key={item}>{item}</li>)}</ul>
        </details>
      </div>)}
      {explanation.adjustments.length ? <div className="flex flex-col gap-2.5 border-t border-border/70 pt-4">
        <h4 className="text-sm font-semibold">{t("推荐尝试的调整方向")}</h4>
        <p className="text-xs leading-relaxed text-muted-foreground">{t("建议尚未验证。选择后可编辑调整要求，再重新建模验证。")}</p>
        <div className="grid gap-2.5 sm:grid-cols-2">
          {explanation.adjustments.map((item, index) => <div key={index} className="flex min-w-0 flex-col justify-between gap-3 rounded-xl border border-border/80 bg-card p-3.5 shadow-2xs transition-colors hover:border-primary/35">
            <div className="space-y-1">
              <p className="text-sm font-medium">{item.title}</p>
              <p className="text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">{item.instruction}</p>
            </div>
            <Button variant="secondary" size="sm" className="self-start rounded-lg" disabled={!onAdjust} onClick={() => onAdjust?.(item.instruction)}>
              {t("尝试这个调整")}<ArrowRight />
            </Button>
          </div>)}
        </div>
      </div> : null}
    </CardContent>
  </Card>;
}
