import { type ReactNode, useEffect, useRef, useState } from "react";
import { useDefaultLayout } from "react-resizable-panels";
import type { Message } from "@langchain/langgraph-sdk";
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpen, CalendarDays, Columns2, Factory, Globe, Menu, Paperclip, RefreshCw, SlidersHorizontal, Sparkles, Truck, X } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { useDesktop } from "@/lib/useDesktop";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Toggle } from "@/components/ui/toggle";
import { ChatInput } from "@/features/chat/ChatInput";
import { ChatMessages, type ChatProgress, type ModelingEvent, type ModelingTask } from "@/features/chat/Messages";
import { useConversation } from "@/features/chat/conversation";
import { useChatScroll } from "@/features/chat/scroll";
import { DATA_FILE_ACCEPT, readDataFiles } from "@/features/composer/files";
import { DataEditor } from "@/features/composer/DataEditor";
import { Outputs, type Tab } from "@/features/runs/Outputs";
import { saveThreadValues } from "@/features/runs/api";
import { client } from "@/features/runs/sdk";
import type { OptimizationMeta, Plan, RunValues, SourceRun, Usage } from "@/features/runs/types";
import { sameSource, sourceKey } from "@/features/runs/types";
import type { Options, Preset } from "@/types";
import { errorText } from "@/format";
import { locale, t } from "@/i18n";
import { cn } from "@/lib/utils";

type Values = { messages?: Message[]; description?: string; data?: Record<string, string>; source?: SourceRun;
  current?: SourceRun; plans?: Plan[]; usage?: Usage; failure?: string | null };

const AGENT_STARTERS = [
  {
    icon: CalendarDays,
    title: "门店排班规划",
    summary: "平衡早晚班人手需求与人力成本",
    prompt: "我想给门店安排下周的班次，既要保证高峰时段人手充足，又想控制总排班成本，应该先提供哪些信息？",
  },
  {
    icon: Factory,
    title: "生产排产优化",
    summary: "在产能与原料约束下最大化收益",
    prompt: "工厂有几条产线和不同利润的产品订单，设备工时有限，帮我梳理一下怎么安排生产最划算。",
  },
  {
    icon: Truck,
    title: "仓储配送调度",
    summary: "多仓库向多客户供货，降低总运费",
    prompt: "我有多个发货仓库和一批门店补货需求，想规划一套总运费最低的调拨方案。",
  },
] as const;

