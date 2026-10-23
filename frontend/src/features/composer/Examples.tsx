import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { t } from "@/i18n";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { api } from "@/api";
import { errorText } from "@/format";
import type { Dataset } from "@/types";

type Case = { id: string; sample_id: string; subset: string; description: string };
const PAGE = 20;

/** Public benchmark problems to read and try. Only for trying the platform; nothing is scored. */
export function Examples({ open, onClose, datasets, onUse }: {
  open: boolean; onClose: () => void; datasets: Dataset[]; onUse: (description: string) => void;
}) {
  const [dataset, setDataset] = useState<Dataset>(datasets[0]);
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data: page, error, refetch, isFetching } = useQuery({
    queryKey: ["dataset", dataset?.id, offset], enabled: open && !!dataset, staleTime: Infinity,
    queryFn: () => api<{ total: number; cases: Case[] }>(`/api/datasets/${dataset.id}?offset=${offset}&limit=${PAGE}`),
  });
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => { list.current?.scrollTo(0, 0); }, [page]);
  const choose = (item: Dataset) => { setDataset(item); setOffset(0); setExpanded(null); };

  return <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
    <DialogContent className="flex h-[min(820px,90dvh)] flex-col gap-0 p-0 sm:max-w-5xl">
      <DialogHeader className="border-b px-6 py-4">
        <DialogTitle>{t("示例题库")}</DialogTitle>
        <DialogDescription>{t("公开 Benchmark 的题面，不含答案。选一道题带回编辑页。")}</DialogDescription>
      </DialogHeader>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav aria-label={t("题库")} className="flex min-h-0 shrink-0 gap-1 overflow-auto border-b p-2 md:w-56 md:flex-col md:border-r md:border-b-0">
          {datasets.map(item => <button key={item.id} aria-current={item.id === dataset?.id} onClick={() => choose(item)}
            className={cn("flex min-w-0 shrink-0 flex-col items-start gap-0.5 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent md:w-full",
              item.id === dataset?.id && "bg-accent")}>
            <span className="max-w-full font-medium [overflow-wrap:anywhere]">{item.title}</span>
            <span className="max-w-full text-[11px] text-muted-foreground [overflow-wrap:anywhere]">{t("{count} 题", { count: item.count })} · {item.license}</span>
          </button>)}
        </nav>
        <div ref={list} className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4">
          {dataset ? <div className="mb-4 flex items-start gap-3 text-sm text-muted-foreground">
            <p className="min-w-0 flex-1 leading-relaxed break-words">{dataset.description}</p>
            <Button variant="link" size="sm" asChild className="h-auto shrink-0 p-0">
              <a href={dataset.source_url} target="_blank" rel="noreferrer">{t("来源")}<ExternalLink /></a></Button>
          </div> : null}
          {error ? <Alert variant="destructive"><AlertDescription>{errorText(error)}
            <Button variant="outline" size="sm" onClick={() => void refetch()}>{t("重试")}</Button></AlertDescription></Alert>
            : !page ? <div className="flex flex-col gap-3">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28 rounded-xl" />)}</div> : <>
            <ol className="flex flex-col gap-3">{page.cases.map(item => <li key={item.id}
              className="group flex flex-col gap-2 rounded-xl border bg-card p-4 transition-colors hover:border-primary/30">
              <div className="flex items-center gap-2">
                <Badge variant="secondary" className="font-mono font-normal">#{item.sample_id}</Badge>
                {item.subset && item.subset !== dataset.id ? <Badge variant="outline" className="font-normal text-muted-foreground">{item.subset}</Badge> : null}
                <Button size="sm" variant="outline" className="ml-auto group-hover:border-primary/40 group-hover:text-primary" onClick={() => onUse(item.description)}>
                  {t("使用这道题")}<ArrowRight /></Button>
              </div>
              <p className={cn("text-sm leading-relaxed whitespace-pre-wrap", expanded !== item.id && "line-clamp-4")}>{item.description}</p>
              {item.description.length > 280 ? <Button variant="link" size="xs" className="self-start p-0"
                onClick={() => setExpanded(expanded === item.id ? null : item.id)}>{expanded === item.id ? t("收起") : t("展开全文")}</Button> : null}
            </li>)}</ol>
          </>}
        </div>
      </div>
      {page ? <div className="flex shrink-0 items-center justify-center gap-3 border-t bg-card px-4 py-3">
        <Button variant="outline" size="sm" disabled={isFetching || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}><ChevronLeft />{t("上一页")}</Button>
        <span className="text-xs text-muted-foreground tabular">{page.total ? offset + 1 : 0}–{Math.min(offset + PAGE, page.total)} / {page.total}</span>
        <Button variant="outline" size="sm" disabled={isFetching || offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>{t("下一页")}<ChevronRight /></Button>
      </div> : null}
    </DialogContent>
  </Dialog>;
}
