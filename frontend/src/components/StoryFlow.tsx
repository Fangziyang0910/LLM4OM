// 按真实事件展示方法步骤与阶段产物，点击有产物的步骤进入对应阅读区。
// `.timeline-step[data-artifact]` 契约保持:run_public 产物事件挂 data-artifact。
import { useMemo, useState } from "react";
import type { ArtifactRef, CheckResult, CodeArtifact, ModelArtifact, Snapshot } from "../types";
import { artifactKey, artifactLabel, failureDiagnosis, format, phaseLabel, roleLabel, shortMethod, status } from "../ui";

const eventLabels: Record<string, string> = {
  formulation_saved: "数学表述已保存",
  code_saved: "求解实现已保存",
  solver_started: "调用求解器",
  solver_finished: "求解完成",
  code_output_saved: "原生代码已生成",
  method_execution_finished: "执行生成代码",
  clarification_requested: "等待补充信息",
  check_finished: "公开检查",
  selection_saved: "最终选择",
  execution_reused: "复用已执行脚本",
};

interface Attempt {
  role?: string;
  model?: string;
  requested_model?: string;
  status?: string;
  start?: number;
  end?: number;
  usage?: { total_tokens?: number | null };
}

interface StoryItem {
  id: string;
  label: string;
  actor?: string;
  phase: string;
  status: string;
  start?: number;
  end?: number;
  artifact?: string;
  linkedArtifact?: string;
  artifactTab: string;
  milestone?: boolean;
  detail?: string;
}

function collectItems(snapshot: Snapshot): StoryItem[] {
  const events = snapshot.events || [];
  const items = new Map<string, StoryItem>();
  for (const event of events) {
    const step = event.method_event;
    if (step?.type === "modeling_step") {
      const prior = items.get(step.step_id);
      items.set(step.step_id, {
        id: "step-" + step.step_id,
        label: step.label,
        actor: step.actor,
        phase: step.phase,
        status: step.status,
        start: prior?.start ?? step.timestamp,
        end: step.status === "completed" ? step.timestamp : prior?.end,
        artifact: prior?.artifact ?? artifactKey(snapshot, step.artifact_ref),
        artifactTab: step.phase === "code" ? "code" : step.phase === "solve" ? "diagnostics" : "formulation",
      });
      continue;
    }
    if (step?.artifact_ref?.namespace === "run_public" && !items.has("artifact-" + event.sequence_no)) {
      const name = artifactKey(snapshot, step.artifact_ref);
      if (name)
        items.set("artifact-" + event.sequence_no, {
          id: "artifact-" + event.sequence_no,
          label: artifactLabel(name),
          actor: "阶段产物",
          phase: step.stage || "formulation",
          status: "completed",
          artifact: name,
          artifactTab: (step.stage || "formulation") === "code" ? "code" : "formulation",
        });
      continue;
    }
    if (event.kind === "run_finished" || event.kind === "run_started") continue;
    const label = eventLabels[event.kind];
    if (!label) continue;
    const runningCore =
      event.kind === "solver_started" &&
      !events.some((item) => item.kind === "solver_finished") &&
      snapshot.job.status === "running";
    const modelKey = artifactKey(snapshot, event.artifact_ref as ArtifactRef | undefined);
    const model = snapshot.contents?.[modelKey || ""] as ModelArtifact | undefined;
    const code = snapshot.contents?.[artifactKey(snapshot, model?.code_ref) || ""] as CodeArtifact | undefined;
    const linked =
      event.kind === "formulation_saved"
        ? artifactKey(snapshot, model?.formulation_ref) || modelKey
        : event.kind === "solver_finished"
          ? artifactKey(snapshot, (event as any).solve_result_ref)
          : event.kind === "code_saved" || event.kind === "code_output_saved"
            ? artifactKey(snapshot, code?.representation_ref || model?.code_ref) || modelKey
            : event.kind === "check_finished"
              ? artifactKey(snapshot, (event as any).check_ref)
              : undefined;
    items.set("event-" + event.sequence_no, {
      id: "event-" + event.sequence_no,
      label,
      actor: event.kind === "solver_started" || event.kind === "solver_finished" ? "求解器" : undefined,
      phase: event.kind.startsWith("solver") || event.kind === "check_finished"
        ? "solve"
        : event.kind === "clarification_requested" || event.kind === "selection_saved"
          ? "coordination"
          : event.kind.startsWith("code") || event.kind.startsWith("method_execution")
            ? "code"
            : "formulation",
      status:
        event.kind === "clarification_requested" && snapshot.job.status === "needs_input"
          ? "needs_input"
          : runningCore
            ? "running"
            : "completed",
      // 方法事件之外的核心事件不占用 data-artifact 契约,产物经按钮跳转。
      linkedArtifact: linked,
      // 澄清问答本身是建模输出(答复构成后续输入),无论何时都展示。
      milestone: event.kind === "clarification_requested" || event.kind === "selection_saved",
      detail: event.kind === "selection_saved"
        ? `检查 ${(event as any).check_id} · ${(event as any).reason}`
        : event.kind === "check_finished"
          ? `检查 ${(event as any).check_id}`
          : undefined,
      artifactTab: event.kind === "solver_finished" ? "result" : event.kind.startsWith("code") ? "code" : "formulation",
    });
  }
  return [...items.values()]
    .filter((item) =>
      item.id.startsWith("step-") || item.milestone || item.status === "running" || Boolean(item.artifact || item.linkedArtifact),
    )
    .sort((a, b) => (orderOf(a, snapshot) - orderOf(b, snapshot)) || a.id.localeCompare(b.id));
}

