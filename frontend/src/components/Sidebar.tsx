import { useState } from "react";
import { BookOpen, ChartSpline, Clock, Cpu, Plus, Search, Trash2 } from "lucide-react";
import { STATUS, formatNumber, tone } from "../api";
import type { Entry, Options, Settings } from "../types";

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

export function Sidebar({ entries, current, options, settings, onNew, onOpen, onDelete, onExamples, onSettings }: {
  entries: Entry[]; current: string | null; options: Options | null; settings: Settings;
  onNew: () => void; onOpen: (id: string) => void; onDelete: (entry: Entry) => void; onExamples: () => void; onSettings: () => void;
}) {
  const [query, setQuery] = useState("");
  const methodName = (id: string) => options?.methods.find(item => item.id === id)?.name ?? id;
  const languageName = (id: string) => options?.languages.find(item => item.id === id)?.name ?? id;
  const search = query.trim().toLowerCase();
  const shown = entries.filter(entry => !search || entry.meta.title.toLowerCase().includes(search)
    || methodName(entry.meta.method).toLowerCase().includes(search));
  const groups = new Map<string, Entry[]>();
  for (const entry of shown) groups.set(group(entry.created), [...(groups.get(group(entry.created)) ?? []), entry]);
  const selected = settings.selected ? settings.profiles[settings.selected] : undefined;

  return <aside className="sidebar" aria-label="导航">
    <div className="sidebar-top">
      <a className="brand" href="/" onClick={event => { event.preventDefault(); onNew(); }}>
        <span className="brand-mark"><ChartSpline /></span>
        <span>LLM4OM</span>
      </a>
      <button className="button primary block" onClick={onNew}><Plus size={16} />新建建模</button>
      {entries.length > 6 ? <div className="search"><Search size={15} />
        <input aria-label="搜索运行" placeholder="搜索运行" value={query} onChange={event => setQuery(event.target.value)} /></div> : null}
    </div>

    <nav className="history" aria-label="运行记录">
      {!entries.length ? <div className="history-empty"><Clock size={20} /><p>运行记录会出现在这里。</p></div> : null}
      {entries.length && !shown.length ? <p className="history-empty">没有匹配的运行。</p> : null}
      {[...groups].map(([label, items]) => <section key={label}>
        <h2>{label}</h2>
        <ul>{items.map(entry => {
          const result = entry.state === "running" ? "建模中" : entry.objective != null && tone(entry.state) === "good"
            ? `目标值 ${formatNumber(entry.objective)}` : STATUS[entry.state] ?? entry.state;
          return <li key={entry.id} className={entry.id === current ? "selected" : ""}>
            <button className="history-item" onClick={() => onOpen(entry.id)} aria-current={entry.id === current ? "page" : undefined}>
              <span className="history-title">{entry.meta.title}</span>
              <span className="history-meta">
                <span className={`dot ${tone(entry.state)}`} />
                <span className={`history-result ${tone(entry.state)}`}>{result}</span>
                <span className="history-config" title={`${methodName(entry.meta.method)} · ${languageName(entry.meta.language)}`}>{methodName(entry.meta.method)}</span>
                <span className="history-time">{when(entry.created)}</span>
              </span>
            </button>
            <button className="icon-button remove" aria-label={`删除 ${entry.meta.title}`} title="删除" onClick={() => onDelete(entry)}>
              <Trash2 size={14} /></button>
          </li>;
        })}</ul>
      </section>)}
    </nav>

    <div className="sidebar-foot">
      <button className="nav-item" onClick={onExamples}><BookOpen size={17} />示例题库</button>
      <button className="nav-item" onClick={onSettings}><Cpu size={17} />
        <span className="nav-text">LLM 服务<span className="muted">{selected ? selected.model : "未配置"}</span></span>
        {!selected ? <span className="dot bad" /> : null}
      </button>
    </div>
  </aside>;
}
