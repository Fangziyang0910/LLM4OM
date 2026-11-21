import { useState } from "react";
import { BookOpen, ChartSpline, ChevronDown, Columns3, Cpu, History, MessageSquareText, MoreHorizontal, PanelLeftClose, Plus, Search, Trash2, X } from "lucide-react";
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

/** Concise, user-friendly outcome summary without developer jargon. */
export function resultText(entry: Entry): string {
  if (!isRunEntry(entry) && ["pending", "interrupted", "error", "timeout"].includes(entry.state)) return STATUS[entry.state];
  if (entry.meta.kind === "optimization") return entry.state === "running" ? t("正在规划…") : entry.failure ? t("对话中断") : t("对话规划");
  if (entry.meta.kind === "solution_chat") return entry.state === "running" ? t("正在解答…") : entry.failure ? t("问答中断") : t("方案追问");
  if (entry.meta.kind === "requirements") return entry.state === "running" ? t("正在梳理…")
    : entry.failure ? t("梳理中断") : t("需求梳理");
  if (entry.state === "running") return t("正在求解…");
  if (entry.paretoTotal && entry.paretoTotal > 0 && tone(entry.state) === "good") return t("{count} 个 Pareto 解", { count: entry.paretoTotal });
  if (entry.objective != null && tone(entry.state) === "good") return `${STATUS[entry.state] ?? entry.state} · ${formatNumber(entry.objective)}`;
  if (entry.state === "infeasible") return t("条件冲突");
  return STATUS[entry.state] ?? entry.state;
}

/** Whether a run matches a search: every word is in its title, method, model, note or tags; `#tag` needs that tag. */
export function matches(entry: Entry, query: string, methodName: (id: string) => string): boolean {
  const text = [entry.meta.title, isRunEntry(entry) ? methodName(entry.meta.method) : entry.meta.kind === "optimization" ? t("对话规划") : entry.meta.kind === "requirements" ? t("需求梳理") : t("方案追问"),
    entry.meta.model ?? "", entry.meta.note ?? "", ...(entry.meta.tags ?? [])]
    .join("\n").toLowerCase();
  const tags = (entry.meta.tags ?? []).map(tag => tag.toLowerCase());
  return query.trim().toLowerCase().split(/\s+/).filter(Boolean)
    .every(word => word.startsWith("#") && word.length > 1 ? tags.includes(word.slice(1)) : text.includes(word));
}

