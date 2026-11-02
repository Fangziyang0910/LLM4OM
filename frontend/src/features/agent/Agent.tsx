import { type ReactNode, useEffect, useRef, useState } from "react";
import { useDefaultLayout } from "react-resizable-panels";
import type { Message } from "@langchain/langgraph-sdk";
import { ArrowDown, ArrowUpRight, BookOpen, Columns2, Globe, Menu, Paperclip, RefreshCw, SlidersHorizontal, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { useDesktop } from "@/lib/useDesktop";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Toggle } from "@/components/ui/toggle";
import { ChatInput } from "@/features/chat/ChatInput";
import { ChatMessages, type ChatProgress, type ModelingEvent, type ModelingTask } from "@/features/chat/Messages";
import { useConversation } from "@/features/chat/conversation";
import { useChatScroll } from "@/features/chat/scroll";
import { DATA_FILE_ACCEPT, readDataFiles } from "@/features/composer/files";
import { DataEditor } from "@/features/composer/DataEditor";
import { Outputs, type Tab } from "@/features/runs/Outputs";
import { client } from "@/features/runs/sdk";
import type { OptimizationMeta, Plan, RunValues, SourceRun, Usage } from "@/features/runs/types";
import { sameSource, sourceKey } from "@/features/runs/types";
import type { Options, Preset } from "@/types";
import { errorText } from "@/format";
import { locale, t } from "@/i18n";
import { cn } from "@/lib/utils";

type Values = { messages?: Message[]; description?: string; data?: Record<string, string>; source?: SourceRun;
  current?: SourceRun; plans?: Plan[]; usage?: Usage; failure?: string | null };