export function Agent({ threadId, options, presets, initial, onThread, openPresets, onMenu, onExamples, onFinished, onOpen, onCompare, renderRun }: {
  threadId?: string; options: Options; presets: Preset[]; initial: { description: string; data: Record<string, string> };
  onThread: (id: string) => void; openPresets: () => void; onManual?: () => void; onMenu: () => void; onExamples: () => void;
  onFinished: () => void; onOpen: (source: SourceRun) => void; onCompare: (id: string) => void; renderRun: (source: SourceRun) => ReactNode;
}) {
  const desktop = useDesktop();
  const layout = useDefaultLayout({ id: "llm4om-agent", panelIds: ["conversation", "workspace"], onlySaveAfterUserInteractions: true });
  const [selected, setSelected] = useState<string>();
  const [thinking, setThinking] = useState<boolean>();
  const [method, setMethod] = useState<string>();
  const [language, setLanguage] = useState<string>();
  const [search, setSearch] = useState<boolean>();
  const [settings, setSettings] = useState(false);
  const { log, content, follow, followLatest } = useChatScroll();
  const [files, setFiles] = useState<Record<string, string> | null>(null);
  const [reading, setReading] = useState(false);
  const [savingData, setSavingData] = useState(false);
  const [editing, setEditing] = useState<string>();
  const [tasks, setTasks] = useState<Record<string, ModelingTask>>({});
  const [progress, setProgress] = useState<ChatProgress>();
  const [viewed, setViewed] = useState<SourceRun>();
  const [liveTask, setLiveTask] = useState<string>();
  const [workspaceOpen, setWorkspace] = useState<boolean>();
  const [pane, setPane] = useState<"chat" | "workspace">("chat");
  const inputArea = useRef<HTMLTextAreaElement>(null);
  const upload = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const conversation = useConversation<Values, { CustomEventType: ChatProgress | ModelingEvent }>({
    assistantId: "optimization", threadId, initialInput: initial.description, reconnectOnMount: false,
    onCreated: onFinished,
    onCustomEvent: event => {
      if (event.type === "scenario_progress") setProgress(event);
      if (event.type === "modeling_step") {
        setTasks(current => {
          const steps = new Map((current[event.tool_call_id]?.steps ?? []).map(step => [step.id, step]));
          steps.set(event.step.id, event.step);
          return { ...current, [event.tool_call_id]: { ...event, steps: [...steps.values()] } };
        });
        setLiveTask(event.tool_call_id); setWorkspace(true);
      }
    },
    onFinish: () => { setFiles(null); setLiveTask(undefined); onFinished(); },
    onError: () => { setLiveTask(undefined); onFinished(); },
  });
  const meta = conversation.thread.metadata as OptimizationMeta | undefined;
  const { input, setInput } = conversation;
  const messages = conversation.messages;
  const data = files ?? conversation.values.data ?? initial.data;
  const preset = presets.find(item => item.id === (selected ?? meta?.preset)) ?? presets[0];
  const presetId = preset?.id;
  const thinkingMode = preset?.provider === "deepseek" ? thinking ?? meta?.thinking ?? null : null;
  const chosenMethod = method ?? meta?.method ?? "auto";
  const chosenLanguage = language ?? meta?.language ?? "auto";
  const searching = search ?? meta?.search ?? false;
  const canSearch = !!options.search_configured || preset?.provider === "deepseek";
  const busy = conversation.busy;
  const dataPending = reading || savingData;
  const failure = conversation.error || conversation.values.failure;
  const plans = conversation.values.plans ?? [];
  const original = conversation.values.source;
  const currentPlan = conversation.values.current ?? original;
  const workspace = workspaceOpen ?? !!currentPlan;
  const shown = viewed ?? currentPlan;
  const viewing = shown ?? plans.at(-1)?.source;
  const task = liveTask ? tasks[liveTask] : undefined;
  const reconnect = useRef(conversation.reconnect);
  const reloadThread = useRef(conversation.thread.reload);
  useEffect(() => {
    reconnect.current = conversation.reconnect;
    reloadThread.current = conversation.thread.reload;
  });
  useEffect(() => {
    if (!threadId) return;
    let disposed = false;
    let pendingRun: string | null = null;
    try {
      pendingRun = sessionStorage.getItem(`llm4om-agent-run-${threadId}`);
      if (pendingRun) sessionStorage.removeItem(`llm4om-agent-run-${threadId}`);
    } catch { /* storage may be unavailable */ }
    void client.runs.list(threadId, { limit: 1 }).then(runs => {
      if (disposed) return;
      const active = runs[0];
      if (active && (active.status === "pending" || active.status === "running")) return reconnect.current(active.run_id);
      if (pendingRun) {
        reloadThread.current();
        return reconnect.current(active?.run_id ?? pendingRun);
      }
    }).catch(error => { if (!disposed) toast.error(errorText(error)); });
    return () => { disposed = true; };
  }, [threadId]);

  const submit = async (retry = false) => {
    if (busy || dataPending || (!retry && !input.trim())) return;
    if (!preset) { toast.error(t("请先配置可用的 AI 模型。")); openPresets(); return; }
    followLatest(); setViewed(undefined); setLiveTask(undefined); setProgress(undefined); setTasks({});
    const context = { preset: preset.id, locale, search: searching && canSearch, thinking: thinkingMode,
      method: chosenMethod === "auto" ? null : chosenMethod, language: chosenLanguage === "auto" ? null : chosenLanguage };
    const metadata = { preset: preset.id, provider: preset.provider, model: preset.name || preset.model,
      method: context.method, language: context.language, search: context.search, thinking: thinkingMode };
    if (!threadId) {
      const created = await conversation.startThread({ context, metadata: { ...metadata, kind: "optimization",
        title: input.trim().split("\n")[0].slice(0, 120) }, values: { data } });
      if (created && mounted.current) { onThread(created); onFinished(); }
    } else await conversation.send({ retry, context, values: { data }, metadata });
  };
  const stop = async () => { if (await conversation.stop()) { setLiveTask(undefined); onFinished(); } };
  const saveData = async (next: Record<string, string>) => {
    setSavingData(true);
    try {
      if (threadId) await saveThreadValues(threadId, { data: next });
      setFiles(next);
    } finally { setSavingData(false); }
  };
  if (conversation.thread.error) return <div className="flex h-full flex-col">
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-2 xl:hidden">
      <Button variant="ghost" size="icon" aria-label={t("打开菜单")} onClick={onMenu}><Menu /></Button><span className="text-sm font-medium">{t("对话规划")}</span>
    </header>
    <div role="alert" className="grid flex-1 place-content-center gap-3 p-6 text-sm text-destructive">
      <p>{errorText(conversation.thread.error)}</p><Button variant="outline" onClick={conversation.thread.reload}><RefreshCw />{t("重试")}</Button></div>
  </div>;

  const empty = !threadId && !messages.length && !failure && !busy && !settings && !Object.keys(data).length;
  const chat = <section aria-label={t("优化对话")} className={cn("flex h-full min-h-0 min-w-0 flex-col", empty && "justify-center", workspace && pane === "workspace" && "hidden lg:flex")}>
    <div className={cn("relative flex min-h-0 flex-col", !empty && "flex-1")}>
      <div ref={log} role="log" aria-label={t("对话记录")} aria-busy={conversation.loading} className={cn("min-h-0 chat-scroll overflow-y-auto overscroll-contain px-4 md:px-8", empty ? "max-h-[60vh]" : "flex-1")}>
        <div ref={content} className="grid min-h-full grid-cols-1">
          {messages.length || failure ? <ChatMessages messages={messages} loading={conversation.loading} label={t("优化助手")}
            failure={failure} disabled={busy || dataPending} onRetry={() => void submit(true)} progress={progress} tasks={tasks}
            onShowTask={id => { setLiveTask(id); setWorkspace(true); setPane("workspace"); }}
            onOpenPlan={source => { setViewed(source); setLiveTask(undefined); setWorkspace(true); setPane("workspace"); }} onCompare={onCompare} />
            : <div className="animate-fade-up mx-auto flex w-full min-h-full max-w-[46rem] flex-col justify-center gap-5 py-6">
              <div className="space-y-2">
                <div className="inline-flex items-center gap-1.5 rounded-full border border-primary/20 bg-primary/8 px-3 py-1 text-xs font-medium text-primary">
                  <Sparkles className="size-3.5" />
                  <span>{t("对话式需求梳理与智能求解")}</span>
                </div>
                <h2 className="text-2xl font-semibold tracking-tight sm:text-[1.7rem]">{t("聊聊你想解决什么问题")}</h2>
                <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
                  {t("哪怕只有初步想法也没关系。告诉我你的业务目标和限制条件，我会一步步帮你理清需求、自动建模并求得最优方案。")}
                </p>
              </div>
              <div className="grid gap-2.5 sm:grid-cols-2">
                {AGENT_STARTERS.map(item => {
                  const Icon = item.icon;
                  return <button
                    key={item.title}
                    type="button"
                    onClick={() => { setInput(t(item.prompt)); inputArea.current?.focus(); }}
                    className="group flex items-start gap-3 rounded-2xl border border-border/80 bg-card/85 p-3.5 text-left shadow-2xs transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/35 hover:bg-card hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                      <Icon className="size-4" />
                    </span>
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-sm font-medium">{t(item.title)}</span>
                        <ArrowRight className="size-3.5 shrink-0 text-muted-foreground opacity-0 transition-all group-hover:translate-x-0.5 group-hover:text-primary group-hover:opacity-100" />
                      </div>
                      <p className="line-clamp-1 text-xs text-muted-foreground">{t(item.summary)}</p>
                    </div>
                  </button>;
                })}
                <button
                  type="button"
                  onClick={onExamples}
                  className="group flex items-start gap-3 rounded-2xl border border-dashed border-border bg-muted/25 p-3.5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/35 hover:bg-card hover:shadow-md focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  <span className="mt-0.5 grid size-8 shrink-0 place-items-center rounded-xl bg-secondary text-secondary-foreground transition-colors group-hover:bg-primary/15 group-hover:text-primary">
                    <BookOpen className="size-4" />
                  </span>
                  <div className="min-w-0 flex-1 space-y-0.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-sm font-medium">{t("浏览案例模板库")}</span>
                      <ArrowRight className="size-3.5 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                    </div>
                    <p className="line-clamp-1 text-xs text-muted-foreground">{t("查看真实行业优化案例并一键带入")}</p>
                  </div>
                </button>
              </div>
            </div>}
        </div>
      </div>
      {!follow ? <Button variant="outline" size="icon-sm" aria-label={t("回到最新消息")} className="absolute right-5 bottom-3 rounded-full bg-background shadow-sm" onClick={followLatest}><ArrowDown /></Button> : null}
    </div>
    <div className="shrink-0 space-y-2 px-4 pt-2 pb-4 md:px-8">
      {Object.keys(data).length ? <div className="mx-auto flex max-w-[46rem] flex-wrap gap-1.5" aria-label={t("数据文件")}>
        {Object.keys(data).map(name => <span key={name} className="inline-flex max-w-full items-center rounded-xl border border-border/80 bg-card text-xs shadow-2xs">
          <button disabled={busy || dataPending} className="min-w-0 truncate px-2.5 py-1.5 font-medium hover:text-primary" onClick={() => setEditing(name)}>{name}</button>
          <Button variant="ghost" size="icon-xs" className="mr-0.5" disabled={busy || dataPending} aria-label={t("移除 {name}", { name })} onClick={() => {
            const next = { ...data }; delete next[name]; void saveData(next).catch(error => toast.error(errorText(error)));
          }}><X /></Button></span>)}
      </div> : null}
      {settings ? <div className="animate-scale-in mx-auto grid max-w-[46rem] grid-cols-1 gap-2.5 rounded-2xl border border-border/80 bg-card/90 p-3.5 shadow-xs sm:grid-cols-2">
        <label className="space-y-1 text-xs font-medium text-muted-foreground">{t("求解策略偏好")}
          <Select value={chosenMethod} onValueChange={setMethod} disabled={busy}><SelectTrigger className="w-full" aria-label={t("固定建模方法")}><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="auto">{t("智能自动选择（推荐）")}</SelectItem>{options.methods.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent></Select></label>
        <label className="space-y-1 text-xs font-medium text-muted-foreground">{t("求解引擎偏好")}
          <Select value={chosenLanguage} onValueChange={setLanguage} disabled={busy}><SelectTrigger className="w-full" aria-label={t("固定建模求解器")}><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="auto">{t("智能自动匹配（推荐）")}</SelectItem>{options.languages.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent></Select></label>
      </div> : null}
      <ChatInput label={t("发送给优化助手")} value={input} onChange={setInput}
        disabled={busy} sendingDisabled={dataPending} loading={conversation.loading} stopping={conversation.stopping} inputRef={inputArea}
        presets={presets} presetId={presetId} onPreset={setSelected} thinking={thinkingMode} onThinking={setThinking} openPresets={openPresets}
        onSend={() => void submit()} onStop={() => void stop()} placeholder={t("描述你想解决的业务问题，或继续补充调整要求…")}>
        <Button type="button" variant="ghost" size="icon-sm" disabled={busy || dataPending} aria-label={t("添加数据文件")}
          title={t(reading ? "正在读取数据……" : savingData ? "正在保存……" : "添加数据文件")} onClick={() => upload.current?.click()}>
          {dataPending ? <Spinner /> : <Paperclip />}</Button>
        <span title={canSearch ? t("搜索公开资料，并在回复中展示来源。") : t("选择支持搜索的模型或由管理员开启搜索服务。")}>
          <Toggle size="sm" pressed={searching && canSearch} disabled={busy || !canSearch} aria-label={t("联网搜索")} onPressedChange={setSearch}><Globe /><span className="hidden @lg:inline">{t("联网搜索")}</span></Toggle>
        </span>
        <Button type="button" variant={settings || chosenMethod !== "auto" || chosenLanguage !== "auto" ? "secondary" : "ghost"} size="icon-sm" aria-label={t("建模偏好")}
          title={`${options.methods.find(item => item.id === chosenMethod)?.name || t("自动选择")} · ${options.languages.find(item => item.id === chosenLanguage)?.name || t("自动选择")}`}
          aria-expanded={settings} onClick={() => setSettings(!settings)}><SlidersHorizontal /></Button>
      </ChatInput>
      <input ref={upload} type="file" multiple accept={DATA_FILE_ACCEPT} className="hidden" disabled={busy || dataPending} aria-label={t("数据文件")} onChange={async event => {
        const field = event.currentTarget;
        if (!field.files?.length || busy || dataPending) return;
        setReading(true);
        try {
          const added = await readDataFiles(field.files, data);
          if (Object.keys(added).length) await saveData({ ...data, ...added });
        } catch (error) { toast.error(errorText(error)); }
        finally { field.value = ""; setReading(false); }
      }} />
    </div>
  </section>;

  const workbench = workspace ? <aside aria-label={t("方案面板")} className={cn("flex h-full min-h-0 min-w-0 flex-col border-l border-border/70 bg-card", pane !== "workspace" && "hidden lg:flex")}>
    <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border/70 bg-muted/15 px-3.5">
      <h2 className="shrink-0 text-xs font-semibold text-muted-foreground">{t("方案面板")}</h2>
      {plans.length ? <Select value={task ? "live" : viewing ? sourceKey(viewing) : ""} onValueChange={id => {
        const chosen = plans.find(plan => sourceKey(plan.source) === id)?.source;
        if (chosen) { setViewed(chosen); setLiveTask(undefined); }
      }}>
        <SelectTrigger size="sm" aria-label={t("查看计算方案")} className="min-w-0 flex-1 border-0 shadow-none"><SelectValue /></SelectTrigger>
        <SelectContent>{task ? <SelectItem value="live">{task.name}</SelectItem> : null}{plans.map(plan => <SelectItem key={sourceKey(plan.source)} value={sourceKey(plan.source)}>{plan.name}{sameSource(plan.source, currentPlan) ? ` · ${t("当前讨论方案")}` : ""}</SelectItem>)}</SelectContent>
      </Select> : <span className="min-w-0 flex-1 truncate text-xs font-medium">{task?.name}</span>}
      {shown && !task ? <Button variant="ghost" size="icon-xs" aria-label={t("打开完整运行")} title={t("独立页面查看")} onClick={() => onOpen(shown)}><ArrowUpRight /></Button> : null}
      <Button variant="ghost" size="icon-xs" aria-label={t("收起方案面板")} onClick={() => { setWorkspace(false); setPane("chat"); }}><X /></Button>
    </div>
    {!task && shown && currentPlan && !sameSource(shown, currentPlan) ? <div className="flex shrink-0 items-center justify-between gap-2 border-b bg-muted/30 px-3.5 py-2 text-xs" aria-label={t("方案上下文")}>
      <Badge variant="outline">{t("正在查看历史方案")}</Badge>
      <Button variant="link" size="xs" className="h-auto p-0" onClick={() => setViewed(undefined)}>{t("返回当前讨论方案")}</Button>
    </div> : null}
    <div className="min-h-0 flex-1">{task ? <LiveWorkspace key={liveTask} task={task} data={data} options={options} /> : shown ? renderRun(shown)
      : <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">{t("开始求解后，最优决策方案、数学模型与计算代码将实时呈现在这里。")}</div>}</div>
  </aside> : null;

  return <div className="flex h-full min-h-0 flex-col">
    <header className="flex h-12 shrink-0 items-center gap-2 border-b border-border/70 bg-background/80 px-4 backdrop-blur-md">
      <Button variant="ghost" size="icon-sm" aria-label={t("打开菜单")} className="-ml-2 xl:hidden" onClick={onMenu}><Menu /></Button>
      <Sparkles className="hidden size-4 text-primary sm:block" />
      <h1 className="min-w-0 flex-1 truncate text-sm font-semibold">{meta?.title || t("对话规划")}</h1>
      {(plans.length > 0 || !!currentPlan || !!task || workspace) ? <Button variant={workspace ? "secondary" : "ghost"} size="sm" className="rounded-lg" aria-pressed={workspace} onClick={() => { setWorkspace(!workspace); setPane("workspace"); }}>
        <Columns2 />{t("方案面板")}
      </Button> : null}
    </header>
    {workspace ? <div className="flex shrink-0 border-b lg:hidden">
      <Button variant={pane === "chat" ? "secondary" : "ghost"} className="flex-1 rounded-none" onClick={() => setPane("chat")}>{t("对话")}</Button>
      <Button variant={pane === "workspace" ? "secondary" : "ghost"} className="flex-1 rounded-none" onClick={() => setPane("workspace")}>{t("方案面板")}</Button>
    </div> : null}
    {desktop ? <ResizablePanelGroup orientation="horizontal" defaultLayout={layout.defaultLayout} onLayoutChanged={layout.onLayoutChanged} className="min-h-0 flex-1">
      <ResizablePanel id="conversation" defaultSize="42%" minSize="320px">{chat}</ResizablePanel>
      {workspace ? <>
        <ResizableHandle withHandle aria-label={t("调整对话与方案面板的宽度")} />
        <ResizablePanel id="workspace" defaultSize="58%" minSize="35%">{workbench}</ResizablePanel>
      </> : null}
    </ResizablePanelGroup> : <div className="grid min-h-0 flex-1 grid-cols-1">{chat}{workbench}</div>}
    {editing && data[editing] != null ? <DataEditor key={editing} name={editing} content={data[editing]} onClose={() => setEditing(undefined)}
      onSave={content => saveData({ ...data, [editing]: content })} /> : null}
  </div>;
}

function LiveWorkspace({ task, data, options }: { task: ModelingTask; data: Record<string, string>; options: Options }) {
  const [tab, setTab] = useState<Tab>("formulation");
  const [picked, setPicked] = useState<Partial<Record<"formulation" | "code", string>>>({});
  const values: RunValues = { data, ...Object.assign({}, ...task.steps.filter(step => step.type === "artifact").map(step => ({
    ...(step.formulation ? { formulation: step.formulation } : {}), ...(step.code ? { code: step.code } : {}),
  }))) };
  return <Outputs values={values} steps={task.steps} active tab={tab} setTab={setTab} picked={picked}
    setPicked={(key, id) => setPicked(current => ({ ...current, [key]: id }))}
    language={options.languages.find(item => item.id === task.language)} finished={false} onAdjust={() => undefined} />;
}
