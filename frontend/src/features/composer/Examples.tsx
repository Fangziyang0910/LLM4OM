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
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { api } from "@/api";
import { errorText } from "@/format";
import type { Dataset } from "@/types";
import { SCENARIOS, type Scenario } from "./scenarios";

type Case = { dataset: string; id: string; sample_id: string; subset: string; description: string };
type Translation = { original: string; translation: string; cached: boolean; locale: string };
const PAGE = 20;
const TRANSLATION_ERRORS = new Map([
  ["The translation was empty. Please retry.", "译文为空，请重试。"],
  ["Could not translate this example. Please retry.", "暂时无法翻译此题，请重试。"],
  ["The translation cache is unavailable. Please retry.", "译文缓存暂不可用，请重试。"],
]);

/** Business scenario templates first, then the bundled public benchmarks to browse and try directly in the workspace. */
export function Examples({ open, onClose, datasets, onUse }: {
  open: boolean; onClose: () => void; datasets: Dataset[]; onUse: (description: string) => void;
}) {
  const [section, setSection] = useState<"templates" | "bench">("templates");
  const [dataset, setDataset] = useState<Dataset>();
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const trimmed = search.trim();
  const bench = section === "bench";
  const { data: page, error, refetch, isFetching } = useQuery({
    queryKey: ["dataset", dataset?.id, offset, trimmed], enabled: open && bench && datasets.length > 0, staleTime: Infinity,
    queryFn: () => {
      const params = new URLSearchParams({ offset: String(offset), limit: String(PAGE) });
      if (trimmed) params.set("q", trimmed);
      return api<{ total: number; cases: Case[] }>(`/api/datasets${dataset ? `/${dataset.id}` : ""}?${params}`);
    },
  });
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => { list.current?.scrollTo(0, 0); }, [page, section]);
  const choose = (item?: Dataset) => { setSection("bench"); setDataset(item); setOffset(0); };
  const words = trimmed.toLowerCase().split(/\s+/).filter(Boolean);
  const templates = SCENARIOS.filter(item => words.every(word =>
    [item.industry, item.title, item.summary, item.description].some(text => t(text).toLowerCase().includes(word))));
  const datasetName = (item: Dataset) => item.id === "mamo_easy" ? t("MAMO 基础") : item.id === "mamo_complex" ? t("MAMO 复杂") : item.title;
  const navItem = (active: boolean, label: string, count: number, onClick: () => void) =>
    <button key={label} aria-current={active} onClick={onClick}
      className={cn("flex min-w-0 shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors md:w-full",
        active ? "bg-primary/10 font-medium text-primary" : "text-foreground/85 hover:bg-accent")}>
      <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">{label}</span>
      <span aria-hidden className={cn("shrink-0 text-[11px] tabular", active ? "text-primary/80" : "text-muted-foreground")}>{count}</span>
    </button>;

  return <Dialog open={open} onOpenChange={value => { if (!value) onClose(); }}>
    <DialogContent className="flex h-[min(820px,90dvh)] flex-col gap-0 overflow-hidden rounded-2xl p-0 sm:max-w-5xl">
      <DialogHeader className="border-b px-6 py-4">
        <DialogTitle className="flex items-center gap-2 text-base font-semibold">
          <span className="grid size-7 place-items-center rounded-lg bg-primary/10 text-primary"><BookOpen className="size-4" /></span>
          {t("案例模板库")}
        </DialogTitle>
        <DialogDescription>{t("按行业挑选场景模板，或从公开评测题库中选题，点击即可带入。")}</DialogDescription>
      </DialogHeader>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="shrink-0 border-b px-4 py-2 md:hidden">
          <Select value={bench ? dataset?.id ?? "all" : "templates"}
            onValueChange={value => value === "templates" ? setSection("templates") : choose(datasets.find(item => item.id === value))}>
            <SelectTrigger aria-label={t("案例分类")} className="w-full"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="templates">{t("场景模板")}</SelectItem>
              <SelectSeparator />
              <SelectGroup>
                <SelectLabel>{t("公开评测题库")}</SelectLabel>
                <SelectItem value="all">{t("全部题库")}</SelectItem>
                {datasets.map(item => <SelectItem key={item.id} value={item.id}>{datasetName(item)}</SelectItem>)}
              </SelectGroup>
            </SelectContent>
          </Select>
        </div>
        <nav aria-label={t("案例分类")} className="hidden min-h-0 shrink-0 flex-col gap-0.5 overflow-auto border-r bg-muted/15 p-2.5 md:flex md:w-60">
          {navItem(!bench, t("场景模板"), SCENARIOS.length, () => setSection("templates"))}
          <p className="px-3 pt-4 pb-1 text-[11px] font-medium text-muted-foreground">{t("公开评测题库")}</p>
          {navItem(bench && !dataset, t("全部题库"), datasets.reduce((total, item) => total + item.count, 0), () => choose())}
          {datasets.map(item => navItem(bench && item.id === dataset?.id, datasetName(item), item.count, () => choose(item)))}
        </nav>
        <div ref={list} className="min-h-0 min-w-0 flex-1 overflow-y-auto p-4 sm:p-5">
          {bench ? <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl bg-muted/40 px-3.5 py-2.5 text-xs text-muted-foreground">
            <p className="min-w-0 flex-1 leading-relaxed break-words">{dataset ? t(dataset.description) : t("公开评测题库收录学术基准中的题目，多为英文，可一键翻译。")}</p>
            {dataset ? <Button variant="link" size="xs" asChild className="h-auto shrink-0 p-0 text-xs">
              <a href={dataset.source_url} target="_blank" rel="noreferrer">{t("数据来源")}<ExternalLink /></a></Button> : null}
          </div> : null}
          <div className="relative mb-3">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input aria-label={t("搜索案例")} maxLength={200} value={search} placeholder={t("搜索案例，如运输、排班或背包…")}
              onChange={event => { setSearch(event.target.value); setOffset(0); }} className="h-9 rounded-xl pr-8 pl-8 text-xs" />
            {search ? <Button variant="ghost" size="icon-xs" aria-label={t("清除搜索")} className="absolute top-1/2 right-1 -translate-y-1/2"
              onClick={() => { setSearch(""); setOffset(0); }}><X /></Button> : null}
          </div>
          {!bench ? templates.length ? <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">
            {templates.map(item => <ScenarioCard key={item.id} item={item} onUse={onUse} />)}
          </ul> : <div className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
            <p>{t("没有匹配的场景模板。")}</p>
            <Button variant="outline" size="sm" onClick={() => choose()}>{t("在公开评测题库中搜索")}</Button>
          </div>
            : error ? <Alert variant="destructive"><AlertDescription className="flex items-center justify-between gap-3">{errorText(error)}
              <Button variant="outline" size="sm" onClick={() => void refetch()}>{t("重试")}</Button></AlertDescription></Alert>
            : !page ? <div className="flex flex-col gap-3">{Array.from({ length: 4 }, (_, index) => <Skeleton key={index} className="h-28 rounded-2xl" />)}</div>
            : !page.cases.length ? <p className="py-10 text-center text-sm text-muted-foreground">{t("没有匹配的案例。")}</p> : <>
              <ol className="flex flex-col gap-3">{page.cases.map(item => <ExampleCard key={`${item.dataset}/${item.id}`} item={item} dataset={item.dataset} sourceName={datasets.find(source => source.id === item.dataset)?.title ?? item.dataset} onUse={onUse} />)}</ol>
            </>}
        </div>
      </div>
      {bench && page ? <div className="flex shrink-0 items-center justify-center gap-3 border-t bg-card px-4 py-3">
        <Button variant="outline" size="sm" className="rounded-lg" disabled={isFetching || offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}><ChevronLeft />{t("上一页")}</Button>
        <span className="text-xs text-muted-foreground tabular">{page.total ? offset + 1 : 0}–{Math.min(offset + PAGE, page.total)} / {page.total}</span>
        <Button variant="outline" size="sm" className="rounded-lg" disabled={isFetching || offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>{t("下一页")}<ChevronRight /></Button>
      </div> : null}
    </DialogContent>
  </Dialog>;
}

