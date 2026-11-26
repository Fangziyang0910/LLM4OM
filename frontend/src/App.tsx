import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Menu, PanelLeftOpen, Plus, RefreshCw, ServerCrash } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/api";
import { chatDraftKey, clearChatDraft, createRequirements, createSolutionChat, deleteRun, getThreadKind, history, startComparison, startRevision, startRun, startScenarios } from "@/features/runs/api";
import { errorText } from "@/format";
import { Sidebar } from "@/components/Sidebar";
import { PageErrorBoundary } from "@/components/PageErrorBoundary";
import { DisplayTranslationProvider } from "@/components/DisplayTranslation";
import { t } from "@/i18n";
import { useDesktop } from "@/lib/useDesktop";
import type { Entry, SourceRun } from "@/features/runs/types";
import { sourceKey } from "@/features/runs/types";
import type { Draft, Options, Preset, Presets } from "@/types";
import { cn } from "@/lib/utils";

const Composer = lazy(() => import("@/features/composer/Composer").then(module => ({ default: module.Composer })));
const Examples = lazy(() => import("@/features/composer/Examples").then(module => ({ default: module.Examples })));
const PresetsDialog = lazy(() => import("@/features/presets/PresetsDialog").then(module => ({ default: module.PresetsDialog })));
const RunView = lazy(() => import("@/features/runs/RunView").then(module => ({ default: module.RunView })));
const Compare = lazy(() => import("@/features/runs/Compare").then(module => ({ default: module.Compare })));
const Requirements = lazy(() => import("@/features/requirements/Requirements").then(module => ({ default: module.Requirements })));
const SolutionChat = lazy(() => import("@/features/solution_chat/SolutionChat").then(module => ({ default: module.SolutionChat })));
const Agent = lazy(() => import("@/features/agent/Agent").then(module => ({ default: module.Agent })));

type Route = { name: "new" } | { name: "agent-new" }
  | { name: "run"; id: string; checkpoint?: string } | { name: "compare" | "chat" | "discussion" | "agent"; id: string };
type Confirm = { title: string; text: string; action: string; run: () => Promise<void> };

const routeFromUrl = (): Route => {
  const match = location.pathname.match(/^\/(run|compare|chat|discussion|agent)\/([\w-]+)/);
  if (!match) return { name: location.pathname === "/model" ? "new" : "agent-new" };
  const name = match[1] as "run" | "compare" | "chat" | "discussion" | "agent";
  // A plain /run/{thread} keeps the latest-run meaning; only an explicit checkpoint selects a saved plan.
  const checkpoint = name === "run" ? new URLSearchParams(location.search).get("checkpoint") ?? undefined : undefined;
  return name === "run" ? { name, id: match[2], ...(checkpoint ? { checkpoint } : {}) } : { name, id: match[2] };
};
const NO_PRESETS: Preset[] = [];

export default function App({ restoredDraft }: { restoredDraft: Draft }) {
  return <DisplayTranslationProvider><WorkbenchApp restoredDraft={restoredDraft} /></DisplayTranslationProvider>;
}

