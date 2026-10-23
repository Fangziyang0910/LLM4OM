import { useInfiniteQuery, useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Menu, Plus, RefreshCw, ServerCrash } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/api";
import { deleteRun, history, startComparison, startRevision, startRun, startScenarios } from "@/features/runs/api";
import { errorText } from "@/format";
import { Composer, initialDraft } from "@/features/composer/Composer";
import { Examples } from "@/features/composer/Examples";
import { PresetsDialog } from "@/features/presets/PresetsDialog";
import { createRequirements } from "@/features/requirements/api";
import { createSolutionChat } from "@/features/solution_chat/api";
import { Sidebar } from "@/components/Sidebar";
import { PageErrorBoundary } from "@/components/PageErrorBoundary";
import { t } from "@/i18n";
import type { Draft } from "@/features/composer/types";
import type { Entry } from "@/features/runs/types";
import type { Options, Preset, Presets } from "@/types";

// Load run pages on demand.
const RunView = lazy(() => import("@/features/runs/RunView").then(module => ({ default: module.RunView })));
const Compare = lazy(() => import("@/features/runs/Compare").then(module => ({ default: module.Compare })));
const Requirements = lazy(() => import("@/features/requirements/Requirements").then(module => ({ default: module.Requirements })));
const SolutionChat = lazy(() => import("@/features/solution_chat/SolutionChat").then(module => ({ default: module.SolutionChat })));
const Agent = lazy(() => import("@/features/agent/Agent").then(module => ({ default: module.Agent })));

type Route = { name: "new" } | { name: "agent-new" } | { name: "run" | "compare" | "chat" | "discussion" | "agent"; id: string };
type Confirm = { title: string; text: string; action: string; run: () => Promise<void> };

const routeFromUrl = (): Route => {
  const match = location.pathname.match(/^\/(run|compare|chat|discussion|agent)\/([\w-]+)/);
  return match ? { name: match[1] as "run" | "compare" | "chat" | "discussion" | "agent", id: match[2] }
    : { name: location.pathname === "/agent" ? "agent-new" : "new" };
};
const NO_PRESETS: Preset[] = [];

