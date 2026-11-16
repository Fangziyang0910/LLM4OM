import { useState } from "react";
import { Columns3, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { errorText } from "@/format";
import { t } from "@/i18n";

export function ScenariosDialog({ onClose, onStart }: {
  onClose: () => void; onStart: (scenarios: { name: string; instruction: string }[]) => Promise<void>;
}) {
  const [scenarios, setScenarios] = useState([1, 2].map(number => ({ name: t("场景 {number}", { number }), instruction: "" })));
  const [busy, setBusy] = useState(false);
  const set = (index: number, change: Partial<typeof scenarios[number]>) => setScenarios(items => items.map((item, i) => i === index ? { ...item, ...change } : item));
  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose(); }}>
    <DialogContent className="flex max-h-[90dvh] flex-col rounded-2xl sm:max-w-2xl">
      <DialogHeader><DialogTitle>{t("多场景对比分析")}</DialogTitle>
        <DialogDescription>{t("基于当前方案衍生多个假设场景（如旺季需求增长、预算收紧、产能扩充），并行计算并横向对比各方案结果。")}</DialogDescription></DialogHeader>
      <form className="flex min-h-0 flex-col gap-4" onSubmit={async event => {
        event.preventDefault();
        if (busy || scenarios.some(item => !item.name.trim() || !item.instruction.trim())) return;
        setBusy(true);
        try { await onStart(scenarios.map(item => ({ name: item.name.trim(), instruction: item.instruction.trim() }))); onClose(); }
        catch (error) { toast.error(errorText(error)); }
        finally { setBusy(false); }
      }}>
        <div className="flex min-h-0 flex-col gap-3 overflow-y-auto pr-1">
          {scenarios.map((scenario, index) => <fieldset key={index} disabled={busy} className="flex flex-col gap-2 rounded-xl border border-border/80 bg-muted/15 p-3.5">
            <div className="flex items-center gap-2"><Input aria-label={t("场景 {number} 名称", { number: index + 1 })} value={scenario.name} maxLength={100}
              onChange={event => set(index, { name: event.target.value })} className="rounded-lg bg-background font-medium" />
              <Button type="button" variant="ghost" size="icon-sm" aria-label={t("移除场景 {number}", { number: index + 1 })}
                disabled={busy || scenarios.length <= 2} onClick={() => setScenarios(items => items.filter((_, i) => i !== index))}><X /></Button></div>
            <Label htmlFor={`scenario-${index}`} className="sr-only">{t("场景 {number} 调整要求", { number: index + 1 })}</Label>
            <Textarea id={`scenario-${index}`} value={scenario.instruction} onChange={event => set(index, { instruction: event.target.value })}
              className="rounded-lg bg-background"
              placeholder={t("例如：假设订单总需求上浮 20%，其他条件保持不变。")} />
          </fieldset>)}
          <Button type="button" variant="outline" className="self-start rounded-lg" disabled={busy || scenarios.length >= 6}
            onClick={() => setScenarios(items => {
              const names = new Set(items.map(item => item.name.trim()));
              let number = 1;
              while (names.has(t("场景 {number}", { number }))) number++;
              return [...items, { name: t("场景 {number}", { number }), instruction: "" }];
            })}><Plus />{t("添加场景")}</Button>
        </div>
        <DialogFooter><Button type="button" variant="outline" disabled={busy} onClick={onClose}>{t("取消")}</Button>
          <Button type="submit" disabled={busy || scenarios.some(item => !item.name.trim() || !item.instruction.trim())}>{busy ? <Spinner /> : <Columns3 />}{t("计算并对比")}</Button></DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