function ScenarioCard({ item, onUse }: { item: Scenario; onUse: (text: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const Icon = item.icon;
  // An open problem takes the whole row, so its tables have room and the neighbouring card keeps its height.
  return <li className={cn("flex flex-col gap-3 rounded-2xl border border-border/80 bg-card p-4 shadow-2xs transition-colors hover:border-primary/35",
    expanded && "lg:col-span-2")}>
    <div className="flex items-start gap-3">
      <span className="grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary"><Icon className="size-4.5" /></span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-x-2 gap-y-0.5"><span className="font-medium">{t(item.title)}</span>
          <span className="text-xs text-muted-foreground">{t(item.industry)}</span></p>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">{t(item.summary)}</p>
      </div>
    </div>
    {expanded ? <div className="rounded-xl bg-muted/40 px-3.5 py-3 text-[13px] leading-relaxed"><Markdown text={t(item.description)} singleDollarMath={false} /></div> : null}
    <div className="mt-auto flex items-center gap-2">
      <Button variant="link" size="xs" className="p-0" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        {expanded ? t("收起题面") : t("查看题面")}</Button>
      <Button size="sm" variant="secondary" className="ml-auto rounded-lg" onClick={() => onUse(t(item.description))}>
        {t("使用此模板")}<ArrowRight /></Button>
    </div>
  </li>;
}

function ExampleCard({ item, dataset, sourceName, onUse }: { item: Case; dataset: string; sourceName: string; onUse: (text: string) => void }) {
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
      <Badge variant="secondary" className="rounded-md text-[11px] font-normal tabular">{sourceName} #{item.sample_id}</Badge>
      {item.subset && item.subset.toLowerCase() !== dataset.toLowerCase() ? <Badge variant="outline" className="rounded-md font-normal text-muted-foreground">{item.subset}</Badge> : null}
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
