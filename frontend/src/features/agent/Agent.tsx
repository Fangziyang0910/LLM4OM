import { type DragEvent, type ReactNode, type Ref, lazy, Suspense, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDefaultLayout } from "react-resizable-panels";
import type { Message } from "@langchain/langgraph-sdk";
import { ArrowDown, ArrowRight, ArrowUpRight, BookOpen, CalendarDays, Columns2, Factory, FileUp, GitFork, Globe, Menu, PanelLeftOpen, Paperclip, SlidersHorizontal, X } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/api";
import { Badge } from "@/components/ui/badge";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { useDesktop } from "@/lib/useDesktop";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Select, SelectContent, SelectGroup, SelectItem, SelectLabel, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { LogoMark } from "@/components/Logo";
import { ChatInput, ToolToggle } from "@/features/chat/ChatInput";
import type { ChatProgress, ModelingEvent, ModelingTask, Suggestion } from "@/features/chat/Messages";
import { resultType, type ComputedPlan, type ToolArtifact } from "@/features/chat/results";
import { inputFingerprint } from "@/features/chat/inputFingerprint";
import { useChatModel, useConversation } from "@/features/chat/conversation";
import { useChatScroll } from "@/features/chat/scroll";
import { DATA_FILE_ACCEPT, readDataFiles } from "@/features/composer/files";
import { DataEditor } from "@/features/composer/DataEditor";
import { saveThreadValues } from "@/features/runs/api";
import { client } from "@/features/runs/sdk";
import type { OptimizationMeta, Plan, SourceRun, Usage } from "@/features/runs/types";
import { sameSource, sourceKey } from "@/features/runs/types";
import type { BackendCatalog, Options, Preset } from "@/types";
import { errorText, shortTitle } from "@/format";
import { DisplayText } from "@/components/DisplayTranslation";
import { locale, t } from "@/i18n";
import { cn } from "@/lib/utils";

const ChatMessages = lazy(() => import("@/features/chat/Messages").then(module => ({ default: module.ChatMessages })));
const ThreadLoadError = lazy(() => import("@/features/chat/Messages").then(module => ({ default: module.ThreadLoadError })));
const LiveWorkspace = lazy(() => import("./LiveWorkspace"));
const CORE_METHODS = new Set(["direct", "or_llm_agent", "llmopt", "trival", "bind", "autoco"]);

type Values = { messages?: Message[]; description?: string; data?: Record<string, string>; source?: SourceRun;
  current?: SourceRun; plans?: Plan[]; usage?: Usage; failure?: string | null };

const AGENT_STARTERS = [
  {
    icon: Factory,
    title: "生产排产优化",
    summary: "在产能与原料约束下最大化总利润",
    prompt: "工厂生产 A、B 两种产品，数量必须是非负整数。每件 A 利润为 3，每件 B 利润为 2。A 消耗 2 单位切割资源和 1 单位加工资源，B 消耗 1 单位切割资源和 2 单位加工资源，两种资源各有 8 单位。请直接帮我算出总利润最高的生产方案。",
  },
  {
    icon: GitFork,
    title: "多目标 GPU 调度",
    summary: "同时权衡总电费与故障风险，生成 Pareto 权衡方案",
    prompt: "请帮我把 12 个 AI 计算任务（算力需求 [18, 25, 14, 30, 22, 16, 28, 19, 24, 15, 27, 20]）分配到 4 个 GPU 集群（算力上限 [80, 90, 75, 85]，电费系数 [1.0, 1.2, 0.9, 1.3]，故障风险系数 [0.08, 0.04, 0.11, 0.02]）。互斥任务对 (0,1)、(3,6)、(5,10) 不能分在同一集群。请同时最小化总电费和总故障风险，给我一组多目标 Pareto 权衡方案。",
  },
  {
    icon: CalendarDays,
    title: "门店排班规划",
    summary: "平衡高峰人手需求与人力成本，边聊边理清约束",
    prompt: "我想给门店安排下周的班次，既要保证高峰时段人手充足，又想控制总排班成本，应该先提供哪些信息？",
  },
] as const;

