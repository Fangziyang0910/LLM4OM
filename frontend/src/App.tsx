import { useCallback, useEffect, useRef, useState } from "react";
import { api, setApiToken } from "./api";
import { useRunSnapshot } from "./useRunSnapshot";
import { shortMethod, status } from "./ui";
import { Datasets } from "./components/Datasets";
import { ProblemEditor } from "./components/ProblemEditor";
import { RunView } from "./components/RunView";
import { Dialog } from "./components/Dialog";
import type { BenchmarkInput, Bootstrap, DatasetSummary, JobRecord } from "./types";

type View = "editor" | "run" | "datasets";

export default function App() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [view, setView] = useState<View>(() => new URLSearchParams(location.search).get("job") ? "run" : "editor");
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [benchmarkInput, setBenchmarkInput] = useState<BenchmarkInput | null>(null);
  const [noticeState, setNoticeState] = useState({ text: "", error: false });
  const notice = useCallback((text: string, error = false) => setNoticeState({ text, error }), []);
  const { jobs, currentJob, selectedRun, snapshot, selectRun, refreshRun, refreshJobs } = useRunSnapshot(notice);
  const started = useRef(false);
  const initialized = useRef(false);
  const openJob = async (id: string, run: string | null = null, preserveLink = false) => {
    if (!preserveLink) {
      const address = new URL("/", location.origin);
      address.searchParams.set("job", id);
      if (run) address.searchParams.set("run", run);
      history.replaceState(null, "", address.pathname + address.search);
    }
    setView("run");
    setHistoryOpen(false);
    notice("");
    await selectRun(id, run);
  };
  const refreshDatasets = async () => {
    const result = await api<{ datasets: DatasetSummary[] }>("/api/datasets");
    setDatasets(result.datasets);
  };
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const params = new URLSearchParams(location.search);
    (async () => {
      try {
        const result = await api<Bootstrap>("/api/bootstrap");
        setApiToken(result.token);
        setBootstrap(result);
        await refreshJobs();
        const job = params.get("job"), run = params.get("run");
        if (job) {
          if (!/^[a-f0-9]{32}$/.test(job) || (run && !/^[a-f0-9]{32}$/.test(run)))
            throw new Error("运行链接中的标识无效。");
          await openJob(job, run, true);
        }
      } catch (error) { notice((error as Error).message, true); }
      finally { initialized.current = true; }
    })();
  }, []);
  useEffect(() => {
    if (initialized.current && view !== "run") history.replaceState(null, "", "/");
  }, [view]);
  return (
    <>
      <header className="app-bar">
        <a className="brand" href="/">
          <span className="brand-symbol">∑</span> LLM<span>4</span>OM
        </a>
        <nav aria-label="工作台导航"><button
          aria-current={view === "editor" ? "page" : undefined}
          id="new-run"
          className={"nav-link" + (view === "editor" ? " active" : "")}
          onClick={() => {
            void selectRun(null);
            setView("editor");
            notice("");
          }}
        >
          <span aria-hidden="true">＋</span> 新建问题
        </button>
          <button
            aria-current={view === "datasets" ? "page" : undefined}
            id="open-datasets"
            className={"nav-link" + (view === "datasets" ? " active" : "")}
            onClick={() => {
              void selectRun(null);
              setView("datasets");
              refreshDatasets().catch((error) => notice((error as Error).message, true));
            }}
          >
            示例题库
          </button>
          <button id="open-history" className="nav-link" onClick={() => setHistoryOpen(true)}>历史记录</button>
        </nav>
      </header>
      <Dialog open={historyOpen} title="历史记录" onClose={() => setHistoryOpen(false)}>
        <div id="jobs" aria-label="运行记录">
          {!jobs.length ? <p className="history-empty">你的建模记录会保存在这里</p> : null}
          {jobs.map((job) => (
            <button
              key={job.job_id}
              data-job-id={job.job_id}
              aria-current={job.job_id === currentJob ? "page" : undefined}
              className={
                "job" +
                (job.job_id === currentJob ? " selected" : "") +
                (["failed", "cancelled"].includes(job.status) ? " failed" : "")
              }
              onClick={() => openJob(job.job_id).catch(error => notice(error.message, true))}
            >
              <strong>{job.description}</strong>
              <span>{`${status(job.status)} · ${shortMethod(job.method)}`}</span>
            </button>
          ))}
        </div>
      </Dialog>
      <main className={view === "run" ? "workspace" : "landing"}>
        <div id="notice" className={noticeState.error ? "error" : ""} role={noticeState.error ? "alert" : "status"} hidden={!noticeState.text}>
          {noticeState.text}
        </div>

        <div className="editor-page" hidden={view !== "editor"}>
          {bootstrap ? <ProblemEditor bootstrap={bootstrap} active={view === "editor"} notice={notice} benchmarkInput={benchmarkInput}
            onSubmitted={async (job: JobRecord) => { await refreshJobs(); await openJob(job.job_id); }} /> : <p>正在读取配置…</p>}
        </div>
        {view === "datasets" ? <Datasets datasets={datasets} refresh={refreshDatasets} notice={notice}
          onTry={(input) => { setBenchmarkInput({ ...input }); setView("editor"); notice("已带入样例，可选择方法并开始建模。"); }} /> : null}
        {view === "run" && !snapshot ? <p className="loading-state" role="status">正在读取建模记录…</p> : null}
        {view === "run" && snapshot ? <RunView key={currentJob} snapshot={snapshot} selectedRun={selectedRun}
          selectRun={selectRun} refreshRun={refreshRun} notice={notice} /> : null}
      </main>
    </>
  );
}
