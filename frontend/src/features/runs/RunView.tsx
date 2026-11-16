import { useEffect, useState } from "react";
import { useDefaultLayout } from "react-resizable-panels";
import { ArrowRight, Check, ChevronDown, CircleCheck, Clock, CodeXml, Columns3, Cpu, FileDown, Layers, Link2, MessageSquare, MoreHorizontal, NotebookPen, Pencil, RefreshCw, Sparkles, Square, Tag, Trash2, TriangleAlert, Zap } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { useDesktop } from "@/lib/useDesktop";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { updateMeta } from "@/features/runs/api";
import { targetLabel } from "@/features/runs/target";
import { client } from "@/features/runs/sdk";
import { t } from "@/i18n";
import { report } from "@/features/runs/report";
import { exportSolution, hasSolution } from "@/features/runs/workbook";
import { STATUS, duration, errorText, formatNumber, formatTokens, outcome, tone } from "@/format";
import { phases } from "@/features/runs/steps";
import type { Draft } from "@/features/composer/types";
import type { Options } from "@/types";
import type { RunMeta, RunValues, SourceRun, Step } from "@/features/runs/types";
import { useRun } from "@/features/runs/useRun";
import { copyText, download, Plain } from "@/components/Content";
import { Outputs, type Tab } from "@/features/runs/Outputs";
import { StatusBadge, TONE } from "@/features/runs/status";
import { Timeline } from "@/features/runs/Timeline";
import { RevisionDialog } from "@/features/runs/RevisionDialog";
import { ScenariosDialog } from "@/features/runs/ScenariosDialog";

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

