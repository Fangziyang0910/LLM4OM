import { useCallback, useEffect, useRef, useState } from "react";
import { api, setApiToken } from "./api";
import { useRunSnapshot } from "./useRunSnapshot";
import { shortMethod, status } from "./ui";
import { Datasets } from "./components/Datasets";
import { ProblemEditor } from "./components/ProblemEditor";
import { RunView } from "./components/RunView";
import type { BenchmarkInput, Bootstrap, DatasetSummary, JobRecord } from "./types";

type View = "editor" | "run" | "datasets";

export default function App() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [view, setView] = useState<View>("editor");
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
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
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-symbol">∑</span> LLM<span>4</span>OM
        </a>
        <p className="subtitle">用自然语言解决优化问题</p>
        <button
          id="new-run"
          className={"nav" + (view === "editor" ? " active" : "")}
          onClick={() => {
            void selectRun(null);
            setView("editor");
            notice("");
          }}
        >
          ＋ 新建问题
        </button>
        <h2 className="small-heading">运行记录</h2>
        <div id="jobs" aria-label="运行记录">
          {jobs.map((job) => (
            <button
              key={job.job_id}
              data-job-id={job.job_id}
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
        <h2 className="small-heading">参考样例</h2>
        <button
          id="open-datasets"
          className={"nav" + (view === "datasets" ? " active" : "")}
          onClick={() => {
            void selectRun(null);
            setView("datasets");
            refreshDatasets().catch((error) => notice((error as Error).message, true));
          }}
        >
          内置 Benchmark
        </button>
        <p className="sidebar-footer">自然语言 → 优化模型 → 决策</p>
      </aside>
      <main>
        <header>
          <h1>
            {view === "run" ? "运行结果" : view === "datasets" ? "内置 Benchmark" : "开始建模"}
          </h1>
        </header>
        <div id="notice" role="status" hidden={!noticeState.text}>
          {noticeState.text}
        </div>

        <div hidden={view !== "editor"}>
          {bootstrap ? <ProblemEditor bootstrap={bootstrap} notice={notice} benchmarkInput={benchmarkInput}
            onSubmitted={async (job: JobRecord) => { await refreshJobs(); await openJob(job.job_id); }} /> : <p>正在读取配置…</p>}
        </div>
        {view === "datasets" ? <Datasets datasets={datasets} refresh={refreshDatasets} notice={notice}
          onTry={(input) => { setBenchmarkInput({ ...input }); setView("editor"); notice("已带入样例，可选择方法并开始建模。"); }} /> : null}
        {view === "run" && snapshot ? <RunView key={currentJob} snapshot={snapshot} selectedRun={selectedRun}
          selectRun={selectRun} refreshRun={refreshRun} notice={notice} /> : null}
      </main>
    </>
  );
}
