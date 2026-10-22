import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Menu, Plus, RefreshCw, ServerCrash } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { api, deleteRun, history, startComparison, startRun } from "./api";
import { errorText } from "./format";
import { Composer, initialDraft } from "./components/Composer";
import { Examples } from "./components/Examples";
import { PresetsDialog } from "./components/PresetsDialog";
import { Sidebar } from "./components/Sidebar";
import { t } from "./i18n";
import type { Draft, Entry, Options, Preset, Presets } from "./types";

// The run page carries Markdown, KaTeX and highlighting; the composer loads without them.
const RunView = lazy(() => import("./components/RunView").then(module => ({ default: module.RunView })));
const Compare = lazy(() => import("./components/Compare").then(module => ({ default: module.Compare })));

type Route = { name: "new" } | { name: "run"; id: string } | { name: "compare"; id: string };
type Confirm = { title: string; text: string; action: string; run: () => Promise<void> };

const routeFromUrl = (): Route => {
  const match = location.pathname.match(/^\/(run|compare)\/([\w-]+)/);
  return match ? { name: match[1] as "run" | "compare", id: match[2] } : { name: "new" };
};
const NO_PRESETS: Preset[] = [];

export default function App() {
  const queryClient = useQueryClient();
  const optionsQuery = useQuery({ queryKey: ["options"], queryFn: () => api<Options>("/api/options"), staleTime: Infinity });
  const presetsQuery = useQuery({ queryKey: ["presets"], queryFn: () => api<Presets>("/api/presets") });
  const presets = presetsQuery.data?.presets ?? NO_PRESETS;
  // Runs started elsewhere (another tab, the CLI against the server) finish without telling this page.
  const entries = useQuery({ queryKey: ["history"], queryFn: () => history(),
    refetchInterval: query => query.state.data?.some(entry => entry.state === "running") ? 4000 : false }).data ?? [];
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
    const id = await startRun(request, presets.find(item => item.id === request.preset) ?? presets[0]);
    void refresh();
    go({ name: "run", id });
  };
  const compare = async (request: Draft, runs: { method: string; preset: Preset }[]) => {
    const { group, started, error } = await startComparison(request, runs);
    void refresh();
    go({ name: "compare", id: group });
    if (error) toast.error(t("只启动了 {started}/{total} 个运行：{error}", { started, total: runs.length, error: errorText(error) }));
  };
  const remove = (entry: Entry) => setConfirm({
    title: t("删除这次运行？"), action: t("删除"),
    text: t("“{title}”的问题、数学模型、代码和过程都会被删除，无法恢复。", { title: entry.meta.title }),
    run: async () => {
      await deleteRun(entry.id);
      if (route.name === "run" && route.id === entry.id) go({ name: "new" });
      await refresh();
      toast.success(t("已删除。"));
    },
  });

  const current = route.name === "run" ? route.id : null;
  const currentEntry = entries.find(entry => entry.id === current);
  const sidebar = <Sidebar entries={entries} current={current} options={options} presets={presets} onNew={() => go({ name: "new" })}
    onOpen={id => go({ name: "run", id })} onCompare={group => go({ name: "compare", id: group })} onDelete={remove}
    onExamples={() => { setExamplesOpen(true); setMenuOpen(false); }} onPresets={() => { setPresetsOpen(true); setMenuOpen(false); }} />;

  return <div className="flex h-dvh overflow-hidden">
    <aside aria-label={t("导航")} className="hidden w-72 shrink-0 border-r border-sidebar-border md:block">{sidebar}</aside>
    <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
      <SheetContent side="left" className="w-72 gap-0 p-0" aria-describedby={undefined}>
        <SheetTitle className="sr-only">{t("导航")}</SheetTitle>
        {sidebar}
      </SheetContent>
    </Sheet>

    <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b px-2 md:hidden">
        <Button variant="ghost" size="icon" aria-label={t("打开菜单")} onClick={() => setMenuOpen(true)}><Menu /></Button>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">{route.name === "new" ? t("新建建模") : "LLM4OM"}</span>
        {route.name !== "new" ? <Button variant="ghost" size="icon" aria-label={t("新建建模")} onClick={() => go({ name: "new" })}><Plus /></Button> : null}
      </header>
      <main className="min-h-0 flex-1">
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
              openPresets={() => setPresetsOpen(true)} openExamples={() => setExamplesOpen(true)} />
            : <Suspense fallback={<div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />{t("正在加载……")}</div>}>
              {route.name === "compare" ? <Compare key={route.id} group={route.id} options={options} onOpen={id => go({ name: "run", id })} />
                : <RunView key={route.id} threadId={route.id} options={options} onFinished={() => void refresh()}
                  onEdit={next => { setDraft({ ...next, comparing: false, methods: draft.methods, presets: draft.presets }); go({ name: "new" }); }}
                  onRerun={start} onDelete={() => currentEntry ? remove(currentEntry) : undefined}
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