export function RunView({ threadId: requested, source, options, onFinished, onEdit, onRerun, onRevise, onDelete, onCompare, onMetaChange, onDiscuss, onScenarios, onConversation, assistantOpen = false, embedded = false }: {
  threadId: string; source?: SourceRun; options: Options; onFinished: () => void; assistantOpen?: boolean; embedded?: boolean;
  onEdit: (draft: Draft) => void; onRerun: (draft: Draft) => Promise<void>; onDelete: (meta: RunMeta) => void;
  onRevise: (instruction: string) => Promise<void>;
  onDiscuss: () => Promise<void>; onScenarios: (scenarios: { name: string; instruction: string }[]) => Promise<void>;
  onConversation: (id: string) => void;
  onCompare: (group: string) => void; onMetaChange: () => void;
}) {
  const threadId = source?.thread_id ?? requested;
  const [refresh, setRefresh] = useState(0);
  const { meta: loaded, values, steps, live, run, streaming, error } = useRun(source ?? threadId, onFinished, refresh);
  const [changed, setChanged] = useState<Partial<RunMeta>>({});  // note and tags saved since the run was read
  const [noting, setNoting] = useState(false);
  const [revision, setRevision] = useState<string | null>(null);
  const [scenarios, setScenarios] = useState(false);
  const meta = loaded ? { ...loaded, ...changed } : null;
  const [chosen, setTab] = useState<Tab | null>(null);  // null follows the run
  const [picked, setPicked] = useState<Partial<Record<"formulation" | "code", string>>>({});
  const [processVisible, setProcessVisible] = useState<boolean | null>(null);
  const [view, setView] = useState<"outputs" | "process">("outputs");  // narrow screens show one pane at a time
  const [stopping, setStopping] = useState(false);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState(false);
  const wide = useDesktop() && !embedded;
  const layout = useDefaultLayout({ id: "llm4om-run", panelIds: ["process", "outputs"], onlySaveAfterUserInteractions: true });
  const active = streaming || run?.status === "pending" || run?.status === "running";
  const now = useNow(active);
  const withProcess = processVisible ?? active;

  if (!meta) return error ? <div className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-sm">
    <TriangleAlert className="size-6 text-destructive" /><p>{error}</p>
    <Button variant="outline" size="sm" onClick={() => location.reload()}><RefreshCw />{t("重新连接")}</Button></div>
    : <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在加载方案详情…")}</div>;

  const method = options.methods.find(item => item.id === meta.method);
  const language = options.languages.find(item => item.id === meta.language);
  const provider = options.providers.find(item => item.id === meta.provider);
  const solve = values.solve ?? null;
  const recordedStatus = run?.status ?? (values.timing?.finished_at ? "success" : undefined);
  const state = outcome(active, recordedStatus, values.failure, solve?.status);
  const finished = !active && recordedStatus === "success";
  const hasFormulation = !!values.formulation || steps.some(step => step.formulation);
  const hasCode = !!values.code || steps.some(step => step.code);
  const tab: Tab = chosen ?? (active ? (hasCode ? "code" : hasFormulation ? "formulation" : "problem")
    : meta.parent && values.revision ? "comparison" : solve ? "solution" : hasFormulation ? "formulation" : hasCode ? "code" : "problem");
  const elapsed = values.timing ? active ? Math.max(0, now / 1000 - values.timing.started_at) : values.timing.elapsed : null;
  const usage = values.usage;
  const calls = usage?.llm_calls ?? steps.filter(step => step.type === "llm").length;
  const tokens = usage ? usage.input_tokens + usage.output_tokens : null;

  const draft = (): Draft => ({ description: values.description ?? "", data: values.data ?? {}, method: meta.method,
    language: meta.language, solver: meta.solver, preset: meta.preset ?? null, origin: threadId });
  const link = new URL(`/run/${threadId}`, location.href);
  if (source?.checkpoint_id) link.searchParams.set("checkpoint", source.checkpoint_id);
  const href = link.href;
  const stop = async () => {
    if (!run) return;
    setStopping(true);
    try {
      await client.runs.cancel(threadId, run.run_id, true);
      setRefresh(current => current + 1);
      onFinished();
    } catch (reason) { toast.error(errorText(reason)); }
    finally { setStopping(false); }
  };
  const rerun = async () => {
    setBusy(true);
    try { await onRerun(draft()); } catch (reason) { toast.error(errorText(reason)); setBusy(false); }
  };
  const exportExcel = async () => {
    setExporting(true);
    try {
      download(`${(meta.title || "solution").slice(0, 40).replace(/[\\/:*?"<>|]/g, "_")}.xlsx`,
        await exportSolution(meta, values, options, href));
    } catch (reason) { toast.error(errorText(reason)); }
    finally { setExporting(false); }
  };
  const showTab = (next: Tab) => { setTab(next); setView("outputs"); };
  const show = (key: "formulation" | "code", id: string) => { setPicked(current => ({ ...current, [key]: id })); showTab(key); };

  const timeline = <Timeline steps={steps} live={live} active={active} onShow={show} />;
  const outputs = <Outputs values={values} steps={steps} active={active} tab={tab} setTab={setTab} picked={picked} language={language}
    finished={finished} source={meta.parent} onAdjust={setRevision} setPicked={(key, id) => setPicked(current => ({ ...current, [key]: id }))} />;
  const title = meta.title || (values.description ?? "").trim().split("\n")[0] || t("未命名方案");
  const facts: [React.ReactNode, React.ReactNode, string?][] = [
    [<Layers />, method?.name ?? meta.method, method?.description],
    [<CodeXml />, targetLabel(options, meta, solve?.solver)],
    [<Cpu />, meta.model ?? provider?.label, provider?.label],
    [<Clock />, elapsed == null ? "—" : duration(elapsed)],
  ];
  if (calls) facts.push([<Zap />, t("{count} 次推理", { count: calls }) + (tokens ? ` · ${formatTokens(tokens)} token` : "")]);

  const followUpActions = !active && !embedded ? <div role="group" aria-label={t("运行操作")} className="flex flex-wrap items-center gap-2">
    <Button variant="secondary" size="sm" className="rounded-lg shadow-2xs" disabled={busy || !values.description} onClick={() => setRevision("")}>
      <Pencil />{t("调整条件")}
    </Button>
    <Button variant="outline" size="sm" className="rounded-lg bg-background/70" disabled={busy || !values.spec} onClick={() => setScenarios(true)}>
      <Columns3 />{t("多场景对比")}
    </Button>
    {!assistantOpen ? <Button variant="outline" size="sm" className="rounded-lg bg-background/70" disabled={busy || !values.spec} onClick={async () => {
      setBusy(true);
      try { await onDiscuss(); } catch (error) { toast.error(errorText(error)); } finally { setBusy(false); }
    }}>{busy ? <Spinner /> : <MessageSquare />}{t("对话追问")}</Button> : null}
  </div> : null;

  return <div className="flex h-full min-h-0 min-w-0 flex-col overflow-y-auto">
    <header className="flex shrink-0 flex-col gap-2.5 border-b border-border/70 bg-background/80 px-4 py-3 backdrop-blur-md sm:px-5 md:flex-row md:items-center">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        {!embedded && !assistantOpen && (meta.group || meta.conversation) ? <div className="flex flex-wrap items-center gap-3">
          {meta.group ? <Button variant="link" size="xs" className="h-auto p-0 text-xs text-muted-foreground hover:text-primary" onClick={() => onCompare(meta.group!)}><Columns3 />{t("返回对比列表")}</Button> : null}
          {meta.conversation ? <Button variant="link" size="xs" className="h-auto p-0 text-xs text-muted-foreground hover:text-primary" onClick={() => onConversation(meta.conversation!)}><MessageSquare />{t("返回对话规划")}</Button> : null}
        </div> : null}
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <Tooltip>
            <TooltipTrigger asChild><h1 className="truncate text-base font-semibold tracking-tight md:text-lg">{title}</h1></TooltipTrigger>
            <TooltipContent className="max-w-md whitespace-pre-wrap">{(values.description || title).slice(0, 400)}</TooltipContent>
          </Tooltip>
          {elapsed != null ? <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-muted/70 px-2 py-0.5 text-[11px] text-muted-foreground tabular">
            <Clock className="size-3" />{duration(elapsed)}
          </span> : null}
        </div>
        <details className="group/info min-w-0 text-xs text-muted-foreground">
          <summary className="inline-flex cursor-pointer list-none items-center gap-1.5 rounded-sm hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
            <span>{t("查看求解配置")}</span><ChevronDown className="size-3.5 shrink-0 transition-transform group-open/info:rotate-180" />
          </summary>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 rounded-xl border border-border/60 bg-muted/20 px-3 py-2 [&_svg]:size-3.5">
            {facts.filter(([, text]) => text).map(([icon, text, hint], index) => <span key={index} title={hint} className="flex min-w-0 items-center gap-1.5 break-all [&_svg]:shrink-0 [&_svg]:text-muted-foreground">{icon}{text}</span>)}
          </div>
        </details>
        <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground [&_svg]:size-3.5 empty:hidden">
          {meta.tags?.map(tag => <Badge key={tag} variant="secondary" title={tag} className="h-5 max-w-48 gap-1 font-normal"><Tag className="size-3" /><span className="truncate">{tag}</span></Badge>)}
          {meta.note ? <button className="flex max-w-80 items-center gap-1.5 truncate hover:text-foreground" title={meta.note} onClick={() => setNoting(true)}>
            <NotebookPen />{meta.note.split("\n")[0]}</button> : null}
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1.5">
        <Button variant={wide && !assistantOpen && withProcess ? "secondary" : "ghost"} size="sm" className="rounded-lg"
          aria-expanded={wide && !assistantOpen ? withProcess : view === "process"}
          onClick={() => { if (wide && !assistantOpen) setProcessVisible(!withProcess); else setView(view === "process" ? "outputs" : "process"); }}>
          <Layers />{t("求解步骤")}</Button>
        {active ? <Button variant="outline" size="sm" className="rounded-lg" disabled={stopping} onClick={() => void stop()}>
          {stopping ? <Spinner /> : <Square className="fill-current" />}{stopping ? t("正在停止") : t("停止")}</Button> : <>
          {["failed", "error", "timeout", "interrupted"].includes(state) ? <Button variant="outline" size="sm" className="rounded-lg"
            disabled={busy || !values.description} title={t("用同样的问题和设置再求解一次")} onClick={() => void rerun()}>
            {busy ? <Spinner /> : <RefreshCw />}{t("重新求解")}</Button> : null}
          {hasSolution(solve) ? <Button variant="outline" size="sm" className="size-8 rounded-lg p-0 sm:w-auto sm:px-3" aria-label={t("导出 Excel")}
            title={t("导出 Excel")} disabled={exporting} onClick={() => void exportExcel()}>
            {exporting ? <Spinner /> : <FileDown />}<span className="hidden sm:inline">{t("导出表格")}</span></Button> : null}
        </>}
        <DropdownMenu>
          <DropdownMenuTrigger asChild><Button variant="ghost" size="icon-sm" className="rounded-lg" disabled={busy} aria-label={t("更多操作")} title={t("更多操作")}><MoreHorizontal /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48 rounded-xl">
            <DropdownMenuItem disabled={active || busy || !values.description} onClick={() => void rerun()}><RefreshCw />{t("重新求解一次")}</DropdownMenuItem>
            <DropdownMenuItem disabled={!values.description} onClick={() => onEdit(draft())}>
              <Pencil />{t("编辑原问题")}</DropdownMenuItem>
            <DropdownMenuItem onClick={() => void copyText(href).then(() => toast.success(t("已复制链接。")), () => toast.error(t("无法复制，请手动复制地址栏中的链接。")))}>
              <Link2 />{t("复制分享链接")}</DropdownMenuItem>
            <DropdownMenuItem onClick={() => setNoting(true)}><NotebookPen />{t("备注与标签")}</DropdownMenuItem>
            <DropdownMenuItem disabled={!values.description} onClick={() => download(`${(meta.title || "run").slice(0, 40).replace(/[\\/:*?"<>|]/g, "_")}.md`,
              report(meta, values, options, href))}><FileDown />{t("导出完整报告（MD）")}</DropdownMenuItem>
            {/* A saved plan's thread may hold later runs; deleting it from a fixed view would remove them too. */}
            {source ? null : <><DropdownMenuSeparator />
              <DropdownMenuItem variant="destructive" onClick={() => onDelete(meta)}><Trash2 />{t("删除此记录")}</DropdownMenuItem></>}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>

    <div className="shrink-0 px-4 pt-3.5 sm:px-5">
      <Summary state={state} values={values} steps={steps} error={error} active={active} elapsed={elapsed} onTab={showTab} actions={followUpActions} />
    </div>

    {wide && !assistantOpen && withProcess ? <ResizablePanelGroup orientation="horizontal" defaultLayout={layout.defaultLayout} onLayoutChanged={layout.onLayoutChanged} className="min-h-0 flex-1 p-4 pt-3.5 sm:px-5">
      <ResizablePanel id="process" defaultSize="32%" minSize="25%"><Pane>{timeline}</Pane></ResizablePanel>
      <ResizableHandle withHandle aria-label={t("调整过程与结果的宽度")} className="mx-2 bg-transparent" />
      <ResizablePanel id="outputs" defaultSize="68%" minSize="30%"><Pane>{outputs}</Pane></ResizablePanel>
    </ResizablePanelGroup> : <div className="flex min-h-96 flex-1 shrink-0 flex-col gap-3 p-4 pt-3.5 sm:px-5 lg:min-h-0 lg:shrink">
      {!wide && !embedded ? <Tabs value={view} onValueChange={value => setView(value as "outputs" | "process")}>
        <TabsList className="w-full rounded-xl">
          <TabsTrigger value="outputs" className="rounded-lg">{t("求解结果")}</TabsTrigger>
          <TabsTrigger value="process" className="rounded-lg">{t("求解步骤")}{active ? <span className="size-1.5 animate-pulse rounded-full bg-primary" /> : null}</TabsTrigger>
        </TabsList>
      </Tabs> : null}
      <Pane>{view === "outputs" ? outputs : timeline}</Pane>
    </div>}
    {noting ? <NoteDialog meta={meta} onClose={() => setNoting(false)} onSave={async change => {
      await updateMeta(threadId, change);
      setChanged(current => ({ ...current, ...change }));
      onMetaChange();
    }} /> : null}
    {revision !== null ? <RevisionDialog initialInstruction={revision} onClose={() => setRevision(null)} onRevise={onRevise} /> : null}
    {scenarios ? <ScenariosDialog onClose={() => setScenarios(false)} onStart={onScenarios} /> : null}
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
    <DialogContent className="flex min-h-0 flex-col rounded-2xl sm:max-w-lg">
      <DialogHeader>
        <DialogTitle>{t("备注与标签")}</DialogTitle>
        <DialogDescription>{t("记录当前方案的业务结论或复盘要点，方便后续检索与对比。")}</DialogDescription>
      </DialogHeader>
      <div className="flex min-h-0 flex-col gap-4 overflow-y-auto">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="run-note" className="text-xs font-medium">{t("备注")}</Label>
          <Textarea id="run-note" value={note} onChange={event => setNote(event.target.value.slice(0, 2000))} className="h-32 min-h-20 field-sizing-fixed resize-none"
            placeholder={t("例如：已确认满足下周交期要求，可作为基准方案")} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="run-tags" className="text-xs font-medium">{t("标签")}</Label>
          <Input id="run-tags" value={tags} onChange={event => setTags(event.target.value)} placeholder={t("用逗号或空格分隔，例如：生产排程 已确认")} />
          <p className="text-xs text-muted-foreground">{t("左侧搜索框输入 #标签 可快速筛选记录。")}</p>
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
  return <section className="flex h-full min-h-0 min-w-0 flex-1 flex-col overflow-hidden rounded-2xl border border-border/80 bg-card shadow-xs">{children}</section>;
}