function WorkbenchApp({ restoredDraft }: { restoredDraft: Draft }) {
  const queryClient = useQueryClient();
  const optionsQuery = useQuery({ queryKey: ["options"], queryFn: () => api<Options>("/api/options"), staleTime: Infinity });
  const presetsQuery = useQuery({ queryKey: ["presets"], queryFn: () => api<Presets>("/api/presets") });
  const presets = presetsQuery.data?.presets ?? NO_PRESETS;
  const [menuOpen, setMenuOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(() => {
    try { return localStorage.getItem("llm4om-sidebar") !== "closed"; } catch { return true; }
  });
  const showSidebar = useDesktop("80rem") && sidebarOpen;
  // Runs started elsewhere (another tab, the CLI against the server) finish without telling this page.
  const historyQuery = useInfiniteQuery({ queryKey: ["history"], initialPageParam: 0,
    enabled: showSidebar || menuOpen,
    queryFn: ({ pageParam }) => history(undefined, pageParam, queryClient), getNextPageParam: page => page.nextOffset,
    refetchInterval: query => query.state.data?.pages.some(page => page.entries.some(entry => ["running", "pending"].includes(entry.state))) ? 4000 : 10000 });
  const entries = useMemo(() => [...new Map((historyQuery.data?.pages.flatMap(page => page.entries) ?? [])
    .map(entry => [entry.id, entry])).values()], [historyQuery.data]);
  const options = optionsQuery.data ?? null;
  const [route, setRoute] = useState<Route>(routeFromUrl);
  const routeRef = useRef(route);
  useEffect(() => { routeRef.current = route; });
  useEffect(() => {
    // A file dropped outside a drop zone would make the browser open it in place of the app.
    const guard = (event: DragEvent) => {
      if (!event.dataTransfer?.types.includes("Files") || event.defaultPrevented) return;
      event.preventDefault();
      if (event.type === "dragover") event.dataTransfer.dropEffect = "none";
    };
    window.addEventListener("dragover", guard);
    window.addEventListener("drop", guard);
    return () => { window.removeEventListener("dragover", guard); window.removeEventListener("drop", guard); };
  }, []);
  const [draft, setDraft] = useState<Draft>(restoredDraft);
  const homeEditor = useRef<{ fillIfEmpty: (description: string) => boolean }>(null);
  const [exampleTarget, setExampleTarget] = useState<Route | null>(null);
  const [caseChoice, setCaseChoice] = useState<string | null>(null);
  const [presetsOpen, setPresetsOpen] = useState(false);
  const toggleSidebar = (open: boolean) => {
    setSidebarOpen(open);
    try { localStorage.setItem("llm4om-sidebar", open ? "open" : "closed"); } catch { /* ignore */ }
  };
  const [search, setSearch] = useState("");
  const [confirm, setConfirm] = useState<Confirm | null>(null);

  const go = useCallback((next: Route) => {
    const path = next.name === "agent-new" ? "/" : next.name === "new" ? "/model"
      : `/${next.name}/${next.id}${next.name === "run" && next.checkpoint ? `?checkpoint=${encodeURIComponent(next.checkpoint)}` : ""}`;
    if (location.pathname + location.search !== path) window.history.pushState(null, "", path);
    setExampleTarget(null);
    setCaseChoice(null);
    setRoute(next);
    setMenuOpen(false);
  }, []);
  const refresh = useCallback(() => queryClient.invalidateQueries({
    predicate: query => ["history", "conversation", "compare"].includes(String(query.queryKey[0])),
  }), [queryClient]);
  const newProblem = () => go({ name: "new" });
  const openAgent = () => {
    if (route.name === "agent") {
      clearChatDraft("optimization-new");
    }
    go({ name: "agent-new" });
  };

  useEffect(() => {
    const onPop = () => {
      setExampleTarget(null); setCaseChoice(null); setMenuOpen(false);
      setRoute(routeFromUrl());
    };
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);

  const start = async (request: Draft) => {
    const id = await startRun(request, request.preset ? presets.find(item => item.id === request.preset) : presets[0]);
    void refresh();
    go({ name: "run", id });
  };
  const compare = async (request: Draft, runs: { method: string; language: string; solver: string; preset: Preset }[]) => {
    const { group, started, error } = await startComparison(request, runs);
    void refresh();
    go({ name: "compare", id: group });
    if (error) toast.error(t("只启动了 {started}/{total} 个运行：{error}", { started, total: runs.length, error: errorText(error) }));
  };
  const remove = (entry: Pick<Entry, "id" | "meta">) => setConfirm({
    title: entry.meta.kind === "optimization" ? t("删除这段对话规划？") : entry.meta.kind === "solution_chat" ? t("删除这段方案追问？") : entry.meta.kind === "requirements" ? t("删除这段需求梳理？") : t("删除这条求解记录？"), action: t("删除"),
    text: entry.meta.kind === "solution_chat" || entry.meta.kind === "optimization" ? t("“{title}”的对话记录会被删除，原方案和已生成的方案会保留。", { title: entry.meta.title })
      : entry.meta.kind === "requirements" ? t("“{title}”的对话、需求稿和附件都会被删除，已创建的建模运行会保留。", { title: entry.meta.title })
      : t("“{title}”的问题、模型和计算结果都会被删除，无法恢复。", { title: entry.meta.title }),
    run: async () => {
      await deleteRun(entry.id);
      const activeRoute = routeRef.current;
      if ("id" in activeRoute && activeRoute.id === entry.id) go({ name: "agent-new" });
      await refresh();
      toast.success(t("已删除。"));
    },
  });

  const openRun = (run: string | SourceRun) => {
    const id = typeof run === "string" ? run : run.thread_id;
    go(typeof run === "string" ? { name: "run", id } : { name: "run", id, checkpoint: run.checkpoint_id });
  };
  const renderRun = (run: string | SourceRun, assistantOpen = false, embedded = false) => {
    const source = typeof run === "string" ? undefined : run;
    const threadId = typeof run === "string" ? run : run.thread_id;
    return <RunView key={typeof run === "string" ? run : sourceKey(run)} threadId={threadId} source={source} options={options!}
      assistantOpen={assistantOpen} embedded={embedded} onFinished={() => void refresh()}
    onDiscuss={async () => {
      if (assistantOpen) { openRun(source ?? threadId); return; }
      const chat = await createSolutionChat(source ?? threadId); void refresh(); go({ name: "discussion", id: chat });
    }}
    onConversation={id => {
      void getThreadKind(id).then(kind => {
        go({ name: kind === "optimization" ? "agent" : "discussion", id });
      }).catch(error => toast.error(errorText(error)));
    }} onScenarios={async scenarios => {
      const result = await startScenarios(threadId, scenarios, presets, source);
      void refresh(); go({ name: "compare", id: result.group });
      if (result.error) toast.error(t("只启动了 {started}/{total} 个运行：{error}", { started: result.started, total: scenarios.length, error: errorText(result.error) }));
    }}
    onEdit={next => { setDraft({ ...next, comparing: false, methods: draft.methods, presets: draft.presets }); go({ name: "new" }); }}
    onRerun={start} onRevise={async instruction => {
      const revised = await startRevision(threadId, instruction, presets, source);
      void refresh(); go({ name: "run", id: revised });
    }} onDelete={meta => remove({ id: threadId, meta })}
    onCompare={group => go({ name: "compare", id: group })} onMetaChange={() => void refresh()} />;
  };
  const modelingProps = (options: Options) => ({ options, presets, draft, setDraft, onStart: start, onCompare: compare,
    presetsStatus: presetsQuery.data ? "ready" as const : presetsQuery.error ? "error" as const : "loading" as const,
    openPresets: () => setPresetsOpen(true) });

  const current = "id" in route ? route.id : null;
  const activeMode: "quick" | "agent" = route.name === "agent-new" || route.name === "agent" ? "agent" : "quick";
  const sidebarProps = { entries, current, activeMode, options, presets, onNew: newProblem, onAgent: openAgent,
    query: search, onQuery: setSearch,
    hasMore: historyQuery.hasNextPage, loading: historyQuery.isFetching, error: historyQuery.error ? errorText(historyQuery.error) : null,
    onLoadMore: () => void historyQuery.fetchNextPage(), onRetry: () => void historyQuery.refetch(),
    onOpen: (entry: Entry) => go({ name: entry.meta.kind === "optimization" ? "agent" : entry.meta.kind === "solution_chat" ? "discussion" : entry.meta.kind === "requirements" ? "chat" : "run", id: entry.id }),
    onCompare: (group: string) => go({ name: "compare", id: group }), onDelete: remove,
    onExamples: () => { setExampleTarget(route); setMenuOpen(false); }, onPresets: () => { setPresetsOpen(true); setMenuOpen(false); } };

  return <div className="flex h-dvh overflow-hidden bg-background">
    {showSidebar ? <aside aria-label={t("导航")} className="hidden w-64 shrink-0 border-r border-sidebar-border xl:block">
      <Sidebar {...sidebarProps} onCollapse={() => toggleSidebar(false)} />
    </aside> : null}
    <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
      <SheetContent side="left" className="w-72 gap-0 p-0" aria-describedby={undefined}>
        <SheetTitle className="sr-only">{t("导航")}</SheetTitle>
        <Sidebar {...sidebarProps} />
      </SheetContent>
    </Sheet>

    <div className="ambient-canvas flex min-w-0 flex-1 flex-col">
      {(route.name !== "agent-new" && route.name !== "agent" || !options || optionsQuery.error) ? <header className={sidebarOpen
        ? "flex h-12 shrink-0 items-center gap-2 border-b bg-background/80 px-2.5 backdrop-blur-md xl:hidden"
        : "flex h-12 shrink-0 items-center gap-2 border-b bg-background/80 px-2.5 backdrop-blur-md"}>
        <Button variant="ghost" size="icon-sm" aria-label={t("打开菜单")} className="xl:hidden" onClick={() => setMenuOpen(true)}><Menu /></Button>
        {!sidebarOpen ? <Button variant="ghost" size="icon-sm" aria-label={t("展开侧边栏")} title={t("展开侧边栏")} className="hidden xl:inline-flex" onClick={() => toggleSidebar(true)}><PanelLeftOpen /></Button> : null}
        <span className={cn("min-w-0 flex-1 truncate text-sm font-semibold tracking-tight", route.name === "new" && "xl:invisible")}>{route.name === "new" ? t("手动建模")
          : route.name === "agent-new" || route.name === "agent" ? t("智能优化对话") : route.name === "chat" ? t("需求梳理") : route.name === "discussion" ? t("方案追问") : route.name === "compare" ? t("方案对比") : t("求解结果")}</span>
        <Button variant="ghost" size="icon-sm" aria-label={t("新建优化任务")} title={t("新建优化任务")} onClick={openAgent}><Plus /></Button>
      </header> : null}
      {presetsQuery.error ? <div role="alert" className="flex w-full items-center justify-between gap-3 border-b bg-destructive/5 px-4 py-2 text-xs text-destructive sm:px-6">
        <span>{t("模型配置加载失败：{error}", { error: errorText(presetsQuery.error) })}</span>
        <Button variant="outline" size="sm" disabled={presetsQuery.isFetching} onClick={() => void presetsQuery.refetch()}><RefreshCw />{t("重试")}</Button>
      </div> : null}
      <main className="min-h-0 w-full flex-1">
        {optionsQuery.error ? <Empty className="h-full">
          <EmptyHeader>
            <EmptyMedia variant="icon"><ServerCrash /></EmptyMedia>
            <EmptyTitle>{t("无法连接服务")}</EmptyTitle>
            <EmptyDescription>{errorText(optionsQuery.error)}</EmptyDescription>
          </EmptyHeader>
          <EmptyContent><Button variant="outline" onClick={() => void optionsQuery.refetch()}><RefreshCw />{t("重试")}</Button></EmptyContent>
        </Empty>
          : !options ? <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在准备环境……")}</div>
          : route.name === "agent-new" || route.name === "agent"
            ? <PageErrorBoundary key={route.name === "agent" ? route.id : "agent-new"}><Suspense fallback={<div className="grid h-full place-items-center"><Spinner /></div>}>
              <Agent key={route.name === "agent" ? route.id : "agent-new"} threadId={route.name === "agent" ? route.id : undefined}
                options={options} presets={presets} ref={route.name === "agent-new" ? homeEditor : undefined}
                sidebarCollapsed={!sidebarOpen} onExpandSidebar={() => toggleSidebar(true)}
                onThread={id => go({ name: "agent", id })}
                openPresets={() => setPresetsOpen(true)} onExamples={() => setExampleTarget(route)} onMenu={() => setMenuOpen(true)}
                onFinished={() => void refresh()} onOpen={openRun} onCompare={id => go({ name: "compare", id })} renderRun={source => renderRun(source, false, true)} />
            </Suspense></PageErrorBoundary>
          : route.name === "new"
            ? <PageErrorBoundary><Suspense fallback={<Spinner />}><Composer {...modelingProps(options)} openExamples={() => setExampleTarget(route)} onDiscuss={async () => {
                const preset = presets.find(item => item.id === draft.preset) ?? presets[0];
                const id = await createRequirements({ description: draft.description, data: draft.data }, preset, draft.origin);
                void refresh(); go({ name: "chat", id });
              }} /></Suspense></PageErrorBoundary>
            : <PageErrorBoundary key={route.id}><Suspense fallback={<div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在加载……")}</div>}>
              {route.name === "compare" ? <Compare key={route.id} group={route.id} options={options} onOpen={openRun} />
                : route.name === "chat" ? <Requirements key={route.id} threadId={route.id} {...modelingProps(options)} searchConfigured={!!options.search_configured}
                  onFinished={() => void refresh()}
                  onUse={next => { setDraft({ ...draft, ...next, origin: route.id }); go({ name: "new" }); }} />
                : route.name === "discussion" ? <SolutionChat key={route.id} threadId={route.id} presets={presets}
                  openPresets={() => setPresetsOpen(true)} onFinished={() => void refresh()}
                  onOpen={openRun} onCompare={id => go({ name: "compare", id })} renderRun={source => renderRun(source, true)} />
                : route.name === "run" ? renderRun(route.checkpoint ? { thread_id: route.id, checkpoint_id: route.checkpoint } : route.id)
                : null}
            </Suspense></PageErrorBoundary>}
      </main>
    </div>

    {options ? <PageErrorBoundary><Suspense fallback={null}>
      {exampleTarget === route ? <Examples open onClose={() => setExampleTarget(null)} datasets={options.datasets}
        onUse={description => {
          if (exampleTarget.name === "new" && !draft.description && !Object.keys(draft.data).length && !draft.origin) {
            setDraft(current => ({ ...current, description }));
            setExampleTarget(null);
          } else if (exampleTarget.name === "agent-new" && homeEditor.current?.fillIfEmpty(description)) {
            setExampleTarget(null);
          } else {
            setCaseChoice(description);
          }
        }} /> : null}
      {presetsOpen ? <PresetsDialog onClose={() => setPresetsOpen(false)} presets={presets} dailyTokens={presetsQuery.data?.daily_tokens ?? 0}
        providers={options.providers}
        onChange={(value, message) => { queryClient.setQueryData(["presets"], value); toast.success(message); }} /> : null}
    </Suspense></PageErrorBoundary> : null}
    <Dialog open={caseChoice !== null && exampleTarget === route} onOpenChange={open => { if (!open) setCaseChoice(null); }}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader><DialogTitle>{t("如何使用这个案例？")}</DialogTitle>
          <DialogDescription>{route.name === "new" ? t("新对话会保留当前题面和附件；替换会移除当前附件。") : t("在新标签页打开案例，当前对话和草稿会保留。")}</DialogDescription>
        </DialogHeader>
        <DialogFooter className="flex-wrap">
          <Button variant="ghost" onClick={() => setCaseChoice(null)}>{t("取消")}</Button>
          {route.name === "new" ? <Button variant="outline" onClick={() => {
            if (caseChoice === null) return;
            const previous = { description: draft.description, data: draft.data, origin: draft.origin };
            const replacement = { description: caseChoice, data: {}, origin: undefined };
            setDraft(current => ({ ...current, ...replacement }));
            setCaseChoice(null); setExampleTarget(null);
            toast.success(t("已替换题面和附件。"), { action: { label: t("撤销"), onClick: () =>
              setDraft(current => current.description === replacement.description && current.data === replacement.data
                ? { ...current, ...previous } : current) } });
          }}>{t("替换当前草稿")}</Button> : null}
          <Button onClick={() => {
            const tab = window.open("about:blank", "_blank");
            if (!tab || caseChoice === null) { toast.error(t("请允许打开案例标签页后重试。")); return; }
            try {
              tab.opener = null;
              const key = chatDraftKey("optimization-new");
              tab.sessionStorage.setItem(key, caseChoice);
              tab.sessionStorage.removeItem(`${key}-pending`);
              tab.location.replace(location.origin);
              setCaseChoice(null); setExampleTarget(null);
            } catch (error) { tab.close(); toast.error(errorText(error)); }
          }}>{t("用案例新建对话")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
    <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />
  </div>;
}

function ConfirmDialog({ confirm, onClose }: { confirm: Confirm | null; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  return <Dialog open={!!confirm} onOpenChange={open => { if (!open && !busy) onClose(); }}>
    <DialogContent showCloseButton={!busy} className="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>{confirm?.title}</DialogTitle>
        <DialogDescription>{confirm?.text}</DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button variant="outline" disabled={busy} onClick={onClose}>{t("取消")}</Button>
        <Button variant="destructive" disabled={busy} onClick={async () => {
          setBusy(true);
          try { await confirm?.run(); onClose(); } catch (error) { toast.error(errorText(error)); } finally { setBusy(false); }
        }}>{busy ? <Spinner /> : null}{confirm?.action}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
