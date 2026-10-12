// 候选与修正视图:候选状态、阶段、求解结果、变化与最终选择理由。
import type { Snapshot } from "../types";
import { artifactKey, format, status } from "../ui";
import { EmptyView, Table } from "./Records";

export function Candidates({
  snapshot,
  onOpenArtifact,
}: {
  snapshot: Snapshot;
  onOpenArtifact: (tab: string, key: string) => void;
}) {
  const contents = snapshot?.contents || {};
  const get = (reference: any) => contents[artifactKey(snapshot, reference) || ""];
  const selection = contents["candidate-selection.json"];
  const selectedId = snapshot?.bundle?.final_candidate_id || selection?.candidate_id;
  const records = new Map<string, any>();
  for (const [name, item] of Object.entries(contents)) {
    if (!/^candidates\/[^/]+\/candidate(?:-snapshot)?\.json$/.test(name) || !item?.candidate_id)
      continue;
    if (name.endsWith("/candidate.json") || !records.has(item.candidate_id))
      records.set(item.candidate_id, item);
  }
  if (!records.size)
    return (
      <EmptyView
        title="候选方案正在形成"
        text="方法保存候选后，可在这里查看模型、修正关系与实际求解结果。"
      />
    );
  return (
    <>
      {selectedId ? (
        <section className="model-card candidate-selection">
          <h3>最终选择 · 候选 {selectedId}</h3>
          <p>{selection?.reason || "该方法未单独保存选择理由。"}</p>
          {selection?.rule ? <span className="hint">选择规则：{selection.rule}</span> : null}
        </section>
      ) : null}
      {[...records.values()]
        .sort((a, b) => a.sequence_no - b.sequence_no)
        .map((candidate) => {
          const assessment = contents[`candidates/${candidate.candidate_id}/assessment.json`];
          const model = get(candidate.artifact_ref);
          const codeArtifact = get(model?.code_ref);
          const solve = get(
            assessment?.solve_result_ref ||
              (candidate.candidate_id === selectedId ? snapshot.bundle?.solve_result_ref : null),
          );
          const changes = get(assessment?.formulation_changes_ref);
          const names = {
            sets: "集合",
            parameters: "参数",
            variables: "变量",
            objective: "目标",
            constraints: "约束",
            assumptions: "假设",
            problem_type: "问题类型",
          } as Record<string, string>;
          return (
            <section
              key={candidate.candidate_id}
              className={
                "model-card candidate-card" +
                (candidate.candidate_id === selectedId ? " final-candidate" : "")
              }
              data-candidate-id={candidate.candidate_id}
            >
              <h3>候选 {candidate.candidate_id}</h3>
              <div className="result-tags">
                <span className="pill">{status(candidate.status)}</span>
                {candidate.parent_ids?.length ? (
                  <span className="pill muted">修正自 {candidate.parent_ids.join("、")}</span>
                ) : null}
              </div>
              <p className="candidate-reason">{candidate.change_reason || "初始候选"}</p>
              <div className="candidate-stages">
                {(
                  [
                    ["formulation", "数学表述"],
                    ["code", "求解实现"],
                    ["solve", "求解"],
                  ] as [string, string][]
                ).map(([phase, title]) => {
                  const state =
                    assessment?.stages?.[phase] ||
                    (phase === "solve" && solve ? { status: "available" } : model?.stage_status?.[phase]);
                  return (
                    <div key={phase}>
                      <span>{title}</span>
                      <strong>{state ? status(state.status) : "未记录"}</strong>
                    </div>
                  );
                })}
              </div>
              {solve ? (
                <div className="candidate-result">
                  <span>{status(solve.termination)}</span>
                  <strong>候选目标 {format(solve.objective_value)}</strong>
                </div>
              ) : null}
              {(assessment?.diagnostics || []).map((diagnostic: any, index: number) => (
                <p className="candidate-diagnostic" key={index}>
                  {diagnostic.message || diagnostic.code}
                </p>
              ))}
              {changes ? (
                <details className="candidate-changes">
                  <summary>查看与上一候选的变化</summary>
                  <Table
                    rows={[
                      [
                        "表述变化",
                        (changes.changed_sections || []).map((key: string) => names[key] || key).join("、") || "未记录变化",
                      ],
                      [
                        "IR变化",
                        (changes.ir_changed_sections || []).map((key: string) => names[key] || key).join("、") || "未记录变化",
                      ],
                      ["增加约束", (changes.constraint_ids_added || []).join("、") || "无"],
                      ["删除约束", (changes.constraint_ids_removed || []).join("、") || "无"],
                      ["丢失需求关联", (changes.requirements_lost || []).join("、") || "无"],
                    ]}
                    fields={[
                      ["项目", (row) => row[0]],
                      ["内容", (row) => row[1]],
                    ]}
                  />
                  <p className="hint">
                    {changes.source_formulation_available
                      ? "这是已声明输出的比较，不构成语义正确性证明。"
                      : "上一候选没有可比较的完整表述；这里保留实际比较记录。"}
                  </p>
                </details>
              ) : null}
              <div className="actions">
                {(
                  [
                    ["查看数学模型", "formulation", model?.formulation_ref],
                    ["查看求解代码", "code", codeArtifact?.representation_ref],
                  ] as [string, string, any][]
                ).map(([label, tab, reference]) => {
                  const key = artifactKey(snapshot, reference);
                  if (!key) return null;
                  return (
                    <button key={label} className="secondary" onClick={() => onOpenArtifact(tab, key)}>
                      {label}
                    </button>
                  );
                })}
              </div>
            </section>
          );
        })}
      <p className="hint">各目标值属于各自的候选模型。候选之间可能改变目标或约束，不自动按目标值排名。</p>
    </>
  );
}

export function Connectivity({ report }: { report: any }) {
  const labels: Record<string, string> = {
    reachable: "接口可达",
    failed: "检查未通过",
    not_supported: "不支持目录检查",
    not_checked: "未执行",
    not_applicable: "无需网络检查",
  };
  const result = report.connectivity_checks;
  return (
    <>
      <strong>配置与兼容性检查通过</strong>
      {result.status === "not_requested" ? (
        <p className="hint">未请求网络检查。勾选上方选项后可读取模型目录。</p>
      ) : (
        (result.checks || []).map((item: any, index: number) => (
          <div className="connectivity-row" key={index}>
            <span>
              {(item.role === "default" ? "默认模型" : item.role) + " · " + (item.model || "")}
            </span>
            <strong>{labels[item.status] || item.status}</strong>
            {item.model_listed != null ? (
              <small>{item.model_listed ? "该页目录包含此模型" : "该页目录未列出此模型"}</small>
            ) : null}
            {item.http_status ? <small>HTTP {item.http_status}</small> : null}
          </div>
        ))
      )}
      <p className="hint">
        只读取目录，不发起文本生成。目录可能分页或使用别名；生成能力以实际运行结果为准。
      </p>
    </>
  );
}
