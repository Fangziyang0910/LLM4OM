import { useEffect, useRef, useState } from "react";
import { Bot, ChevronDown, ChevronsDownUp, ChevronsUpDown, CodeXml, Ellipsis, ListTree, Play, Sigma, TriangleAlert, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { t } from "@/i18n";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from "@/components/ui/empty";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { STATUS, duration, formatNumber, formatTokens, tone } from "@/format";
import { phases, preview, roleName, working, type Phase } from "@/features/runs/steps";
import type { Step } from "@/features/runs/types";
import type { Live } from "@/features/runs/useRun";
import { Code, Markdown, Plain } from "@/components/Content";
import { StatusBadge, TONE } from "@/features/runs/status";

/** The modeling process as phases: each intermediate result, solve or error with the LLM calls that led to it. */
export function Timeline({ steps, live, active, onShow }: {
  steps: Step[]; live: Live; active: boolean; onShow: (tab: "formulation" | "code", id: string) => void;
}) {
  const items = phases(steps);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const scroller = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  // Follow new phases while the run is live, unless the reader scrolled up to look at an earlier one.
  useEffect(() => {
    const pane = scroller.current;
    if (!pane) return;
    const onScroll = () => { follow.current = pane.scrollHeight - pane.scrollTop - pane.clientHeight < 80; };
    pane.addEventListener("scroll", onScroll);
    return () => pane.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    const pane = scroller.current;
    if (active && follow.current && pane) pane.scrollTop = pane.scrollHeight;
  }, [active, items.length, live]);

  const calls = steps.filter(step => step.type === "llm").length;
  const milestones = items.filter(item => item.kind !== "working");
  const allOpen = milestones.length > 0 && milestones.every(item => open.has(item.id));
  return <div className="flex h-full min-h-0 flex-col">
    <div className="flex h-11 shrink-0 items-center gap-2 border-b px-4">
      <h2 className="text-sm font-medium">{t("建模过程")}</h2>
      <span className="text-xs text-muted-foreground tabular">{t("{phases} 个阶段 · {calls} 次 LLM 调用", { phases: milestones.length, calls })}</span>
      {milestones.length ? <Button variant="ghost" size="xs" className="ml-auto text-muted-foreground"
        onClick={() => setOpen(allOpen ? new Set() : new Set(milestones.map(item => item.id)))}>
        {allOpen ? <ChevronsDownUp /> : <ChevronsUpDown />}{allOpen ? t("全部收起") : t("全部展开")}</Button> : null}
    </div>
    <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto">
      {!items.length ? <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">{active ? <Spinner /> : <ListTree />}</EmptyMedia>
          <EmptyDescription>{active ? t("等待方法开始……") : t("没有记录到过程。")}</EmptyDescription>
        </EmptyHeader>
      </Empty> : <ol className="flex flex-col p-4">
        {items.map((item, index) => <PhaseItem key={item.id} phase={item} index={index + 1} last={index === items.length - 1}
          live={live} active={active} open={item.kind === "working" || open.has(item.id)}
          onOpenChange={value => setOpen(current => {
            const next = new Set(current);
            if (value) next.add(item.id); else next.delete(item.id);
            return next;
          })} onShow={onShow} />)}
      </ol>}
    </div>
  </div>;
}

function PhaseItem({ phase, index, last, live, active, open, onOpenChange, onShow }: {
  phase: Phase; index: number; last: boolean; live: Live; active: boolean; open: boolean; onOpenChange: (open: boolean) => void;
  onShow: (tab: "formulation" | "code", id: string) => void;
}) {
  const { step, calls } = phase;
  const running = phase.kind === "working" ? active && calls.some(call => call.running) : !!step?.running;
  const failed = phase.kind === "error" || (phase.kind === "solve" && step?.status === "error") || calls.some(call => call.failed);
  const state = running ? "live" : phase.kind === "solve" ? tone(step?.status ?? "") : failed ? "bad" : phase.kind === "working" ? "idle" : "done";
  const title = phase.kind === "working"
    ? (running ? t("正在调用 LLM：{calls}", { calls: working(calls) ?? "" }) : active ? t("等待下一步") : t("没有产出结果的 LLM 调用"))
    : t(step!.title);
  const summary = phase.kind === "artifact" ? preview(step!.content)
    : phase.kind === "solve" && !running ? (step!.status === "error" ? step!.content.split("\n").find(line => line && !line.startsWith("Status"))
      : step!.objective != null ? t("目标值 {value}", { value: formatNumber(step!.objective) }) : STATUS[step!.status ?? ""])
    : phase.kind === "error" ? step!.content.trim().split("\n").pop() : "";
  const meta = [calls.length ? t("{count} 次调用", { count: calls.length }) : "", phase.seconds ? duration(phase.seconds) : ""].filter(Boolean).join(" · ");
  const markerTone = state === "done" ? "border-primary/25 bg-primary/10 text-primary" : state === "live" ? TONE.live.soft
    : state === "idle" ? TONE.idle.soft : TONE[state as "good" | "bad" | "warn"].soft;

  return <li className="relative flex gap-3 pb-3">
    {!last ? <span aria-hidden className="absolute top-7 bottom-0 left-3 w-px bg-border" /> : null}
    <span aria-hidden className={cn("relative z-10 mt-1.5 grid size-6 shrink-0 place-items-center rounded-full border text-[11px] font-semibold tabular [&_svg]:size-3", markerTone)}>
      {running ? <Spinner className="size-3" /> : state === "bad" ? <X /> : phase.kind === "solve" ? <Play className="fill-current" />
        : phase.kind === "working" ? <Ellipsis /> : index}
    </span>
    <Collapsible open={open} onOpenChange={onOpenChange} disabled={phase.kind === "working"}
      className={cn("min-w-0 flex-1 rounded-lg border bg-background transition-colors", open ? "shadow-xs" : "hover:border-foreground/15",
        running && "border-primary/30")}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-left disabled:cursor-default">
        <span className={cn("min-w-0 flex-1 truncate text-[13px] font-medium", phase.kind === "working" && "text-muted-foreground")}>{title}</span>
        {phase.kind === "solve" && step?.status && !running ? <StatusBadge status={step.status} className="h-5 text-[11px]" /> : null}
        <span className="shrink-0 text-[11px] text-muted-foreground tabular">{meta}</span>
        {phase.kind !== "working" ? <ChevronDown className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")} /> : null}
      </CollapsibleTrigger>
      {!open && summary ? <p className="-mt-1 truncate px-3 pb-2 text-xs text-muted-foreground">{summary}</p> : null}
      <CollapsibleContent className="flex flex-col gap-3 border-t px-3 py-3">
        {phase.kind === "artifact" ? <>
          <Clipped><Markdown text={step!.content} /></Clipped>
          {step!.formulation || step!.code ? <div className="flex flex-wrap gap-2">
            {step!.formulation ? <Button variant="secondary" size="xs" onClick={() => onShow("formulation", step!.id)}><Sigma />{t("查看这一版数学模型")}</Button> : null}
            {step!.code ? <Button variant="secondary" size="xs" onClick={() => onShow("code", step!.id)}><CodeXml />{t("查看这一版代码")}</Button> : null}
          </div> : null}
        </> : null}
        {phase.kind === "solve" ? running ? <p className="flex items-center gap-2 text-xs text-muted-foreground"><Spinner className="size-3" />{t("正在沙箱中构建模型并求解……")}</p> : <>
          <Plain tone={step!.status === "error" ? "bad" : undefined}>{step!.content}</Plain>
          {step!.code ? <Collapsible className="group/code">
            <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
              <ChevronDown className="size-3.5 -rotate-90 transition-transform group-data-[state=open]/code:rotate-0" />{t("这次执行的代码")}</CollapsibleTrigger>
            <CollapsibleContent className="pt-2"><Code text={step!.code} /></CollapsibleContent>
          </Collapsible> : null}
        </> : null}
        {phase.kind === "error" ? <Plain tone="bad">{step!.content}</Plain> : null}
        {calls.length ? <Calls calls={calls} live={live} expanded={phase.kind === "working"} /> : null}
      </CollapsibleContent>
    </Collapsible>
  </li>;
}

function Calls({ calls, live, expanded }: { calls: Step[]; live: Live; expanded: boolean }) {
  const list = <ul className="flex flex-col gap-1.5">{calls.map(call => <Call key={call.id} call={call} live={live[call.id]} />)}</ul>;
  if (expanded) return list;
  return <Collapsible className="group/calls">
    <CollapsibleTrigger className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
      <ChevronDown className="size-3.5 -rotate-90 transition-transform group-data-[state=open]/calls:rotate-0" />{t("LLM 调用（{count}）", { count: calls.length })}</CollapsibleTrigger>
    <CollapsibleContent className="pt-2">{list}</CollapsibleContent>
  </Collapsible>;
}

function Call({ call, live }: { call: Step; live?: Live[string] }) {
  const tokens = call.output_tokens != null ? `${formatTokens(call.input_tokens ?? 0)} → ${formatTokens(call.output_tokens)} token` : "";
  const meta = [tokens, call.seconds != null ? duration(call.seconds) : ""].filter(Boolean).join(" · ");
  if (call.running) return <li className="rounded-md border border-primary/25 bg-primary/5 p-2">
    <div className="flex items-center gap-2 text-xs"><Spinner className="size-3 text-primary" /><span className="font-medium">{roleName(call.title)}</span>
      <span className="text-muted-foreground">{t("正在写……")}</span></div>
    <LiveText live={live} />
  </li>;
  return <li>
    <Collapsible className={cn("group/call rounded-md border", call.failed && "border-destructive/30")}>
      <CollapsibleTrigger className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs hover:bg-muted/50">
        {call.failed ? <TriangleAlert className="size-3.5 text-destructive" /> : <Bot className="size-3.5 text-muted-foreground" />}
        <span className="font-medium">{roleName(call.title)}</span>
        <span className="ml-auto text-muted-foreground tabular">{meta}</span>
        <ChevronDown className="size-3.5 text-muted-foreground transition-transform group-data-[state=open]/call:rotate-180" />
      </CollapsibleTrigger>
      <CollapsibleContent className="border-t p-2">
        {call.content ? <Plain className="max-h-96 overflow-y-auto border-0 bg-transparent p-0">{call.content}</Plain>
          : <p className="text-xs text-muted-foreground">{t("（没有文本输出）")}</p>}
      </CollapsibleContent>
    </Collapsible>
  </li>;
}

function LiveText({ live }: { live?: Live[string] }) {
  const ref = useRef<HTMLPreElement>(null);
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [live]);
  if (!live) return <p className="pt-1.5 text-xs text-muted-foreground">{t("等待模型回复……")}</p>;
  return <pre ref={ref} className="mt-1.5 max-h-56 overflow-y-auto font-mono text-xs leading-relaxed whitespace-pre-wrap break-words">
    {live.reasoning ? <span className="text-muted-foreground italic">{live.reasoning}{live.text ? "\n\n" : ""}</span> : null}{live.text}
    <span className="caret" />
  </pre>;
}

function Clipped({ children }: { children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const [tall, setTall] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => { if (ref.current) setTall(ref.current.scrollHeight > 420); }, [children]);
  return <div className="flex flex-col gap-1">
    <div ref={ref} className={cn("relative", tall && !open && "max-h-[420px] overflow-hidden")}>
      {children}
      {tall && !open ? <div className="pointer-events-none absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-background" /> : null}
    </div>
    {tall ? <Button variant="link" size="xs" className="self-start px-0" onClick={() => setOpen(!open)}>{open ? t("收起") : t("展开全文")}</Button> : null}
  </div>;
}

