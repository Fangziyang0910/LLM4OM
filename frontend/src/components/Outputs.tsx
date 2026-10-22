import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, CodeXml, Copy, Download, FileText, type LucideIcon, Search, Sigma, Table } from "lucide-react";
import { STATUS, formatNumber, tone } from "../format";
import { versions, type Version } from "../steps";
import type { Language, RunValues, Solve, Step } from "../types";
import { Code, Markdown, copyText, download } from "./Content";

export type Tab = "solution" | "formulation" | "code" | "problem";
const TABS: [Tab, string, LucideIcon][] = [
  ["solution", "解", Table], ["formulation", "数学模型", Sigma], ["code", "求解代码", CodeXml], ["problem", "问题", FileText],
];

/** What the run produced: the solution, the formulation and the code (each in every version), and the problem. */
export function Outputs({ values, steps, active, tab, setTab, picked, setPicked, language, finished }: {
  values: RunValues; steps: Step[]; active: boolean; tab: Tab; setTab: (tab: Tab) => void;
  picked: Partial<Record<"formulation" | "code", string>>; setPicked: (key: "formulation" | "code", id: string | undefined) => void;
  language?: Language; finished: boolean;
}) {
  const formulations = useMemo(() => versions(steps, "formulation", values.formulation), [steps, values.formulation]);
  const codes = useMemo(() => versions(steps, "code", values.code), [steps, values.code]);
  const fresh: Partial<Record<Tab, boolean>> = active ? { formulation: formulations.length > 0, code: codes.length > 0 } : {};

  return <div className="outputs">
    <div className="tabs" role="tablist" aria-label="运行产物">
      {TABS.map(([id, label, TabIcon]) => <button key={id} role="tab" aria-selected={tab === id}
        className={"tab" + (tab === id ? " active" : "")} onClick={() => setTab(id)}>
        <TabIcon size={15} />{label}
        {id === "formulation" && formulations.length > 1 ? <span className="count">{formulations.length}</span> : null}
        {id === "code" && codes.length > 1 ? <span className="count">{codes.length}</span> : null}
        {fresh[id] ? <span className="live-dot" aria-label="正在更新" /> : null}
      </button>)}
    </div>
    <div className="pane-scroll tab-body" role="tabpanel">
      {tab === "solution" ? values.solve ? <SolveView solve={values.solve} />
        : <Empty icon={Table} text={active ? "代码在沙箱中求解后，解会显示在这里。" : values.failure ? "方法没有给出可求解的代码，因此没有解。" : finished ? "没有求解结果。" : "运行没有完成。"} />
        : null}
      {tab === "formulation" ? <Versioned items={formulations} picked={picked.formulation} pick={id => setPicked("formulation", id)}
        noun="数学模型" active={active} file="formulation.md"
        empty={active ? "方法给出数学模型后显示在这里。" : "这个方法没有单独给出数学模型；请看求解代码。"}
        render={text => <Markdown text={text} />} /> : null}
      {tab === "code" ? <Versioned items={codes} picked={picked.code} pick={id => setPicked("code", id)}
        noun="代码" active={active} file="model.py" extra={language ? `${language.name} · 由 ${language.solver} 求解` : undefined}
        empty={active ? "方法写出代码后显示在这里。" : "没有求解代码。"}
        render={text => <Code text={text} />} /> : null}
      {tab === "problem" ? <div className="problem">
        <p className="problem-text">{values.description}</p>
        {Object.entries(values.data ?? {}).map(([name, content]) => <details key={name} className="disclosure">
          <summary><FileText size={14} />{name}<span className="muted">{content.split("\n").filter(Boolean).length} 行</span></summary>
          <pre className="plain">{content}</pre>
        </details>)}
      </div> : null}
    </div>
  </div>;
}

function Empty({ icon: EmptyIcon, text }: { icon: LucideIcon; text: string }) {
  return <div className="empty"><EmptyIcon size={28} /><p>{text}</p></div>;
}

