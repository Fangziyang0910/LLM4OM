// 决策面板:失败诊断、进行中提示、求解结果、决策探索与独立检查。
import { useState } from "react";
import type { Snapshot } from "../types";
import { activeStep, failureDiagnosis, format, roleLabel, senseKey, senseOperator, shortMethod, status } from "../ui";

function Failure({ snapshot, onOpenDiagnostics }: { snapshot: Snapshot; onOpenDiagnostics: () => void }) {
  const error = snapshot?.job?.error || snapshot?.bundle?.error;
  if (!error) return null;
  const connection = snapshot.contents?.["llm-trace.json"]?.attempts
    ?.filter((item: any) => item.diagnostic === error.code && item.connection_diagnostic)
    .at(-1);
  const [title, detail] = failureDiagnosis(error.code, connection?.connection_diagnostic);
  return (
    <div className="failure-summary">
      <span className="eyebrow">运行需要处理</span>
      <h2>{title}</h2>
      <p className="hint">{detail}</p>
      <code className="failure-code">{error.code}</code>
      <details className="failure-detail">
        <summary>技术详情</summary>
        <dl className="failure-facts">
          <div>
            <dt>错误码</dt>
            <dd>{error.code}</dd>
          </div>
          {error.message ? (
            <div>
              <dt>错误信息</dt>
              <dd>{error.message}</dd>
            </div>
          ) : null}
          {connection?.connection_diagnostic ? (
            <div>
              <dt>连接诊断</dt>
              <dd>{connection.connection_diagnostic}</dd>
            </div>
          ) : null}
        </dl>
      </details>
      <button className="secondary" onClick={onOpenDiagnostics}>
        查看运行详情
      </button>
    </div>
  );
}

