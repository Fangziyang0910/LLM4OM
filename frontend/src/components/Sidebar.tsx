import { useState } from "react";
import { ChevronDown, BookOpen, ChartSpline, Columns3, Cpu, History, MessageSquare, MoreHorizontal, Plus, Search, Sparkles, Trash2, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { STATUS, formatNumber, tone } from "@/format";
import { dateLocale, t } from "@/i18n";
import { isRunEntry, type Entry } from "@/features/runs/types";
import { groupHistory, type HistoryGroup } from "@/features/runs/history";
import type { Options, Preset } from "@/types";
import { StatusIcon, TONE } from "@/features/runs/status";
import { ThemeMenu } from "@/components/theme";

const DAY = 86_400_000;

function group(created: string): string {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const time = Date.parse(created);
  if (time >= today.getTime()) return t("今天");
  if (time >= today.getTime() - DAY) return t("昨天");
  if (time >= today.getTime() - 6 * DAY) return t("近 7 天");
  return t("更早");
}

function when(created: string): string {
  const date = new Date(created);
  return group(created) === t("今天") ? date.toLocaleTimeString(dateLocale, { hour: "2-digit", minute: "2-digit", hour12: false })
    : date.toLocaleDateString(dateLocale, { month: "numeric", day: "numeric" });
}

/** What came of a run, in a few characters: the objective when it solved, otherwise its state. */
export function resultText(entry: Entry): string {
  if (entry.meta.kind === "optimization") return entry.state === "running" ? t("正在处理") : entry.failure ? t("对话未完成") : t("优化对话");
  if (entry.meta.kind === "solution_chat") return entry.state === "running" ? t("正在讨论") : entry.failure ? t("讨论未完成") : t("方案对话");
  if (entry.meta.kind === "requirements") return entry.state === "running" ? t("正在整理")
    : entry.failure ? t("整理未完成") : t("需求对话");
  if (entry.state === "running") return t("建模中");
  return entry.objective != null && tone(entry.state) === "good" ? formatNumber(entry.objective) : STATUS[entry.state] ?? entry.state;
}

/** Whether a run matches a search: every word is in its title, method, model, note or tags; `#tag` needs that tag. */
export function matches(entry: Entry, query: string, methodName: (id: string) => string): boolean {
  const text = [entry.meta.title, isRunEntry(entry) ? methodName(entry.meta.method) : entry.meta.kind === "optimization" ? t("优化对话") : entry.meta.kind === "requirements" ? t("需求对话") : t("方案对话"),
    entry.meta.model ?? "", entry.meta.note ?? "", ...(entry.meta.tags ?? [])]
    .join("\n").toLowerCase();
  const tags = (entry.meta.tags ?? []).map(tag => tag.toLowerCase());
  return query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    .every(word => word.startsWith("#") && word.length > 1 ? tags.includes(word.slice(1)) : text.includes(word));
}

export function Sidebar({ entries, current, options, presets, query, onQuery, hasMore, loading, error, onLoadMore, onRetry,
  onNew, onAgent, onOpen, onCompare, onDelete, onExamples, onPresets }: {
  entries: Entry[]; current: string | null; options: Options | null; presets: Preset[];
  query: string; onQuery: (query: string) => void;
  hasMore: boolean; loading: boolean; error: string | null; onLoadMore: () => void; onRetry: () => void;
  onNew: () => void; onAgent: () => void; onOpen: (entry: Entry) => void; onCompare: (group: string) => void; onDelete: (entry: Entry) => void;
  onExamples: () => void; onPresets: () => void;
}) {
  const methodName = (id: string) => options?.methods.find(item => item.id === id)?.name ?? id;
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const shown = groupHistory(entries).filter(item => [item.entry, ...item.related].some(entry => matches(entry, query, methodName)));
  const tags = [...new Set(entries.flatMap(entry => entry.meta.tags ?? []))].slice(0, 12);
  const groups = new Map<string, HistoryGroup[]>();
  for (const item of shown) groups.set(group(item.created), [...(groups.get(group(item.created)) ?? []), item]);
  const preset = presets[0];

  const row = (entry: Entry) => {
    const selectedItem = entry.id === current;
    const comparison = isRunEntry(entry) ? entry.meta.group : null;
    return <div className="group/item relative">
      <button onClick={() => onOpen(entry)} title={entry.meta.title} aria-current={selectedItem ? "page" : undefined}
        className={cn("flex w-full flex-col gap-1 rounded-md px-2.5 py-2 pr-8 text-left transition-colors hover:bg-sidebar-accent",
          selectedItem && "bg-sidebar-accent")}>
        <span className="flex items-center gap-2">
          {!isRunEntry(entry) ? <MessageSquare className="size-3.5 shrink-0 text-muted-foreground" />
            : <StatusIcon status={entry.state} className="size-3.5 shrink-0" />}
          <span className={cn("truncate text-[13px]", selectedItem ? "font-medium" : "text-foreground/90")}>{entry.meta.title}</span>
        </span>
        <span className="flex items-center gap-1.5 pl-5.5 text-[11px] text-muted-foreground">
          <span className={cn("shrink-0 whitespace-nowrap tabular font-medium", TONE[tone(entry.state)].text)}>{resultText(entry)}</span>
          <span>·</span><span className="truncate">{isRunEntry(entry) ? methodName(entry.meta.method) : entry.meta.model}</span>
          {comparison ? <Columns3 className="size-3 shrink-0" aria-label={isRunEntry(entry) && entry.meta.scenario ? t("业务场景对比") : t("方法对比")} /> : null}
          <span className="ml-auto shrink-0 tabular">{when(entry.created)}</span>
        </span>
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-sm" aria-label={t("更多操作：{title}", { title: entry.meta.title })}
            className="absolute top-1 right-1 opacity-100 [@media(hover:hover)]:opacity-0 group-hover/item:opacity-100 group-focus-within/item:opacity-100 data-[state=open]:opacity-100">
            <MoreHorizontal /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" side="right">
          {comparison ? <DropdownMenuItem onClick={() => onCompare(comparison)}><Columns3 />{t("查看对比")}</DropdownMenuItem> : null}
          <DropdownMenuItem variant="destructive" onClick={() => onDelete(entry)}><Trash2 />{t("删除")}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>;
  };

  return <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
    <div className="flex flex-col gap-3 p-3 pb-2">
      <a className="flex items-center gap-2.5 rounded-md px-1.5 py-1" href="/" onClick={event => { event.preventDefault(); onNew(); }}>
        <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-primary to-violet-500 text-primary-foreground shadow-sm">
          <ChartSpline className="size-4.5" />
        </span>
        <span className="flex flex-col leading-tight">
          <span className="text-sm font-semibold tracking-tight">LLM4OM</span>
          <span className="text-[11px] text-muted-foreground">{t("优化建模工作台")}</span>
        </span>
      </a>
      <Button onClick={onNew} className="w-full justify-start"><Plus />{t("新建建模")}</Button>
      <Button variant="outline" onClick={onAgent} className="w-full justify-start"><Sparkles />{t("优化对话")}</Button>
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input aria-label={t("搜索运行")} placeholder={t("搜索问题或方法")} value={query} onChange={event => onQuery(event.target.value)}
          className="h-9 bg-background pr-8 pl-8 text-[13px]" />
        {query ? <Button variant="ghost" size="icon-xs" aria-label={t("清除搜索")} className="absolute top-1/2 right-1 -translate-y-1/2" onClick={() => onQuery("")}><X /></Button> : null}
      </div>
      {tags.length ? <div className="flex flex-wrap gap-1" aria-label={t("按标签筛选")}>
        {tags.map(tag => {
          const on = query.split(/\s+/).includes(`#${tag}`);
          return <button key={tag} onClick={() => onQuery(on ? query.split(/\s+/).filter(word => word !== `#${tag}`).join(" ")
            : `${query.trim()} #${tag}`.trim())} className={cn("rounded-full border px-2 py-0.5 text-[11px] transition-colors hover:bg-sidebar-accent",
            on ? "border-primary/40 bg-primary/10 text-primary" : "text-muted-foreground")}>#{tag}</button>;
        })}
      </div> : null}
    </div>

    <div className="min-h-0 flex-1 overflow-y-auto">
      <nav aria-label={t("运行记录")} className="px-2 pb-3">
        {!entries.length && !loading && !error ? <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-xs text-muted-foreground">
          <History className="size-5" />{t("运行记录会出现在这里。")}</div> : null}
        {entries.length && !shown.length ? <p className="px-3 py-6 text-center text-xs text-muted-foreground">{t("没有匹配的运行。")}</p> : null}
        {[...groups].map(([label, items]) => <section key={label} className="mt-2">
          <h2 className="px-2.5 py-1.5 text-[11px] font-medium text-muted-foreground">{label}</h2>
          <ul className="flex flex-col gap-0.5">{items.map(({ entry, related }) => {
            const open = expanded[entry.id] ?? (!!query.trim() || related.some(item => item.id === current));
            return <li key={entry.id}>
              {row(entry)}
              {related.length ? <>
                <Button variant="ghost" size="xs" aria-expanded={open} className="mb-1 ml-6 h-6 gap-1 text-[11px] font-normal text-muted-foreground"
                  aria-label={t("相关记录：{title}", { title: entry.meta.title })}
                  onClick={() => setExpanded(value => ({ ...value, [entry.id]: !open }))}>
                  <ChevronDown className={cn("size-3 transition-transform", !open && "-rotate-90")} />{t("{count} 条相关记录", { count: related.length })}
                </Button>
                {open ? <ul className="mb-2 ml-4 border-l pl-1">{related.map(item => <li key={item.id}>{row(item)}</li>)}</ul> : null}
              </> : null}
            </li>;
          })}</ul>
        </section>)}
        {error ? <div className="p-3 text-xs text-destructive"><p>{error}</p><Button variant="link" size="sm" onClick={onRetry}>{t("重试")}</Button></div> : null}
        {hasMore ? <div className="p-2 text-center">
          {query ? <p className="mb-1 text-xs text-muted-foreground">{t("正在搜索已加载的 {count} 条记录", { count: entries.length })}</p> : null}
          <Button variant="outline" size="sm" className="w-full" disabled={loading} onClick={onLoadMore}>
            {loading ? t("正在加载……") : t("加载更早的运行")}</Button>
        </div> : null}
      </nav>
    </div>

    <div className="flex flex-col gap-0.5 border-t p-2">
      <Button variant="ghost" className="h-9 justify-start font-normal" onClick={onExamples}><BookOpen />{t("示例题库")}</Button>
      <div className="flex items-center gap-1">
        <Button variant="ghost" className="h-auto min-w-0 flex-1 justify-start py-1.5 font-normal" onClick={onPresets}>
          <Cpu />
          <span className="flex min-w-0 flex-col items-start leading-tight">
            <span>{t("预设模型")}</span>
            <span className={cn("truncate text-[11px]", preset ? "text-muted-foreground" : "text-destructive")}>
              {preset ? presets.length > 1 ? t("{model} 等 {count} 个", { model: preset.name || preset.model, count: presets.length }) : preset.name || preset.model : t("未配置")}</span>
          </span>
        </Button>
        <ThemeMenu />
      </div>
    </div>
  </div>;
}