/** The plans the latest turn computed, if it computed any. */
function latestPlans(messages: Message[]): ComputedPlan[] | undefined {
  for (const message of [...messages].reverse()) {
    if (message.type === "human") return undefined;
    if (message.type === "tool" && resultType(message.artifact as ToolArtifact | undefined, message.name) === "plans")
      return (message.artifact as ToolArtifact | undefined)?.plans;
  }
  return undefined;
}

/** Next questions after a turn that computed plans; templates leave a place for the user's own condition. */
function planSuggestions(plans: ComputedPlan[]): Suggestion[] {
  const ask = (label: string, text: string): Suggestion => ({ label, text, send: true });
  const fill = (label: string, text: string, after: string): Suggestion => ({ label, text, after, send: false });
  const compare = fill(t("对比几种情况"), t("请分别计算以下几种情况并对比：\n1. "), "\n2. ");
  const solved = plans.filter(plan => !plan.failure && (plan.objective != null || !!plan.pareto?.total));
  if (!solved.length) return [ask(t("分析原因"), t("为什么没有得到可行方案？请指出可能互相冲突的条件。")),
    fill(t("放宽条件后重算"), t("请把"), t("放宽后重新计算。"))];
  if (plans.length > 1) return [ask(t("选出最合适的方案"), t("请比较这几个方案，告诉我哪个最合适以及原因。")), compare];
  return [
    solved[0].pareto?.total ? ask(t("比较权衡方案"), t("请挑几个有代表性的权衡方案，说明各自的取舍。"))
      : ask(t("解释主要决策"), t("请用业务语言解释这个方案的主要决策。")),
    fill(t("如果条件变化…"), t("如果"), t("，方案会怎样变化？")), compare,
  ];
}