export default function App() {
  const queryClient = useQueryClient();
  const optionsQuery = useQuery({ queryKey: ["options"], queryFn: () => api<Options>("/api/options"), staleTime: Infinity });
  const presetsQuery = useQuery({ queryKey: ["presets"], queryFn: () => api<Presets>("/api/presets") });
  const presets = presetsQuery.data?.presets ?? NO_PRESETS;
  // Runs started elsewhere (another tab, the CLI against the server) finish without telling this page.
  const historyQuery = useInfiniteQuery({ queryKey: ["history"], initialPageParam: 0,
    queryFn: ({ pageParam }) => history(undefined, pageParam), getNextPageParam: page => page.nextOffset,
    refetchInterval: query => query.state.data?.pages.some(page => page.entries.some(entry => entry.state === "running")) ? 4000 : false });
  const entries = [...new Map((historyQuery.data?.pages.flatMap(page => page.entries) ?? []).map(entry => [entry.id, entry])).values()];
  const options = optionsQuery.data ?? null;
  const [route, setRoute] = useState<Route>(routeFromUrl);
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [agentDraft, setAgentDraft] = useState({ description: "", data: {} as Record<string, string> });
  const [examplesOpen, setExamplesOpen] = useState(false);
  const [presetsOpen, setPresetsOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [confirm, setConfirm] = useState<Confirm | null>(null);

  const go = useCallback((next: Route) => {
    const path = next.name === "new" ? "/" : next.name === "agent-new" ? "/agent" : `/${next.name}/${next.id}`;
    if (location.pathname !== path) window.history.pushState(null, "", path);
    setRoute(next);
    setMenuOpen(false);
  }, []);
  const refresh = useCallback(() => queryClient.invalidateQueries({ queryKey: ["history"] }), [queryClient]);
  const newProblem = () => { setDraft(current => ({ ...current, origin: undefined })); go({ name: "new" }); };
  const newAgent = () => { setAgentDraft({ description: "", data: {} }); go({ name: "agent-new" }); };

  useEffect(() => {
    const onPop = () => setRoute(routeFromUrl());
    addEventListener("popstate", onPop);
    return () => removeEventListener("popstate", onPop);
  }, []);

  const start = async (request: Draft) => {
    const id = await startRun(request, request.preset ? presets.find(item => item.id === request.preset) : presets[0]);
    void refresh();
    go({ name: "run", id });
  };
  const compare = async (request: Draft, runs: { method: string; preset: Preset }[]) => {
    const { group, started, error } = await startComparison(request, runs);
    void refresh();
    go({ name: "compare", id: group });
    if (error) toast.error(t("只启动了 {started}/{total} 个运行：{error}", { started, total: runs.length, error: errorText(error) }));
  };
  const remove = (entry: Pick<Entry, "id" | "meta">) => setConfirm({
    title: entry.meta.kind === "optimization" ? t("删除这段优化对话？") : entry.meta.kind === "solution_chat" ? t("删除这段方案对话？") : entry.meta.kind === "requirements" ? t("删除这段需求对话？") : t("删除这次运行？"), action: t("删除"),
    text: entry.meta.kind === "solution_chat" || entry.meta.kind === "optimization" ? t("“{title}”的对话记录会被删除，原方案和已生成的方案会保留。", { title: entry.meta.title })
      : entry.meta.kind === "requirements" ? t("“{title}”的对话、需求稿和附件都会被删除，已创建的建模运行会保留。", { title: entry.meta.title })
      : t("“{title}”的问题、数学模型、代码和过程都会被删除，无法恢复。", { title: entry.meta.title }),
    run: async () => {
      await deleteRun(entry.id);
      try { sessionStorage.removeItem(`llm4om-message-${entry.id}`); } catch { /* storage may be unavailable */ }
      if ("id" in route && route.id === entry.id) go({ name: entry.meta.kind === "optimization" ? "agent-new" : "new" });
      await refresh();
      toast.success(t("已删除。"));
    },
  });

  const renderRun = (id: string, assistantOpen = false, embedded = false) => <RunView key={id} threadId={id} options={options!} assistantOpen={assistantOpen} embedded={embedded} onFinished={() => void refresh()}
    onDiscuss={async () => {
      if (assistantOpen) { go({ name: "run", id }); return; }
      const chat = await createSolutionChat(id); void refresh(); go({ name: "discussion", id: chat });
    }}
    onConversation={id => {
      void import("@/features/runs/sdk").then(async ({ client }) => {
        const thread = await client.threads.get(id);
        go({ name: thread.metadata?.kind === "optimization" ? "agent" : "discussion", id });
      }).catch(error => toast.error(errorText(error)));
    }} onScenarios={async scenarios => {
      const result = await startScenarios(id, scenarios, presets);
      void refresh(); go({ name: "compare", id: result.group });
      if (result.error) toast.error(t("只启动了 {started}/{total} 个运行：{error}", { started: result.started, total: scenarios.length, error: errorText(result.error) }));
    }}
    onEdit={next => { setDraft({ ...next, comparing: false, methods: draft.methods, presets: draft.presets }); go({ name: "new" }); }}
    onRerun={start} onRevise={async instruction => {
      const revised = await startRevision(id, instruction, presets);
      void refresh(); go({ name: "run", id: revised });
    }} onDelete={meta => remove({ id, meta })}
    onCompare={group => go({ name: "compare", id: group })} onMetaChange={() => void refresh()} />;
  const modelingProps = (options: Options) => ({ options, presets, draft, setDraft, onStart: start, onCompare: compare,
    presetsStatus: presetsQuery.data ? "ready" as const : presetsQuery.error ? "error" as const : "loading" as const,
    openPresets: () => setPresetsOpen(true), openExamples: () => setExamplesOpen(true) });

  const current = "id" in route ? route.id : null;
  const sidebar = <Sidebar entries={entries} current={current} options={options} presets={presets} onNew={newProblem} onAgent={newAgent}
    query={search} onQuery={setSearch}
    hasMore={historyQuery.hasNextPage} loading={historyQuery.isFetching} error={historyQuery.error ? errorText(historyQuery.error) : null}
    onLoadMore={() => void historyQuery.fetchNextPage()} onRetry={() => void historyQuery.refetch()}
    onOpen={entry => go({ name: entry.meta.kind === "optimization" ? "agent" : entry.meta.kind === "solution_chat" ? "discussion" : entry.meta.kind === "requirements" ? "chat" : "run", id: entry.id })}
    onCompare={group => go({ name: "compare", id: group })} onDelete={remove}
    onExamples={() => { setExamplesOpen(true); setMenuOpen(false); }} onPresets={() => { setPresetsOpen(true); setMenuOpen(false); }} />;

  return <div className="flex h-dvh overflow-hidden">
    <aside aria-label={t("导航")} className="hidden w-64 shrink-0 border-r border-sidebar-border xl:block">{sidebar}</aside>
    <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
      <SheetContent side="left" className="w-72 gap-0 p-0" aria-describedby={undefined}>
        <SheetTitle className="sr-only">{t("导航")}</SheetTitle>
        {sidebar}
      </SheetContent>
    </Sheet>

    <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b px-2 xl:hidden">
        <Button variant="ghost" size="icon" aria-label={t("打开菜单")} onClick={() => setMenuOpen(true)}><Menu /></Button>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">{route.name === "new" ? t("新建建模")
          : route.name === "agent-new" || route.name === "agent" ? t("优化对话") : route.name === "chat" ? t("需求对话") : route.name === "discussion" ? t("方案对话") : route.name === "compare" ? t("对比") : t("建模结果")}</span>
        {route.name !== "new" ? <Button variant="ghost" size="icon" aria-label={t("新建建模")} onClick={newProblem}><Plus /></Button> : null}
      </header>
      {presetsQuery.error ? <div role="alert" className="mx-auto flex w-full max-w-[1600px] items-center justify-between gap-3 border-b px-4 py-2 text-xs text-destructive sm:px-6">
        <span>{t("预设模型加载失败：{error}", { error: errorText(presetsQuery.error) })}</span>
        <Button variant="outline" size="sm" disabled={presetsQuery.isFetching} onClick={() => void presetsQuery.refetch()}><RefreshCw />{t("重试")}</Button>
      </div> : null}
      <main className="mx-auto min-h-0 w-full max-w-[1600px] flex-1">
        {optionsQuery.error ? <Empty className="h-full">
          <EmptyHeader>
            <EmptyMedia variant="icon"><ServerCrash /></EmptyMedia>
            <EmptyTitle>{t("无法连接服务器")}</EmptyTitle>
            <EmptyDescription>{errorText(optionsQuery.error)}</EmptyDescription>
          </EmptyHeader>
          <EmptyContent><Button variant="outline" onClick={() => void optionsQuery.refetch()}><RefreshCw />{t("重试")}</Button></EmptyContent>
        </Empty>
          : !options ? <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在加载……")}</div>
          : route.name === "agent-new" || route.name === "agent"
            ? <PageErrorBoundary key={route.name === "agent" ? route.id : `new-${agentDraft.description}`}><Suspense fallback={<div className="grid h-full place-items-center"><Spinner /></div>}>
              <Agent key={route.name === "agent" ? route.id : `new-${agentDraft.description}`} threadId={route.name === "agent" ? route.id : undefined}
                options={options} presets={presets} initial={agentDraft} onThread={id => go({ name: "agent", id })}
                openPresets={() => setPresetsOpen(true)} onExamples={() => setExamplesOpen(true)} onManual={() => go({ name: "new" })}
                onFinished={() => void refresh()} onOpen={id => go({ name: "run", id })} onCompare={id => go({ name: "compare", id })} renderRun={id => renderRun(id, false, true)} />
            </Suspense></PageErrorBoundary>
          : route.name === "new"
            ? <Composer {...modelingProps(options)} onDiscuss={async () => {
                const preset = presets.find(item => item.id === draft.preset) ?? presets[0];
                const id = await createRequirements({ description: draft.description, data: draft.data }, preset, draft.origin);
                void refresh(); go({ name: "chat", id });
              }} />
            : <PageErrorBoundary key={route.id}><Suspense fallback={<div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在加载……")}</div>}>
              {route.name === "compare" ? <Compare key={route.id} group={route.id} options={options} onOpen={id => go({ name: "run", id })} />
                : route.name === "chat" ? <Requirements key={route.id} threadId={route.id} {...modelingProps(options)} searchConfigured={!!options.search_configured}
                  onFinished={() => void refresh()}
                  onUse={next => { setDraft({ ...draft, ...next, origin: route.id }); go({ name: "new" }); }} />
                : route.name === "discussion" ? <SolutionChat key={route.id} threadId={route.id} presets={presets}
                  openPresets={() => setPresetsOpen(true)} onFinished={() => void refresh()}
                  onOpen={id => go({ name: "run", id })} onCompare={id => go({ name: "compare", id })} renderRun={id => renderRun(id, true)} />
                : renderRun(route.id)}
            </Suspense></PageErrorBoundary>}
      </main>
    </div>

    {options ? <>
      <Examples open={examplesOpen} onClose={() => setExamplesOpen(false)} datasets={options.datasets}
        onUse={description => {
          if (route.name === "agent-new" || route.name === "agent") { setAgentDraft({ description, data: {} }); go({ name: "agent-new" }); }
          else { setDraft({ ...draft, description, data: {}, origin: undefined }); go({ name: "new" }); }
          setExamplesOpen(false);
        }} />
      {presetsOpen ? <PresetsDialog onClose={() => setPresetsOpen(false)} presets={presets} dailyTokens={presetsQuery.data?.daily_tokens ?? 0}
        providers={options.providers}
        onChange={(value, message) => { queryClient.setQueryData(["presets"], value); toast.success(message); }} /> : null}
    </> : null}
    <ConfirmDialog confirm={confirm} onClose={() => setConfirm(null)} />
  </div>;
}

function ConfirmDialog({ confirm, onClose }: { confirm: Confirm | null; onClose: () => void }) {
  const [busy, setBusy] = useState(false);
  return <Dialog open={!!confirm} onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="sm:max-w-md">
      <DialogHeader>
        <DialogTitle>{confirm?.title}</DialogTitle>
        <DialogDescription>{confirm?.text}</DialogDescription>
      </DialogHeader>
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>{t("取消")}</Button>
        <Button variant="destructive" disabled={busy} onClick={async () => {
          setBusy(true);
          try { await confirm?.run(); onClose(); } catch (error) { toast.error(errorText(error)); } finally { setBusy(false); }
        }}>{busy ? <Spinner /> : null}{confirm?.action}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