const orderOf = (item: StoryItem, snapshot: Snapshot) => {
  if (item.id.startsWith("artifact-")) return Number(item.id.slice(8));
  if (item.id.startsWith("event-")) return Number(item.id.slice(6));
  const sequence = (snapshot.events || []).find(
    (event) => event.method_event?.step_id === item.id.slice(5),
  )?.sequence_no;
  return sequence ?? 0;
};

function assessmentFeedback(snapshot: Snapshot, item: StoryItem) {
  if (!item.linkedArtifact?.includes("/check.json")) return null;
  const assessment = snapshot.contents?.[item.linkedArtifact] as CheckResult | undefined;
  if (!assessment) return null;
  const diagnostics = assessment.diagnostics || [];
  const stages = Object.entries(assessment.stages || {})
    .filter(([, value]) => value?.status === "available")
    .map(([key]) => ({ formulation: "数学表述", code: "求解实现", solve: "求解" })[key] || key);
  return { stages, diagnostics };
}

export function StoryFlow({
  snapshot,
  finalObjective,
  onOpenArtifact,
  onOpenResult,
}: {
  snapshot: Snapshot;
  finalObjective: { value: number | null; termination: string } | null;
  onOpenArtifact: (tab: string, key: string) => void;
  onOpenResult: () => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const job = snapshot.job;
  const items = useMemo(() => collectItems(snapshot), [snapshot]);
  const attempts: Attempt[] = useMemo(() => {
    const collected: Attempt[] = [];
    for (const name of Object.keys(snapshot.contents || {}))
      if (/(?:^|\/)llm-trace\.json$/.test(name))
        collected.push(...(((snapshot.contents[name] as { attempts?: Attempt[] })?.attempts || []) as Attempt[]));
    return collected;
  }, [snapshot]);
  const ledger = snapshot.contents?.["budget-ledger.json"];
  const tokenTotal = attempts.reduce((sum, attempt) => sum + (attempt.usage?.total_tokens ?? 0), 0);
  const consumption = {
    requests: ledger?.llm_attempts ?? attempts.length,
    tokens: ledger?.known_total_tokens ?? ledger?.total_tokens ?? tokenTotal,
    solves: ledger?.solver_calls,
  };
  const finished = ["completed", "artifact_ready"].includes(job.status);
  const failed = ["failed", "cancelled"].includes(job.status);
  const runError = job.error || snapshot.bundle?.error;
  const connection = snapshot.contents?.["llm-trace.json"]?.attempts
    ?.filter((item: any) => item.diagnostic === runError?.code && item.connection_diagnostic)
    .at(-1);
  const [failureTitle, failureDetail] = failureDiagnosis(
    runError?.code,
    connection?.connection_diagnostic,
  );
  return (
    <>
      <div className="panel-title">
        <h3>建模过程</h3>
        <span id="process-state" className="pill">
          {status(job.status)}
        </span>
      </div>
      <p id="process-summary" className="hint">
        {shortMethod(snapshot.contents?.["public-config.json"]?.method?.plugin_id || job.method) +
          (job.status === "running" ? " · 正在执行方法步骤" : "")}
      </p>
      <div id="method-timeline" className={items.length ? undefined : "story-empty"}>
        {!items.length ? (
          <p className="hint">{job.status === "queued" ? "正在等待执行…" : "正在读取问题与检查配置…"}</p>
        ) : null}
        {items.map((item) => {
          const failedStep = item.status === "running" && failed;
          const className = "timeline-step story-card " + (failedStep ? "failed" : item.status);
          const jumpKey = item.artifact || item.linkedArtifact;
          const feedback = assessmentFeedback(snapshot, item);
          const expandable = !!feedback;
          const isOpen = expandable && expanded[item.id];
          return (
            <article key={item.id} className={className} data-artifact={item.artifact || undefined}>
              <button type="button" className="story-head" disabled={!jumpKey && !expandable}
                aria-expanded={expandable ? Boolean(isOpen) : undefined}
                onClick={() => {
                  if (jumpKey && !expandable) onOpenArtifact(item.artifactTab, jumpKey);
                  if (expandable) setExpanded(prior => ({ ...prior, [item.id]: !isOpen }));
                }}>
                <span className="step-marker" aria-hidden="true">
                  {item.status === "completed" ? "✓" : failedStep ? "!" : item.status === "needs_input" ? "?" : ""}
                </span>
                <span className="step-content">
                  <strong>{roleLabel(item.label)}</strong>
                  <span>{phaseLabel(item.phase)}{item.status === "running" && !failedStep ? " · 进行中" : ""}</span>
                </span>
                {expandable ? <span aria-hidden="true">{isOpen ? "−" : "+"}</span> : jumpKey ? (
                  <span className="story-artifact-button" title={artifactLabel(jumpKey)} aria-label={"查看" + artifactLabel(jumpKey)}>↗</span>
                ) : null}
              </button>
              {item.detail ? <details className="step-detail"><summary>{item.label === "最终选择" ? "选择依据" : "检查记录"}</summary>
                <p>{item.detail}</p>
              </details> : null}
              {isOpen && feedback ? (
                <div className="story-body" onClick={(event) => event.stopPropagation()}>
                  {feedback.stages.length ? (
                    <p className="hint">已通过检查的阶段:{feedback.stages.join("、")}</p>
                  ) : (
                    <p className="hint">该检查尚无通过记录的阶段。</p>
                  )}
                  {feedback.diagnostics.length ? (
                    feedback.diagnostics.map((diagnostic: any, index: number) => (
                      <p className="model-warning" key={index}>
                        {diagnostic.message || diagnostic.code}
                      </p>
                    ))
                  ) : (
                    <p className="hint">公开检查未记录诊断信息。</p>
                  )}
                </div>
              ) : null}
            </article>
          );
        })}
        {finished || failed ? (
          <article className={"timeline-step story-card ending " + (finished ? "completed" : "failed")}>
            <header className="story-head">
              <span className="step-marker">{finished ? "✓" : "!"}</span>
              <div className="step-content">
                <strong>{finished ? "建模完成" : failureTitle}</strong>
                <span>
                  {finished
                    ? finalObjective
                      ? finalObjective.value == null
                        ? status(finalObjective.termination)
                        : "目标值 " + format(finalObjective.value)
                      : "过程记录已保存"
                    : failureDetail}
                </span>
              </div>
            </header>
            <div className="story-body">
              <button type="button" className="secondary" onClick={onOpenResult}>
                {finished ? "查看求解结果 →" : "查看运行详情 →"}
              </button>
            </div>
          </article>
        ) : null}
      </div>
      <details className="process-resources"><summary>运行用量</summary>
      <div className="story-consumption" aria-live="polite">
        <span className="pill">模型请求 {format(consumption.requests)}</span>
        <span className="pill">Token {consumption.tokens == null ? "未知" : format(consumption.tokens)}</span>
        {consumption.solves != null ? (
          <span className="pill muted">求解 {format(consumption.solves)} 次</span>
        ) : null}
      </div>
      </details>
    </>
  );
}
