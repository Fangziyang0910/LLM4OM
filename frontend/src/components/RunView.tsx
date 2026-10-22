import { useEffect, useState, useSyncExternalStore } from "react";
import { ArrowRight, CircleCheck, Clock, CodeXml, Cpu, Layers, Link2, MoreHorizontal, Pencil, RefreshCw, Sigma, Square, Trash2, TriangleAlert, Zap } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { client } from "@/api";
import { STATUS, duration, errorText, formatNumber, formatTokens, outcome, tone } from "@/format";
import { phases, working } from "@/steps";
import type { Draft, Options, RunValues, Step } from "@/types";
import { useRun } from "@/useRun";
import { Outputs, type Tab } from "./Outputs";
import { StatusBadge, TONE } from "./status";
import { Timeline } from "./Timeline";

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

const WIDE = "(min-width: 1024px)";
function useWide(): boolean {
  return useSyncExternalStore(change => {
    const query = matchMedia(WIDE);
    query.addEventListener("change", change);
    return () => query.removeEventListener("change", change);
  }, () => matchMedia(WIDE).matches);
}

export function RunView({ threadId, options, onFinished, onEdit, onRerun, onDelete }: {
  threadId: string; options: Options; onFinished: () => void;
  onEdit: (draft: Draft) => void; onRerun: (draft: Draft) => Promise<void>; onDelete: () => void;
}) {
  const { meta, values, steps, live, run, streaming, error } = useRun(threadId, onFinished);
  const [chosen, setTab] = useState<Tab | null>(null);  // null follows the run
  const [picked, setPicked] = useState<Partial<Record<"formulation" | "code", string>>>({});
  const [view, setView] = useState<"outputs" | "process">("outputs");  // narrow screens show one pane at a time
  const [stopping, setStopping] = useState(false);
  const [busy, setBusy] = useState(false);
  const wide = useWide();
  const active = streaming || run?.status === "pending" || run?.status === "running";
  const now = useNow(active);

  if (!meta) return error ? <div className="flex h-full flex-col items-center justify-center gap-2 p-6 text-center text-sm">
    <TriangleAlert className="size-6 text-destructive" /><p>{error}</p></div>
    : <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />正在读取运行……</div>;

  const method = options.methods.find(item => item.id === meta.method);
  const language = options.languages.find(item => item.id === meta.language);
  const provider = options.providers.find(item => item.id === meta.provider);
  const solve = values.solve ?? null;
  const state = outcome(active, run?.status, values.failure, solve?.status);
  const finished = !active && run?.status === "success";
  const hasFormulation = !!values.formulation || steps.some(step => step.formulation);
  const hasCode = !!values.code || steps.some(step => step.code);
  const tab: Tab = chosen ?? (active ? (hasCode ? "code" : hasFormulation ? "formulation" : "problem")
    : solve ? "solution" : hasFormulation ? "formulation" : hasCode ? "code" : "problem");
  const started = run ? Date.parse(run.created_at) : now;
  const elapsed = Math.max(0, ((active ? now : run ? Date.parse(run.updated_at) : now) - started) / 1000);
  const usage = values.usage;
  const calls = usage?.llm_calls ?? steps.filter(step => step.type === "llm").length;
  const tokens = usage ? usage.input_tokens + usage.output_tokens : null;

  const draft = (): Draft => ({ description: values.description ?? "", data: values.data ?? {}, method: meta.method,
    language: meta.language, provider: meta.provider, model: meta.model ?? "" });
  const stop = async () => {
    if (!run) return;
    setStopping(true);
    await client.runs.cancel(threadId, run.run_id).catch(reason => { toast.error(errorText(reason)); setStopping(false); });
  };
  const rerun = async () => {
    setBusy(true);
    try { await onRerun(draft()); } catch (reason) { toast.error(errorText(reason)); setBusy(false); }
  };
  const showTab = (next: Tab) => { setTab(next); setView("outputs"); };
  const show = (key: "formulation" | "code", id: string) => { setPicked(current => ({ ...current, [key]: id })); showTab(key); };

  const timeline = <Timeline steps={steps} live={live} active={active} onShow={show} />;
  const outputs = <Outputs values={values} steps={steps} active={active} tab={tab} setTab={setTab} picked={picked} language={language}
    finished={finished} setPicked={(key, id) => setPicked(current => ({ ...current, [key]: id }))} />;
  const title = meta.title || (values.description ?? "").trim().split("\n")[0] || "未命名运行";
  const facts: [React.ReactNode, React.ReactNode, string?][] = [
    [<Layers />, method?.name ?? meta.method, method?.description],
    [<CodeXml />, language ? <>{language.name}<span className="text-muted-foreground/70"> · {language.solver}</span></> : meta.language],
    [<Cpu />, meta.model ?? provider?.label ?? "默认模型", provider?.label],
    [<Clock />, duration(elapsed)],
  ];
  if (calls) facts.push([<Zap />, `${calls} 次调用${tokens ? ` · ${formatTokens(tokens)} token` : ""}`]);

  return <div className="flex h-full flex-col">
    <header className="flex flex-col gap-3 border-b px-4 py-3 md:flex-row md:items-center md:px-6">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <Tooltip>
          <TooltipTrigger asChild><h1 className="truncate text-base font-semibold tracking-tight md:text-lg">{title}</h1></TooltipTrigger>
          <TooltipContent className="max-w-md whitespace-pre-wrap">{(values.description || title).slice(0, 400)}</TooltipContent>
        </Tooltip>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground [&_svg]:size-3.5">
          {facts.filter(([, text]) => text).map(([icon, text, hint], index) => <span key={index} title={hint} className="flex items-center gap-1.5">{icon}{text}</span>)}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {active ? <Button variant="outline" size="sm" disabled={stopping} onClick={() => void stop()}>
          {stopping ? <Spinner /> : <Square className="fill-current" />}{stopping ? "正在停止" : "停止"}</Button> : <>
          <Button variant="outline" size="sm" disabled={busy || !values.description} onClick={() => void rerun()} title="用同样的问题和设置再运行一次">
            {busy ? <Spinner /> : <RefreshCw />}再运行一次</Button>
          <Button size="sm" disabled={!values.description} onClick={() => onEdit(draft())} title="把问题和设置带回编辑页">
            <Pencil />修改后运行</Button>
        </>}
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="更多操作"><MoreHorizontal /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => void navigator.clipboard?.writeText(location.href).then(() => toast.success("已复制链接。"))}>
              <Link2 />复制链接</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={onDelete}><Trash2 />删除这次运行</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>

    <div className="px-4 pt-4 md:px-6">
      <Summary state={state} values={values} steps={steps} error={error} active={active} elapsed={elapsed} onTab={showTab} />
    </div>

    {wide ? <ResizablePanelGroup orientation="horizontal" className="min-h-0 flex-1 px-6 pt-4 pb-6">
      <ResizablePanel defaultSize="40" minSize="25"><Pane>{timeline}</Pane></ResizablePanel>
      <ResizableHandle withHandle className="mx-2 bg-transparent" />
      <ResizablePanel defaultSize="60" minSize="30"><Pane>{outputs}</Pane></ResizablePanel>
    </ResizablePanelGroup> : <div className="flex min-h-0 flex-1 flex-col gap-3 px-4 pt-3 pb-4">
      <Tabs value={view} onValueChange={value => setView(value as "outputs" | "process")}>
        <TabsList className="w-full">
          <TabsTrigger value="outputs">结果</TabsTrigger>
          <TabsTrigger value="process">过程{active ? <span className="size-1.5 animate-pulse rounded-full bg-primary" /> : null}</TabsTrigger>
        </TabsList>
      </Tabs>
      <Pane>{view === "outputs" ? outputs : timeline}</Pane>
    </div>}
  </div>;
}

