import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, ChevronLeft, ChevronRight, ExternalLink, Search, X } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { locale, t } from "@/i18n";
import { Markdown } from "@/components/Content";
import { Spinner } from "@/components/ui/spinner";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { api } from "@/api";
import { errorText } from "@/format";
import type { Dataset } from "@/types";

type Case = { id: string; sample_id: string; subset: string; description: string };
type Translation = { original: string; translation: string; cached: boolean; locale: string };
const PAGE = 20;
const TRANSLATION_ERRORS = new Map([
  ["The translation was empty. Please retry.", "译文为空，请重试。"],
  ["Could not translate this example. Please retry.", "暂时无法翻译此题，请重试。"],
  ["The translation cache is unavailable. Please retry.", "译文缓存暂不可用，请重试。"],
]);

/** Curated public optimization scenarios to explore and try directly in the workspace. */
export function Examples({ open, onClose, datasets, onUse }: {
  open: boolean; onClose: () => void; datasets: Dataset[]; onUse: (description: string) => void;
}) {
  const [dataset, setDataset] = useState<Dataset>(datasets[0]);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const trimmed = search.trim();
  const { data: page, error, refetch, isFetching } = useQuery({
    queryKey: ["dataset", dataset?.id, offset, trimmed], enabled: open && !!dataset, staleTime: Infinity,
    queryFn: () => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(PAGE) });
      if (trimmed) params.set("q", trimmed);
      return api<{ total: number; cases: Case[] }>(`/api/datasets/${dataset.id}?${params}`);
    },
  });
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => { list.current?.scrollTo(0, 0); }, [page]);
  const choose = (item: Dataset) => { setDataset(item); setOffset(0); };

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
              <span className="max-w-full font-medium [overflow-wrap:anywhere]">{item.id === "mamo_easy" ? t("MAMO 基础") : item.id === "mamo_complex" ? t("MAMO 复杂") : item.title}</span>
              <span className={cn("max-w-full text-[11px]", active ? "text-primary/80" : "text-muted-foreground")}>
                {t("{count} 个案例", { count: item.count })}
              </span>
            </button>;
          })}
        </nav>
        <div ref={list} className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4 sm:p-5">
          {dataset ? <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-border/70 bg-muted/25 px-3.5 py-2.5 text-xs text-muted-foreground">
            <p className="min-w-0 flex-1 leading-relaxed break-words">{t(dataset.description)}</p>
            <Button variant="link" size="xs" asChild className="h-auto shrink-0 p-0 text-xs">
              <a href={dataset.source_url} target="_blank" rel="noreferrer">{t("数据来源")}<ExternalLink /></a></Button>
          </div> : null}
          <div className="relative mb-3">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input aria-label={t("搜索案例")} value={search} placeholder={t("按关键词筛选当前题库（如 routing、knapsack、schedule）…")}
              onChange={event => { setSearch(event.target.value); setOffset(0); }} className="h-9 rounded-xl pr-8 pl-8 text-xs" />
            {search ? <Button variant="ghost" size="icon-xs" aria-label={t("清除搜索")} className="absolute top-1/2 right-1 -translate-y-1/2"
              onClick={() => { setSearch(""); setOffset(0); }}><X /></Button> : null}
          </div>
          {error ? <Alert variant="destructive"><AlertDescription className="flex items-center justify-between gap-3">{errorText(error)}
            <Button variant="outline" size="sm" onClick={() => void refetch()}>{t("重试")}</Button></AlertDescription></Alert>
            : !page ? <div className="flex flex-col gap-3">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28 rounded-2xl" />)}</div>
            : !page.cases.length ? <p className="py-10 text-center text-sm text-muted-foreground">{t("当前题库中没有匹配的案例。")}</p> : <>
            <ol className="flex flex-col gap-3">{page.cases.map(item => <ExampleCard key={item.id} item={item} dataset={dataset.id} onUse={onUse} />)}</ol>
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

function ExampleCard({ item, dataset, onUse }: { item: Case; dataset: string; onUse: (text: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const [showTranslation, setShowTranslation] = useState(false);
  const translation = useMutation({
    mutationFn: () => api<Translation>(`/api/datasets/${dataset}/translation`, { case_id: item.id, locale }),
    onSuccess: () => { setShowTranslation(true); setExpanded(true); },
  });
  const translated = translation.data?.original === item.description ? translation.data.translation : undefined;
  const showingTranslation = showTranslation && translated !== undefined;
  const text = showingTranslation ? translated : item.description;
  const message = translation.isError ? errorText(translation.error) : "";

  return <li className="group flex flex-col gap-2.5 rounded-2xl border border-border/80 bg-card p-4 shadow-2xs transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/35 hover:shadow-md">
    <div className="flex flex-wrap items-center gap-2">
      <Badge variant="secondary" className="rounded-md font-mono text-[11px] font-normal">#{item.sample_id}</Badge>
      {item.subset && item.subset !== dataset ? <Badge variant="outline" className="rounded-md font-normal text-muted-foreground">{item.subset}</Badge> : null}
      <Button size="sm" variant="secondary" className="ml-auto rounded-lg" onClick={() => onUse(text)}>
        {showingTranslation ? t("带入译文") : translated !== undefined ? t("带入原文") : t("带入此案例")}<ArrowRight />
      </Button>
    </div>
    <div className={cn("text-sm leading-relaxed text-foreground/90", !expanded && "line-clamp-4")}>
      <Markdown text={text} singleDollarMath={false} />
    </div>
    {showingTranslation ? <p className="text-xs text-muted-foreground">{t("机器译文，请对照原文核对条件。")}</p> : null}
    <div className="flex flex-wrap items-center gap-3">
      {translated !== undefined ? <Button variant="link" size="xs" className="p-0" onClick={() => setShowTranslation(!showTranslation)}>
        {showingTranslation ? t("查看原文") : t("查看译文")}</Button>
        : !translation.isError ? <Button variant="link" size="xs" className="p-0" disabled={translation.isPending} onClick={() => translation.mutate()}>
          {translation.isPending ? <><Spinner />{t("正在翻译题目……")}</> : locale === "zh" ? t("翻译为中文") : t("翻译为英文")}
        </Button> : null}
      {text.length > 280 ? <Button variant="link" size="xs" className="p-0" onClick={() => setExpanded(!expanded)}>
        {expanded ? t("收起") : t("展开全文")}</Button> : null}
    </div>
    {translation.isError ? <Alert variant="destructive"><AlertDescription className="flex flex-wrap items-center justify-between gap-2">
      <span>{t(TRANSLATION_ERRORS.get(message) ?? message)}</span>
      <Button variant="outline" size="sm" onClick={() => translation.mutate()}>{t("重新翻译")}</Button>
    </AlertDescription></Alert> : null}
  </li>;
}
