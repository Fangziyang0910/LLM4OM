import { useEffect, useRef, useState } from "react";
import { ChevronDown, CodeXml, Cpu, Ellipsis, Play, Sigma, TriangleAlert, X } from "lucide-react";
import { STATUS, duration, formatNumber, formatTokens, tone } from "../format";
import { phases, preview, roleName, working, type Phase } from "../steps";
import type { Step } from "../types";
import type { Live } from "../useRun";
import { Code, Markdown } from "./Content";

/** The modeling process as phases: each intermediate result, solve or error with the LLM calls that led to it. */
export function Timeline({ steps, live, active, onShow }: {
  steps: Step[]; live: Live; active: boolean; onShow: (tab: "formulation" | "code", id: string) => void;
}) {
  const items = phases(steps);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const toggle = (id: string) => setOpen(current => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const end = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  // Follow new phases while the run is live, unless the reader scrolled up to look at an earlier one.
  useEffect(() => {
    const pane = end.current?.closest(".pane-scroll");
    if (!pane) return;
    const onScroll = () => { follow.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 80; };
    pane.addEventListener("scroll", onScroll);
    return () => pane.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    if (active && follow.current) end.current?.scrollIntoView({ block: "end" });
  }, [active, items.length, live]);

  const calls = steps.filter(step => step.type === "llm").length;
  const allOpen = items.length > 0 && items.every(item => item.kind === "working" || open.has(item.id));
  return <div className="timeline">
    <div className="pane-head">
      <h2>建模过程</h2>
      <span className="muted">{items.filter(item => item.kind !== "working").length} 个阶段 · {calls} 次 LLM 调用</span>
      <span className="spacer" />
      {items.length ? <button className="link" onClick={() => setOpen(allOpen ? new Set() : new Set(items.map(item => item.id)))}>
        {allOpen ? "全部收起" : "全部展开"}</button> : null}
    </div>
    {!items.length ? <p className="empty">{active ? "等待方法开始……" : "没有记录到过程。"}</p> : null}
    <ol className="phases">
      {items.map((item, index) => <PhaseItem key={item.id} phase={item} index={index + 1} live={live} active={active}
        open={item.kind === "working" || open.has(item.id)} onToggle={() => toggle(item.id)} onShow={onShow} />)}
    </ol>
    <div ref={end} />
  </div>;
}

function PhaseItem({ phase, index, live, active, open, onToggle, onShow }: {
  phase: Phase; index: number; live: Live; active: boolean; open: boolean; onToggle: () => void;
  onShow: (tab: "formulation" | "code", id: string) => void;
}) {
  const { step, calls } = phase;
  const running = phase.kind === "working" ? active && calls.some(call => call.running) : !!step?.running;
  const failed = phase.kind === "error" || (phase.kind === "solve" && step?.status === "error") || calls.some(call => call.failed);
  const state = running ? "live" : phase.kind === "solve" ? tone(step?.status ?? "") : failed ? "bad" : phase.kind === "working" ? "idle" : "done";
  const title = phase.kind === "working"
    ? (running ? `正在调用 LLM：${working(calls)}` : active ? "等待下一步" : "没有产出结果的 LLM 调用")
    : step!.title;

  const summary = phase.kind === "artifact" ? preview(step!.content)
    : phase.kind === "solve" && !running ? (step!.status === "error" ? step!.content.split("\n").find(line => line && !line.startsWith("Status"))
      : step!.objective != null ? `目标值 ${formatNumber(step!.objective)}` : STATUS[step!.status ?? ""])
    : phase.kind === "error" ? step!.content.trim().split("\n").pop() : "";
  const meta = [calls.length ? `${calls.length} 次调用` : "", phase.seconds ? duration(phase.seconds) : ""].filter(Boolean).join(" · ");

  return <li className={`phase ${phase.kind} ${state}${open ? " open" : ""}`}>
    <span className="phase-marker" aria-hidden="true">
      {running ? <span className="spinner" /> : state === "bad" ? <X size={12} />
        : phase.kind === "solve" ? <Play size={10} /> : phase.kind === "working" ? <Ellipsis size={12} /> : <span>{index}</span>}
    </span>
    <div className="phase-card">
      {phase.kind === "working" ? <div className="phase-head static">
        <span className="phase-title">{title}</span><span className="phase-meta">{meta}</span>
      </div> : <button className="phase-head" aria-expanded={open} onClick={onToggle}>
        <span className="phase-title">{title}</span>
        {phase.kind === "solve" && step?.status && !running ? <span className={`badge ${tone(step.status)}`}>{STATUS[step.status] ?? step.status}</span> : null}
        <span className="phase-meta">{meta}</span>
        <ChevronDown size={15} className="phase-chevron" />
      </button>}
      {!open && summary ? <p className="phase-summary">{summary}</p> : null}
      {open ? <div className="phase-body">
        {phase.kind === "artifact" ? <>
          <Clipped><Markdown text={step!.content} /></Clipped>
          {step!.formulation || step!.code ? <div className="phase-links">
            {step!.formulation ? <button className="chip-button" onClick={() => onShow("formulation", step!.id)}><Sigma size={14} />在右侧查看这一版数学模型</button> : null}
            {step!.code ? <button className="chip-button" onClick={() => onShow("code", step!.id)}><CodeXml size={14} />在右侧查看这一版代码</button> : null}
          </div> : null}
        </> : null}
        {phase.kind === "solve" ? running ? <p className="muted">正在沙箱中构建模型并求解……</p> : <>
          <pre className={"plain" + (step!.status === "error" ? " error-text" : "")}>{step!.content}</pre>
          {step!.code ? <details className="disclosure"><summary>这次执行的代码</summary><Code text={step!.code} /></details> : null}
        </> : null}
        {phase.kind === "error" ? <pre className="plain error-text">{step!.content}</pre> : null}
        {calls.length ? <Calls calls={calls} live={live} expanded={phase.kind === "working"} /> : null}
      </div> : null}
    </div>
  </li>;
}

function Calls({ calls, live, expanded }: { calls: Step[]; live: Live; expanded: boolean }) {
  const list = <ul className="calls">{calls.map(call => <Call key={call.id} call={call} live={live[call.id]} />)}</ul>;
  if (expanded) return list;
  return <details className="disclosure"><summary>LLM 调用（{calls.length}）</summary>{list}</details>;
}

function Call({ call, live }: { call: Step; live?: Live[string] }) {
  const tokens = call.output_tokens != null ? `${formatTokens(call.input_tokens ?? 0)} → ${formatTokens(call.output_tokens)} token` : "";
  const meta = [tokens, call.seconds != null ? duration(call.seconds) : ""].filter(Boolean).join(" · ");
  if (call.running) return <li className="call running">
    <div className="call-head"><span className="spinner" /><span className="call-role">{roleName(call.title)}</span><span className="muted">正在写……</span></div>
    <LiveText live={live} />
  </li>;
  return <li className={"call" + (call.failed ? " failed" : "")}>
    <details>
      <summary className="call-head">
        {call.failed ? <TriangleAlert size={14} /> : <Cpu size={14} />}<span className="call-role">{roleName(call.title)}</span>
        <span className="muted">{meta}</span>
      </summary>
      {call.content ? <pre className="plain call-text">{call.content}</pre> : <p className="muted">（没有文本输出）</p>}
    </details>
  </li>;
}

function LiveText({ live }: { live?: Live[string] }) {
  const ref = useRef<HTMLPreElement>(null);
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [live]);
  if (!live) return <p className="muted live-wait">等待模型回复……</p>;
  return <pre ref={ref} className="plain live">
    {live.reasoning ? <span className="reasoning">{live.reasoning}{live.text ? "\n\n" : ""}</span> : null}{live.text}
    <span className="caret" />
  </pre>;
}

function Clipped({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [tall, setTall] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (ref.current) setTall(ref.current.scrollHeight > 460); }, [children]);
  return <div className={"clipped" + (tall && !open ? " closed" : "")}>
    <div ref={ref} className="clipped-body">{children}</div>
    {tall ? <button className="link" onClick={() => setOpen(!open)}>{open ? "收起" : "展开全文"}</button> : null}
  </div>;
}
