import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { Menu, Plus, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { api, client, errorText, history, startRun } from "./api";
import { Composer, initialDraft } from "./components/Composer";
import { Dialog } from "./components/Dialog";
import { Examples } from "./components/Examples";
import { RunView } from "./components/RunView";
import { SettingsDialog } from "./components/SettingsDialog";
import { Sidebar } from "./components/Sidebar";
import type { Draft, Entry, Options, Settings } from "./types";

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
    title: "删除运行", action: "删除",
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
  return <div className={"shell" + (menuOpen ? " menu-open" : "")}>
    <Sidebar entries={entries} current={current} options={options} settings={settings} onNew={() => go({ name: "new" })}
      onOpen={id => go({ name: "run", id })} onDelete={remove}
      onExamples={() => { setExamplesOpen(true); setMenuOpen(false); }} onSettings={() => { setSettingsOpen(true); setMenuOpen(false); }} />
    <button className="scrim" aria-label="关闭菜单" tabIndex={-1} onClick={() => setMenuOpen(false)} />

    <div className="main">
      <header className="topbar">
        <button className="icon-button" aria-label="打开菜单" onClick={() => setMenuOpen(true)}><Menu /></button>
        <span className="topbar-title">{route.name === "new" ? "新建建模" : currentEntry?.meta.title ?? "运行"}</span>
        {route.name === "run" ? <button className="icon-button" aria-label="新建建模" onClick={() => go({ name: "new" })}><Plus /></button> : null}
      </header>
      <main>
        {optionsQuery.error ? <div className="page-error"><TriangleAlert size={22} /><p>无法连接服务器：{errorText(optionsQuery.error)}</p>
          <button className="button" onClick={() => void optionsQuery.refetch()}>重试</button></div>
          : !options ? <div className="page-loading"><span className="spinner" />正在加载……</div>
          : route.name === "new"
            ? <Composer options={options} settings={settings} draft={draft} setDraft={setDraft} onStart={start}
              openSettings={() => setSettingsOpen(true)} openExamples={() => setExamplesOpen(true)} />
            : <RunView key={route.id} threadId={route.id} options={options} onFinished={() => void refresh()}
              onEdit={next => { setDraft(next); go({ name: "new" }); }} onRerun={start}
              onDelete={() => currentEntry ? remove(currentEntry) : undefined} />}
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
  return <Dialog open={!!confirm} title={confirm?.title ?? ""} onClose={onClose} footer={<>
    <button className="button" onClick={onClose}>取消</button>
    <button className="button danger" disabled={busy} onClick={async () => {
      setBusy(true);
      try { await confirm?.run(); onClose(); } catch (error) { toast.error(errorText(error)); } finally { setBusy(false); }
    }}>{confirm?.action}</button>
  </>}>
    <p>{confirm?.text}</p>
  </Dialog>;
}