const PROGRESS_STAGES = [
  { key: "understand", label: "理解问题" },
  { key: "model", label: "建立模型" },
  { key: "solve", label: "自动求解" },
  { key: "explain", label: "生成方案" },
] as const;

function inferStageIndex(steps: Step[], values: RunValues): number {
  if (values.solve || steps.some(step => step.type === "solve" && !step.running)) return 3;
  if (steps.some(step => step.type === "solve" && step.running) || values.code || steps.some(step => step.code)) return 2;
  if (values.formulation || steps.some(step => step.formulation || step.type === "artifact")) return 1;
  return 0;
}

/** The answer to "what came of this run?" with clear visual progress or executive KPI + next actions. */
function Summary({ state, values, steps, error, active, elapsed, onTab, actions }: {
  state: string; values: RunValues; steps: Step[]; error: string | null; active: boolean; elapsed: number | null;
  onTab: (tab: Tab) => void; actions?: React.ReactNode;
}) {
  const solve = values.solve;
  const frame = (kind: keyof typeof TONE, icon: React.ReactNode, body: React.ReactNode, side?: React.ReactNode) =>
    <div className={cn("animate-fade-up flex flex-wrap items-center gap-x-4 gap-y-3 rounded-2xl border bg-card p-4 shadow-xs", TONE[kind].border)}>
      <span className={cn("grid size-11 shrink-0 place-items-center rounded-xl border [&_svg]:size-5", TONE[kind].soft)}>{icon}</span>
      <div className="min-w-0 flex-1 basis-52">{body}</div>
      {side ? <div className="flex flex-wrap items-center gap-2">{side}</div> : null}
    </div>;

  if (error) return frame("bad", <TriangleAlert />, <><p className="font-medium">{t("无法读取方案")}</p><p className="text-sm text-muted-foreground">{error}</p></>,
    <Button variant="outline" size="sm" onClick={() => location.reload()}><RefreshCw />{t("重新连接")}</Button>);

  if (active) {
    const stageIdx = inferStageIndex(steps, values);
    const stageHints = [
      t("正在梳理业务目标、决策变量与约束条件…"),
      t("正在构建严谨的数学优化模型与求解程序…"),
      t("正在调用求解引擎计算全局最优方案…"),
      t("已完成核心计算，正在整理通俗易懂的方案解读…"),
    ];
    const all = phases(steps);
    const current = all.at(-1);
    const subtitle = current?.step?.running ? t("正在隔离环境中执行优化求解计算…") : stageHints[stageIdx];
    return <div className="animate-fade-up relative overflow-hidden rounded-2xl border border-primary/25 bg-gradient-to-br from-primary/[0.06] via-card to-card p-4 shadow-xs">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex min-w-0 items-center gap-3">
          <span className="grid size-10 shrink-0 place-items-center rounded-xl border border-primary/20 bg-primary/10 text-primary">
            <Sparkles className="size-5 animate-pulse" />
          </span>
          <div className="min-w-0">
            <p className="font-semibold tracking-tight">{t("正在智能建模与求解")}</p>
            <p className="truncate text-xs text-muted-foreground sm:text-sm">{subtitle}</p>
          </div>
        </div>
        <span className="rounded-full border border-primary/20 bg-primary/10 px-3 py-1 text-xs font-semibold text-primary tabular">
          {elapsed == null ? "0s" : duration(elapsed)}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
        {PROGRESS_STAGES.map((stage, idx) => {
          const done = idx < stageIdx;
          const currentStage = idx === stageIdx;
          return <div key={stage.key} className={cn(
            "flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-medium transition-colors",
            done ? "border-primary/25 bg-primary/10 text-primary"
              : currentStage ? "border-primary/40 bg-background text-foreground shadow-2xs"
                : "border-border/60 bg-muted/25 text-muted-foreground"
          )}>
            <span className={cn("grid size-5 shrink-0 place-items-center rounded-full text-[10px] font-semibold",
              done ? "bg-primary text-primary-foreground" : currentStage ? "bg-primary/15 text-primary" : "bg-muted text-muted-foreground")}>
              {done ? <Check className="size-3" /> : currentStage ? <Spinner className="size-3" /> : idx + 1}
            </span>
            <span className="truncate">{t(stage.label)}</span>
          </div>;
        })}
      </div>
    </div>;
  }

  if (state === "interrupted") return frame("warn", <Square />, <><p className="font-medium">{t("已停止求解")}</p>
    <p className="text-sm text-muted-foreground">{steps.length ? t("停止前已生成的中间模型与记录仍可查看。") : t("任务在生成结果前已停止。")}</p></>, actions);
  if (state === "failed") return frame("bad", <TriangleAlert />, <><p className="font-medium">{t("求解未能完成")}</p>
    <p className="line-clamp-2 text-sm text-muted-foreground">{values.failure}</p>
    <details className="mt-2 text-xs"><summary className="cursor-pointer text-muted-foreground hover:text-foreground">{t("查看详细原因")}</summary><Plain className="mt-2 max-h-64 overflow-auto">{values.failure}</Plain></details></>, actions);
  if (!solve) return frame(tone(state), <TriangleAlert />, <><p className="font-medium">{STATUS[state] ?? state}</p>
    <p className="text-sm text-muted-foreground">{t("本次求解未返回完整结果。")}</p></>, actions);
  if (solve.error) return frame("bad", <TriangleAlert />, <><p className="font-medium">{t("模型计算时遇到错误")}</p>
    <p className="truncate font-mono text-xs text-muted-foreground">{solve.error.trim().split("\n").pop()}</p></>,
    <>{actions}<Button variant="outline" size="sm" className="rounded-lg" onClick={() => onTab("solution")}>{t("查看详情")}<ArrowRight /></Button></>);

  const kind = tone(solve.status);
  const explain = kind === "good" ? null
    : solve.status === "infeasible" ? (solve.diagnosis?.items.length
      ? t("当前条件存在冲突，无法同时满足（共定位到 {count} 处冲突条件），请查看下方冲突诊断与调整建议。", { count: solve.diagnosis.total })
      : t("当前约束条件之间存在矛盾，无法同时满足。建议点击右侧“调整条件”放宽部分限制后重试。"))
    : solve.status === "unbounded" ? t("优化目标可以无限放大或缩小，通常是因为缺少上限或预算等约束条件。")
    : STATUS[solve.status] ?? solve.status;

  return frame(kind, kind === "good" ? <CircleCheck /> : <TriangleAlert />, <div className="flex flex-col gap-1">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
      {solve.objective != null ? <span className="flex flex-wrap items-baseline gap-2">
        <span className="text-xs font-medium text-muted-foreground">{values.explanation?.objective_label || t("最优目标值")}</span>
        <span className="text-2xl font-bold tracking-tight tabular sm:text-3xl">{formatNumber(solve.objective)}</span>
        {values.explanation?.objective_unit ? <span className="text-xs font-medium text-muted-foreground">{values.explanation.objective_unit}</span> : null}
      </span> : <span className="font-semibold">{STATUS[solve.status] ?? solve.status}</span>}
      <StatusBadge status={solve.status} />
    </div>
    {explain ? <p className="text-sm leading-relaxed text-muted-foreground">{explain}</p> : null}
  </div>, actions);
}