function LiveModeling({ snapshot }: { snapshot: Snapshot }) {
  const state = snapshot?.job?.status;
  const step = activeStep(snapshot);
  return (
    <div className={"live-modeling " + state} role="status" aria-live="polite">
      <div className="modeling-orbit" aria-hidden="true">
        ∑
      </div>
      <div className="modeling-copy">
        <span className="eyebrow">
          {shortMethod(snapshot.contents?.["public-config.json"]?.method?.plugin_id || snapshot.job.method)}
        </span>
        <h2>
          {state === "queued"
            ? "问题已提交，等待执行"
            : state === "needs_input"
              ? "等待你补充问题信息"
              : step
                ? roleLabel(step.label)
                : "正在准备建模"}
        </h2>
        {step && state === "running" ? (
          <div className="modeling-detail">
            <span className="pill">
              {
                {
                  formulation: "数学表述",
                  code: "求解实现",
                  solve: "数值求解",
                  coordination: "方法协作",
                }[step.phase as string]
              }
            </span>
            <span className="hint">{roleLabel(step.actor)}</span>
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Checks({ evaluation }: { evaluation: any }) {
  return (
    <section className="result-checks">
      <h3>模型检查</h3>
      {(
        [
          ["formulation_validation", "表述结构"],
          ["code_validation", "代码接口 / 构建"],
          ["independent_feasibility", "原问题可行性"],
          ["objective_match", "参考目标匹配"],
          ["semantic_validation", "业务语义证据"],
        ] as [string, string][]
      ).map(([key, label]) => {
        const result = evaluation?.[key];
        return (
          <div className="check-row" key={key} title={result?.reason || undefined}>
            <span>{label}</span>
            <span className={"pill " + (result?.status === "pass" ? "success" : "muted")}>
              {({ pass: "通过", fail: "未通过", error: "检查异常", not_available: "未提供" } as Record<string, string>)[
                result?.status
              ] || "未提供"}
            </span>
          </div>
        );
      })}
    </section>
  );
}

function DecisionExplorer({ ir, solution }: { ir: any; solution: any }) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(ir.variables.map((item: any) => [item.id, String(solution.variables[item.id])])),
  );
  const parsed = ir.variables.map((item: any) => Number(values[item.id]));
  const valid = ir.variables.every((item: any, index: number) => {
    const raw = values[item.id];
    const numeric = parsed[index];
    if (raw === "" || !Number.isFinite(numeric)) return false;
    if (item.lower_bound != null && numeric < item.lower_bound) return false;
    if (item.upper_bound != null && numeric > item.upper_bound) return false;
    if (item.domain === "binary" && (numeric < 0 || numeric > 1)) return false;
    return true;
  });
  const value = (expression: any) =>
    expression.constant +
    expression.terms.reduce(
      (sum: number, term: any) => sum + term.coefficient * Number(values[term.variable_id]),
      0,
    );
  return (
    <section className="model-card decision-explorer">
      <h3>目标与约束余量</h3>
      <p className="hint">只代入当前模型计算，不修改已保存结果。</p>
      <div className="explorer-output" aria-live="polite">
        {!valid ? (
          <p className="hint">请填写符合变量边界和类型的数值。</p>
        ) : (
          <>
            <div className="explorer-objective">
              <span>{ir.objective.sense === "max" ? "试算目标 · 最大化" : "试算目标 · 最小化"}</span>
              <strong>{format(value(ir.objective.expression))}</strong>
            </div>
            {(ir.constraints || []).map((item: any) => {
              const activity = value(item.expression);
              const key = senseKey(item.sense);
              const margin = key === "le" ? item.rhs - activity : activity - item.rhs;
              return (
                <div key={item.id} className={"explorer-constraint" + (key !== "eq" && margin < 0 ? " exceeded" : "")}>
                  <strong>{item.name || item.id}</strong>
                  <span>
                    {format(activity)} {senseOperator(item.sense)} {format(item.rhs)}
                  </span>
                  <span className="constraint-margin">
                    {key === "eq" ? "偏差" : "余量"} {format(margin)}
                  </span>
                  {key === "le" && item.rhs > 0 && activity >= 0 ? (
                    <meter
                      min={0}
                      max={item.rhs}
                      value={activity}
                      aria-label={`${item.name || item.id} ${format(activity)} / ${format(item.rhs)}`}
                    />
                  ) : null}
                </div>
              );
            })}
          </>
        )}
      </div>
      <details className="decision-controls">
        <summary>调整决策值 · 交互试算</summary>
        <div className="explorer-fields">
          {ir.variables.map((item: any) => (
            <label key={item.id}>
              {item.name || item.id}
              <input
                type="number"
                step={item.domain === "continuous" ? "any" : "1"}
                min={item.domain === "binary" ? Math.max(item.lower_bound ?? 0, 0) : item.lower_bound ?? undefined}
                max={item.domain === "binary" ? Math.min(item.upper_bound ?? 1, 1) : item.upper_bound ?? undefined}
                value={values[item.id]}
                data-decision-variable={item.id}
                onChange={(event) => setValues((prior) => ({ ...prior, [item.id]: event.target.value }))}
              />
            </label>
          ))}
        </div>
        <button className="secondary" type="button" onClick={() => setValues(Object.fromEntries(
          ir.variables.map((item: any) => [item.id, String(solution.variables[item.id])]),
        ))}>
          恢复求解结果
        </button>
      </details>
    </section>
  );
}

export function DecisionSummary({ solve, snapshot, onOpenDiagnostics }: {
  solve: any; snapshot: Snapshot; onOpenDiagnostics: () => void;
}) {
  const hasFailure = Boolean(snapshot.job.error || snapshot.bundle?.error);
  const failure = hasFailure ? <Failure snapshot={snapshot} onOpenDiagnostics={onOpenDiagnostics} /> : null;
  if (!solve) {
    if (failure) return failure;
    if (["queued", "running", "needs_input"].includes(snapshot.job.status)) return <LiveModeling snapshot={snapshot} />;
    return <p className="hint">本次运行尚无求解结果，可查看已生成的模型与代码。</p>;
  }
  return <>{failure}<div className="decision-hero">
    <div className="objective-result"><span>目标值</span><strong>{format(solve.objective_value)}</strong></div>
    <div className="solution-status">
      <span className="eyebrow">{solve.has_primal_solution ? "求解完成" : "求解状态"}</span>
      <h2>{status(solve.termination)}</h2>
      <span className="hint">{(solve.solver_id || "").split(".").at(-1).toUpperCase()}
        {snapshot.bundle?.assisted ? " · 人工辅助结果" : ""}</span>
    </div>
  </div></>;
}

export function Decision({
  solve,
  solution,
  snapshot,
  solvedIR,
  onOpenDiagnostics,
  showSummary = true,
}: {
  solve: any;
  solution: any;
  snapshot: Snapshot;
  solvedIR: any;
  onOpenDiagnostics: () => void;
  showSummary?: boolean;
}) {
  const [selectedRows, setSelectedRows] = useState<Record<string, boolean>>({});
  const summary = <DecisionSummary solve={solve} snapshot={snapshot} onOpenDiagnostics={onOpenDiagnostics} />;
  if (!solve) return showSummary ? summary : <p className="hint">求解结束后，决策值会显示在这里。</p>;
  const values: [string, any][] = Object.entries(solution?.variables || {});
  const variableNames = new Map(
    (solvedIR?.variables || []).map((item: any) => [item.id, item.name || item.id]),
  );
  const maximum = Math.max(...values.map(([, value]) => Math.abs(Number(value))), 1);
  const expression = solvedIR?.objective?.expression;
  const canInspect = solve.has_primal_solution && expression &&
    expression.terms.every((term: any) => Number.isFinite(solution?.variables?.[term.variable_id]));
  return (
    <>
      {showSummary ? summary : null}
      {values.length ? (
        <>
          <h3 className="decision-label">决策变量</h3>
          <div className="decision-bars">
            {values.map(([name, value]) => (
              <button
                key={name}
                type="button"
                className={"decision-row" + (selectedRows[name] ? " selected" : "")}
                aria-pressed={selectedRows[name] ? "true" : "false"}
                onClick={() => setSelectedRows((prior) => ({ ...prior, [name]: !prior[name] }))}
              >
                <span className="decision-name">
                  {String(variableNames.get(name) || name)}
                  {variableNames.get(name) && variableNames.get(name) !== name ? (
                    <small className="decision-id">{String(name)}</small>
                  ) : null}
                </span>
                <div className="bar-track">
                  <span
                    className={"bar-fill" + (Number(value) < 0 ? " negative" : "")}
                    style={{ width: (Math.abs(Number(value)) / maximum) * 100 + "%" }}
                  />
                </div>
                <strong>{format(Number(value))}</strong>
              </button>
            ))}
          </div>
        </>
      ) : <p className="hint">本次求解没有返回可用的决策变量值。</p>}
      {canInspect ? <details className="result-analysis"><summary>目标构成与交互试算</summary>
        <section className="model-card objective-breakdown">
          <h3>目标值如何构成</h3>
          <div className="contribution-grid">
            {expression.terms.map((term: any, index: number) => (
              <div className="contribution-item" key={index}>
                <span>{variableNames.get(term.variable_id) || term.variable_id}</span>
                <strong>{format(term.coefficient * solution.variables[term.variable_id])}</strong>
                <small className="hint">
                  {format(term.coefficient)} × {format(solution.variables[term.variable_id])}
                </small>
              </div>
            ))}
            {expression.constant !== 0 ? (
              <div className="contribution-item">
                <span>常数项</span>
                <strong>{format(expression.constant)}</strong>
              </div>
            ) : null}
          </div>
        </section>
      {solvedIR.variables?.length &&
      solvedIR.variables.every((item: any) => Number.isFinite(solution?.variables?.[item.id])) ? (
        <DecisionExplorer ir={solvedIR} solution={solution} />
      ) : null}
      </details> : null}
      {snapshot.contents["evaluation.json"] ? <details className="result-analysis"><summary>验证记录</summary>
        <Checks evaluation={snapshot.contents["evaluation.json"]} />
      </details> : null}
    </>
  );
}
