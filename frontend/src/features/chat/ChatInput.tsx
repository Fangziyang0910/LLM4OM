import { useEffect, useImperativeHandle, useId, useRef, useState, type ReactNode, type Ref } from "react";
import { ArrowUp, Brain, ChevronDown, Cpu, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";
import type { Preset } from "@/types";

/**
 * An on/off tool in the input toolbar: muted when off, tinted when on. A narrow input beside a desktop panel shows its
 * icon alone; on a phone the tools fold into their own row, where the label fits.
 */
export function ToolToggle({ label, icon, pressed, disabled, title, onPressedChange }: {
  label: string; icon: ReactNode; pressed: boolean; disabled?: boolean; title?: string; onPressedChange: (pressed: boolean) => void;
}) {
  return <Button type="button" variant="ghost" size="sm" aria-label={label} aria-pressed={pressed} title={title} disabled={disabled}
    onClick={() => onPressedChange(!pressed)}
    className={cn("h-8 shrink-0 gap-1.5 rounded-lg px-2 text-xs font-normal text-muted-foreground",
      pressed && "bg-primary/10 font-medium text-primary hover:bg-primary/15 hover:text-primary")}>
    {icon}<span className="md:@max-lg:hidden">{label}</span></Button>;
}

/** Both conversations use the same keyboard, composition and model-selection behavior. */
export function ChatInput({ value, onChange, disabled, loading, sendingDisabled = false, stopping = false, onSend, onStop, presets, presetId, onPreset, openPresets,
  attachment, searchActive, children, inputRef, label, placeholder, thinking, onThinking, onFiles }: {
  value: string; onChange: (value: string) => void; disabled: boolean; loading: boolean;
  stopping?: boolean;
  sendingDisabled?: boolean;
  onSend: () => void; onStop: () => void; presets: Preset[]; presetId?: string; onPreset: (id: string) => void;
  openPresets: () => void; attachment?: ReactNode; searchActive?: boolean; children?: ReactNode; inputRef?: Ref<HTMLTextAreaElement>; label: string; placeholder?: string;
  thinking?: boolean | null; onThinking: (enabled: boolean) => void;
  /** Files pasted into the message; without it, a paste only inserts text. */
  onFiles?: (files: FileList) => void;
}) {
  const [toolsOpen, setToolsOpen] = useState(false);
  const toolsId = useId();
  const field = useRef<HTMLTextAreaElement>(null);
  const responding = useRef(loading);
  const preset = presets.find(item => item.id === presetId);
  const thinkingType = (preset?.extra_body.thinking as { type?: string } | undefined)?.type;
  const thinkingOn = thinking ?? (thinkingType === "enabled" || (thinkingType !== "disabled" && /reasoner/i.test(preset?.model ?? "")));
  useImperativeHandle(inputRef, () => field.current!, []);
  useEffect(() => {
    if (responding.current && !loading && matchMedia("(pointer: fine)").matches && document.activeElement === document.body)
      field.current?.focus({ preventScroll: true });
    responding.current = loading;
  }, [loading]);
  return <form className="@container mx-auto w-full min-w-0 max-w-[46rem] shrink-0"
    onSubmit={event => { event.preventDefault(); if (!disabled && !sendingDisabled && value.trim()) onSend(); }}>
    <div className="rounded-2xl border border-border/80 bg-card/95 p-2.5 shadow-sm backdrop-blur-sm transition-all duration-200 focus-within:border-primary/45 focus-within:ring-4 focus-within:ring-primary/10 sm:p-3">
      <Textarea ref={field} aria-label={label} placeholder={loading ? t("正在生成回复，可先输入下一条消息…") : placeholder ?? t("说说你的想法，或补充更多条件…")} value={value} disabled={disabled && !loading}
        onChange={event => onChange(event.target.value)}
        onPaste={event => { if (onFiles && event.clipboardData.files.length) { event.preventDefault(); onFiles(event.clipboardData.files); } }} className="max-h-36 min-h-14 resize-none border-0 bg-transparent px-1.5 py-1 text-base leading-relaxed shadow-none field-sizing-content focus-visible:border-0 focus-visible:ring-0 sm:text-sm dark:bg-transparent"
        onKeyDown={event => {
          if (event.key === "Enter" && (!event.shiftKey || event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) {
            event.preventDefault(); if (!disabled && !sendingDisabled && value.trim()) onSend();
          }
        }} />
      <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-1.5 border-t border-border/50 pt-2">
        {attachment}
        <Button type="button" size="sm" variant="ghost" className="h-8 gap-1 px-2 text-xs md:hidden"
          aria-expanded={toolsOpen} aria-controls={toolsId} onClick={() => setToolsOpen(!toolsOpen)}>
          {t("更多工具")}<ChevronDown className={cn("size-3", toolsOpen && "rotate-180")} />
        </Button>
        {searchActive && !toolsOpen ? <span className="text-xs text-primary md:hidden">{t("联网已开启")}</span> : null}
        <div id={toolsId} className={cn("order-last min-w-0 basis-full flex-wrap items-center gap-1 rounded-lg bg-muted/30 p-1 md:order-none md:flex md:flex-1 md:basis-auto md:bg-transparent md:p-0",
          toolsOpen ? "flex" : "hidden")}>
            {presets.length ? <Select value={presetId ?? ""} onValueChange={id => { if (id) onPreset(id); }} disabled={disabled}>
              <SelectTrigger aria-label={t("对话模型")} title={preset?.name || preset?.model}
                className="h-8! w-32 min-w-0 overflow-hidden rounded-lg border-0 bg-muted/45 px-2.5 text-xs font-medium shadow-none hover:bg-muted @lg:w-44 [&_[data-slot=select-value]]:min-w-0 [&_[data-slot=select-value]]:overflow-hidden">
                <SelectValue placeholder={t("选择 AI 模型")} />
              </SelectTrigger>
              <SelectContent>{presets.map(item => <SelectItem key={item.id} value={item.id}>{item.name || item.model}</SelectItem>)}</SelectContent>
            </Select> : <Button type="button" variant="outline" size="sm" className="h-8 gap-1.5 rounded-lg text-xs" onClick={openPresets}>
              <Cpu className="size-3.5" />{t("配置 AI 模型")}
            </Button>}
            {preset?.provider === "deepseek" ? <ToolToggle label={t("深度思考")} icon={<Brain />} pressed={thinkingOn} disabled={disabled}
              title={t("开启深度推理以处理复杂逻辑问题")} onPressedChange={onThinking} /> : null}
            {children}
        </div>
        <div className="ml-auto flex shrink-0 items-center">
          {loading || stopping ? <Button type="button" variant="secondary" size="icon-sm" className="rounded-full" aria-label={t("停止")}
            title={stopping ? t("正在停止…") : t("停止")} disabled={stopping} onClick={onStop}><Square className="size-3 fill-current" /></Button>
            : <Button type="submit" size="icon-sm" className="rounded-full shadow-xs" aria-label={t("发送")} title={t("发送")} disabled={disabled || sendingDisabled || !value.trim()}><ArrowUp /></Button>}
        </div>
      </div>
    </div>
  </form>;
}
