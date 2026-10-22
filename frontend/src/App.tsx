import { useQuery, useQueryClient } from "@tanstack/react-query";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Menu, Plus, RefreshCw, ServerCrash } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Spinner } from "@/components/ui/spinner";
import { api, client, history, startRun } from "./api";
import { errorText } from "./format";
import { Composer, initialDraft } from "./components/Composer";
import { Examples } from "./components/Examples";
import { SettingsDialog } from "./components/SettingsDialog";
import { Sidebar } from "./components/Sidebar";
import type { Draft, Entry, Options, Settings } from "./types";

// The run page carries Markdown, KaTeX and highlighting; the composer loads without them.
const RunView = lazy(() => import("./components/RunView").then(module => ({ default: module.RunView })));

type Route = { name: "new" } | { name: "run"; id: string };
type Confirm = { title: string; text: string; action: string; run: () => Promise<void> };

const routeFromUrl = (): Route => {
  const match = location.pathname.match(/^\/run\/([\w-]+)/);
  return match ? { name: "run", id: match[1] } : { name: "new" };
};
const NO_SETTINGS: Settings = { selected: null, profiles: {} };

export default function App() {
  const queryClient = useQueryClient();
  const optionsQuery = useQuery({ queryKey: ["options"], queryFn: () => api<Options>("/api/options"), staleTime: Infinity });
  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<Settings>("/api/settings") }).data ?? NO_SETTINGS;
  // Runs started elsewhere (another tab, the CLI against the server) finish without telling this page.
  const entries = useQuery({ queryKey: ["history"], queryFn: history,
    refetchInterval: query => query.state.data?.some(entry => entry.state === "running") ? 4000 : false }).data ?? [];
  const options = optionsQuery.data ?? null;
  const [route, setRoute] = useState<Route>(routeFromUrl);
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [examplesOpen, setExamplesOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [confirm, setConfirm] = useState<Confirm | null>(null);

  const go = useCallback((next: Route) => {
    const path = next.name === "run" ? `/run/${next.id}` : "/";
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
    const id = await startRun(request);
    void refresh();
    go({ name: "run", id });
  };
  const remove = (entry: Entry) => setConfirm({
    title: "删除这次运行？", action: "删除",
    text: `“${entry.meta.title}”的问题、数学模型、代码和过程都会被删除，无法恢复。`,
    run: async () => {
      await client.threads.delete(entry.id);
      if (route.name === "run" && route.id === entry.id) go({ name: "new" });
      await refresh();
      toast.success("已删除。");
    },
  });

  const current = route.name === "run" ? route.id : null;
  const currentEntry = entries.find(entry => entry.id === current);
  const sidebar = <Sidebar entries={entries} current={current} options={options} settings={settings} onNew={() => go({ name: "new" })}
    onOpen={id => go({ name: "run", id })} onDelete={remove}
    onExamples={() => { setExamplesOpen(true); setMenuOpen(false); }} onSettings={() => { setSettingsOpen(true); setMenuOpen(false); }} />;

  return <div className="flex h-dvh overflow-hidden">
    <aside aria-label="导航" className="hidden w-72 shrink-0 border-r border-sidebar-border md:block">{sidebar}</aside>
    <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
      <SheetContent side="left" className="w-72 gap-0 p-0" aria-describedby={undefined}>
        <SheetTitle className="sr-only">导航</SheetTitle>
        {sidebar}
      </SheetContent>
    </Sheet>

    <div className="flex min-w-0 flex-1 flex-col">
      <header className="flex h-12 shrink-0 items-center gap-2 border-b px-2 md:hidden">
        <Button variant="ghost" size="icon" aria-label="打开菜单" onClick={() => setMenuOpen(true)}><Menu /></Button>
        <span className="min-w-0 flex-1 truncate text-sm font-semibold tracking-tight">{route.name === "new" ? "新建建模" : "LLM4OM"}</span>
        {route.name === "run" ? <Button variant="ghost" size="icon" aria-label="新建建模" onClick={() => go({ name: "new" })}><Plus /></Button> : null}
      </header>
      <main className="min-h-0 flex-1">
        {optionsQuery.error ? <Empty className="h-full">
          <EmptyHeader>
            <EmptyMedia variant="icon"><ServerCrash /></EmptyMedia>
            <EmptyTitle>无法连接服务器</EmptyTitle>
            <EmptyDescription>{errorText(optionsQuery.error)}</EmptyDescription>
          </EmptyHeader>
          <EmptyContent><Button variant="outline" onClick={() => void optionsQuery.refetch()}><RefreshCw />重试</Button></EmptyContent>
        </Empty>
          : !options ? <div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />正在加载……</div>
          : route.name === "new"
            ? <Composer options={options} settings={settings} draft={draft} setDraft={setDraft} onStart={start}
              openSettings={() => setSettingsOpen(true)} openExamples={() => setExamplesOpen(true)} />
            : <Suspense fallback={<div className="flex h-full items-center justify-center gap-2 text-sm text-muted-foreground"><Spinner />正在加载……</div>}>
              <RunView key={route.id} threadId={route.id} options={options} onFinished={() => void refresh()}
                onEdit={next => { setDraft(next); go({ name: "new" }); }} onRerun={start}
                onDelete={() => currentEntry ? remove(currentEntry) : undefined} />
            </Suspense>}
      </main>
    </div>

    {options ? <>
      <Examples open={examplesOpen} onClose={() => setExamplesOpen(false)} datasets={options.datasets}
        onUse={description => { setDraft({ ...draft, description, data: {} }); setExamplesOpen(false); go({ name: "new" }); }} />
      {settingsOpen ? <SettingsDialog onClose={() => setSettingsOpen(false)} settings={settings} providers={options.providers}
        onChange={(value, message) => { queryClient.setQueryData(["settings"], value); toast.success(message); }} /> : null}
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
        <Button variant="outline" onClick={onClose}>取消</Button>
        <Button variant="destructive" disabled={busy} onClick={async () => {
          setBusy(true);
          try { await confirm?.run(); onClose(); } catch (error) { toast.error(errorText(error)); } finally { setBusy(false); }
        }}>{busy ? <Spinner /> : null}{confirm?.action}</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