function Versioned({ items, picked, pick, noun, active, file, extra, empty, render }: {
  items: Version[]; picked?: string; pick: (id: string | undefined) => void; noun: string; active: boolean; file: string;
  extra?: string; empty: string; render: (text: string) => React.ReactNode;
}) {
  if (!items.length) return <Empty icon={noun === "代码" ? CodeXml : Sigma} text={empty} />;
  const index = Math.max(0, items.findIndex(item => item.id === picked));
  const current = picked && items.some(item => item.id === picked) ? items[index] : items[items.length - 1];
  const position = items.indexOf(current);
  const latest = position === items.length - 1;
  return <div className="versioned">
    <div className="toolbar">
      {items.length > 1 ? <div className="stepper">
        <button className="icon-button" aria-label="上一版" disabled={position === 0} onClick={() => pick(items[position - 1].id)}><ChevronLeft size={15} /></button>
        <select aria-label={`${noun}版本`} value={current.id} onChange={event => pick(event.target.value === items[items.length - 1].id ? undefined : event.target.value)}>
          {items.map((item, number) => <option key={item.id} value={item.id}>第 {number + 1} 版 · {item.title}</option>)}
        </select>
        <button className="icon-button" aria-label="下一版" disabled={latest} onClick={() => pick(position + 1 === items.length - 1 ? undefined : items[position + 1].id)}><ChevronRight size={15} /></button>
      </div> : <span className="muted">{current.title}</span>}
      {extra ? <span className="muted">{extra}</span> : null}
      <span className="spacer" />
      <button className="icon-button" title="复制" aria-label={`复制${noun}`} onClick={() => copyText(current.text)}><Copy size={15} /></button>
      <button className="icon-button" title="下载" aria-label={`下载${noun}`} onClick={() => download(file, current.text)}><Download size={15} /></button>
    </div>
    {!latest ? <p className="note">这是第 {position + 1} 版，不是{active ? "目前" : "最终"}的{noun}。<button className="link" onClick={() => pick(undefined)}>看最新一版</button></p> : null}
    {render(current.text)}
  </div>;
}

function SolveView({ solve }: { solve: Solve }) {
  const [all, setAll] = useState(false);
  const [filter, setFilter] = useState("");
  const [limit, setLimit] = useState(200);
  const entries = Object.entries(solve.variables);
  const nonzero = entries.filter(([, value]) => value !== 0).length;
  const query = filter.trim().toLowerCase();
  const shown = entries.filter(([name, value]) => (all || value !== 0) && (!query || name.toLowerCase().includes(query)));
  return <div className="solution">
    <div className="metrics">
      <div><span className="eyebrow">求解状态</span><span className={`badge large ${tone(solve.status)}`}>{STATUS[solve.status] ?? solve.status}</span></div>
      <div><span className="eyebrow">目标值</span><strong className="number">{solve.objective != null ? formatNumber(solve.objective) : "—"}</strong></div>
      <div><span className="eyebrow">非零变量 / 变量</span><strong className="number">{nonzero} / {entries.length}</strong></div>
    </div>
    {solve.error ? <div className="callout bad"><strong>代码执行出错</strong><pre className="plain">{solve.error}</pre></div> : null}
    {entries.length ? <>
      <div className="toolbar">
        <div className="search"><Search size={15} />
          <input aria-label="筛选变量" placeholder="按名称筛选" value={filter} onChange={event => setFilter(event.target.value)} /></div>
        <label className="check"><input type="checkbox" checked={all} onChange={event => setAll(event.target.checked)} />含取值为 0 的变量</label>
        <span className="spacer" />
        <button className="icon-button" title="下载 CSV" aria-label="下载变量取值 CSV"
          onClick={() => download("solution.csv", "variable,value\n" + entries.map(([name, value]) => `"${name.replace(/"/g, '""')}",${value}`).join("\n"))}>
          <Download size={15} /></button>
      </div>
      <table className="variables">
        <thead><tr><th>变量</th><th>取值</th></tr></thead>
        <tbody>{shown.slice(0, limit).map(([name, value]) => <tr key={name} className={value === 0 ? "zero" : ""}>
          <td><code>{name}</code></td><td>{formatNumber(value)}</td></tr>)}</tbody>
      </table>
      {!shown.length ? <p className="muted center">没有匹配的变量。</p> : null}
      {shown.length > limit ? <button className="link center" onClick={() => setLimit(limit + 500)}>再显示 {Math.min(500, shown.length - limit)} 个（共 {shown.length} 个）</button> : null}
    </> : null}
    {solve.output.trim() ? <details className="disclosure"><summary>代码输出</summary><pre className="plain">{solve.output}</pre></details> : null}
    {tone(solve.status) === "good" ? <p className="footnote">求解器只保证这个数学模型的解是{STATUS[solve.status]}。模型是否完整表达了问题，请在“数学模型”中核对。</p> : null}
  </div>;
}
