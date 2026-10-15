// 阶段产物修正历史:同一阶段的每个不同产物按公开检查顺序列出,带父检查、改动理由与最终选择标记。
import type { ArtifactRef, CheckRecord, CheckResult, CodeArtifact, FormulationChanges, ModelArtifact, Snapshot } from "../types";
import { artifactKey } from "../ui";

const sectionNames: Record<string, string> = {
  sets: "集合", parameters: "参数", variables: "变量", objective: "目标", constraints: "约束",
};

export function checkRecords(snapshot: Snapshot): CheckRecord[] {
  const records = new Map<string, CheckRecord>();
  for (const [name, value] of Object.entries(snapshot.contents || {})) {
    const item = value as CheckRecord | undefined;
    if (!/^checks\/[^/]+\/record(?:-snapshot)?\.json$/.test(name) || !item?.check_id) continue;
    if (name.endsWith("/record.json") || !records.has(item.check_id)) records.set(item.check_id, item);
  }
  return [...records.values()].sort((a, b) => a.sequence_no - b.sequence_no);
}

export function StageHistory({ snapshot, stage, current, onOpen }: {
  snapshot: Snapshot;
  stage: "formulation" | "code";
  current: string;
  onOpen: (key: string) => void;
}) {
  const contents = snapshot.contents || {};
  const get = <T,>(reference: ArtifactRef | null | undefined) => contents[artifactKey(snapshot, reference) || ""] as T | undefined;
  const records = checkRecords(snapshot);
  const selected = snapshot.bundle?.selected_check_id || contents["selection.json"]?.check_id;
  const versions: { key: string; record: CheckRecord; checks: string[] }[] = [];
  for (const record of records) {
    const model = get<ModelArtifact>(record.artifact_ref);
    const reference = stage === "formulation" ? model?.formulation_ref : get<CodeArtifact>(model?.code_ref)?.representation_ref;
    const key = artifactKey(snapshot, reference);
    if (!key) continue;
    const prior = versions.find((version) => version.key === key);
    if (prior) prior.checks.push(record.check_id);
    else versions.push({ key, record, checks: [record.check_id] });
  }
  const produced = versions.reduce((sum, version) => sum + version.checks.length, 0);
  if (produced < 2) return null;
  const finalKey = versions.find((version) => selected && version.checks.includes(selected))?.key;
  return (
    <section className="model-card stage-history">
      <h3>{stage === "formulation" ? "数学表述" : "求解代码"}修正历史</h3>
      {versions.length < 2 ? (
        <p className="hint">{produced} 次公开检查都使用同一份{stage === "formulation" ? "数学表述，修正只改了代码" : "求解代码"}。</p>
      ) : (
        <ol>
          {versions.map((version, index) => {
            const check = contents[`checks/${version.record.check_id}/check.json`] as CheckResult | undefined;
            const changes = stage === "formulation" ? get<FormulationChanges>(check?.formulation_changes_ref) : undefined;
            return (
              <li key={version.key}>
                <button
                  type="button"
                  className={"secondary" + (version.key === current ? " active" : "")}
                  aria-pressed={version.key === current}
                  onClick={() => onOpen(version.key)}
                >
                  第 {index + 1} 版 · 检查 {version.checks.join("、")}
                  {version.key === finalKey ? " · 最终选择" : ""}
                </button>
                <span className="hint">
                  {version.record.parent_ids?.length
                    ? `修正自检查 ${version.record.parent_ids.join("、")}：${version.record.change_reason || "未记录理由"}`
                    : "初始生成"}
                  {changes?.changed_sections?.length
                    ? ` · 变化：${changes.changed_sections.map((key) => sectionNames[key] || key).join("、")}`
                    : ""}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
