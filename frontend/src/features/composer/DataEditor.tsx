import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { errorText } from "@/format";
import { t } from "@/i18n";
import { parseCsv, toCsv } from "@/lib/csv";

const PAGE = 50;

/** Keep unsaved file edits in the dialog; cancel and failed saves leave the original attachment intact. */
export function DataEditor({ name, content, onSave, onClose }: {
  name: string; content: string; onSave: (content: string) => void | Promise<void>; onClose: () => void;
}) {
  const [text, setText] = useState(content);
  const [page, setPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tabular = /\.(csv|tsv)$/i.test(name);
  const delimiter = /\.tsv$/i.test(name) ? "\t" : ",";
  const parsed = useMemo(() => {
    try { return { rows: tabular ? parseCsv(text, delimiter) : null, error: null }; }
    catch (error) { return { rows: null, error: errorText(error) }; }
  }, [text, tabular, delimiter]);
  const rows = parsed.rows;
  const columns = rows?.reduce((size, row) => Math.max(size, row.length), 0) ?? 0;
  // shortcut: wide files use raw editing; add column paging when users need large spreadsheet grids.
  const grid = !!rows?.length && columns <= 50;
  const pages = Math.max(1, Math.ceil(Math.max(0, (rows?.length ?? 0) - 1) / PAGE));
  const current = Math.min(page, pages - 1);
  const changeCell = (row: number, column: number, value: string) => {
    const next = rows!.map(cells => [...cells]);
    while (next[row].length <= column) next[row].push("");
    next[row][column] = value;
    setText(toCsv(next, delimiter));
  };
  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose(); }}>
    <DialogContent className="flex max-h-[90dvh] min-h-0 flex-col sm:max-w-4xl" aria-busy={busy}
      onKeyDown={event => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) event.stopPropagation(); }}>
      <DialogHeader>
        <DialogTitle className="break-all">{t("编辑数据：{name}", { name })}</DialogTitle>
        <DialogDescription>{t("检查数据后再建模。可在列名中补充含义和单位，例如“单价（元）”。保存后使用修改后的附件。")}</DialogDescription>
      </DialogHeader>
      <Tabs defaultValue={grid ? "table" : "text"} className="min-h-0 flex-1 gap-3">
        <TabsList className="shrink-0 self-start"><TabsTrigger value="table" disabled={!grid}>{t("表格")}</TabsTrigger><TabsTrigger value="text">{t("原文")}</TabsTrigger></TabsList>
        <TabsContent value="table" className="mt-0 flex min-h-0 flex-col data-[state=inactive]:hidden">
          {grid && rows ? <>
              <Table containerClassName="min-h-0 max-h-[50dvh] flex-1 rounded-lg border"><TableHeader className="sticky top-0 z-10 bg-muted"><TableRow>
                <TableHead className="w-10 text-center">#</TableHead>
                {Array.from({ length: columns }, (_, column) => <TableHead key={column} className="p-1">
                  <Input aria-label={t("第 {column} 列列名", { column: column + 1 })} disabled={busy} value={rows[0][column] ?? ""}
                    onChange={event => changeCell(0, column, event.target.value)} className="min-w-32 border-transparent font-medium" />
                </TableHead>)}
              </TableRow></TableHeader><TableBody>
                {rows.slice(current * PAGE + 1, (current + 1) * PAGE + 1).map((cells, index) => {
                  const row = current * PAGE + index + 1;
                  return <TableRow key={row}><TableCell className="text-center text-xs text-muted-foreground">{row}</TableCell>
                    {Array.from({ length: columns }, (_, column) => <TableCell key={column} className="p-1">
                      <Textarea rows={1} aria-label={t("第 {row} 行，第 {column} 列", { row, column: column + 1 })} value={cells[column] ?? ""} disabled={busy}
                        onChange={event => changeCell(row, column, event.target.value)} className="max-h-24 min-h-8 min-w-32 resize-none border-transparent py-1.5 font-mono text-xs field-sizing-content" />
                    </TableCell>)}
                  </TableRow>;
                })}
              </TableBody></Table>
            <div className="mt-2 flex shrink-0 items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>{t("{count} 行数据 · 第 {page}/{pages} 页", { count: rows.length - 1, page: current + 1, pages })}</span>
              <div className="flex gap-1"><Button variant="ghost" size="icon-sm" aria-label={t("上一页")} disabled={!current} onClick={() => setPage(current - 1)}><ChevronLeft /></Button>
                <Button variant="ghost" size="icon-sm" aria-label={t("下一页")} disabled={current === pages - 1} onClick={() => setPage(current + 1)}><ChevronRight /></Button></div>
            </div>
          </> : null}
        </TabsContent>
        <TabsContent value="text" className="mt-0 flex min-h-0 flex-col data-[state=inactive]:hidden">
          {columns > 50 ? <p className="mb-2 text-xs text-muted-foreground">{t("列数较多，请在原文中编辑；数据会完整保留。")}</p> : null}
          <Textarea aria-label={t("数据文件原文")} value={text} disabled={busy} onChange={event => setText(event.target.value)}
            className="h-[50dvh] min-h-0 flex-1 field-sizing-fixed resize-none font-mono text-xs" />
        </TabsContent>
      </Tabs>
      {error || parsed.error ? <p role="alert" className="text-sm text-destructive">{error || parsed.error}</p> : null}
      <DialogFooter>
        <Button variant="outline" disabled={busy} onClick={onClose}>{t("取消")}</Button>
        <Button disabled={busy || text === content || !!parsed.error} onClick={async () => {
          setBusy(true); setError(null);
          try {
            if (new Blob([text]).size > 2_000_000) throw new Error(t("文件超过 2 MB，请缩减数据。"));
            if (/\.json$/i.test(name)) JSON.parse(text);
            await onSave(text); onClose();
          } catch (error) { setError(errorText(error)); }
          finally { setBusy(false); }
        }}>{busy ? <Spinner /> : <Save />}{t("保存数据")}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
