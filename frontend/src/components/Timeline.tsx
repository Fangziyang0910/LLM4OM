// 方法过程时间线:步骤卡片、阶段/耗时、角色输出与产物直达。
import { useState } from "react";
import type { Snapshot } from "../types";
import { artifactKey, artifactLabel, format, phaseLabel, roleLabel, shortMethod, status } from "../ui";

interface TimelineItem {
  sequence?: number;
  label: string;
  actor?: string;
  phase: string;
  status: string;
  start?: number;
  end?: number;
  artifact?: string;
}

export function Timeline({
  snapshot,
  onOpenArtifact,
  onShowStepOutput,
}: {
  snapshot: Snapshot;
  onOpenArtifact: (tab: string, key: string) => void;
  onShowStepOutput: (output: { actor: string; comments: { name: string; text: string }[] } | null) => void;
}) {
  const [expanded, setExpanded] = useState<string | null>(null);
  const events = snapshot.events || [];
  const job = snapshot.job;
  const items = new Map<string, TimelineItem>();
  for (const event of events) {
    const step = event.method_event;
    if (step?.type === "modeling_step") {
      const prior = items.get(step.step_id);
      items.set(step.step_id, {
        ...prior,
        ...step,
        sequence: prior?.sequence || event.sequence_no,
        start: prior?.start || step.timestamp,
        end: step.status === "completed" ? step.timestamp : undefined,
      });
    }
    if (step?.artifact_ref?.namespace === "run_public") {
      const name = artifactKey(snapshot, step.artifact_ref);
      if (name) {
        items.set("artifact-" + event.sequence_no, {
          sequence: event.sequence_no,
          label: artifactLabel(name),
          phase: step.stage || "formulation",
          status: "completed",
          actor: "已保存的公开产物",
          artifact: name,
        });
      }
    }
  }
  if (!events.some((event) => event.method_event?.type === "modeling_step")) {
    const calls =
      snapshot.contents?.["method/calls.json"]?.calls ||
      snapshot.contents?.["method/source-calls.json"]?.calls ||
      [];
    calls.forEach((call: any, index: number) =>
      items.set("call-" + index, {
        label: roleLabel(call.role),
        actor: call.role,
        phase: /conductor|reducer/.test(call.role)
          ? "coordination"
          : /code|Programming|Reviewer/.test(call.role)
            ? "code"
            : "formulation",
        status: "completed",
      }),
    );
    const labels: Record<string, string> = {
      run_started: "读取问题与数据",
      formulation_saved: "数学表述已生成",
      code_saved: "求解实现已保存",
      solver_started: "调用求解器",
      solver_finished: "求解完成",
      code_output_saved: "原生代码已生成",
      method_execution_finished: "执行候选代码",
    };
    for (const event of events) {
      if (labels[event.kind])
        items.set("event-" + event.sequence_no, {
          sequence: event.sequence_no,
          label: labels[event.kind],
          status:
            event.kind.endsWith("started") && job.status === "running" ? "running" : "completed",
          phase: event.kind.startsWith("solver")
            ? "solve"
            : event.kind.startsWith("code") || event.kind.startsWith("method_execution")
              ? "code"
              : "formulation",
        });
    }
  } else
    for (const event of events) {
      if (["code_saved", "solver_started", "solver_finished", "method_execution_finished"].includes(event.kind))
        items.set("core-" + event.sequence_no, {
          sequence: event.sequence_no,
          label: {
            code_saved: "生成的代码已保存",
            solver_started: "调用求解器",
            solver_finished: "求解结果已保存",
            method_execution_finished: "执行候选代码",
          }[event.kind] || event.kind,
          status:
            event.kind === "solver_started" &&
            !events.some((e) => e.kind === "solver_finished") &&
            job.status === "running"
              ? "running"
              : "completed",
          phase: event.kind.startsWith("solver") ? "solve" : "code",
        });
    }
  const listed = Array.from(items).sort((a, b) => (a[1].sequence || 0) - (b[1].sequence || 0));
  const open = (item: TimelineItem, id: string) => {
    const tab =
      item.phase === "code" ? "code" : item.phase === "formulation" ? "formulation" : "diagnostics";
    onOpenArtifact(tab, item.artifact || "");
    setExpanded((prior) => {
      const next = prior === id ? null : id;
      if (next) {
        const comments = Object.entries(snapshot.contents || {}).flatMap(([name, value]: [string, any]) =>
          Array.isArray(value?.comments)
            ? value.comments
                .filter(
                  (comment: unknown[]) =>
                    Array.isArray(comment) && comment[0] === item.actor && typeof comment[1] === "string",
                )
                .map((comment: unknown[]) => ({ name, text: comment[1] as string }))
            : [],
        );
        onShowStepOutput(comments.length ? { actor: item.actor || "", comments } : null);
      } else onShowStepOutput(null);
      return next;
    });
  };
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
          " · " +
          (job.status === "running" ? "正在执行方法步骤" : "已保存 " + items.size + " 个过程记录")}
      </p>
      <div id="method-timeline">
        {!items.size ? (
          <p className="hint">{job.status === "queued" ? "正在等待执行…" : "正在读取问题与检查配置…"}</p>
        ) : null}
        {listed.map(([id, item]) => {
          const failed = item.status === "running" && ["failed", "cancelled"].includes(job.status);
          const className = "timeline-step " + (failed ? "failed" : item.status);
          return (
            <button key={id} type="button" className={className} onClick={() => open(item, id)}>
              <span className="step-marker">
                {item.status === "completed" ? "✓" : failed ? "!" : ""}
              </span>
              <div className="step-content">
                <strong>{roleLabel(item.label)}</strong>
                <span>
                  {phaseLabel(item.phase)}
                  {item.end && item.start ? " · " + format(item.end - item.start) + " s" : ""}
                </span>
                {expanded === id ? <small className="step-detail">{item.actor || "应用流程"}</small> : null}
              </div>
            </button>
          );
        })}
      </div>
    </>
  );
}