function Pane({ children }: { children: React.ReactNode }) {
  return <section className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-card shadow-xs">{children}</section>;
}

/** The answer to "what came of this run?" with the next thing to look at. */
function Summary({ state, values, steps, error, active, elapsed, onTab }: {
  state: string; values: RunValues; steps: Step[]; error: string | null; active: boolean; elapsed: number; onTab: (tab: Tab) => void;
}) {
  const solve = values.solve;
  const frame = (t: keyof typeof TONE, icon: React.ReactNode, body: React.ReactNode, side?: React.ReactNode) =>
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border bg-card p-4 shadow-xs", TONE[t].border)}>
      <span className={cn("grid size-10 shrink-0 place-items-center rounded-full [&_svg]:size-5", TONE[t].soft)}>{icon}</span>
      <div className="min-w-0 flex-1 basis-56">{body}</div>
      {side ? <div className="flex flex-wrap gap-2">{side}</div> : null}
    </div>;

  if (error) return frame("bad", <TriangleAlert />, <><p className="font-medium">无法读取运行</p><p className="text-sm text-muted-foreground">{error}</p></>,
    <Button variant="outline" size="sm" onClick={() => location.reload()}><RefreshCw />重新连接</Button>);
  if (active) {
    const all = phases(steps);
    const current = all.at(-1);
    const calls = current ? working(current.calls) : null;
    const doing = calls ? `LLM 正在处理：${calls}`
      : current?.step?.running ? "正在沙箱中求解代码" : current?.step ? `刚完成：${current.step.title}` : "正在准备";
    const done = all.filter(phase => phase.kind !== "working").length;
    return frame("live", <Spinner />, <><p className="font-medium">正在建模</p><p className="truncate text-sm text-muted-foreground">{doing}</p></>,
      <div className="flex items-baseline gap-4 text-sm text-muted-foreground">
        <span><strong className="text-lg font-semibold text-foreground tabular">{done}</strong> 个阶段</span>
        <span><strong className="text-lg font-semibold text-foreground tabular">{duration(elapsed)}</strong></span>
      </div>);
  }
  if (state === "interrupted") return frame("warn", <Square />, <><p className="font-medium">运行已停止</p>
    <p className="text-sm text-muted-foreground">{steps.length ? "停止前的过程仍可查看。停止的运行不保存结果；服务器重启后，这些过程也不再保留。" : "停止前的过程没有保存。"}</p></>);
  if (state === "failed") return frame("bad", <TriangleAlert />, <><p className="font-medium">没有得到可求解的代码</p>
    <p className="line-clamp-2 text-sm text-muted-foreground">{values.failure}</p></>);
  if (!solve) return frame(tone(state), <TriangleAlert />, <><p className="font-medium">{STATUS[state] ?? state}</p>
    <p className="text-sm text-muted-foreground">运行没有正常结束。</p></>);
  if (solve.error) return frame("bad", <TriangleAlert />, <><p className="font-medium">代码执行出错</p>
    <p className="truncate font-mono text-xs text-muted-foreground">{solve.error.trim().split("\n").pop()}</p></>,
    <Button variant="outline" size="sm" onClick={() => onTab("solution")}>查看详情<ArrowRight /></Button>);

  const t = tone(solve.status);
  const variables = Object.values(solve.variables);
  const nonzero = variables.filter(value => value !== 0).length;
  const explain = t === "good" ? `${nonzero} 个非零变量 · 共 ${variables.length} 个变量`
    : solve.status === "infeasible" ? "求解器判定模型不可行：约束之间互相矛盾。请检查数学模型的约束与数据。"
    : solve.status === "unbounded" ? "求解器判定模型无界：目标可以无限改进，通常是缺少约束。"
    : STATUS[solve.status] ?? solve.status;
  return frame(t, t === "good" ? <CircleCheck /> : <TriangleAlert />, <div className="flex flex-col gap-1">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {solve.objective != null ? <span className="flex items-baseline gap-2"><span className="text-xs text-muted-foreground">目标值</span>
        <span className="text-2xl font-semibold tracking-tight tabular">{formatNumber(solve.objective)}</span></span> : null}
      <StatusBadge status={solve.status} />
    </div>
    <p className="text-sm text-muted-foreground">{explain}</p>
  </div>, <>
    <Button variant="outline" size="sm" onClick={() => onTab("formulation")}><Sigma />核对数学模型</Button>
    <Button variant="outline" size="sm" onClick={() => onTab("solution")}>查看解<ArrowRight /></Button>
  </>);
}
