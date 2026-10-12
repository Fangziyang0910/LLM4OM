// 决策面板:失败诊断、进行中提示、求解结果、决策探索与独立检查。
import { useState } from "react";
import type { Snapshot } from "../types";
import { activeStep, format, roleLabel, shortMethod, status } from "../ui";

function Failure({ snapshot, onOpenDiagnostics }: { snapshot: Snapshot; onOpenDiagnostics: () => void }) {
  const error = snapshot?.job?.error || snapshot?.bundle?.error;
  if (!error) return null;
  const advice: Record<string, [string, string]> = {
    provider_timeout: ["模型服务响应超时", "检查模型服务状态与请求时限，再决定是否创建新运行。"],
    provider_connection_error: ["暂时无法连接模型服务", "检查服务地址和连接。已保存的记录会保留。"],
    auth_error: ["模型服务认证失败", "检查服务端配置的凭据。"],
    llm_output_truncated: ["模型输出未生成完整", "调整输出上限或简化问题后重新建模。"],
    budget_exhausted: ["本次运行已达到预算上限", "查看实际消耗，调整预算后创建新的运行。"],
    checkpoint_incompatible: [
      "保存记录与当前版本不兼容",
      "历史结果仍可查看。新的执行需要使用当前版本的配置。",
    ],
  };
  const connection = snapshot.contents?.["llm-trace.json"]?.attempts
    ?.filter((item: any) => item.diagnostic === error.code && item.connection_diagnostic)
    .at(-1);
  const diagnosis: Record<string, [string, string]> = {
    tls_interrupted: [
      "模型服务的 TLS 连接被中断",
      "检查服务或显式代理的连接路线。请求用量可能未知，原记录已保留。",
    ],
    tls_certificate: [
      "模型服务证书校验失败",
      "检查服务证书与本机可信证书配置，再创建新运行。",
    ],
    tls_error: ["模型服务的 TLS 连接失败", "检查服务和代理的 TLS 连接配置。"],
    dns_error: ["模型服务域名解析失败", "检查服务地址和使用路线的 DNS。"],
    connection_refused: [
      "模型服务连接被拒绝",
      "检查服务或代理是否正在监听配置的地址和端口。",
    ],
    connection_reset: [
      "模型服务连接被重置",
      "检查服务或显式代理的连接路线。请求用量可能未知。",
    ],
    timeout: advice.provider_timeout,
  };
  const [title, detail] =
    diagnosis[connection?.connection_diagnostic] ||
    advice[error.code] || ["这次建模未完成", "查看已保存的步骤和诊断，修改输入或配置后再执行。"];
  return (
    <div className="failure-summary">
      <span className="eyebrow">RUN NEEDS ATTENTION</span>
      <h2>{title}</h2>
      <p className="hint">{detail}</p>
      <code className="failure-code">{error.code}</code>
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
        <p className="hint">
          {state === "needs_input"
            ? "请完成下方问题，模型将依据你的回答继续。"
            : state === "queued"
              ? "开始执行后，这里会显示实际建模步骤。"
              : "正在执行所选方法。步骤与模型输出会自动更新。"}
        </p>
        {step && state === "running" ? (
          <div className="modeling-detail">
            <span className="pill">
              {
                {
                  formulation: "Formulation · 数学表述",
                  code: "Code · 求解实现",
                  solve: "Solve · 数值求解",
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
      <p className="hint">
        仅代入当前候选模型计算，不重新求解或修改已保存结果。约束余量为负表示超出该限制；等式显示左侧减右侧的偏差。
      </p>
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
              const margin = item.sense === "le" ? item.rhs - activity : activity - item.rhs;
              return (
                <div key={item.id} className={"explorer-constraint" + (item.sense !== "eq" && margin < 0 ? " exceeded" : "")}>
                  <strong>{item.name || item.id}</strong>
                  <span>
                    {format(activity)} {({ le: "≤", ge: "≥", eq: "=" } as Record<string, string>)[item.sense]} {format(item.rhs)}
                  </span>
                  <span className="constraint-margin">
                    {item.sense === "eq" ? "偏差" : "余量"} {format(margin)}
                  </span>
                  {item.sense === "le" && item.rhs > 0 && activity >= 0 ? (
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

export function Decision({
  solve,
  solution,
  ledger,
  snapshot,
  solvedIR,
  onOpenDiagnostics,
}: {
  solve: any;
  solution: any;
  ledger: any;
  snapshot: Snapshot;
  solvedIR: any;
  onOpenDiagnostics: () => void;
}) {
  const [selectedRows, setSelectedRows] = useState<Record<string, boolean>>({});
  const hasFailure = Boolean(snapshot?.job?.error || snapshot?.bundle?.error);
  const failed = hasFailure ? <Failure snapshot={snapshot} onOpenDiagnostics={onOpenDiagnostics} /> : null;
  if (!solve) {
    const state = snapshot?.job?.status;
    if (hasFailure) return <>{failed}</>;
    if (["queued", "running", "needs_input"].includes(state)) return <LiveModeling snapshot={snapshot} />;
    return <div className="empty-view"><div className="empty-icon">◇</div><h3>求解结果将在这里出现</h3><p className="hint">建模进行时，可在左侧查看实际步骤。</p></div>;
  }
  const values: [string, any][] = Object.entries(solution?.variables || {});
  const variableNames = new Map(
    (solvedIR?.variables || []).map((item: any) => [item.id, item.name || item.id]),
  );
  const maximum = Math.max(...values.map(([, value]) => Math.abs(Number(value))), 1);
  const expression = solvedIR?.objective?.expression;
  return (
    <>
      {failed}
      <div className="decision-hero">
        <div>
          <span className="eyebrow">MODEL SOLUTION</span>
          <h2>{solve.has_primal_solution ? "候选模型求解完成" : status(solve.termination)}</h2>
        </div>
        <div className="objective-result">
          <span className="hint">目标值</span>
          <strong>{format(solve.objective_value)}</strong>
        </div>
      </div>
      <div className="result-tags">
        {snapshot?.bundle?.assisted ? <span className="pill muted">人工辅助结果</span> : null}
        <span className="pill success">{status(solve.termination)}</span>
        <span className="pill muted">{(solve.solver_id || "").split(".").at(-1)}</span>
        <span className="pill muted">Token {format(ledger?.total_tokens ?? ledger?.known_total_tokens)}</span>
        <span className="pill muted">
          {ledger?.cost == null ? "费用未提供" : "费用 " + format(ledger.cost)}
        </span>
      </div>
      {values.length ? (
        <>
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
          <p className="hint">柱长表示决策值的绝对大小；点击可选中比较，准确值显示在右侧。</p>
        </>
      ) : null}
      {solve.has_primal_solution &&
      expression &&
      expression.terms.every((term: any) => Number.isFinite(solution?.variables?.[term.variable_id])) ? (
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
          <p className="hint">各项来自已求解的目标函数；负数表示负贡献。</p>
        </section>
      ) : null}
      {solve.has_primal_solution &&
      solvedIR?.objective?.expression &&
      solvedIR.variables?.length &&
      solvedIR.variables.every((item: any) => Number.isFinite(solution?.variables?.[item.id])) ? (
        <DecisionExplorer ir={solvedIR} solution={solution} />
      ) : null}
      <Checks evaluation={snapshot?.contents?.["evaluation.json"]} />
      <p className="evidence-note">
        以上是当前候选模型的求解结果。原问题的独立验证以已保存的检查证据为准。
      </p>
    </>
  );
}
