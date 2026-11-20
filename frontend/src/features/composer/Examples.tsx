import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
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

/** Curated public optimization scenarios to explore and try directly in the workspace. */
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
    <DialogContent className="flex h-[min(820px,90dvh)] flex-col gap-0 overflow-hidden rounded-2xl p-0 sm:max-w-5xl">
      <DialogHeader className="border-b bg-muted/20 px-6 py-4">
        <DialogTitle className="flex items-center gap-2 text-base font-semibold">
          <span className="grid size-7 place-items-center rounded-lg bg-primary/10 text-primary"><BookOpen className="size-4" /></span>
          {t("案例模板库")}
        </DialogTitle>
        <DialogDescription>{t("精选生产制造、仓储物流、排班调度等真实优化场景，点击即可带入体验。")}</DialogDescription>
      </DialogHeader>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav aria-label={t("案例分类")} className="flex min-h-0 shrink-0 gap-1.5 overflow-auto border-b bg-muted/15 p-2.5 md:w-60 md:flex-col md:border-r md:border-b-0">
          {datasets.map(item => {
            const active = item.id === dataset?.id;
            return <button key={item.id} aria-current={active} onClick={() => choose(item)}
              className={cn("flex min-w-0 shrink-0 flex-col items-start gap-1 rounded-xl px-3 py-2.5 text-left text-sm transition-all md:w-full",
                active ? "bg-primary/10 text-primary shadow-2xs ring-1 ring-primary/20" : "text-foreground/85 hover:bg-accent")}>
              <span className="max-w-full font-medium [overflow-wrap:anywhere]">{item.title}</span>
              <span className={cn("max-w-full text-[11px]", active ? "text-primary/80" : "text-muted-foreground")}>
                {t("{count} 个案例", { count: item.count })}
              </span>
            </button>;
          })}
        </nav>
        <div ref={list} className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4 sm:p-5">
          {dataset ? <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/70 bg-muted/25 px-3.5 py-2.5 text-xs text-muted-foreground">
            <p className="min-w-0 flex-1 leading-relaxed break-words">{dataset.description}</p>
            <Button variant="link" size="xs" asChild className="h-auto shrink-0 p-0 text-xs">
              <a href={dataset.source_url} target="_blank" rel="noreferrer">{t("数据来源")}<ExternalLink /></a></Button>
          </div> : null}
          {error ? <Alert variant="destructive"><AlertDescription className="flex items-center justify-between gap-3">{errorText(error)}
            <Button variant="outline" size="sm" onClick={() => void refetch()}>{t("重试")}</Button></AlertDescription></Alert>
            : !page ? <div className="flex flex-col gap-3">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28 rounded-2xl" />)}</div> : <>
            <ol className="flex flex-col gap-3">{page.cases.map(item => <li key={item.id}
              className="group flex flex-col gap-2.5 rounded-2xl border border-border/80 bg-card p-4 shadow-2xs transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/35 hover:shadow-md">
              <div className="flex items-center gap-2">
                <Badge variant="secondary" className="rounded-md font-mono text-[11px] font-normal">#{item.sample_id}</Badge>
                {item.subset && item.subset !== dataset.id ? <Badge variant="outline" className="rounded-md font-normal text-muted-foreground">{item.subset}</Badge> : null}
                <Button size="sm" variant="secondary" className="ml-auto rounded-lg transition-colors group-hover:bg-primary group-hover:text-primary-foreground" onClick={() => onUse(item.description)}>
                  {t("带入此案例")}<ArrowRight /></Button>
              </div>
              <p className={cn("text-sm leading-relaxed text-foreground/90 whitespace-pre-wrap", expanded !== item.id && "line-clamp-4")}>{item.description}</p>
              {item.description.length > 280 || item.description.split(/\r?\n/).length > 4 ? <Button variant="link" size="xs" className="self-start p-0"
                onClick={() => setExpanded(expanded === item.id ? null : item.id)}>{expanded === item.id ? t("收起") : t("展开全文")}</Button> : null}
            </li>)}</ol>
          </>}
        </div>
      </div>
      {page ? <div className="flex shrink-0 items-center justify-center gap-3 border-t bg-card px-4 py-3">
        <Button variant="outline" size="sm" className="rounded-lg" disabled={isFetching || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}><ChevronLeft />{t("上一页")}</Button>
        <span className="text-xs text-muted-foreground tabular">{page.total ? offset + 1 : 0}–{Math.min(offset + PAGE, page.total)} / {page.total}</span>
        <Button variant="outline" size="sm" className="rounded-lg" disabled={isFetching || offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>{t("下一页")}<ChevronRight /></Button>
      </div> : null}
    </DialogContent>
  </Dialog>;
}
