import { useState } from "react";
import { BookOpen, FileText, Paperclip, Trash2, Upload, X } from "lucide-react";
import { Markdown } from "@/components/Content";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { t } from "@/i18n";

/** Editing and preview share the original text; rendering never changes the submitted problem. */
export function ProblemEditor({ value, data, onChange, onFiles, onRemove, onClear, onExamples }: {
  value: string; data: Record<string, string>; onChange: (value: string) => void;
  onFiles: (files: FileList | null) => void; onRemove: (name: string) => void; onClear: () => void; onExamples: () => void;
}) {
  const [mode, setMode] = useState("edit");
  const [dragging, setDragging] = useState(false);
  const files = Object.entries(data);

  return <Card className={cn("relative h-[min(60dvh,32rem)] min-h-80 min-w-0 flex-none gap-0 overflow-hidden py-0 lg:h-auto lg:min-h-0 lg:flex-1",
    dragging && "border-primary ring-2 ring-primary/20")}
    onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
    onDrop={event => { event.preventDefault(); setDragging(false); onFiles(event.dataTransfer.files); }}>
    <Tabs value={mode} onValueChange={setMode} className="min-h-0 flex-1 gap-0">
      <div className="flex h-14 shrink-0 items-center justify-between gap-3 border-b px-4">
        <Label htmlFor="problem-description" className="text-sm font-semibold">{t("问题描述")}</Label>
        <TabsList aria-label={t("问题显示方式")}>
          <TabsTrigger value="edit">{t("编辑")}</TabsTrigger>
          <TabsTrigger value="preview" title={t("支持 Markdown；公式使用 \\(...\\)、\\[...\\] 或 $$...$$。")}>{t("预览")}</TabsTrigger>
        </TabsList>
      </div>
      <TabsContent value="edit" className="mt-0 flex min-h-0 flex-col">
        <Textarea id="problem-description" aria-label={t("问题描述")} value={value}
          placeholder={t("例如：工厂生产 A、B 两种产品……请确定生产数量，使总利润最大。")}
          onChange={event => onChange(event.target.value)}
          className="h-full min-h-0 flex-1 field-sizing-fixed resize-none rounded-none border-0 bg-transparent p-4 text-base leading-relaxed shadow-none focus-visible:ring-0 sm:text-sm dark:bg-transparent" />
      </TabsContent>
      <TabsContent value="preview" aria-label={t("问题预览")} className="mt-0 min-h-0 overflow-y-auto p-4">
        {value.trim() ? <Markdown text={value} singleDollarMath={false} />
          : <p className="text-sm text-muted-foreground">{t("输入问题后，可在这里预览 Markdown。")} </p>}
      </TabsContent>
    </Tabs>
    {files.length ? <ul aria-label={t("数据文件")} className="flex max-h-28 shrink-0 flex-wrap gap-2 overflow-y-auto border-t px-4 py-3">
      {files.map(([name, content]) => <li key={name} title={name}
        className="flex min-w-0 max-w-full items-center gap-1.5 rounded-md border bg-muted/50 py-1 pr-1 pl-2 text-xs">
        <FileText className="size-3.5 shrink-0 text-muted-foreground" /><span className="max-w-48 truncate font-medium">{name}</span>
        <span className="shrink-0 text-muted-foreground">{t("{count} 行", { count: content.split("\n").filter(Boolean).length })}</span>
        <Button variant="ghost" size="icon-xs" aria-label={t("移除 {name}", { name })} onClick={() => onRemove(name)}><X /></Button>
      </li>)}
    </ul> : null}
    <div className="flex shrink-0 flex-wrap items-center gap-1 border-t bg-muted/30 px-3 py-2">
      <Button variant="ghost" size="sm" asChild>
        <label title={t("CSV、JSON、文本或 Excel（转换为 CSV）；代码中以 data[文件名] 读取")} className="cursor-pointer">
          <Paperclip />{t("数据文件")}
          <input type="file" multiple accept=".csv,.json,.txt,.tsv,.xlsx" className="sr-only"
            onChange={event => { onFiles(event.target.files); event.target.value = ""; }} />
        </label>
      </Button>
      <Button variant="ghost" size="sm" onClick={onExamples}><BookOpen />{t("从题库选题")}</Button>
      {value || files.length ? <Button variant="ghost" size="sm" onClick={() => { onClear(); setMode("edit"); }}><Trash2 />{t("清空")}</Button> : null}
      <span className="ml-auto px-1 text-xs text-muted-foreground tabular">{value.length ? t("{count} 字", { count: value.length }) : ""}</span>
    </div>
    {dragging ? <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center gap-2 bg-card/90 text-sm font-medium text-primary">
      <Upload className="size-4" />{t("松开以添加数据文件")}</div> : null}
  </Card>;
}