export function Agent({ threadId, options, presets, initial, onThread, openPresets, onManual, onMenu, onExamples, onFinished, onOpen, onCompare, renderRun }: {
  threadId?: string; options: Options; presets: Preset[]; initial: { description: string; data: Record<string, string> };
  onThread: (id: string) => void; openPresets: () => void; onManual: () => void; onMenu: () => void; onExamples: () => void;
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
  const [editing, setEditing] = useState<string>();
  const [tasks, setTasks] = useState<Record<string, ModelingTask>>({});
  const [progress, setProgress] = useState<ChatProgress>();
  const [viewed, setViewed] = useState<SourceRun>();
  const [liveTask, setLiveTask] = useState<string>();
  const [workspaceOpen, setWorkspace] = useState<boolean>();
  const [pane, setPane] = useState<"chat" | "workspace">("chat");
  const inputArea = useRef<HTMLTextAreaElement>(null);
  const upload = useRef<HTMLInputElement>(null);
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
    onFinish: () => { setLiveTask(undefined); onFinished(); },
    onError: () => { setLiveTask(undefined); onFinished(); },
  });
  const meta = conversation.thread.metadata as OptimizationMeta | undefined;
  const { input, setInput } = conversation;
  const messages = conversation.messages;
  const data = files ?? conversation.values.data ?? initial.data;
  const presetId = selected ?? meta?.preset ?? presets[0]?.id;
  const preset = presets.find(item => item.id === presetId);
  const thinkingMode = preset?.provider === "deepseek" ? thinking ?? meta?.thinking ?? null : null;
  const chosenMethod = method ?? meta?.method ?? "auto";
  const chosenLanguage = language ?? meta?.language ?? "auto";
  const searching = search ?? meta?.search ?? false;
  const canSearch = !!options.search_configured || preset?.provider === "deepseek";
  const busy = conversation.busy;
  const failure = conversation.error || conversation.values.failure;
  const plans = conversation.values.plans ?? [];
  const original = conversation.values.source;
  const currentPlan = conversation.values.current ?? original;
  const workspace = workspaceOpen ?? !!currentPlan;
  const shown = viewed ?? currentPlan;
  const viewing = shown ?? plans.at(-1)?.source;
  const task = liveTask ? tasks[liveTask] : undefined;
  const reconnect = useRef(conversation.reconnect);
  useEffect(() => { reconnect.current = conversation.reconnect; });
  useEffect(() => {
    if (!threadId) return;
    let disposed = false;
    // The first run is started before navigation, so attach through the SDK even without a tab-local receipt.
    void client.runs.list(threadId, { limit: 1 }).then(runs => {
      const active = runs[0];
      if (!disposed && active && (active.status === "pending" || active.status === "running")) return reconnect.current(active.run_id);
    }).catch(error => { if (!disposed) toast.error(errorText(error)); });
    return () => { disposed = true; };
  }, [threadId]);

  const submit = async (retry = false) => {
    if (busy || (!retry && !input.trim())) return;
    if (!preset) { toast.error(t("先选择一个可用的预设模型。")); openPresets(); return; }
    followLatest(); setViewed(undefined); setLiveTask(undefined); setProgress(undefined); setTasks({});
    const context = { preset: preset.id, locale, search: searching && canSearch, thinking: thinkingMode,
      method: chosenMethod === "auto" ? null : chosenMethod, language: chosenLanguage === "auto" ? null : chosenLanguage };
    const metadata = { preset: preset.id, provider: preset.provider, model: preset.name || preset.model,
      method: context.method, language: context.language, search: context.search, thinking: thinkingMode };
    if (!threadId) {
      // Persist the question with the native thread first, then start its run before navigating to the thread.
      const created = await conversation.startThread({ context, metadata: { ...metadata, kind: "optimization",
        title: input.trim().split("\n")[0].slice(0, 120) }, values: { description: initial.description, data } });
      if (created) { onThread(created); onFinished(); }
    } else if (await conversation.send({ retry, context, values: { data }, metadata })) setFiles(null);
  };
  const stop = async () => { if (await conversation.stop()) { setLiveTask(undefined); onFinished(); } };
  const saveData = async (next: Record<string, string>) => {
    if (threadId) await client.threads.updateState(threadId, { values: { data: next }, asNode: "discuss" });
    setFiles(next);
  };
  if (conversation.thread.error) return <div className="flex h-full flex-col">
    <header className="flex h-12 shrink-0 items-center gap-2 border-b px-2 xl:hidden">
      <Button variant="ghost" size="icon" aria-label={t("打开菜单")} onClick={onMenu}><Menu /></Button><span className="text-sm font-medium">{t("优化对话")}</span>
    </header>
    <div role="alert" className="grid flex-1 place-content-center gap-3 p-6 text-sm text-destructive">
      <p>{errorText(conversation.thread.error)}</p><Button variant="outline" onClick={conversation.thread.reload}><RefreshCw />{t("重试")}</Button></div>
  </div>;
  const empty = !threadId && !messages.length && !failure && !busy && !settings && !Object.keys(data).length;
  const chat = <section aria-label={t("优化对话")} className={cn("flex h-full min-h-0 min-w-0 flex-col", empty && "justify-center", workspace && pane === "workspace" && "hidden lg:flex")}>
    <div className={cn("relative flex min-h-0 flex-col", !empty && "flex-1")}>
      <div ref={log} role="log" aria-label={t("对话记录")} aria-busy={conversation.loading} className={cn("min-h-0 chat-scroll overflow-y-auto overscroll-contain px-4 md:px-8", empty ? "max-h-[50vh]" : "flex-1")}>
        <div ref={content} className="grid min-h-full grid-cols-1">
          {messages.length || failure ? <ChatMessages messages={messages} loading={conversation.loading} label={t("优化助手")}
            failure={failure} disabled={busy} onRetry={() => void submit(true)} progress={progress} tasks={tasks}
            onShowTask={id => { setLiveTask(id); setWorkspace(true); setPane("workspace"); }}
            onOpenPlan={source => { setViewed(source); setLiveTask(undefined); setWorkspace(true); setPane("workspace"); }} onCompare={onCompare} />
            : <div className="mx-auto flex w-full min-h-full max-w-[46rem] flex-col justify-center gap-4 py-5">
              <h2 className="text-2xl font-semibold tracking-tight">{t("说说你想优化什么")}</h2>
              <p className="text-sm leading-7 text-muted-foreground">{t("可以先提问、聊想法或整理资料，也可以直接描述要优化的问题。需要计算时，助手会调用建模方法，和你一起把方案做出来。")}</p>
              <div className="flex flex-wrap gap-2">
                <Button variant="outline" onClick={() => { setInput(t("我想给门店安排下周的班次，应该先提供哪些信息？")); inputArea.current?.focus(); }}>{t("聊聊排班需求")}</Button>
                <Button variant="outline" onClick={onExamples}><BookOpen />{t("从示例开始")}</Button>
              </div>
            </div>}
        </div>
      </div>
      {!follow ? <Button variant="outline" size="icon-sm" aria-label={t("回到最新消息")} className="absolute right-5 bottom-3 rounded-full bg-background shadow-sm" onClick={followLatest}><ArrowDown /></Button> : null}
    </div>
    <div className="shrink-0 space-y-2 px-4 pt-2 pb-3 md:px-8">
      {Object.keys(data).length ? <div className="mx-auto flex max-w-[46rem] flex-wrap gap-1.5" aria-label={t("数据文件")}>
        {Object.keys(data).map(name => <span key={name} className="inline-flex max-w-full items-center rounded-lg border bg-card text-xs">
          <button disabled={busy} className="min-w-0 truncate px-2 py-1.5 hover:text-primary" onClick={() => setEditing(name)}>{name}</button>
          <Button variant="ghost" size="icon-xs" disabled={busy} aria-label={t("移除 {name}", { name })} onClick={() => {
            const next = { ...data }; delete next[name]; void saveData(next).catch(error => toast.error(errorText(error)));
          }}><X /></Button></span>)}
      </div> : null}
      {settings ? <div className="mx-auto grid max-w-[46rem] grid-cols-2 gap-2 rounded-xl border bg-muted/30 p-3">
        <label className="space-y-1 text-xs text-muted-foreground">{t("建模方法")}
          <Select value={chosenMethod} onValueChange={setMethod} disabled={busy}><SelectTrigger className="w-full" aria-label={t("固定建模方法")}><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="auto">{t("自动选择")}</SelectItem>{options.methods.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent></Select></label>
        <label className="space-y-1 text-xs text-muted-foreground">{t("建模求解器")}
          <Select value={chosenLanguage} onValueChange={setLanguage} disabled={busy}><SelectTrigger className="w-full" aria-label={t("固定建模求解器")}><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="auto">{t("自动选择")}</SelectItem>{options.languages.map(item => <SelectItem key={item.id} value={item.id}>{item.name}</SelectItem>)}</SelectContent></Select></label>
      </div> : null}
      <ChatInput label={t("发送给优化助手")} value={input} onChange={setInput}
        disabled={busy} loading={conversation.loading} stopping={conversation.stopping} inputRef={inputArea}
        presets={presets} presetId={presetId} onPreset={setSelected} thinking={thinkingMode} onThinking={setThinking} openPresets={openPresets}
        onSend={() => void submit()} onStop={() => void stop()} placeholder={t("提问、聊聊想法，或继续调整当前方案……")}>
        <Button type="button" variant="ghost" size="icon-sm" disabled={busy} aria-label={t("添加数据文件")} onClick={() => upload.current?.click()}><Paperclip /></Button>
        <Toggle size="sm" pressed={searching} disabled={busy || !canSearch} aria-label={t("联网搜索")} onPressedChange={setSearch}><Globe /><span className="hidden @lg:inline">{t("联网搜索")}</span></Toggle>
        <Button type="button" variant={settings ? "secondary" : "ghost"} size="icon-sm" aria-label={t("建模偏好")} aria-expanded={settings} onClick={() => setSettings(!settings)}><SlidersHorizontal /></Button>
      </ChatInput>
      <p className="text-center text-[11px] text-muted-foreground">{chosenMethod !== "auto" || chosenLanguage !== "auto"
        ? `${options.methods.find(item => item.id === chosenMethod)?.name || t("自动选择")} · ${options.languages.find(item => item.id === chosenLanguage)?.name || t("自动选择")}`
          : t("Enter 发送，Shift+Enter 换行")}</p>
      <input ref={upload} type="file" multiple accept={DATA_FILE_ACCEPT} className="hidden" aria-label={t("数据文件")} onChange={async event => {
        const field = event.currentTarget;
        try {
          const added = await readDataFiles(field.files);
          field.value = "";
          await saveData({ ...data, ...added });
        } catch (error) { toast.error(errorText(error)); }
      }} />
    </div>
  </section>;
  const workbench = workspace ? <aside aria-label={t("建模工作区")} className={cn("flex h-full min-h-0 min-w-0 flex-col bg-card", pane !== "workspace" && "hidden lg:flex")}>
    <div className="flex h-12 shrink-0 items-center gap-2 border-b px-3">
      <h2 className="shrink-0 text-xs font-medium text-muted-foreground">{t("建模工作区")}</h2>
      {plans.length ? <Select value={task ? "live" : viewing ? sourceKey(viewing) : ""} onValueChange={id => {
        const chosen = plans.find(plan => sourceKey(plan.source) === id)?.source;
        if (chosen) { setViewed(chosen); setLiveTask(undefined); }
      }}>
        <SelectTrigger size="sm" aria-label={t("查看计算方案")} className="min-w-0 flex-1 border-0 shadow-none"><SelectValue /></SelectTrigger>
        <SelectContent>{task ? <SelectItem value="live">{task.name}</SelectItem> : null}{plans.map(plan => <SelectItem key={sourceKey(plan.source)} value={sourceKey(plan.source)}>{plan.name}{sameSource(plan.source, currentPlan) ? ` · ${t("当前讨论方案")}` : ""}</SelectItem>)}</SelectContent>
      </Select> : <span className="min-w-0 flex-1 truncate text-xs">{task?.name}</span>}
      {shown && !task ? <Button variant="ghost" size="icon-xs" aria-label={t("打开完整运行")} onClick={() => onOpen(shown)}><ArrowUpRight /></Button> : null}
      <Button variant="ghost" size="icon-xs" aria-label={t("收起建模工作区")} onClick={() => { setWorkspace(false); setPane("chat"); }}><X /></Button>
    </div>
    {!task && shown && currentPlan ? <div className="flex shrink-0 items-center justify-between gap-2 border-b bg-muted/30 px-3 py-2 text-xs" aria-label={t("方案上下文")}>
      {sameSource(shown, currentPlan) ? <span className="text-muted-foreground">{t("后续对话将基于此方案继续。")}</span> : <>
        <Badge variant="outline">{t("正在查看历史方案")}</Badge>
        <Button variant="link" size="xs" className="h-auto p-0" onClick={() => setViewed(undefined)}>{t("查看讨论中的方案")}</Button>
      </>}
    </div> : null}
    <div className="min-h-0 flex-1">{task ? <LiveWorkspace key={liveTask} task={task} data={data} options={options} /> : shown ? renderRun(shown)
      : <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">{t("开始计算后，在这里查看数学模型、代码和求解结果。")}</div>}</div>
  </aside> : null;
  return <div className="flex h-full min-h-0 flex-col">
    <header className="flex h-13 shrink-0 items-center gap-2 border-b px-4">
      <Button variant="ghost" size="icon-sm" aria-label={t("打开菜单")} className="-ml-2 xl:hidden" onClick={onMenu}><Menu /></Button>
      <Sparkles className="hidden size-4 text-muted-foreground sm:block" /><h1 className="min-w-0 flex-1 truncate text-sm font-medium">{meta?.title || t("优化对话")}</h1>
      <Button variant="ghost" size="sm" onClick={onManual}>{t("手动建模")}</Button>
      <Button variant={workspace ? "secondary" : "ghost"} size="sm" aria-pressed={workspace} onClick={() => { setWorkspace(!workspace); setPane("workspace"); }}>
        <Columns2 />{t("建模工作区")}</Button>
    </header>
    {workspace ? <div className="flex shrink-0 border-b lg:hidden">
      <Button variant={pane === "chat" ? "secondary" : "ghost"} className="flex-1 rounded-none" onClick={() => setPane("chat")}>{t("对话")}</Button>
      <Button variant={pane === "workspace" ? "secondary" : "ghost"} className="flex-1 rounded-none" onClick={() => setPane("workspace")}>{t("建模工作区")}</Button>
    </div> : null}
    {desktop ? <ResizablePanelGroup orientation="horizontal" defaultLayout={layout.defaultLayout} onLayoutChanged={layout.onLayoutChanged} className="min-h-0 flex-1">
      <ResizablePanel id="conversation" defaultSize="40%" minSize="320px">{chat}</ResizablePanel>
      {workspace ? <>
        <ResizableHandle withHandle aria-label={t("调整对话与建模工作区的宽度")} />
        <ResizablePanel id="workspace" defaultSize="60%" minSize="35%">{workbench}</ResizablePanel>
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
