import { type ReactNode, useEffect, useRef, useState } from "react";
import { BookOpen, Eye, FileSpreadsheet, Paperclip, PenLine, Trash2, Upload, X } from "lucide-react";
import { Markdown } from "@/components/Content";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";
import { parseCsv } from "@/lib/csv";
import { DATA_FILE_ACCEPT } from "./files";
import { DataEditor } from "./DataEditor";

function dataRowCount(name: string, content: string): number {
  if (/\.(csv|tsv)$/i.test(name)) {
    try { return parseCsv(content, /\.tsv$/i.test(name) ? "\t" : ",").length; }
    catch { /* Keep the attachment usable while it is being repaired. */ }
  }
  return content.split("\n").filter(Boolean).length;
}

/** Unified problem & data composer card: natural-language input, inline data attachments, and integrated action bar. */
export function ProblemEditor({ value, data, onChange, onFiles, onDataChange, onRemove, onClear, onExamples, disabled = false, reading = false,
  label = t("问题描述"), actions, toolbarExtra, primaryAction, placeholder, autoFocus = false }: {
  value: string; data: Record<string, string>; onChange: (value: string) => void;
  onFiles: (files: FileList | null) => void; onRemove: (name: string) => void; onClear: () => void; onExamples?: () => void;
  onDataChange: (name: string, content: string) => void | Promise<void>;
  disabled?: boolean; reading?: boolean;
  autoFocus?: boolean;
  label?: string; actions?: ReactNode; toolbarExtra?: ReactNode; primaryAction?: ReactNode; placeholder?: string;
}) {
  const [mode, setMode] = useState("edit");
  const [dragging, setDragging] = useState(false);
  const [editing, setEditing] = useState<string | null>(null);
  const files = Object.entries(data);
  const locked = disabled || reading;
  const input = useRef<HTMLTextAreaElement>(null);
  useEffect(() => {
    if (autoFocus && matchMedia("(pointer: fine)").matches && document.activeElement === document.body) input.current?.focus({ preventScroll: true });
  }, [autoFocus]);

  return <Card className={cn(
    "relative min-h-56 min-w-0 flex-1 gap-0 overflow-hidden rounded-2xl border-border/90 bg-card py-0 shadow-sm transition-[border-color,box-shadow] duration-200 focus-within:border-primary/45 focus-within:ring-3 focus-within:ring-primary/10",
    dragging && "border-primary ring-3 ring-primary/20")}
    onDragOver={event => {
      if (!event.dataTransfer.types?.includes("Files") && !event.dataTransfer.files?.length) return;
      event.preventDefault(); if (!locked) setDragging(true);
    }} onDragLeave={event => {
      if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDragging(false);
    }}
    onDrop={event => {
      setDragging(false);
      if (!event.dataTransfer.types?.includes("Files") && !event.dataTransfer.files?.length) return;
      event.preventDefault(); if (!locked) onFiles(event.dataTransfer.files);
    }}>
    <Tabs value={mode} onValueChange={setMode} className="min-h-0 flex-1 gap-0">
      <div className="flex h-11 shrink-0 items-center justify-between gap-2 border-b border-border/60 bg-muted/20 px-4">
        <div className="flex min-w-0 items-center gap-2">
          <Label htmlFor="problem-description" className="min-w-0 truncate text-[13px] font-semibold text-foreground/90">{label}</Label>
          {value.length ? <span className="hidden text-[11px] text-muted-foreground tabular sm:inline">{t("{count} 字", { count: value.length })}</span> : null}
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {actions}
          {value || files.length ? <Button type="button" variant="ghost" size="xs" disabled={locked}
            className="h-7 gap-1 rounded-lg px-2 text-xs text-muted-foreground hover:text-destructive"
            onClick={() => { onClear(); setMode("edit"); }}><Trash2 className="size-3.5" />{t("清空")}</Button> : null}
          <TabsList aria-label={t("问题显示方式")} className="h-7 rounded-lg p-0.5">
            <TabsTrigger value="edit" className="h-6 gap-1 rounded-md px-2 text-xs"><PenLine className="size-3" />{t("编辑")}</TabsTrigger>
            <TabsTrigger value="preview" className="h-6 gap-1 rounded-md px-2 text-xs" title={t("预览排版与数学公式")}>{t("预览")}<Eye className="sr-only" /></TabsTrigger>
          </TabsList>
        </div>
      </div>

      <TabsContent value="edit" forceMount className="mt-0 flex min-h-0 flex-1 flex-col data-[state=inactive]:hidden">
        <Textarea ref={input} id="problem-description" aria-label={t("问题描述")} value={value} disabled={disabled}
          placeholder={placeholder ?? t("请用日常语言描述你要优化的目标和限制条件。\n例如：工厂生产 A、B 两种产品，单件利润分别为 3 元和 2 元，怎样安排产量能让总利润最高？（支持直接拖拽 Excel / CSV 表格到这里）")}
          onChange={event => onChange(event.target.value)}
          className="h-full min-h-36 flex-1 field-sizing-fixed resize-none rounded-none border-0 bg-transparent px-4 py-3.5 text-base leading-relaxed shadow-none focus-visible:ring-0 sm:text-[15px] dark:bg-transparent" />
      </TabsContent>

      <TabsContent value="preview" aria-label={t("问题预览")} className="mt-0 min-h-36 flex-1 overflow-y-auto px-4 py-3.5">
        {value.trim() ? <Markdown text={value} singleDollarMath={false} />
          : <p className="text-sm text-muted-foreground">{t("输入问题描述后，可在此预览排版效果。")}</p>}
      </TabsContent>
    </Tabs>

    {files.length ? <ul aria-label={t("数据文件")} className="flex max-h-28 shrink-0 flex-wrap gap-2 overflow-y-auto border-t border-border/60 bg-muted/15 px-4 py-2.5">
      {files.map(([name, content]) => <li key={name} title={t("点击可在线查看或编辑 {name}", { name })}
        className="group/file flex min-w-0 max-w-full items-center gap-1.5 rounded-xl border bg-background py-1 pr-1 pl-2.5 text-xs shadow-2xs transition-colors hover:border-primary/40">
        <button type="button" disabled={locked} aria-label={t("编辑 {name}", { name })} onClick={() => setEditing(name)}
          className="flex min-w-0 items-center gap-1.5 rounded-sm hover:text-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
          <FileSpreadsheet className="size-3.5 shrink-0 text-primary/80" /><span className="max-w-44 truncate font-medium">{name}</span>
        </button>
        <span className="shrink-0 rounded-md bg-muted px-1.5 py-0.5 text-[11px] text-muted-foreground tabular">{t("{count} 行", { count: dataRowCount(name, content) })}</span>
        <Button variant="ghost" size="icon-xs" disabled={locked} aria-label={t("移除 {name}", { name })} className="rounded-lg text-muted-foreground hover:text-destructive" onClick={() => onRemove(name)}><X /></Button>
      </li>)}
    </ul> : null}

    <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-border/60 bg-muted/25 px-3 py-2.5 sm:px-4">
      <div className="flex min-w-0 flex-wrap items-center gap-1.5">
        <Button variant="outline" size="sm" asChild className="h-8 rounded-xl bg-background/80 text-xs font-normal shadow-2xs">
          <label title={t("支持 Excel (.xlsx)、CSV、TSV、JSON 和文本文件；上传后可直接点击文件名在线编辑。")}
            className={cn("cursor-pointer", locked && "pointer-events-none opacity-50")}>
            {reading ? <Spinner /> : <Paperclip className="size-3.5 text-primary/80" />}{t(reading ? "正在读取数据……" : "上传数据表")}
            <input type="file" multiple disabled={locked} accept={DATA_FILE_ACCEPT} className="sr-only"
              onChange={event => { onFiles(event.target.files); event.target.value = ""; }} />
          </label>
        </Button>
        {onExamples && !primaryAction ? <Button variant="ghost" size="sm" className="h-8 rounded-xl text-xs font-normal text-muted-foreground" disabled={locked} onClick={onExamples}><BookOpen className="size-3.5" />{t("案例模板")}</Button> : null}
        {toolbarExtra}
      </div>
      {primaryAction ? <div className="flex w-full items-center justify-end sm:w-auto">{primaryAction}</div> : null}
    </div>

    {dragging ? <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-2 bg-card/92 backdrop-blur-xs text-sm font-medium text-primary">
      <span className="grid size-11 place-items-center rounded-2xl bg-primary/10 text-primary"><Upload className="size-5" /></span>
      <span>{t("松开以添加数据文件")}</span>
      <span className="text-xs font-normal text-muted-foreground">{t("支持 Excel、CSV、TSV、JSON、TXT")}</span>
    </div> : null}
    {editing !== null && editing in data ? <DataEditor key={editing} name={editing} content={data[editing]}
      onSave={content => onDataChange(editing, content)} onClose={() => setEditing(null)} /> : null}
  </Card>;
}
