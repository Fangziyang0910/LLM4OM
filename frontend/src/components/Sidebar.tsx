import { useState } from "react";
import { BookOpen, ChartSpline, Cpu, History, MoreHorizontal, Plus, Search, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { STATUS, formatNumber, tone } from "@/format";
import type { Entry, Options, Preset } from "@/types";
import { StatusIcon, TONE } from "./status";
import { ThemeMenu } from "./theme";

const DAY = 86_400_000;

function group(created: string): string {
  const today = new Date(); today.setHours(0, 0, 0, 0);
  const time = Date.parse(created);
  if (time >= today.getTime()) return "今天";
  if (time >= today.getTime() - DAY) return "昨天";
  if (time >= today.getTime() - 6 * DAY) return "近 7 天";
  return "更早";
}

function when(created: string): string {
  const date = new Date(created);
  return group(created) === "今天" ? date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false })
    : date.toLocaleDateString("zh-CN", { month: "numeric", day: "numeric" });
}

/** What came of a run, in a few characters: the objective when it solved, otherwise its state. */
export function resultText(entry: Entry): string {
  if (entry.state === "running") return "建模中";
  return entry.objective != null && tone(entry.state) === "good" ? formatNumber(entry.objective) : STATUS[entry.state] ?? entry.state;
}

export function Sidebar({ entries, current, options, presets, onNew, onOpen, onDelete, onExamples, onPresets }: {
  entries: Entry[]; current: string | null; options: Options | null; presets: Preset[];
  onNew: () => void; onOpen: (id: string) => void; onDelete: (entry: Entry) => void; onExamples: () => void; onPresets: () => void;
}) {
  const [query, setQuery] = useState("");
  const methodName = (id: string) => options?.methods.find(item => item.id === id)?.name ?? id;
  const search = query.trim().toLowerCase();
  const shown = entries.filter(entry => !search || entry.meta.title.toLowerCase().includes(search)
    || methodName(entry.meta.method).toLowerCase().includes(search));
  const groups = new Map<string, Entry[]>();
  for (const entry of shown) groups.set(group(entry.created), [...(groups.get(group(entry.created)) ?? []), entry]);
  const preset = presets[0];

  return <div className="flex h-full flex-col bg-sidebar text-sidebar-foreground">
    <div className="flex flex-col gap-3 p-3 pb-2">
      <a className="flex items-center gap-2.5 rounded-md px-1.5 py-1" href="/" onClick={event => { event.preventDefault(); onNew(); }}>
        <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-primary to-violet-500 text-primary-foreground shadow-sm">
          <ChartSpline className="size-4.5" />
        </span>
        <span className="flex flex-col leading-tight">
          <span className="text-sm font-semibold tracking-tight">LLM4OM</span>
          <span className="text-[11px] text-muted-foreground">优化建模工作台</span>
        </span>
      </a>
      <Button onClick={onNew} className="w-full justify-start"><Plus />新建建模</Button>
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input aria-label="搜索运行" placeholder="搜索问题或方法" value={query} onChange={event => setQuery(event.target.value)}
          className="h-8 bg-background pl-8 text-[13px]" />
      </div>
    </div>

    <div className="min-h-0 flex-1 overflow-y-auto">
      <nav aria-label="运行记录" className="px-2 pb-3">
        {!entries.length ? <div className="flex flex-col items-center gap-2 px-4 py-10 text-center text-xs text-muted-foreground">
          <History className="size-5" />运行记录会出现在这里。</div> : null}
        {entries.length && !shown.length ? <p className="px-3 py-6 text-center text-xs text-muted-foreground">没有匹配的运行。</p> : null}
        {[...groups].map(([label, items]) => <section key={label} className="mt-2">
          <h2 className="px-2.5 py-1.5 text-[11px] font-medium text-muted-foreground">{label}</h2>
          <ul className="flex flex-col gap-0.5">{items.map(entry => {
            const selectedItem = entry.id === current;
            return <li key={entry.id} className="group/item relative">
              <button onClick={() => onOpen(entry.id)} aria-current={selectedItem ? "page" : undefined}
                className={cn("flex w-full flex-col gap-1 rounded-md px-2.5 py-2 pr-8 text-left transition-colors hover:bg-sidebar-accent",
                  selectedItem && "bg-sidebar-accent")}>
                <span className="flex items-center gap-2">
                  <StatusIcon status={entry.state} className="size-3.5 shrink-0" />
                  <span className={cn("truncate text-[13px]", selectedItem ? "font-medium" : "text-foreground/90")}>{entry.meta.title}</span>
                </span>
                <span className="flex items-center gap-1.5 pl-5.5 text-[11px] text-muted-foreground">
                  <span className={cn("tabular font-medium", TONE[tone(entry.state)].text)}>{resultText(entry)}</span>
                  <span>·</span><span className="truncate">{methodName(entry.meta.method)}</span>
                  <span className="ml-auto shrink-0 tabular">{when(entry.created)}</span>
                </span>
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="ghost" size="icon-xs" aria-label={`更多操作：${entry.meta.title}`}
                    className="absolute top-1.5 right-1.5 opacity-0 group-hover/item:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100">
                    <MoreHorizontal /></Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" side="right">
                  <DropdownMenuItem variant="destructive" onClick={() => onDelete(entry)}><Trash2 />删除</DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </li>;
          })}</ul>
        </section>)}
      </nav>
    </div>

    <div className="flex flex-col gap-0.5 border-t p-2">
      <Button variant="ghost" className="h-9 justify-start font-normal" onClick={onExamples}><BookOpen />示例题库</Button>
      <div className="flex items-center gap-1">
        <Button variant="ghost" className="h-auto min-w-0 flex-1 justify-start py-1.5 font-normal" onClick={onPresets}>
          <Cpu />
          <span className="flex min-w-0 flex-col items-start leading-tight">
            <span>预设模型</span>
            <span className={cn("truncate text-[11px]", preset ? "text-muted-foreground" : "text-destructive")}>
              {preset ? presets.length > 1 ? `${preset.model} 等 ${presets.length} 个` : preset.model : "未配置"}</span>
          </span>
        </Button>
        <ThemeMenu />
      </div>
    </div>
  </div>;
}
