import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { t } from "@/i18n";
import type { Infeasibility as InfeasibilityData } from "@/features/runs/types";

export function Infeasibility({ explanation, onAdjust }: {
  explanation: InfeasibilityData; onAdjust?: (instruction: string) => void;
}) {
  return <Card className="gap-3 border-destructive/30 py-4 shadow-none">
    <CardHeader className="gap-2 px-4">
      <CardTitle className="text-sm">{t("为什么无解")}</CardTitle>
      <p className="text-sm leading-relaxed whitespace-pre-wrap">{explanation.summary}</p>
    </CardHeader>
    <CardContent className="flex min-w-0 flex-col gap-4 px-4">
      {explanation.conflicts.map((conflict, index) => <div key={index} className="flex flex-col gap-1.5">
        <p className="text-sm leading-relaxed whitespace-pre-wrap">{conflict.explanation}</p>
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer">{t("查看对应约束")}</summary>
          <ul className="mt-2 space-y-1 font-mono break-all">{conflict.constraints.map(item => <li key={item}>{item}</li>)}</ul>
        </details>
      </div>)}
      {explanation.adjustments.length ? <div className="flex flex-col gap-2 border-t pt-3">
        <h4 className="text-sm font-medium">{t("可以尝试的调整")}</h4>
        <p className="text-xs leading-relaxed text-muted-foreground">{t("建议尚未验证。选择后可编辑调整要求，再重新建模验证。")}</p>
        {explanation.adjustments.map((item, index) => <div key={index} className="flex min-w-0 flex-col gap-2 rounded-lg border p-3">
          <p className="text-sm font-medium">{item.title}</p>
          <p className="text-xs leading-relaxed whitespace-pre-wrap text-muted-foreground">{item.instruction}</p>
          <Button variant="outline" size="sm" className="self-start" disabled={!onAdjust} onClick={() => onAdjust?.(item.instruction)}>
            {t("尝试这个调整")}<ArrowRight />
          </Button>
        </div>)}
      </div> : null}
    </CardContent>
  </Card>;
}
