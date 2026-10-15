import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { artifactKey, artifactLabel, activeStep, shortMethod, status } from "../ui";
import { StageHistory } from "./StageHistory";
import { Clarification, type ClarificationRequest } from "./Clarification";
import { Decision } from "./Decision";
import { Records } from "./Records";
import { RuntimeDetails } from "./RuntimeDetails";
import { StoryFlow } from "./StoryFlow";
import { RevisionEditor } from "./RevisionEditor";
import type { ArtifactRef, CodeArtifact, ModelArtifact, Notice, Snapshot, SolveResult } from "../types";

const tabPatterns: Record<string, RegExp> = {
  formulation: /formulation|model-ir|structured-ir|method\/state_/,
  code: /code|build|symbol-map|model\.py|factory\.py|native.*\.py/,
  diagnostics: /diagnostic|execution|budget|report|trace/,
  data: /public-problem|data-views|dataset-manifest|data-bind/,
};

const tabHeadings: Record<string, string> = {
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
      tabPatterns[activeTab].test(key),
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
  return (
    <section id="result">
      <div className="run-heading">
        <div>
          <p className="eyebrow">建模与求解</p>
          <h2 id="run-title">{snapshot.job.description}</h2>
          <p id="run-meta">
            {`${status(snapshot.job.status)} · ${
              snapshot.bundle?.assisted &&
              (contents["public-config.json"]?.method?.plugin_id || snapshot.job.method) !==
                "llm4om.methods.assisted"
                ? "人工辅助 · "
                : ""
            }${shortMethod(contents["public-config.json"]?.method?.plugin_id || snapshot.job.method)} · ${
              snapshot.job.run_id || "正在准备"
            }`}
          </p>
          <label className="version-selector" hidden={(snapshot.versions || []).length < 2}>
            运行版本
            <select
              id="run-version"
              aria-label="选择运行版本"
              value={selectedRun || ""}
              onChange={async (event) => {
                setEditOpen(false);
                setArtifactChoice("");
                setArtifactSelectedByUser(false);
                try { await selectRun(currentJob, event.target.value || null); }
                catch (error) { notice((error as Error).message, true); }
              }}
            >
              <option value="">最新版本 / 正在执行</option>
              {(snapshot.versions || []).map((version) => (
                <option key={version.run_id} value={version.run_id}>
                  {(version.assisted ? "人工修订" : "运行") +
                    " · " +
                    status(version.status) +
                    " · " +
                    version.run_id.slice(0, 8) +
                    (version.parent_run_id
                      ? " ← " + version.parent_run_id.slice(0, 8)
                      : " · 原始版本")}
                </option>
              ))}
            </select>
          </label>
        </div>
        <div className="actions">
          <button
            id="cancel"
            className="secondary"
            hidden={snapshot.historical || !runBusy}
            onClick={async () => {
              try {
                await api(`/api/jobs/${currentJob}/cancel`, {});
                notice("操作已提交。");
                await refreshRun();
              } catch (error) {
                notice((error as Error).message, true);
              }
            }}
          >
            取消
          </button>
          <button
            id="resume"
            className="secondary"
            hidden={snapshot.historical || !["failed", "cancelled"].includes(snapshot.job.status)}
            onClick={async () => {
              try {
                await api(`/api/jobs/${currentJob}/resume`, {}, apiKey || undefined);
                notice("操作已提交。");
                await refreshRun();
              } catch (error) {
                notice((error as Error).message, true);
              }
            }}
          >
            继续恢复
          </button>
          <button
            id="rerun"
            className="secondary"
            hidden={Boolean(snapshot.historical)}
            onClick={async () => {
              try {
                if (
                  !confirm("创建派生运行并继承预算记录。真实 LLM 可能产生新的请求费用，是否继续？")
                )
                  return;
                await api(`/api/jobs/${currentJob}/resume`, { strategy: "rerun" }, apiKey || undefined);
                notice("操作已提交。");
                await refreshRun();
              } catch (error) {
                notice((error as Error).message, true);
              }
            }}
          >
            派生重跑
          </button>
          <button
            id="edit-run"
            className="secondary"
            disabled={runBusy}
            onClick={async () => {
              try {
                setEditOpen(true);
              } catch (error) {
                notice((error as Error).message, true);
              }
            }}
          >
            编辑新版本
          </button>
          <a id="run-link" className="secondary" href={runLink.href} hidden={runLink.hidden}>
            此版本链接
          </a>
          <a
            id="export"
            className="secondary"
            href={`/api/jobs/${currentJob}/export${selectedRun ? "?run_id=" + selectedRun : ""}`}
            hidden={!snapshot.bundle}
          >
            下载结果
          </a>
        </div>
      </div>

      {contents['requested-config.json']?.llm?.config?.credential_env === 'LLM4OM_WEB_API_KEY' ? (
        <details className="advanced-controls">
          <summary>运行密钥</summary>
          <label>API Key
            <input id="run-api-key" type="password" autoComplete="off" spellCheck={false} maxLength={4096}
              value={apiKey} onChange={(event) => setApiKey(event.target.value.trim())} />
          </label>
          <p className="hint">恢复、派生重跑或修订会使用该服务已保存的密钥。需要替换本次使用的密钥时，可在此填写。</p>
        </details>
      ) : null}
      {editOpen ? (
        <RevisionEditor key={snapshot.job.run_id} snapshot={snapshot} notice={notice} apiKey={apiKey}
          onClose={() => setEditOpen(false)} onSubmitted={() => selectRun(currentJob, null).then(() => {})} />
      ) : null}

      <div id="stages" className="stage-grid">
        {(() => {
          const runningStep =
            snapshot.job.status === "running" ? activeStep(snapshot) : null;
          return (["formulation", "code", "solve"] as const).map((stage) => {
            const state =
              runningStep?.phase === stage
                ? "running"
                : ["running", "queued"].includes(snapshot.job.status) &&
                    (!snapshot.bundle?.stages?.[stage]?.status ||
                      snapshot.bundle.stages[stage].status === "not_available")
                  ? "pending"
                  : snapshot.bundle?.stages?.[stage]?.status || "pending";
            return (
              <div className={"stage " + state} key={stage}>
                <strong>
                  {{ formulation: "01 数学表述", code: "02 求解实现", solve: "03 求解结果" }[stage]}
                </strong>
                <span>{status(state)}</span>
              </div>
            );
          });
        })()}
      </div>
      <div className="experience-grid">
        <aside id="process-panel" className="panel process-panel">
          <StoryFlow
            snapshot={snapshot}
            finalObjective={
              solve
                ? { value: solve.objective_value ?? null, termination: solve.termination }
                : null
            }
            onOpenArtifact={openArtifact}
          />
        </aside>
        <div className="output-column">
          {snapshot.job.status === "needs_input" && clarificationRequest ? (
            <Clarification
              key={clarificationRequest.request_id}
              request={clarificationRequest}
              problem={contents["public-problem.json"]}
              onSubmit={async (payload) => {
                await api(`/api/jobs/${currentJob}/resume`, payload, apiKey || undefined);
                notice("回答已提交，正在恢复。");
                await refreshRun();
              }}
              onError={(message) => notice(message, true)}
            />
          ) : (
            <div id="clarification" className="panel" hidden />
          )}
          <div id="decision" className="panel">
            <Decision
              solve={solve}
              solution={solution}
              ledger={contents["budget-ledger.json"]}
              snapshot={snapshot}
              solvedIR={solvedIR}
              onOpenDiagnostics={() => setActiveTab("diagnostics")}
            />
          </div>
          <div className="tabs" role="tablist">
            {(
              [
                ["formulation", "数学模型"],
                ["code", "求解代码"],
                ["diagnostics", "运行详情"],
                ["data", "输入数据"],
              ] as [string, string][]
            ).map(([tab, label]) => (
              <button
                key={tab}
                className={"tab" + (activeTab === tab ? " active" : "")}
                data-tab={tab}
                onClick={() => {
                  setActiveTab(tab);
                  setArtifactSelectedByUser(false);
                }}
              >
                {label}
              </button>
            ))}
          </div>
          <div className="panel">
            <div id="output-heading" className="output-heading">
              {tabHeadings[activeTab]}
            </div>
            <select
              id="artifact-choice"
              aria-label="选择阶段记录"
              hidden={artifactEntries.length < 2}
              value={artifactChoice}
              onChange={(event) => {
                setArtifactChoice(event.target.value);
                setArtifactSelectedByUser(true);
              }}
            >
              {artifactEntries.map(([name]) => (
                <option key={name} value={name}>
                  {(name.startsWith("checks/") ? "检查 " + name.split("/")[1] + " · " : "") +
                    (name === "运行事件" ? "运行事件" : artifactLabel(name))}
                </option>
              ))}
            </select>
            <div id="model-view" className="model-grid">
              {activeTab === "formulation" || activeTab === "code" ? (
                <StageHistory
                  snapshot={snapshot}
                  stage={activeTab}
                  current={artifactChoice}
                  onOpen={(key) => openArtifact(activeTab, key)}
                />
              ) : null}
              {activeTab === "diagnostics" ? (
                <RuntimeDetails snapshot={snapshot} />
              ) : selectedArtifact === undefined &&
                ["running", "queued", "needs_input"].includes(snapshot.job.status) ? (
                <div className="empty-view">
                  <div className="empty-icon">◇</div>
                  <h3>
                    {snapshot.job.status === "needs_input"
                      ? "补充信息后继续建模"
                      : activeTab === "code"
                        ? "求解实现正在形成"
                        : "建模输出正在形成"}
                  </h3>
                  <p className="hint">完成的公开产物会自动出现在这里。</p>
                </div>
              ) : (
                <Records
                  value={recordView}
                  tab={activeTab}
                  contents={isolatedContents}
                  dataPreviews={snapshot.data_previews}
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
