// 垂直故事流:建模过程每个事件一张顺读卡片。展开可见该步公开输出摘要
// (角色发言、中间状态预览、时间窗内的模型调用消耗);头部为实时消耗条,
// 结束卡衔接结果区。`.timeline-step[data-artifact]` 契约保持:只有方法事件
// 引用挂 data-artifact,数量与旧时间线一致。
import { useMemo, useState } from "react";
import type { Snapshot } from "../types";
import { artifactKey, artifactLabel, failureDiagnosis, format, phaseLabel, pretty, roleLabel, shortMethod, status } from "../ui";

const eventLabels: Record<string, string> = {
  run_started: "读取问题与数据",
  formulation_saved: "数学表述已保存",
  code_saved: "求解实现已保存",
  solver_started: "调用求解器",
  solver_finished: "求解完成",
  code_output_saved: "原生代码已生成",
  method_execution_finished: "执行候选代码",
  clarification_requested: "等待补充信息",
  candidate_assessed: "候选已评估",
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
          actor: "已保存的公开产物",
          phase: step.stage || "formulation",
          status: "completed",
          artifact: name,
          artifactTab: (step.stage || "formulation") === "code" ? "code" : "formulation",
        });
      continue;
    }
    if (event.kind === "run_finished") continue;
    const label = eventLabels[event.kind];
    if (!label) continue;
    const runningCore =
      event.kind === "solver_started" &&
      !events.some((item) => item.kind === "solver_finished") &&
      snapshot.job.status === "running";
    const linked =
      event.kind === "formulation_saved"
        ? artifactKey(snapshot, (event as any).artifact_ref)
        : event.kind === "solver_finished"
          ? artifactKey(snapshot, (event as any).solve_result_ref)
          : event.kind === "code_saved"
            ? artifactKey(snapshot, (event as any).artifact_ref)
            : event.kind === "candidate_assessed"
              ? artifactKey(snapshot, (event as any).assessment_ref)
              : undefined;
    items.set("event-" + event.sequence_no, {
      id: "event-" + event.sequence_no,
      label,
      actor: event.kind === "solver_started" || event.kind === "solver_finished" ? "求解器" : undefined,
      phase: event.kind.startsWith("solver")
        ? "solve"
        : event.kind === "clarification_requested"
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
      milestone: event.kind === "clarification_requested",
      artifactTab: event.kind === "solver_finished" ? "diagnostics" : "formulation",
    });
  }
  return [...items.values()].sort(
    (a, b) => (orderOf(a, snapshot) - orderOf(b, snapshot)) || a.id.localeCompare(b.id),
  );
}

const orderOf = (item: StoryItem, snapshot: Snapshot) => {
  if (item.id.startsWith("artifact-")) return Number(item.id.slice(8));
  if (item.id.startsWith("event-")) return Number(item.id.slice(6));
  const sequence = (snapshot.events || []).find(
    (event) => event.method_event?.step_id === item.id.slice(5),
  )?.sequence_no;
  return sequence ?? 0;
};

function commentsFor(snapshot: Snapshot, actor: string | undefined) {
  if (!actor) return [];
  return Object.entries(snapshot.contents || {}).flatMap(([name, value]: [string, any]) =>
    Array.isArray(value?.comments)
      ? value.comments
          .filter(
            (comment: unknown[]) =>
              Array.isArray(comment) && comment[0] === actor && typeof comment[1] === "string",
          )
          .map((comment: unknown[]) => ({ name, text: comment[1] as string }))
      : [],
  );
}

function assessmentFeedback(snapshot: Snapshot, item: StoryItem) {
  if (!item.linkedArtifact?.includes("/assessment.json")) return null;
  const assessment = snapshot.contents?.[item.linkedArtifact];
  if (!assessment) return null;
  const diagnostics = assessment.diagnostics || [];
  const stages = Object.entries(assessment.stages || {})
    .filter(([, value]) => (value as any)?.status === "available")
    .map(([key]) => ({ formulation: "数学表述", code: "求解实现", solve: "求解" })[key] || key);
  return { stages, diagnostics };
}

