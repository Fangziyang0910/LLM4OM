// 运行详情:资源账本、求解与执行记录、模型调用与最近事件。
import type { Snapshot } from "../types";
import { artifactKey, format, roleLabel, status } from "../ui";
import { Card, Table } from "./Records";

export function RuntimeDetails({ snapshot }: { snapshot: Snapshot | null | undefined }) {
  const contents = snapshot?.contents || {};
  const ledger = contents["budget-ledger.json"] || {};
  const budget = contents["public-config.json"]?.budget || {};
  const shown = (value: unknown) => (value == null ? "未提供" : format(value));
  const solve = contents[artifactKey(snapshot, snapshot?.bundle?.solve_result_ref) || ""];
  const execution = contents[artifactKey(snapshot, snapshot?.bundle?.execution_result_ref) || ""];
  const attempts = new Map<string, any>();
  for (const [name, trace] of Object.entries(contents).sort(
    ([a], [b]) => Number(b === "llm-trace.json") - Number(a === "llm-trace.json"),
  )) {
    if (!/(?:^|\/)llm-trace\.json$/.test(name)) continue;
    (trace.attempts || []).forEach((item: any, index: number) => {
      const key = item.attempt_id || name + "#" + index;
      if (!attempts.has(key))
        attempts.set(key, {
          ...item,
          source: name.startsWith("parent/")
            ? "父版本 " + name.split("/")[1].slice(0, 8)
            : "当前版本",
        });
    });
  }
  const events = snapshot?.events || [];
  return (
    <>
      <Card title="资源使用" subtitle="累计资源来自保存的账本，可包含父版本消耗。" className="model-card runtime-card">
        <div className="runtime-metrics">
          {(
            [
              ["模型尝试", "llm_attempts", "max_llm_attempts"],
              ["外部模型请求", "external_llm_requests"],
              ["候选", "candidates", "max_candidates"],
              ["求解", "solver_calls", "max_solver_calls"],
            ] as [string, string, string?][]
          ).map(([label, key, limit]) => (
            <div className="metric" key={key}>
              <span>{label}</span>
              <strong>{shown(ledger[key])}</strong>
              {limit && budget[limit] != null ? <small>总上限 {format(budget[limit])}</small> : null}
            </div>
          ))}
        </div>
        <Table
          rows={[
            ["总Token", ledger.total_tokens == null ? "未知" : format(ledger.total_tokens)],
            ["已知Token", shown(ledger.known_total_tokens ?? ledger.total_tokens)],
            ["未知用量预留", shown(ledger.reserved_tokens)],
            ["Token总上限", shown(budget.max_total_tokens)],
            ["修正轮数", shown(ledger.repairs)],
            ["新运行时间上限（秒）", shown(budget.wall_time_s)],
            ["费用", shown(ledger.cost)],
          ]}
          fields={[
            ["项目", (row) => row[0]],
            ["记录", (row) => row[1]],
          ]}
        />
      </Card>
      {solve || execution ? (
        <Card
          title="最终候选的求解与执行"
          subtitle="耗时与资源按记录来源分别呈现；Gap保留求解器报告原值。"
          className="model-card runtime-card"
        >
          <Table
            rows={[
              ["求解器", solve?.solver_id || "未提供"],
              ["终止状态", solve ? status(solve.termination) : "未提供"],
              ["原始状态", solve?.raw_status || "未提供"],
              ["候选模型可行解", solve ? (solve.has_primal_solution ? "有" : "无") : "未提供"],
              ["目标值", shown(solve?.objective_value)],
              ["最优界", shown(solve?.best_bound)],
              ["报告 Gap", shown(solve?.reported_gap)],
              ["求解耗时（秒）", shown(solve?.solve_time_s)],
              ["执行耗时（秒）", shown(execution?.wall_time_s)],
              ["CPU时间（秒）", shown(execution?.resources?.cpu_time_s)],
              [
                "峰值内存（MiB）",
                execution?.resources?.peak_memory_bytes == null
                  ? "未提供"
                  : format(execution.resources.peak_memory_bytes / 1048576),
              ],
            ]}
            fields={[
              ["项目", (row) => row[0]],
              ["记录", (row) => row[1]],
            ]}
          />
        </Card>
      ) : null}
      {attempts.size ? (
        <Card
          title="已保存的模型调用"
          subtitle="未知 Token 与费用不记为零。"
          className="model-card runtime-card"
        >
          <Table
            rows={[...attempts.values()]}
            fields={[
              ["来源", (item) => item.source],
              ["角色", (item) => roleLabel(item.role || "模型调用")],
              ["模型", (item) => item.model || item.requested_model || "未提供"],
              [
                "状态",
                (item) =>
                  ({ success: "成功", response_unknown: "响应未确认" } as Record<string, string>)[item.status] ||
                    status(item.status),
              ],
              [
                "耗时（秒）",
                (item) =>
                  item.start != null && item.end != null ? format(item.end - item.start) : "未提供",
              ],
              [
                "Token",
                (item) => (item.usage?.total_tokens == null ? "未知" : format(item.usage.total_tokens)),
              ],
              ["预留", (item) => shown(item.reservation)],
            ]}
          />
        </Card>
      ) : null}
      {events.length ? (
        <details className="model-card runtime-card">
          <summary>查看最近运行事件</summary>
          <Table
            rows={events.slice(-30)}
            fields={[
              ["顺序", (item) => String(item.sequence_no)],
              ["事件", (item) => item.kind],
              ["状态", (item) => status(item.status || item.method_event?.status)],
            ]}
          />
        </details>
      ) : null}
    </>
  );
}
