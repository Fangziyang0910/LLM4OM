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
import { t } from "@/i18n";
import type { Draft } from "@/features/composer/types";
import type { Entry } from "@/features/runs/types";
import type { Options, Preset, Presets } from "@/types";

// Load run pages on demand.
const RunView = lazy(() => import("@/features/runs/RunView").then(module => ({ default: module.RunView })));
const Compare = lazy(() => import("@/features/runs/Compare").then(module => ({ default: module.Compare })));
const Requirements = lazy(() => import("@/features/requirements/Requirements").then(module => ({ default: module.Requirements })));
const SolutionChat = lazy(() => import("@/features/solution_chat/SolutionChat").then(module => ({ default: module.SolutionChat })));

type Route = { name: "new" } | { name: "run" | "compare" | "chat" | "discussion"; id: string };
type Confirm = { title: string; text: string; action: string; run: () => Promise<void> };

const routeFromUrl = (): Route => {
  const match = location.pathname.match(/^\/(run|compare|chat|discussion)\/([\w-]+)/);
  return match ? { name: match[1] as "run" | "compare" | "chat" | "discussion", id: match[2] } : { name: "new" };
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
  const [examplesOpen, setExamplesOpen] = useState(false);
  const [presetsOpen, setPresetsOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);

  const go = useCallback((next: Route) => {
    const path = next.name === "new" ? "/" : `/${next.name}/${next.id}`;
    if (location.pathname !== path) window.history.pushState(null, "", path);
    setRoute(next);
    setMenuOpen(false);
  }, []);
  const refresh = useCallback(() => queryClient.invalidateQueries({ queryKey: ["history"] }), [queryClient]);

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
    title: entry.meta.kind === "solution_chat" ? t("删除这段方案对话？") : entry.meta.kind === "requirements" ? t("删除这段需求对话？") : t("删除这次运行？"), action: t("删除"),
    text: entry.meta.kind === "solution_chat" ? t("“{title}”的对话记录会被删除，原方案和已生成的方案会保留。", { title: entry.meta.title })
      : entry.meta.kind === "requirements" ? t("“{title}”的对话、需求稿和附件都会被删除，已创建的建模运行会保留。", { title: entry.meta.title })
      : t("“{title}”的问题、数学模型、代码和过程都会被删除，无法恢复。", { title: entry.meta.title }),
    run: async () => {
      await deleteRun(entry.id);
      if ((route.name === "run" || route.name === "chat" || route.name === "discussion") && route.id === entry.id) go({ name: "new" });
      await refresh();
      toast.success(t("已删除。"));
    },
  });

  const current = route.name === "run" || route.name === "chat" || route.name === "discussion" ? route.id : null;
  const sidebar = <Sidebar entries={entries} current={current} options={options} presets={presets} onNew={() => go({ name: "new" })}
    hasMore={historyQuery.hasNextPage} loading={historyQuery.isFetching} error={historyQuery.error ? errorText(historyQuery.error) : null}
    onLoadMore={() => void historyQuery.fetchNextPage()} onRetry={() => void historyQuery.refetch()}
    onOpen={entry => go({ name: entry.meta.kind === "solution_chat" ? "discussion" : entry.meta.kind === "requirements" ? "chat" : "run", id: entry.id })}
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
        <span className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">{route.name === "new" ? t("新建建模") : "LLM4OM"}</span>
        {route.name !== "new" ? <Button variant="ghost" size="icon" aria-label={t("新建建模")} onClick={() => go({ name: "new" })}><Plus /></Button> : null}
      </header>
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
          : route.name === "new"
            ? <Composer options={options} presets={presets} draft={draft} setDraft={setDraft} onStart={start} onCompare={compare}
              openPresets={() => setPresetsOpen(true)} openExamples={() => setExamplesOpen(true)} onDiscuss={async () => {
                const preset = presets.find(item => item.id === draft.preset) ?? presets[0];
                const id = await createRequirements({ description: draft.description, data: draft.data }, preset);
                void refresh(); go({ name: "chat", id });
              }} />
            : <Suspense fallback={<div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在加载……")}</div>}>
              {route.name === "compare" ? <Compare key={route.id} group={route.id} options={options} onOpen={id => go({ name: "run", id })} />
                : route.name === "chat" ? <Requirements key={route.id} threadId={route.id} presets={presets} searchConfigured={!!options.search_configured}
                  openPresets={() => setPresetsOpen(true)} onFinished={() => void refresh()}
                  onUse={next => { setDraft({ ...draft, ...next }); go({ name: "new" }); }} />
                : route.name === "discussion" ? <SolutionChat key={route.id} threadId={route.id} presets={presets}
                  openPresets={() => setPresetsOpen(true)} onFinished={() => void refresh()}
                  onOpen={id => go({ name: "run", id })} onCompare={id => go({ name: "compare", id })} />
                : <RunView key={route.id} threadId={route.id} options={options} onFinished={() => void refresh()}
                  onDiscuss={async () => { const id = await createSolutionChat(route.id); void refresh(); go({ name: "discussion", id }); }}
                  onConversation={id => go({ name: "discussion", id })} onScenarios={async scenarios => {
                    const result = await startScenarios(route.id, scenarios, presets);
                    void refresh(); go({ name: "compare", id: result.group });
                    if (result.error) toast.error(t("只启动了 {started}/{total} 个运行：{error}", { started: result.started, total: scenarios.length, error: errorText(result.error) }));
                  }}
                  onEdit={next => { setDraft({ ...next, comparing: false, methods: draft.methods, presets: draft.presets }); go({ name: "new" }); }}
                  onRerun={start} onRevise={async instruction => {
                    const id = await startRevision(route.id, instruction, presets);
                    void refresh(); go({ name: "run", id });
                  }} onDelete={meta => remove({ id: route.id, meta })}
                  onCompare={group => go({ name: "compare", id: group })} onMetaChange={() => void refresh()} />}
            </Suspense>}
      </main>
    </div>

    {options ? <>
      <Examples open={examplesOpen} onClose={() => setExamplesOpen(false)} datasets={options.datasets}
        onUse={description => { setDraft({ ...draft, description, data: {} }); setExamplesOpen(false); go({ name: "new" }); }} />
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