function statePreview(snapshot: Snapshot, artifact: string | undefined) {
  if (!artifact?.startsWith("method/state_")) return null;
  const state = snapshot.contents?.[artifact]?.representation?.state;
  if (!state) return null;
  const fragments = [
    { description: "优化目标", code: state.objective?.code },
    ...(state.constraints || []),
  ].filter((item: any) => typeof item.code === "string" && item.code);
  return {
    description: state.description as string | undefined,
    objective: state.objective?.description || state.objective?.expression_text,
    constraints: (state.constraints || []).length,
    codeLines: fragments
      .flatMap((fragment: any) => fragment.code.split("\n"))
      .slice(0, 8),
  };
}

export function StoryFlow({
  snapshot,
  finalObjective,
  onOpenArtifact,
}: {
  snapshot: Snapshot;
  finalObjective: { value: number | null; termination: string } | null;
  onOpenArtifact: (tab: string, key: string) => void;
}) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const job = snapshot.job;
  const items = useMemo(() => collectItems(snapshot), [snapshot]);
  const attempts: Attempt[] = useMemo(() => {
    const collected: Attempt[] = [];
    for (const name of Object.keys(snapshot.contents || {}))
      if (/(?:^|\/)llm-trace\.json$/.test(name))
        collected.push(...((snapshot.contents[name]?.attempts || []) as Attempt[]));
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
  const scrollToDecision = () =>
    document.getElementById("decision")?.scrollIntoView({ behavior: "smooth", block: "start" });
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
      <div className="story-consumption" aria-live="polite">
        <span className="pill">模型请求 {format(consumption.requests)}</span>
        <span className="pill">Token {consumption.tokens == null ? "未知" : format(consumption.tokens)}</span>
        {consumption.solves != null ? (
          <span className="pill muted">求解 {format(consumption.solves)} 次</span>
        ) : null}
      </div>
      <div id="method-timeline" className={items.length ? undefined : "story-empty"}>
        {!items.length ? (
          <p className="hint">{job.status === "queued" ? "正在等待执行…" : "正在读取问题与检查配置…"}</p>
        ) : null}
        {items.map((item) => {
          const failedStep = item.status === "running" && failed;
          const className = "timeline-step story-card " + (failedStep ? "failed" : item.status);
          const comments = commentsFor(snapshot, item.actor);
          // 步骤时间戳与调用计时来自同一进程时钟;±秒级余量吸收事件与
          // trace 的写入顺序差,不用于精确归因,只用于展示摘要。
          const matched = attempts.filter(
            (attempt) =>
              item.start != null &&
              item.end != null &&
              attempt.start != null &&
              attempt.end != null &&
              attempt.start >= item.start - 1 &&
              attempt.end <= item.end + 5,
          );
          const jumpKey = item.artifact || item.linkedArtifact;
          const preview = statePreview(snapshot, item.artifact);
          const feedback = assessmentFeedback(snapshot, item);
          // 里程碑化:只有带真实建模输出(保存的产物、中间状态、检查反馈、
          // 角色发言、时间窗内的模型调用)或正在发生(进行中/待补充)的
          // 步骤才成为卡片;纯事件标记不单独成卡,避免展开为空。
          const expandable =
            !!preview || !!feedback || comments.length > 0 || matched.length > 0;
          const hasOutput = expandable || !!jumpKey || item.milestone;
          const inFlight = item.status === "running" || item.status === "needs_input";
          if (!hasOutput && !inFlight) return null;
          const isOpen = expandable && (expanded[item.id] || item.status === "running");
          return (
            <article
              key={item.id}
              className={className}
              role="button"
              tabIndex={0}
              data-artifact={item.artifact || undefined}
              onClick={() => {
                if (jumpKey) onOpenArtifact(item.artifactTab, jumpKey);
                if (expandable) setExpanded((prior) => ({ ...prior, [item.id]: !isOpen }));
              }}
              onKeyDown={(event) => {
                if (event.key !== "Enter" && event.key !== " ") return;
                event.preventDefault();
                if (jumpKey) onOpenArtifact(item.artifactTab, jumpKey);
                if (expandable) setExpanded((prior) => ({ ...prior, [item.id]: !isOpen }));
              }}
            >
              <header className="story-head">
                <span className="step-marker">
                  {item.status === "completed" ? "✓" : failedStep ? "!" : item.status === "needs_input" ? "?" : ""}
                </span>
                <div className="step-content">
                  <strong>{roleLabel(item.label)}</strong>
                  <span>
                    {phaseLabel(item.phase)}
                    {item.end && item.start ? " · " + format(item.end - item.start) + " s" : ""}
                    {item.actor && item.actor !== "direct" ? " · " + roleLabel(item.actor) : ""}
                  </span>
                </div>
                {jumpKey ? (
                  <button
                    type="button"
                    className="secondary story-artifact-button"
                    onClick={(event) => {
                      event.stopPropagation();
                      onOpenArtifact(item.artifactTab, jumpKey);
                    }}
                  >
                    {artifactLabel(jumpKey)}
                  </button>
                ) : null}
              </header>
              {isOpen ? (
                <div className="story-body" onClick={(event) => event.stopPropagation()}>
                  {preview ? (
                    <div className="story-summary">
                      {preview.description ? <p className="problem-text">{preview.description}</p> : null}
                      {preview.objective ? (
                        <p className="hint">目标:{preview.objective}</p>
                      ) : null}
                      {preview.constraints ? (
                        <p className="hint">已识别约束 {preview.constraints} 条</p>
                      ) : null}
                      {preview.codeLines.length ? (
                        <pre className="story-code">
                          {preview.codeLines.join("\n")}
                          {preview.codeLines.length >= 8 ? "\n…" : ""}
                        </pre>
                      ) : null}
                    </div>
                  ) : null}
                  {comments.length ? (
                    <div className="story-comments">
                      {comments.map((comment) => (
                        <details key={comment.name}>
                          <summary>{comment.name.split("/").at(-1)}</summary>
                          <pre>{comment.text}</pre>
                        </details>
                      ))}
                    </div>
                  ) : null}
                  {feedback ? (
                    <div className="story-summary">
                      {feedback.stages.length ? (
                        <p className="hint">已通过检查的阶段:{feedback.stages.join("、")}</p>
                      ) : (
                        <p className="hint">该候选尚无通过记录的阶段。</p>
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
                  {matched.length ? (
                    <div className="story-attempts">
                      {matched.map((attempt, index) => (
                        <span className="pill muted" key={index}>
                          {roleLabel(attempt.role || "模型调用")} ·{" "}
                          {attempt.start != null && attempt.end != null
                            ? format(attempt.end - attempt.start) + " s"
                            : ""}{" "}
                          ·{" "}
                          {attempt.usage?.total_tokens == null
                            ? "Token 未知"
                            : "Token " + format(attempt.usage.total_tokens)}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {item.status === "running" && !expandable ? (
                    <p className="hint">
                      {failedStep
                        ? "运行未完成:该步骤进行中被中断;原因见结束卡与诊断。"
                        : "该步正在进行;输出与消耗会在完成后记录在这里。"}
                    </p>
                  ) : null}
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
              {finished ? null : (
                <details className="failure-detail">
                  <summary>技术详情:错误码与原始记录</summary>
                  <pre>{pretty({ code: runError?.code, message: runError?.message, connection_diagnostic: connection?.connection_diagnostic ?? null })}</pre>
                </details>
              )}
              <button type="button" className="secondary" onClick={scrollToDecision}>
                {finished ? "查看最终结果 ↓" : "查看诊断与恢复选项 ↓"}
              </button>
            </div>
          </article>
        ) : null}
      </div>
    </>
  );
}
