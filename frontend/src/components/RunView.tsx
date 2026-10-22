import { useEffect, useState, useSyncExternalStore } from "react";
import { ArrowRight, CircleCheck, Clock, CodeXml, Columns3, Cpu, FileDown, Layers, Link2, MoreHorizontal, NotebookPen, Pencil, RefreshCw, Sigma, Square, Tag, Trash2, TriangleAlert, Zap } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { updateMeta } from "@/api";
import { client } from "@/sdk";
import { t } from "@/i18n";
import { report } from "@/report";
import { STATUS, duration, errorText, formatNumber, formatTokens, outcome, tone } from "@/format";
import { phases, working } from "@/steps";
import type { Draft, Options, RunMeta, RunValues, Step } from "@/types";
import { useRun } from "@/useRun";
import { copyText, download } from "./Content";
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

export function RunView({ threadId, options, onFinished, onEdit, onRerun, onDelete, onCompare, onMetaChange }: {
  threadId: string; options: Options; onFinished: () => void;
  onEdit: (draft: Draft) => void; onRerun: (draft: Draft) => Promise<void>; onDelete: () => void;
  onCompare: (group: string) => void; onMetaChange: () => void;
}) {
  const { meta: loaded, values, steps, live, run, streaming, error } = useRun(threadId, onFinished);
  const [changed, setChanged] = useState<Partial<RunMeta>>({});  // note and tags saved since the run was read
  const [noting, setNoting] = useState(false);
  const meta = loaded ? { ...loaded, ...changed } : null;
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
    : <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在读取运行……")}</div>;

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
    language: meta.language, preset: meta.preset ?? null });
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
  const title = meta.title || (values.description ?? "").trim().split("\n")[0] || t("未命名运行");
  const facts: [React.ReactNode, React.ReactNode, string?][] = [
    [<Layers />, method?.name ?? meta.method, method?.description],
    [<CodeXml />, language ? <>{language.name}<span className="text-muted-foreground/70"> · {language.solver}</span></> : meta.language],
    [<Cpu />, meta.model ?? provider?.label, provider?.label],
    [<Clock />, duration(elapsed)],
  ];
  if (calls) facts.push([<Zap />, t("{count} 次调用", { count: calls }) + (tokens ? ` · ${formatTokens(tokens)} token` : "")]);

  return <div className="flex h-full flex-col">
    <header className="flex flex-col gap-3 border-b px-4 py-3 md:flex-row md:items-center md:px-6">
      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        <Tooltip>
          <TooltipTrigger asChild><h1 className="truncate text-base font-semibold tracking-tight md:text-lg">{title}</h1></TooltipTrigger>
          <TooltipContent className="max-w-md whitespace-pre-wrap">{(values.description || title).slice(0, 400)}</TooltipContent>
        </Tooltip>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground [&_svg]:size-3.5">
          {facts.filter(([, text]) => text).map(([icon, text, hint], index) => <span key={index} title={hint} className="flex items-center gap-1.5">{icon}{text}</span>)}
          {meta.tags?.map(tag => <Badge key={tag} variant="secondary" className="h-5 gap-1 font-normal"><Tag className="size-3" />{tag}</Badge>)}
          {meta.note ? <button className="flex max-w-80 items-center gap-1.5 truncate hover:text-foreground" title={meta.note} onClick={() => setNoting(true)}>
            <NotebookPen />{meta.note.split("\n")[0]}</button> : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {meta.group ? <Button variant="ghost" size="sm" onClick={() => onCompare(meta.group!)} title={t("这次运行属于一组方法对比")}>
          <Columns3 />{t("查看对比")}</Button> : null}
        {active ? <Button variant="outline" size="sm" disabled={stopping} onClick={() => void stop()}>
          {stopping ? <Spinner /> : <Square className="fill-current" />}{stopping ? t("正在停止") : t("停止")}</Button> : <>
          <Button variant="outline" size="sm" disabled={busy || !values.description} onClick={() => void rerun()} title={t("用同样的问题和设置再运行一次")}>
            {busy ? <Spinner /> : <RefreshCw />}{t("再运行一次")}</Button>
          <Button size="sm" disabled={!values.description} onClick={() => onEdit(draft())} title={t("把问题和设置带回编辑页")}>
            <Pencil />{t("修改后运行")}</Button>
        </>}
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" aria-label={t("更多操作")}><MoreHorizontal /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onClick={() => void copyText(location.href).then(() => toast.success(t("已复制链接。")), () => toast.error(t("无法复制，请手动复制地址栏中的链接。")))}>
              <Link2 />{t("复制链接")}</DropdownMenuItem>
            <DropdownMenuItem onClick={() => setNoting(true)}><NotebookPen />{t("备注与标签")}</DropdownMenuItem>
            <DropdownMenuItem disabled={!values.description} onClick={() => download(`${(meta.title || "run").slice(0, 40).replace(/[\\/:*?"<>|]/g, "_")}.md`,
              report(meta, values, options, location.href))}><FileDown />{t("导出报告（Markdown）")}</DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" onClick={onDelete}><Trash2 />{t("删除这次运行")}</DropdownMenuItem>
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
          <TabsTrigger value="outputs">{t("结果")}</TabsTrigger>
          <TabsTrigger value="process">{t("过程")}{active ? <span className="size-1.5 animate-pulse rounded-full bg-primary" /> : null}</TabsTrigger>
        </TabsList>
      </Tabs>
      <Pane>{view === "outputs" ? outputs : timeline}</Pane>
    </div>}
    {noting ? <NoteDialog meta={meta} onClose={() => setNoting(false)} onSave={async change => {
      await updateMeta(threadId, change);
      setChanged(current => ({ ...current, ...change }));
      onMetaChange();
    }} /> : null}
  </div>;
}