export function Sidebar({ entries, current, activeMode = "quick", options, presets, query, onQuery, hasMore, loading, error, onLoadMore, onRetry,
  onNew, onAgent, onOpen, onCompare, onDelete, onExamples, onPresets, onCollapse }: {
  entries: Entry[]; current: string | null; activeMode?: "quick" | "agent"; options: Options | null; presets: Preset[];
  query: string; onQuery: (query: string) => void;
  hasMore: boolean; loading: boolean; error: string | null; onLoadMore: () => void; onRetry: () => void;
  onNew: () => void; onAgent: () => void; onOpen: (entry: Entry) => void; onCompare: (group: string) => void; onDelete: (entry: Entry) => void;
  onExamples: () => void; onPresets: () => void; onCollapse?: () => void;
}) {
  const methodName = (id: string) => options?.methods.find(item => item.id === id)?.name ?? id;
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const shown = groupHistory(entries).filter(item => [item.entry, ...item.related].some(entry => matches(entry, query, methodName)));
  const tags = [...new Set(entries.flatMap(entry => entry.meta.tags ?? []))].slice(0, 12);
  const groups = new Map<string, HistoryGroup[]>();
  for (const item of shown) {
    const label = group(item.created);
    groups.set(label, [...(groups.get(label) ?? []), item]);
  }
  const preset = presets[0];

  const row = (entry: Entry) => {
    const selectedItem = entry.id === current;
    const comparison = isRunEntry(entry) ? entry.meta.group : null;
    return <div className="group/item relative">
      <button onClick={() => onOpen(entry)} title={entry.meta.title} aria-current={selectedItem ? "page" : undefined}
        className={cn("flex w-full flex-col gap-0.5 rounded-lg px-2.5 py-2 text-left transition-colors duration-150 hover:bg-sidebar-accent/70",
          selectedItem && "bg-sidebar-accent ring-1 ring-primary/15")}>
        <span className="flex min-w-0 items-center gap-2 pr-5 [@media(hover:hover)]:pr-0 [@media(hover:hover)]:group-hover/item:pr-6 [@media(hover:hover)]:group-focus-within/item:pr-6">
          {!isRunEntry(entry) ? <MessageSquareText className={cn("size-3.5 shrink-0", selectedItem ? "text-primary" : "text-muted-foreground")} />
            : <StatusIcon status={entry.state} className="size-3.5 shrink-0" />}
          <span className={cn("min-w-0 flex-1 truncate text-[13px] leading-5", selectedItem ? "font-medium text-foreground" : "text-foreground/90")}>{entry.meta.title}</span>
        </span>
        <span className="flex min-w-0 items-center gap-1.5 pl-[22px] text-[11px] leading-4 text-muted-foreground">
          <span className={cn("min-w-0 truncate tabular", TONE[tone(entry.state)].text)}>{resultText(entry)}</span>
          {comparison ? <Columns3 className="size-3 shrink-0 text-muted-foreground/70" aria-label={isRunEntry(entry) && entry.meta.scenario ? t("多情景对比") : t("多方案对比")} /> : null}
          <span className="ml-auto shrink-0 tabular text-muted-foreground/70 transition-opacity [@media(hover:hover)]:group-hover/item:opacity-0 [@media(hover:hover)]:group-focus-within/item:opacity-0">{when(entry.created)}</span>
        </span>
      </button>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button variant="ghost" size="icon-xs" aria-label={t("更多操作：{title}", { title: entry.meta.title })}
            className="absolute top-1.5 right-1.5 size-6 rounded-md opacity-100 [@media(hover:hover)]:opacity-0 group-hover/item:opacity-100 group-focus-within/item:opacity-100 data-[state=open]:opacity-100">
            <MoreHorizontal className="size-3.5" /></Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" side="right">
          {comparison ? <DropdownMenuItem onClick={() => onCompare(comparison)}><Columns3 />{t("查看对比")}</DropdownMenuItem> : null}
          <DropdownMenuItem variant="destructive" onClick={() => onDelete(entry)}><Trash2 />{t("删除")}</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>;
  };

  return <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground select-none">
    <div className="flex flex-col gap-2.5 px-3 pt-3 pb-2.5">
      <div className="flex items-center gap-1">
        <a className="group flex min-w-0 flex-1 items-center gap-2 rounded-lg px-1 py-1 transition-colors hover:bg-sidebar-accent/50" href="/"
          title={t("通用智能优化求解器 — 求解各种复杂优化问题的通用求解器")} onClick={event => { event.preventDefault(); onAgent(); }}>
          <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground shadow-2xs">
            <ChartSpline className="size-4" />
          </span>
          <span className="min-w-0 truncate text-[14px] font-semibold tracking-tight">{t("通用智能优化求解器")}</span>
        </a>
        {onCollapse ? <Button type="button" variant="ghost" size="icon-sm" aria-label={t("收起侧边栏")} title={t("收起侧边栏")}
          className="size-7 shrink-0 rounded-lg text-muted-foreground hover:text-foreground" onClick={onCollapse}>
          <PanelLeftClose className="size-4" />
        </Button> : null}
      </div>

      <Button type="button" onClick={onAgent} className="h-9 w-full justify-center gap-1.5 rounded-lg text-[13px] font-medium shadow-2xs">
        <Plus className="size-4" />
        <span>{t("新建优化任务")}</span>
      </Button>

      {entries.length > 0 || query ? <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input aria-label={t("搜索记录")} placeholder={t("搜索历史记录…")} value={query} onChange={event => onQuery(event.target.value)}
          className="h-8 rounded-lg bg-background/80 pr-7 pl-8 text-xs shadow-none" />
        {query ? <Button variant="ghost" size="icon-xs" aria-label={t("清除搜索")} className="absolute top-1/2 right-1 -translate-y-1/2" onClick={() => onQuery("")}><X /></Button> : null}
      </div> : null}

      {tags.length ? <div className="flex flex-wrap gap-1" aria-label={t("按标签筛选")}>
        {tags.map(tag => {
          const words = query.trim().split(/\s+/).filter(Boolean);
          const lowerTag = `#${tag.toLowerCase()}`;
          const on = words.some(word => word.toLowerCase() === lowerTag);
          return <button key={tag} onClick={() => onQuery(on ? words.filter(word => word.toLowerCase() !== lowerTag).join(" ")
            : `${query.trim()} #${tag}`.trim())} title={`#${tag}`} className={cn("max-w-full truncate rounded-full border px-2 py-0.5 text-[11px] transition-colors hover:bg-sidebar-accent",
            on ? "border-primary/40 bg-primary/10 font-medium text-primary" : "text-muted-foreground")}>#{tag}</button>;
        })}
      </div> : null}
    </div>

    <div className="min-h-0 flex-1 overflow-y-auto">
      <nav aria-label={t("运行记录")} className="px-3 pb-3">
        {!entries.length && !loading && !error ? <div className="mt-2 flex flex-col items-center gap-1.5 rounded-lg border border-dashed bg-background/40 px-4 py-7 text-center text-xs text-muted-foreground">
          <History className="size-4 text-muted-foreground/60" />
          <p className="font-medium text-foreground/75">{t("暂无求解记录")}</p>
        </div> : null}
        {entries.length && !shown.length ? <p className="px-2.5 py-6 text-center text-xs text-muted-foreground">{t("没有找到匹配的记录。")}</p> : null}
        {[...groups].map(([label, items]) => <section key={label} className="mt-3 first:mt-1">
          <h2 className="px-2.5 pb-1 text-[11px] font-medium text-muted-foreground/75">{label}</h2>
          <ul className="flex flex-col gap-0.5">{items.map(({ entry, related }) => {
            const hasActiveOrMatchingChild = related.some(item => item.id === current)
              || (!!query.trim() && related.some(item => matches(item, query, methodName)));
            const open = (!!query.trim() && related.some(item => matches(item, query, methodName)))
              || (expanded[entry.id] ?? hasActiveOrMatchingChild);
            return <li key={entry.id}>
              {row(entry)}
              {related.length ? <>
                <Button variant="ghost" size="xs" aria-expanded={open} className="mb-1 ml-[22px] h-6 gap-1 rounded-md px-1.5 text-[11px] font-normal text-muted-foreground"
                  aria-label={t("相关记录：{title}", { title: entry.meta.title })}
                  onClick={() => setExpanded(value => ({ ...value, [entry.id]: !open }))}>
                  <ChevronDown className={cn("size-3 transition-transform duration-150", !open && "-rotate-90")} />{t("{count} 条衍生方案", { count: related.length })}
                </Button>
                {open ? <ul className="mb-2 ml-4 border-l border-border/70 pl-1.5">{related.map(item => <li key={item.id}>{row(item)}</li>)}</ul> : null}
              </> : null}
            </li>;
          })}</ul>
        </section>)}
        {error ? <div className="p-2.5 text-xs text-destructive"><p>{error}</p><Button variant="link" size="sm" className="px-0" onClick={onRetry}>{t("重试")}</Button></div> : null}
        {hasMore ? <div className="pt-2 text-center">
          {query ? <p className="mb-1 text-xs text-muted-foreground">{t("正在搜索已加载的 {count} 条记录", { count: entries.length })}</p> : null}
          <Button variant="outline" size="sm" className="w-full rounded-lg" disabled={loading} onClick={onLoadMore}>
            {loading ? t("正在加载……") : t("加载更早的记录")}</Button>
        </div> : null}
      </nav>
    </div>

    <div className="flex flex-col gap-0.5 border-t border-sidebar-border/80 bg-sidebar/80 p-3 py-2">
      <Button variant={activeMode === "quick" && !current ? "secondary" : "ghost"}
        className="h-8.5 justify-start gap-2.5 rounded-lg px-2.5 text-[13px] font-normal text-foreground/85 hover:bg-sidebar-accent"
        title={t("同一问题并排体验多种建模方法、模型或求解器")}
        onClick={onNew}>
        <Columns3 className="size-4 shrink-0 text-muted-foreground" />{t("多方案对比")}
      </Button>
      <Button variant="ghost" className="h-8.5 justify-start gap-2.5 rounded-lg px-2.5 text-[13px] font-normal text-foreground/85 hover:bg-sidebar-accent" onClick={onExamples}>
        <BookOpen className="size-4 shrink-0 text-muted-foreground" />{t("案例模板库")}
      </Button>
      <div className="flex items-center gap-1">
        <Button variant="ghost" className="h-8.5 min-w-0 flex-1 justify-start gap-2.5 rounded-lg px-2.5 text-[13px] font-normal text-foreground/85 hover:bg-sidebar-accent"
          title={preset ? `${preset.name || preset.model}` : t("点击配置可用模型")} onClick={onPresets}>
          <Cpu className="size-4 shrink-0 text-muted-foreground" />
          <span className="truncate">{t("AI 模型")}</span>
          <span className={cn("ml-auto size-1.5 shrink-0 rounded-full", preset ? "bg-success" : "bg-destructive")} />
        </Button>
        <ThemeMenu />
      </div>
    </div>
  </div>;
}