export function Agent({ threadId, options, presets, ref, sidebarCollapsed = false, onExpandSidebar, onThread, openPresets, onMenu, onExamples, onFinished, onOpen, onCompare, renderRun }: {
  threadId?: string; options: Options; presets: Preset[];
  ref?: Ref<{ fillIfEmpty: (description: string) => boolean }>; sidebarCollapsed?: boolean; onExpandSidebar?: () => void;
  onThread: (id: string) => void; openPresets: () => void; onMenu: () => void; onExamples?: () => void;
  onFinished: () => void; onOpen: (source: SourceRun) => void; onCompare: (id: string) => void; renderRun: (source: SourceRun) => ReactNode;
}) {
  const desktop = useDesktop();
  const layout = useDefaultLayout({ id: "llm4om-agent", panelIds: ["conversation", "workspace"], onlySaveAfterUserInteractions: true });
  const [method, setMethod] = useState<string>();
  const [language, setLanguage] = useState<string>();
  const [solver, setSolver] = useState<string>();
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
  const [dragging, setDragging] = useState(false);
  const inputArea = useRef<HTMLTextAreaElement>(null);
  const upload = useRef<HTMLInputElement>(null);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const conversation = useConversation<Values, { CustomEventType: ChatProgress | ModelingEvent }>({
    assistantId: "optimization", threadId, reconnectOnMount: false,
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
  const data = files ?? conversation.values.data ?? {};
  const { preset, presetId, setSelected, thinkingMode, setThinking } = useChatModel(presets, meta);
  const chosenMethod = method ?? meta?.method ?? "auto";
  const chosenMethodMeta = options.methods.find(item => item.id === chosenMethod);
  const chosenSelfContained = !!chosenMethodMeta?.builtin_solver;
  const rawLanguage = chosenSelfContained ? "auto" : (language ?? meta?.language ?? "auto");
  const languageAllowed = (id: string) =>
    !chosenMethodMeta || chosenMethodMeta.builtin_solver || !chosenMethodMeta.languages || chosenMethodMeta.languages.includes(id);
  const chosenLanguage = rawLanguage === "auto" || languageAllowed(rawLanguage) ? rawLanguage : "auto";
  const chosenSolver = chosenSelfContained || chosenLanguage === "auto" ? "AUTO" : (solver ?? meta?.solver ?? "AUTO");
  const catalog = useQuery({
    queryKey: ["backends"],
    queryFn: () => api<BackendCatalog>("/api/backends"),
    enabled: settings && chosenLanguage !== "auto",
    staleTime: Infinity,
    retry: false,
  });
  const backends = chosenLanguage !== "auto" ? catalog.data?.libraries[chosenLanguage] : undefined;
  const coreMethods = options.methods.filter(item => CORE_METHODS.has(item.id));
  const extraMethods = options.methods.filter(item => !CORE_METHODS.has(item.id));
  const customized = chosenMethod !== "auto" || chosenLanguage !== "auto" || chosenSolver !== "AUTO";
  const configSummary = !customized
    ? t("自动求解")
    : [
      chosenMethodMeta?.name ?? (chosenMethod === "auto" ? t("自动方法") : chosenMethod),
      !chosenSelfContained && chosenLanguage !== "auto" ? (options.languages.find(item => item.id === chosenLanguage)?.name ?? chosenLanguage) : null,
      !chosenSelfContained && chosenSolver !== "AUTO" ? chosenSolver : null,
    ].filter(Boolean).join(" · ");
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
  const occupied = !!input || !!Object.keys(data).length || reading || savingData || conversation.busy;
  useImperativeHandle(ref, () => ({
    fillIfEmpty(description) {
      if (occupied) return false;
      setInput(description);
      return true;
    },
  }), [occupied, setInput]);
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
    void client.runs.list(threadId, { limit: 1, select: ["run_id", "status"] }).then(runs => {
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

  /** The model, tools and pinned configuration of a new turn; null when no model is configured yet. */
  const startTurn = () => {
    if (!preset) { toast.error(t("请先配置可用的 AI 模型。")); openPresets(); return null; }
    followLatest(); setViewed(undefined); setLiveTask(undefined); setProgress(undefined); setTasks({});
    const context = { input_fingerprint: inputFingerprint(data), preset: preset.id, locale, search: searching && canSearch, thinking: thinkingMode,
      method: chosenMethod === "auto" ? null : chosenMethod,
      language: chosenLanguage === "auto" ? null : chosenLanguage,
      solver: chosenSolver === "AUTO" ? null : chosenSolver };
    const metadata = { preset: preset.id, provider: preset.provider, model: preset.name || preset.model,
      method: context.method, language: context.language, solver: context.solver, search: context.search, thinking: thinkingMode };
    return { context, metadata };
  };
  const submit = async (retry = false, text?: string) => {
    if (busy || dataPending || (!retry && !(text ?? input).trim())) return;
    const turn = startTurn();
    if (!turn) return;
    if (!threadId) {
      const created = await conversation.startThread({ ...turn, metadata: { ...turn.metadata, kind: "optimization",
        title: input.trim().split("\n")[0].slice(0, 120) }, values: { data } });
      if (created && mounted.current) { onThread(created); onFinished(); }
    } else await conversation.send({ retry, text, ...turn });
  };
  /** Ask the last question again, edited or unchanged; the files now attached go with it. */
  const rewrite = async (text?: string) => {
    const question = [...messages].reverse().find(message => message.type === "human");
    const original = typeof question?.content === "string" ? question.content : "";
    if (busy || dataPending || !(text ?? original).trim()) return;
    const turn = startTurn();
    if (!turn) return;
    // The conversation is named after its first question, so editing that question renames it.
    const first = messages.find(message => message.type === "human") === question;
    const metadata = first && text ? { ...turn.metadata, title: text.trim().split("\n")[0].slice(0, 120) } : turn.metadata;
    await conversation.rewrite(text ?? original, { ...turn, metadata, values: { data } });
  };
  /** Put a question template in the input, keeping any draft, with the cursor where the user's condition goes. */
  const fill = (before: string, after = "") => {
    const prefix = input.trim() ? `${input.trimEnd()}\n${before}` : before;
    setInput(prefix + after);
    requestAnimationFrame(() => { inputArea.current?.focus(); inputArea.current?.setSelectionRange(prefix.length, prefix.length); });
  };
  const addFiles = async (list: FileList) => {
    if (!list.length) return;
    if (busy || dataPending) { toast(t("请等当前回复结束后再添加文件。")); return; }
    setReading(true);
    try {
      const added = await readDataFiles(list, data);
      if (Object.keys(added).length) await saveData({ ...data, ...added });
    } catch (error) { toast.error(errorText(error)); }
    finally { setReading(false); }
  };
  const stop = async () => { if (await conversation.stop()) { setLiveTask(undefined); onFinished(); } };
  const saveData = async (next: Record<string, string>) => {
    setSavingData(true);
    try {
      if (threadId) await saveThreadValues(threadId, { data: next });
      setFiles(next);
    } finally { setSavingData(false); }
  };
  if (conversation.thread.error) return <ThreadLoadError error={conversation.thread.error} onReload={conversation.thread.reload}
    header={<header className="flex h-12 shrink-0 items-center gap-2 border-b px-2 xl:hidden">
      <Button variant="ghost" size="icon" aria-label={t("打开菜单")} onClick={onMenu}><Menu /></Button><span className="text-sm font-medium">{t("对话规划")}</span>
    </header>} />;

  const empty = !threadId && !messages.length && !failure && !busy && !settings && !Object.keys(data).length;
  const hasConversation = !!threadId || messages.length > 0 || !!meta?.title || plans.length > 0 || !!currentPlan || !!task || workspace;
  const chatHeader = <header className={cn(
    "flex h-12 shrink-0 items-center gap-2 px-4",
    hasConversation ? "border-b border-border/70 bg-background/80 backdrop-blur-md"
      : sidebarCollapsed ? "bg-transparent" : "border-b border-border/70 bg-background/80 backdrop-blur-md xl:hidden",
  )}>
    <Button variant="ghost" size="icon-sm" aria-label={t("打开菜单")} className="-ml-2 xl:hidden" onClick={onMenu}><Menu /></Button>
    {sidebarCollapsed && onExpandSidebar ? <Button variant="ghost" size="icon-sm" aria-label={t("展开侧边栏")} title={t("展开侧边栏")}
      className="-ml-1 hidden rounded-lg text-muted-foreground hover:text-foreground xl:inline-flex" onClick={onExpandSidebar}>
      <PanelLeftOpen className="size-4" />
    </Button> : null}
    <h1 className="flex min-w-0 flex-1 items-center gap-2 text-sm font-medium text-foreground/90">{hasConversation ? <span className="truncate" title={meta?.title}>{meta?.title ? <DisplayText text={shortTitle(meta.title)} /> : t("智能优化对话")}</span>
      : <><LogoMark className="size-6" /><span className="truncate font-semibold tracking-tight text-foreground">{t("通用智能优化求解器")}</span></>}</h1>
    {!workspace && (plans.length > 0 || !!currentPlan || !!task) ? <Button variant="outline" size="sm" className="h-8 rounded-lg text-xs" onClick={() => { setWorkspace(true); setPane("workspace"); }}>
      <Columns2 className="size-3.5" />{t("方案面板")}
    </Button> : null}
  </header>;
  const hasFiles = (event: DragEvent) => !!event.dataTransfer.types?.includes("Files");
  const plansNow = !busy ? latestPlans(messages) : undefined;
  const suggestions = plansNow?.length ? planSuggestions(plansNow) : undefined;
  const chat = <section aria-label={t("优化对话")} className={cn("relative flex h-full min-h-0 min-w-0 flex-col", workspace && pane === "workspace" && "hidden lg:flex")}
    onDragOver={event => { if (!hasFiles(event)) return; event.preventDefault(); event.dataTransfer.dropEffect = "copy"; setDragging(true); }}
    onDragLeave={event => { if (!(event.relatedTarget instanceof Node) || !event.currentTarget.contains(event.relatedTarget)) setDragging(false); }}
    onDrop={event => { setDragging(false); if (!hasFiles(event)) return; event.preventDefault(); void addFiles(event.dataTransfer.files); }}>
    {dragging ? <div className="pointer-events-none absolute inset-2 z-30 grid place-items-center rounded-2xl border-2 border-dashed border-primary/55 bg-background/80 backdrop-blur-sm">
      <div className="flex flex-col items-center gap-2 text-center">
        <span className="grid size-11 place-items-center rounded-xl bg-primary/10 text-primary"><FileUp className="size-5" /></span>
        <p className="text-sm font-medium">{t("松开即可添加数据文件")}</p>
        <p className="text-xs text-muted-foreground">{t("支持 CSV、Excel、JSON、TSV 和文本文件")}</p>
      </div>
    </div> : null}
    {chatHeader}
    <div className={cn("flex min-h-0 flex-1 flex-col", empty && "justify-center")}>
    <div className={cn("relative flex min-h-0 flex-col", !empty && "flex-1")}>
      <div ref={log} role="log" aria-label={t("对话记录")} aria-busy={conversation.loading} className={cn("min-h-0 chat-scroll overflow-y-auto overscroll-contain px-4 md:px-8", empty ? "max-h-[60vh]" : "flex-1")}>
        <div ref={content} className="grid min-h-full grid-cols-1">
          {messages.length || failure ? <Suspense fallback={<Spinner />}><ChatMessages messages={messages} loading={conversation.loading} label={t("优化助手")}
            failure={failure} disabled={busy || dataPending} onRetry={() => void submit(true)} progress={progress} tasks={tasks}
            activeTaskId={desktop && workspace ? liveTask : undefined} options={options} suggestions={suggestions}
            onSuggest={item => item.send ? void submit(false, item.text) : fill(item.text, item.after)}
            onEdit={text => void rewrite(text)} onRegenerate={() => void rewrite()}
            onShowTask={id => { setLiveTask(id); setWorkspace(true); setPane("workspace"); }}
            onOpenPlan={source => { setViewed(source); setLiveTask(undefined); setWorkspace(true); setPane("workspace"); }} onCompare={onCompare} /></Suspense>
            : threadId ? <div role="status" className="grid place-content-center gap-2 text-sm text-muted-foreground">
              {conversation.busy ? t("正在加载对话记录……") : t("暂无对话消息。")}
            </div> : <div className="animate-fade-up mx-auto flex w-full min-h-full max-w-[46rem] flex-col justify-center gap-6 py-6">
              <div className="flex flex-col items-center gap-1.5 text-center">
                <LogoMark className="mb-2 size-11 drop-shadow-sm" />
                <h2 className="text-2xl font-semibold tracking-tight sm:text-[1.75rem]">{t("想优化什么问题？")}</h2>
                <p className="text-sm text-muted-foreground">{t("用日常语言描述目标和条件，或拖入表格直接求解。")}</p>
              </div>
              <div className="grid gap-2.5 sm:grid-cols-3">
                {!input && !Object.keys(data).length && AGENT_STARTERS.map(item => {
                  const Icon = item.icon;
                  return <button
                    key={item.title}
                    type="button"
                    onClick={() => { setInput(t(item.prompt)); inputArea.current?.focus(); }}
                    className="group flex flex-col gap-2 rounded-xl border border-border/80 bg-card p-3.5 text-left shadow-2xs transition-all duration-150 hover:border-primary/35 hover:shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <div className="flex items-center gap-2">
                      <span className="grid size-7 shrink-0 place-items-center rounded-lg bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
                        <Icon className="size-3.5" />
                      </span>
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{t(item.title)}</span>
                      <ArrowRight className="size-3.5 shrink-0 text-muted-foreground/60 opacity-0 transition-all group-hover:translate-x-0.5 group-hover:text-primary group-hover:opacity-100" />
                    </div>
                    <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{t(item.summary)}</p>
                  </button>;
                })}
              </div>
              {onExamples && !input && !Object.keys(data).length ? <Button variant="ghost" size="sm" className="self-center rounded-lg text-xs text-muted-foreground hover:text-foreground" onClick={onExamples}>
                <BookOpen className="size-3.5" />{t("浏览更多场景模板")}<ArrowRight className="size-3" />
              </Button> : null}
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
      {settings ? <div className="animate-scale-in mx-auto flex max-w-[46rem] flex-col gap-2.5 rounded-2xl border border-border/80 bg-card/95 p-3.5 shadow-xs">
        <div className="flex items-center justify-between gap-2 text-xs">
          <span className="font-medium text-foreground/85">{t("建模方法与求解器（默认自动选择）")}</span>
          {customized ? <button type="button" disabled={busy}
            onClick={() => { setMethod("auto"); setLanguage("auto"); setSolver("AUTO"); }}
            className="text-xs font-medium text-primary hover:underline disabled:opacity-50">{t("恢复默认自动")}</button> : null}
        </div>
        <div className={cn("grid grid-cols-1 gap-2.5", chosenSelfContained ? "sm:grid-cols-2" : "sm:grid-cols-3")}>
          <label className="space-y-1 text-xs font-medium text-muted-foreground">{t("建模方法")}
            <Select value={chosenMethod} onValueChange={next => {
              setMethod(next);
              const nextMeta = options.methods.find(item => item.id === next);
              if (nextMeta?.builtin_solver) { setLanguage("auto"); setSolver("AUTO"); }
              else if (nextMeta?.languages && chosenLanguage !== "auto" && !nextMeta.languages.includes(chosenLanguage)) {
                setLanguage("auto"); setSolver("AUTO");
              }
            }} disabled={busy}>
              <SelectTrigger className="w-full" aria-label={t("固定建模方法")}><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="auto">{t("自动选择（推荐）")}</SelectItem>
                {coreMethods.length ? <SelectGroup>
                  <SelectLabel>{t("常用方法")}</SelectLabel>
                  {coreMethods.map(item => <SelectItem key={item.id} value={item.id}>{item.name}{item.builtin_solver ? ` · ${t("智能优化")}` : ""}</SelectItem>)}
                </SelectGroup> : null}
                {extraMethods.length ? <>
                  <SelectSeparator />
                  <SelectGroup>
                    <SelectLabel>{t("更多研究方法（{count}）", { count: extraMethods.length })}</SelectLabel>
                    {extraMethods.map(item => <SelectItem key={item.id} value={item.id}>{item.name}{item.builtin_solver ? ` · ${t("智能优化")}` : ""}</SelectItem>)}
                  </SelectGroup>
                </> : null}
              </SelectContent>
            </Select>
          </label>
          {chosenSelfContained ? <div className="space-y-1 text-xs font-medium text-muted-foreground">{t("求解引擎")}
            <div className="flex h-9 items-center rounded-md border bg-muted/40 px-3 text-xs font-normal text-muted-foreground">
              {t("{method} 内置 12 类算法池（自动选配）", { method: chosenMethodMeta?.name ?? chosenMethod })}
            </div>
          </div> : <>
            <label className="space-y-1 text-xs font-medium text-muted-foreground">{t("建模框架")}
              <Select value={chosenLanguage} onValueChange={next => { setLanguage(next); setSolver("AUTO"); }} disabled={busy}>
                <SelectTrigger className="w-full" aria-label={t("固定建模求解器")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="auto">{t("自动匹配（推荐）")}</SelectItem>
                  {options.languages.map(item => <SelectItem key={item.id} value={item.id} disabled={!languageAllowed(item.id)}>{item.name}</SelectItem>)}
                </SelectContent>
              </Select>
            </label>
            <label className="space-y-1 text-xs font-medium text-muted-foreground">{t("底层求解器")}
              {chosenLanguage === "auto" ? <div className="flex h-9 items-center rounded-md border bg-muted/40 px-3 text-xs font-normal text-muted-foreground">
                {t("随建模框架自动匹配")}
              </div> : <Select value={chosenSolver} onValueChange={setSolver} disabled={busy}>
                <SelectTrigger className="w-full" aria-label={t("固定底层求解器")}><SelectValue /></SelectTrigger>
                <SelectContent>
                  {(backends ?? [{ id: "AUTO", available: true, detail: "" }]).map(item => (
                    <SelectItem key={item.id} value={item.id} disabled={!item.available} title={item.detail}>
                      {item.id === "AUTO" ? t("自动匹配最优求解器") : item.id}{!item.available ? ` · ${t("当前环境未安装")}` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>}
            </label>
          </>}
        </div>
      </div> : null}
      <ChatInput label={t("发送给优化助手")} value={input} onChange={setInput}
        disabled={busy} sendingDisabled={dataPending} loading={conversation.loading} stopping={conversation.stopping} inputRef={inputArea}
        presets={presets} presetId={presetId} onPreset={setSelected} thinking={thinkingMode} onThinking={setThinking} openPresets={openPresets}
        searchActive={canSearch && searching} attachment={<Button type="button" variant="ghost" size="icon-sm" disabled={busy || dataPending} aria-label={t("添加数据文件")}
          title={t(reading ? "正在读取数据……" : savingData ? "正在保存……" : "添加数据文件")} onClick={() => upload.current?.click()}>
          {dataPending ? <Spinner /> : <Paperclip />}</Button>}
        onSend={() => void submit()} onStop={() => void stop()} onFiles={list => void addFiles(list)} placeholder={t("描述你想解决的业务问题，或继续补充调整要求…")}>

        <Button type="button" variant={settings || customized ? "secondary" : "ghost"} size="sm" aria-label={t("建模偏好")}
          title={t("可选指定建模方法与求解器，默认自动匹配")}
          className={cn("h-8 max-w-44 gap-1.5 rounded-lg px-2 text-xs font-normal", customized ? "text-primary font-medium" : "text-muted-foreground")}
          aria-expanded={settings} onClick={() => setSettings(!settings)}>
          <SlidersHorizontal className="size-3.5 shrink-0" />
          <span className="truncate">{configSummary}</span>
        </Button>
        {canSearch ? <ToolToggle label={t("联网搜索")} icon={<Globe />} pressed={searching} disabled={busy}
          title={t("搜索公开资料，并在回复中展示来源。")} onPressedChange={setSearch} /> : null}
      </ChatInput>
      <input ref={upload} type="file" multiple accept={DATA_FILE_ACCEPT} className="hidden" disabled={busy || dataPending} aria-label={t("数据文件")} onChange={async event => {
        const field = event.currentTarget;
        if (!field.files?.length || busy || dataPending) return;
        try { await addFiles(field.files); } finally { field.value = ""; }
      }} />
    </div>
    </div>
  </section>;

  const showPlanPicker = plans.length > 1 || (!!task && plans.length > 0);
  const activePlanName = task?.name ?? plans.find(plan => viewing && sameSource(plan.source, viewing))?.name ?? t("方案面板");
  const workbench = workspace ? <aside aria-label={t("方案面板")} className={cn("flex h-full min-h-0 min-w-0 flex-col border-l border-border/70 bg-card", pane !== "workspace" && "hidden lg:flex")}>
    <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border/70 bg-background/80 px-4">
      {showPlanPicker ? <Select value={task ? "live" : viewing ? sourceKey(viewing) : ""} onValueChange={id => {
        const chosen = plans.find(plan => sourceKey(plan.source) === id)?.source;
        if (chosen) { setViewed(chosen); setLiveTask(undefined); }
      }}>
        <SelectTrigger size="sm" aria-label={t("查看计算方案")} className="min-w-0 flex-1 border-0 bg-transparent px-0 text-sm font-semibold shadow-none"><SelectValue /></SelectTrigger>
        <SelectContent>{task ? <SelectItem value="live">{task.name}</SelectItem> : null}{plans.map(plan => <SelectItem key={sourceKey(plan.source)} value={sourceKey(plan.source)}>{plan.name}{sameSource(plan.source, currentPlan) ? ` · ${t("当前")}` : ""}</SelectItem>)}</SelectContent>
      </Select> : <h2 className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">{activePlanName}</h2>}
      {shown && !task ? <Button variant="ghost" size="icon-xs" aria-label={t("打开完整运行")} title={t("独立页面查看")} className="text-muted-foreground hover:text-foreground" onClick={() => onOpen(shown)}><ArrowUpRight /></Button> : null}
      <Button variant="ghost" size="icon-xs" aria-label={t("收起方案面板")} className="text-muted-foreground hover:text-foreground" onClick={() => { setWorkspace(false); setPane("chat"); }}><X /></Button>
    </div>
    {!task && shown && currentPlan && !sameSource(shown, currentPlan) ? <div className="flex shrink-0 items-center justify-between gap-2 border-b bg-muted/30 px-4 py-1.5 text-xs" aria-label={t("方案上下文")}>
      <Badge variant="outline">{t("正在查看历史方案")}</Badge>
      <Button variant="link" size="xs" className="h-auto p-0" onClick={() => setViewed(undefined)}>{t("返回当前讨论方案")}</Button>
    </div> : null}
    <div className="min-h-0 flex-1">{task ? <Suspense fallback={<Spinner />}><LiveWorkspace key={liveTask} task={task} data={data} options={options} /></Suspense> : shown ? renderRun(shown)
      : <div className="flex h-full items-center justify-center p-6 text-center text-sm text-muted-foreground">{t("开始求解后，最优决策方案、数学模型与计算代码将实时呈现在这里。")}</div>}</div>
  </aside> : null;

  return <div className="flex h-full min-h-0 flex-col">
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