/** Tags are split on commas or spaces. */
export const parseTags = (text: string) => [...new Set(text.split(/[,，、\s]+/).map(tag => tag.trim().replace(/^#/, "")).filter(Boolean))].slice(0, 12);

/** A run's note and tags, which anyone can edit; they help find and compare runs later. */
function NoteDialog({ meta, onClose, onSave }: { meta: RunMeta; onClose: () => void; onSave: (change: Partial<RunMeta>) => Promise<void> }) {
  const [note, setNote] = useState(meta.note ?? "");
  const [tags, setTags] = useState((meta.tags ?? []).join(", "));
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await onSave({ note: note.trim(), tags: parseTags(tags) }); toast.success(t("已保存备注。")); onClose(); }
    catch (reason) { toast.error(errorText(reason)); setBusy(false); }
  };
  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>{t("备注与标签")}</DialogTitle>
        <DialogDescription>{t("记录这次运行的结论或问题。能打开工作台的人都能看到和修改。")}</DialogDescription>
      </DialogHeader>
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="run-note" className="text-xs">{t("备注")}</Label>
          <Textarea id="run-note" value={note} onChange={event => setNote(event.target.value.slice(0, 2000))} className="min-h-28"
            placeholder={t("例如：漏了整数约束，目标值偏大")} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="run-tags" className="text-xs">{t("标签")}</Label>
          <Input id="run-tags" value={tags} onChange={event => setTags(event.target.value)} placeholder={t("用逗号或空格分隔，例如：NL4Opt 已核对")} />
          <p className="text-xs text-muted-foreground">{t("左侧搜索框输入 #标签 可筛选运行。")}</p>
        </div>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>{t("取消")}</Button>
        <Button disabled={busy} onClick={() => void save()}>{busy ? <Spinner /> : null}{t("保存")}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}

function Pane({ children }: { children: React.ReactNode }) {
  return <section className="flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-xl border bg-card shadow-xs">{children}</section>;
}

/** The answer to "what came of this run?" with the next thing to look at. */
function Summary({ state, values, steps, error, active, elapsed, onTab }: {
  state: string; values: RunValues; steps: Step[]; error: string | null; active: boolean; elapsed: number; onTab: (tab: Tab) => void;
}) {
  const solve = values.solve;
  const frame = (kind: keyof typeof TONE, icon: React.ReactNode, body: React.ReactNode, side?: React.ReactNode) =>
    <div className={cn("flex flex-wrap items-center gap-x-4 gap-y-3 rounded-xl border bg-card p-4 shadow-xs", TONE[kind].border)}>
      <span className={cn("grid size-10 shrink-0 place-items-center rounded-full [&_svg]:size-5", TONE[kind].soft)}>{icon}</span>
      <div className="min-w-0 flex-1 basis-56">{body}</div>
      {side ? <div className="flex flex-wrap gap-2">{side}</div> : null}
    </div>;

  if (error) return frame("bad", <TriangleAlert />, <><p className="font-medium">{t("无法读取运行")}</p><p className="text-sm text-muted-foreground">{error}</p></>,
    <Button variant="outline" size="sm" onClick={() => location.reload()}><RefreshCw />{t("重新连接")}</Button>);
  if (active) {
    const all = phases(steps);
    const current = all.at(-1);
    const calls = current ? working(current.calls) : null;
    const doing = calls ? t("LLM 正在处理：{calls}", { calls })
      : current?.step?.running ? t("正在沙箱中求解代码") : current?.step ? t("刚完成：{title}", { title: t(current.step.title) }) : t("正在准备");
    const done = all.filter(phase => phase.kind !== "working").length;
    return frame("live", <Spinner />, <><p className="font-medium">{t("正在建模")}</p><p className="truncate text-sm text-muted-foreground">{doing}</p></>,
      <div className="flex items-baseline gap-4 text-sm text-muted-foreground">
        <span><strong className="text-lg font-semibold text-foreground tabular">{done}</strong> {t("个阶段")}</span>
        <span><strong className="text-lg font-semibold text-foreground tabular">{duration(elapsed)}</strong></span>
      </div>);
  }
  if (state === "interrupted") return frame("warn", <Square />, <><p className="font-medium">{t("运行已停止")}</p>
    <p className="text-sm text-muted-foreground">{steps.length ? t("停止前的过程仍可查看。停止的运行不保存结果；服务器重启后，这些过程也不再保留。") : t("停止前的过程没有保存。")}</p></>);
  if (state === "failed") return frame("bad", <TriangleAlert />, <><p className="font-medium">{t("没有得到可求解的代码")}</p>
    <p className="line-clamp-2 text-sm text-muted-foreground">{values.failure}</p></>);
  if (!solve) return frame(tone(state), <TriangleAlert />, <><p className="font-medium">{STATUS[state] ?? state}</p>
    <p className="text-sm text-muted-foreground">{t("运行没有正常结束。")}</p></>);
  if (solve.error) return frame("bad", <TriangleAlert />, <><p className="font-medium">{t("代码执行出错")}</p>
    <p className="truncate font-mono text-xs text-muted-foreground">{solve.error.trim().split("\n").pop()}</p></>,
    <Button variant="outline" size="sm" onClick={() => onTab("solution")}>{t("查看详情")}<ArrowRight /></Button>);

  const kind = tone(solve.status);
  const variables = Object.values(solve.variables);
  const nonzero = variables.filter(value => value !== 0).length;
  const explain = kind === "good" ? t("{nonzero} 个非零变量 · 共 {total} 个变量", { nonzero, total: variables.length })
    : solve.status === "infeasible" ? (solve.diagnosis?.items.length
      ? t("求解器判定模型不可行。{tool} 找到 {count} 条不能同时满足的约束，见“解”。", { tool: solve.diagnosis.tool, count: solve.diagnosis.total })
      : t("求解器判定模型不可行：约束之间互相矛盾。请检查数学模型的约束与数据。"))
    : solve.status === "unbounded" ? t("求解器判定模型无界：目标可以无限改进，通常是缺少约束。")
    : STATUS[solve.status] ?? solve.status;
  return frame(kind, kind === "good" ? <CircleCheck /> : <TriangleAlert />, <div className="flex flex-col gap-1">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {solve.objective != null ? <span className="flex items-baseline gap-2"><span className="text-xs text-muted-foreground">{t("目标值")}</span>
        <span className="text-2xl font-semibold tracking-tight tabular">{formatNumber(solve.objective)}</span></span> : null}
      <StatusBadge status={solve.status} />
    </div>
    <p className="text-sm text-muted-foreground">{explain}</p>
  </div>, <>
    <Button variant="outline" size="sm" onClick={() => onTab("formulation")}><Sigma />{t("核对数学模型")}</Button>
    <Button variant="outline" size="sm" onClick={() => onTab("solution")}>{t("查看解")}<ArrowRight /></Button>
  </>);
}
