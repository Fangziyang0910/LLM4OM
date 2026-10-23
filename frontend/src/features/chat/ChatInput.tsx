import { useEffect, useImperativeHandle, useRef, type ReactNode, type Ref } from "react";
import { ArrowUp, Settings2, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { t } from "@/i18n";
import type { Preset } from "@/types";

/** Both conversations use the same keyboard, composition and model-selection behavior. */
export function ChatInput({ value, onChange, disabled, loading, stopping = false, onSend, onStop, presets, presetId, onPreset, openPresets,
  children, inputRef, label, placeholder }: {
  value: string; onChange: (value: string) => void; disabled: boolean; loading: boolean;
  stopping?: boolean;
  onSend: () => void; onStop: () => void; presets: Preset[]; presetId?: string; onPreset: (id: string) => void;
  openPresets: () => void; children?: ReactNode; inputRef?: Ref<HTMLTextAreaElement>; label: string; placeholder?: string;
}) {
  const field = useRef<HTMLTextAreaElement>(null);
  const responding = useRef(loading);
  useImperativeHandle(inputRef, () => field.current!, []);
  useEffect(() => {
    if (responding.current && !loading && matchMedia("(pointer: fine)").matches && document.activeElement === document.body)
      field.current?.focus({ preventScroll: true });
    responding.current = loading;
  }, [loading]);
  return <form className="@container mx-auto w-full max-w-3xl shrink-0 rounded-2xl border bg-card p-3 shadow-sm focus-within:ring-1 focus-within:ring-primary/30"
    onSubmit={event => { event.preventDefault(); if (!disabled && value.trim()) onSend(); }}>
    <Textarea ref={field} aria-label={label} placeholder={loading ? t("正在回复，可先写下一条消息……") : placeholder ?? t("说说你的想法，或回答上一个问题……")} value={value} disabled={disabled && !loading}
      onChange={event => onChange(event.target.value)} className="max-h-36 min-h-16 resize-none border-0 bg-transparent px-1 py-1 text-base shadow-none field-sizing-content focus-visible:ring-0 sm:text-sm dark:bg-transparent"
      onKeyDown={event => {
        if (event.key === "Enter" && (!event.shiftKey || event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
          event.preventDefault(); if (!disabled) onSend();
        }
      }} />
    <div className="mt-2 flex items-center gap-1">
      <Select value={presetId ?? ""} onValueChange={onPreset} disabled={disabled}>
        <SelectTrigger aria-label={t("对话模型")} title={presets.find(item => item.id === presetId)?.name || presets.find(item => item.id === presetId)?.model}
          className="h-8! min-w-0 w-32 border-0 bg-transparent px-2 text-xs shadow-none @lg:w-44"><SelectValue placeholder={t("选择预设模型")} /></SelectTrigger>
        <SelectContent>{presets.map(item => <SelectItem key={item.id} value={item.id}>{item.name || item.model}</SelectItem>)}</SelectContent>
      </Select>
      <Button type="button" variant="ghost" size="icon-sm" aria-label={t("管理预设模型")} title={t("管理预设模型")} onClick={openPresets}><Settings2 /></Button>
      {children}
      {loading || stopping ? <Button type="button" variant="secondary" size="icon-sm" className="ml-auto rounded-full" aria-label={t("停止")}
        title={stopping ? t("正在停止……") : t("停止")} disabled={stopping} onClick={onStop}><Square className="size-3 fill-current" /></Button>
        : <Button type="submit" size="icon-sm" className="ml-auto rounded-full" aria-label={t("发送")} disabled={disabled || !value.trim()}><ArrowUp /></Button>}
    </div>
  </form>;
}
