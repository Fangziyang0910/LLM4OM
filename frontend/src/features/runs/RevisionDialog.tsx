import { useState } from "react";
import { ArrowRight } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { errorText } from "@/format";
import { t } from "@/i18n";

export function RevisionDialog({ onClose, onRevise }: { onClose: () => void; onRevise: (instruction: string) => Promise<void> }) {
  const [instruction, setInstruction] = useState("");
  const [busy, setBusy] = useState(false);
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>{t("调整条件")}</DialogTitle>
        <DialogDescription>{t("沿用原运行的方法、预设模型和附件，整理新题面后重新建模。原方案保留，可查看方案变化。")}</DialogDescription>
      </DialogHeader>
      <form className="flex min-w-0 flex-col gap-4" onSubmit={async event => {
        event.preventDefault();
        if (!instruction.trim() || busy) return;
        setBusy(true);
        try { await onRevise(instruction.trim()); onClose(); }
        catch (error) { toast.error(errorText(error)); }
        finally { setBusy(false); }
      }}>
        <div className="flex flex-col gap-2">
          <Label htmlFor="revision-instruction">{t("要调整什么？")}</Label>
          <Textarea id="revision-instruction" value={instruction} disabled={busy}
            onChange={event => setInstruction(event.target.value)} className="min-h-32 text-base sm:text-sm"
            placeholder={t("例如：B 至少生产 3 件，其他条件保持不变。")}/>
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={onClose}>{t("取消")}</Button>
          <Button type="submit" disabled={!instruction.trim() || busy}>{busy ? <Spinner /> : <ArrowRight />}{t("生成新方案")}</Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>;
}
