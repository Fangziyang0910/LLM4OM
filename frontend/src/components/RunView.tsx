import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { artifactKey, artifactLabel, activeStep, shortMethod, status } from "../ui";
import { StageHistory } from "./StageHistory";
import { Clarification, type ClarificationRequest } from "./Clarification";
import { Decision, DecisionSummary } from "./Decision";
import { Records } from "./Records";
import { RuntimeDetails } from "./RuntimeDetails";
import { StoryFlow } from "./StoryFlow";
import { RevisionEditor } from "./RevisionEditor";
import type { ArtifactRef, CodeArtifact, ModelArtifact, Notice, Snapshot, SolveResult } from "../types";

const tabPatterns: Record<string, RegExp | null> = {
  result: null,
  formulation: /formulation|model-ir|structured-ir|method\/state_/,
  code: /code|build|symbol-map|model\.py|factory\.py|native.*\.py/,
  diagnostics: /diagnostic|execution|budget|report|trace/,
  data: /public-problem|data-views|dataset-manifest|data-bind/,
};

const tabHeadings: Record<string, string> = {
  result: "求解结果",
  formulation: "数学模型",
  code: "求解实现",
  diagnostics: "实际运行记录",
  data: "问题与数据",
};

export function RunView({ snapshot, selectedRun, selectRun, refreshRun, notice }: {
  snapshot: Snapshot; selectedRun: string | null;
  selectRun: (job: string | null, run?: string | null) => Promise<Snapshot | null>;
  refreshRun: () => Promise<Snapshot | null>; notice: Notice;
}) {
  const currentJob = snapshot.job.job_id;
  const [activeTab, setActiveTab] = useState(() => {
    const tab = new URLSearchParams(location.search).get("tab");
    return tab && Object.hasOwn(tabPatterns, tab) ? tab :
      snapshot.bundle?.stages?.formulation?.status === "not_available" ? "code" : "formulation";
  });
  const [artifactChoice, setArtifactChoice] = useState(new URLSearchParams(location.search).get("artifact") || "");
  const [artifactSelectedByUser, setArtifactSelectedByUser] = useState(Boolean(artifactChoice));
  const [editOpen, setEditOpen] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const contents = snapshot.contents || {};
  const publicValue = (ref: ArtifactRef | null | undefined) => artifactKey(snapshot, ref);
  const solve = contents[publicValue(snapshot.bundle?.solve_result_ref) || ""] as SolveResult | undefined;
  const solution = contents[publicValue(solve?.solution_ref) || ""];
  const model = contents[publicValue(snapshot.bundle?.model_artifact_ref) || ""] as ModelArtifact | undefined;
  const code = contents[publicValue(model?.code_ref) || ""] as CodeArtifact | undefined;
  const solvedIR =
    code?.provenance?.origin === "deterministic_compilation"
      ? contents[publicValue(code.provenance.source_ir_ref) || ""]
      : null;

  const artifactEntries = useMemo(() => {
    const entries = Object.entries(snapshot.contents || {}).filter(([key]) =>
      tabPatterns[activeTab]?.test(key),
    );
    if (activeTab === "diagnostics") entries.unshift(["运行事件", snapshot.events || []]);
    const selectedCheck = snapshot.bundle?.selected_check_id || "001";
    const score = ([name, value]: [string, unknown]) =>
      activeTab === "code"
        ? name === `checks/${selectedCheck}/model.py`
          ? 2
          : Number(name.endsWith(".py"))
        : value && typeof value === "object" && "representation" in value && value.representation
          ? 100 + Number(name.startsWith(`checks/${selectedCheck}/`))
          : Number(name.match(/method\/state_(\d+)/)?.[1] || 0);
    entries.sort((a, b) => score(b) - score(a));
    return entries;
  }, [snapshot, activeTab]);

  useEffect(() => {
    if (!snapshot) return;
    const previous = artifactChoice;
    const values = artifactEntries.map(([name]) => name);
    if (artifactSelectedByUser && values.includes(previous)) setArtifactChoice(previous);
    else setArtifactChoice(values[0] || "");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [artifactEntries, artifactSelectedByUser]);

  const address = (runId: string | null | undefined) => {
    const url = new URL("/", location.origin);
    if (currentJob) {
      url.searchParams.set("job", currentJob);
      if (runId) url.searchParams.set("run", runId);
      if (activeTab !== "formulation") url.searchParams.set("tab", activeTab);
      if (artifactSelectedByUser && artifactChoice) url.searchParams.set("artifact", artifactChoice);
    }
    return url;
  };
  const runLinkAddress = address(snapshot?.job?.run_id);
  const runLink = {
    hidden: !currentJob || !snapshot?.job?.run_id,
    href: runLinkAddress.href,
  };
  useEffect(() => {
    const current = address(selectedRun);
    history.replaceState(null, "", current.pathname + current.search);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentJob, selectedRun, activeTab, artifactSelectedByUser, artifactChoice, snapshot?.job?.run_id]);

  const selectedArtifact = artifactEntries.find(([name]) => name === artifactChoice)?.[1];
  const selectedName = artifactChoice;
  const checkPrefix = selectedName.startsWith("checks/")
    ? selectedName.split("/")[1]
    : null;
  const isolatedContents = checkPrefix
    ? Object.fromEntries(
        Object.entries(contents).filter(
          ([key]) => !key.startsWith("checks/") || key.startsWith(`checks/${checkPrefix}/`),
        ),
      )
    : contents;
  const recordView =
    activeTab === "formulation" && selectedName.startsWith("method/state_")
      ? { representation: { state: selectedArtifact } }
      : selectedArtifact;

  const clarificationRequest = contents[publicValue(snapshot.bundle?.clarification_request_ref) || ""] as ClarificationRequest | undefined;

  const openArtifact = (tab: string, key?: string) => {
    setActiveTab(tab);
    if (key) {
      setArtifactChoice(key);
      setArtifactSelectedByUser(true);
    }
  };

  const runBusy = ["running", "queued"].includes(snapshot.job.status);
  const runningStep = runBusy ? activeStep(snapshot) : null;
  const method = shortMethod(contents["public-config.json"]?.method?.plugin_id || snapshot.job.method);
  const title = snapshot.job.description.split(/[。\n]/)[0];
  const stageState = (tab: string) => {
    const stage = tab === "result" ? "solve" : tab;
    if (!["formulation", "code", "solve"].includes(stage)) return null;
    if (runningStep?.phase === stage) return "running";
    const saved = snapshot.bundle?.stages?.[stage]?.status;
    return runBusy && (!saved || saved === "not_available") ? "pending" : saved || "pending";
  };
  return (
    <section id="result">
      <div className="run-heading">
        <div className="run-intro">
          <div id="run-meta" className="run-meta">
            <span className={"run-status " + snapshot.job.status}>{status(snapshot.job.status)}</span>
            <span>{method}</span>
            {snapshot.historical ? <span>历史版本</span> : null}
          </div>
          <h2 id="run-title">{title.length > 64 ? title.slice(0, 64) + "…" : title}</h2>
          <details className="problem-brief"><summary>查看完整问题</summary>
            <p className="problem-text">{contents["public-problem.json"]?.description || snapshot.job.description}</p>
          </details>
          <label className="version-selector" hidden={(snapshot.versions || []).length < 2}>
            运行版本
            <select id="run-version" aria-label="选择运行版本" value={selectedRun || ""}
              onChange={async event => {
                setEditOpen(false); setArtifactChoice(""); setArtifactSelectedByUser(false);
                try { await selectRun(currentJob, event.target.value || null); }
                catch (error) { notice((error as Error).message, true); }
              }}>
              <option value="">最新版本</option>
              {(snapshot.versions || []).map((version) => <option key={version.run_id} value={version.run_id}>
                {`${version.assisted ? "人工修订" : "运行"} · ${status(version.status)} · ${version.run_id.slice(0, 8)}`}
              </option>)}
            </select>
          </label>
        </div>
        <div className="actions run-actions">
          <button id="cancel" className="secondary" hidden={snapshot.historical || !runBusy}
            onClick={async () => {
              try { await api(`/api/jobs/${currentJob}/cancel`, {}); notice("操作已提交。"); await refreshRun(); }
              catch (error) { notice((error as Error).message, true); }
            }}>停止运行</button>
          <button id="resume" className="primary" hidden={snapshot.historical || !["failed", "cancelled"].includes(snapshot.job.status)}
            onClick={async () => {
              try { await api(`/api/jobs/${currentJob}/resume`, {}, apiKey || undefined); notice("操作已提交。"); await refreshRun(); }
              catch (error) { notice((error as Error).message, true); }
            }}>继续恢复</button>
          <button id="edit-run" className="secondary" disabled={runBusy} onClick={() => setEditOpen(true)}>编辑新版本</button>
          <a id="export" className="secondary" href={`/api/jobs/${currentJob}/export${selectedRun ? "?run_id=" + selectedRun : ""}`}
            hidden={!snapshot.bundle}>下载产物 ↓</a>
          <details className="run-tools"><summary className="secondary" aria-label="更多运行操作">···</summary>
            <div className="run-tools-menu">
              <a id="run-link" href={runLink.href} hidden={runLink.hidden}>此版本链接 ↗</a>
              <button id="rerun" hidden={Boolean(snapshot.historical)} disabled={runBusy}
                onClick={async () => {
                  try {
                    if (!confirm("创建派生运行并继承预算记录。真实 LLM 可能产生新的请求费用，是否继续？")) return;
                    await api(`/api/jobs/${currentJob}/resume`, { strategy: "rerun" }, apiKey || undefined);
                    notice("操作已提交。"); await refreshRun();
                  } catch (error) { notice((error as Error).message, true); }
                }}>派生重跑</button>
            </div>
          </details>
        </div>
      </div>
      {contents['requested-config.json']?.llm?.config?.credential_env === 'LLM4OM_WEB_API_KEY' ? (
        <details className="run-key-settings">
          <summary>运行密钥</summary>
          <label>API Key<input id="run-api-key" type="password" autoComplete="off" spellCheck={false} maxLength={4096}
            value={apiKey} onChange={event => setApiKey(event.target.value.trim())} /></label>
          <p className="hint">默认使用已保存的密钥。这里填写的密钥只用于本次恢复或修订。</p>
        </details>
      ) : null}
      {editOpen ? <RevisionEditor key={snapshot.job.run_id} snapshot={snapshot} notice={notice} apiKey={apiKey}
        onClose={() => setEditOpen(false)} onSubmitted={() => selectRun(currentJob, null).then(() => {})} /> : null}
      <div className="experience-grid">
        <aside id="process-panel" className="panel process-panel" aria-label="建模过程">
          <StoryFlow snapshot={snapshot}
            finalObjective={solve ? { value: solve.objective_value ?? null, termination: solve.termination } : null}
            onOpenArtifact={openArtifact} onOpenResult={() => setActiveTab(solve ? "result" : "diagnostics")} />
        </aside>
        <div className="output-column">
          {snapshot.job.status === "needs_input" && clarificationRequest ? (
            <Clarification key={clarificationRequest.request_id} request={clarificationRequest}
              problem={contents["public-problem.json"]}
              onSubmit={async payload => {
                await api(`/api/jobs/${currentJob}/resume`, payload, apiKey || undefined);
                notice("回答已提交，正在恢复。"); await refreshRun();
              }} onError={message => notice(message, true)} />
          ) : <div id="clarification" hidden />}
          <div id="decision" className="panel decision-summary">
            <DecisionSummary solve={solve} snapshot={snapshot} onOpenDiagnostics={() => setActiveTab("diagnostics")} />
          </div>
          <section className="panel artifact-panel" aria-label="建模产物">
            <div className="tabs" role="tablist" aria-label="建模产物">
              {[["formulation", "数学模型"], ["code", "求解代码"], ["result", "求解结果"],
                ["data", "问题数据"], ["diagnostics", "运行详情"]].map(([tab, label], index) => {
                const state = stageState(tab);
                return <button key={tab} id={`tab-${tab}`} role="tab" aria-selected={activeTab === tab}
                  aria-controls="artifact-reader" tabIndex={activeTab === tab ? 0 : -1}
                  className={"tab" + (activeTab === tab ? " active" : "") + (state ? "" : " secondary-tab")} data-tab={tab}
                  onClick={() => { setActiveTab(tab); setArtifactSelectedByUser(false); }}
                  onKeyDown={event => {
                    const tabs = Array.from(event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('[role="tab"]'));
                    const target = event.key === "ArrowRight" ? (index + 1) % tabs.length : event.key === "ArrowLeft"
                      ? (index + tabs.length - 1) % tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : null;
                    if (target !== null) { event.preventDefault(); tabs[target].focus(); tabs[target].click(); }
                  }}>
                  {state ? <span className={"stage-dot " + state} title={status(state)} aria-label={status(state)} /> : null}{label}
                </button>;
              })}
            </div>
            <div id="artifact-reader" role="tabpanel" aria-labelledby={`tab-${activeTab}`}>
              <div className="artifact-toolbar">
                <h3 id="output-heading">{tabHeadings[activeTab]}</h3>
                <select id="artifact-choice" aria-label="选择阶段记录" hidden={artifactEntries.length < 2} value={artifactChoice}
                  onChange={event => { setArtifactChoice(event.target.value); setArtifactSelectedByUser(true); }}>
                  {artifactEntries.map(([name]) => <option key={name} value={name}>
                    {(name.startsWith("checks/") ? "检查 " + name.split("/")[1] + " · " : "") +
                      (name === "运行事件" ? "运行事件" : artifactLabel(name))}
                  </option>)}
                </select>
              </div>
              <div id="model-view" className="model-grid">
                {activeTab === "formulation" || activeTab === "code" ? <StageHistory snapshot={snapshot} stage={activeTab}
                  current={artifactChoice} onOpen={key => openArtifact(activeTab, key)} /> : null}
                {activeTab === "diagnostics" ? <RuntimeDetails snapshot={snapshot} /> : activeTab === "result" ? (
                  <Decision solve={solve} solution={solution} snapshot={snapshot}
                    solvedIR={solvedIR} showSummary={false} onOpenDiagnostics={() => setActiveTab("diagnostics")} />
                ) : selectedArtifact === undefined && ["running", "queued", "needs_input"].includes(snapshot.job.status) ? (
                  <div className="empty-view"><div className="empty-icon" aria-hidden="true">∑</div>
                    <h3>{snapshot.job.status === "needs_input" ? "补充信息后继续建模" : activeTab === "code" ? "正在生成求解代码" : "正在构建数学模型"}</h3>
                    <p className="hint">完成后自动展示，可在左侧查看建模进展。</p>
                  </div>
                ) : <Records value={recordView} tab={activeTab} contents={isolatedContents} dataPreviews={snapshot.data_previews} />}
              </div>
            </div>
          </section>
        </div>
      </div>
    </section>
  );
}
