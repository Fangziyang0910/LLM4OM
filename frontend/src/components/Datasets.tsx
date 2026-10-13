// 数据集浏览:列出已导入的冻结快照,逐条查看公开输入与结构化参考答案。
// 参考答案只在本地工作台呈现,不进入方法 Context、LLM 提示或公共导出;
// 界面一律结构化渲染,不展示原始 JSON。
import { useEffect, useState } from "react";
import { api } from "../api";
import { format } from "../ui";

const PAGE_SIZE = 100;

const adapterNames: Record<string, string> = {
  "llm4om.tasks.checker_fixture": "本地检查器",
  "llm4om.tasks.nl4opt": "NL4Opt",
  "llm4om.tasks.nlp4lp": "NLP4LP",
  "llm4om.tasks.mamo": "MAMO",
};

const referenceLabels: Record<string, string> = {
  schema_version: "结构版本",
  checker: "检查器",
  decision_mapping: "决策映射",
  reported_objective_mapping: "目标映射",
  reference_objective: "参考目标",
  probe_points: "探针点",
  variable_domains: "变量域",
  reference_quality: "参考质量",
  annotations: "标注",
  checker_id: "检查器标识",
  version: "版本",
  required_decisions: "必需决策",
  public_data_ids: "公开数据",
  quality: "质量",
  source: "来源",
  sense: "方向",
  value: "数值",
  abs_tol: "绝对容差",
  rel_tol: "相对容差",
};

const qualityLabels: Record<string, string> = {
  proven_optimum: "已证最优",
  claimed_optimum: "声明最优",
  feasible: "可行解",
  incomplete_declarations: "声明不完整",
};

const labelOf = (key: string) => referenceLabels[key] || key;
const isScalar = (value: unknown) =>
  value == null || ["string", "number", "boolean"].includes(typeof value);

function GenericTable({ value }: { value: Record<string, unknown> }) {
  return (
    <table className="visual-table reference-table">
      <tbody>
        {Object.entries(value || {}).map(([key, entry]) => (
          <tr key={key}>
            <td className="reference-key">{labelOf(key)}</td>
            <td>
              {isScalar(entry) ? (
                entry == null || entry === "" ? (
                  "—"
                ) : (
                  String(entry)
                )
              ) : Array.isArray(entry) ? (
                entry.every(isScalar) ? (
                  entry.length ? entry.map(String).join("、") : "—"
                ) : (
                  entry.map((row, index) => (
                    <div className="reference-item" key={index}>
                      {row && typeof row === "object" ? (
                        <GenericTable value={row as Record<string, unknown>} />
                      ) : (
                        String(row)
                      )}
                    </div>
                  ))
                )
              ) : (
                <GenericTable value={entry as Record<string, unknown>} />
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ReferenceView({ value }: { value: Record<string, unknown> }) {
  const objective = value?.reference_objective as Record<string, unknown> | undefined;
  const rest = { ...value };
  delete rest.reference_objective;
  return (
    <>
      {objective ? (
        <p className="reference-objective">
          参考目标值{" "}
          <strong>{format(objective.value as number)}</strong>
          {objective.sense === "max" ? " · 最大化" : objective.sense === "min" ? " · 最小化" : ""}
          {objective.quality
            ? " · " + (qualityLabels[String(objective.quality)] || String(objective.quality))
            : ""}
        </p>
      ) : null}
      <GenericTable value={rest} />
    </>
  );
}

function DatasetCase({ value }: { value: any }) {
  const problem = value?.problem || {};
  return (
    <div id="dataset-case" className="dataset-case">
      <section className="model-card">
        <h3>问题描述</h3>
        <p className="problem-text">{problem.description || "该条目没有保存问题描述。"}</p>
        {problem.requirements?.length ? (
          <table className="visual-table">
            <thead>
              <tr>
                <th>输入规则</th>
                <th>内容</th>
              </tr>
            </thead>
            <tbody>
              {problem.requirements.map((row: any) => (
                <tr key={row.id}>
                  <td>{row.id}</td>
                  <td>{row.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {problem.assumptions?.length ? (
          <table className="visual-table">
            <thead>
              <tr>
                <th>输入假设</th>
                <th>内容</th>
              </tr>
            </thead>
            <tbody>
              {problem.assumptions.map((row: any) => (
                <tr key={row.id}>
                  <td>{row.id}</td>
                  <td>{row.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
        {problem.data_refs?.length ? (
          <p className="hint">
            绑定数据:{problem.data_refs.map((row: any) => `${row.data_id}(${row.format})`).join("、")}
          </p>
        ) : null}
      </section>
      <section className="model-card">
        <h3>参考答案</h3>
        {value?.reference ? (
          <ReferenceView value={value.reference} />
        ) : (
          <p className="hint">
            {value?.error ? "参考答案读取失败,该条记录可能已被改动。" : "该条目未保存参考答案。"}
          </p>
        )}
      </section>
    </div>
  );
}

function DatasetDetail({ taskId, onBack }: { taskId: string; onBack: () => void }) {
  const [page, setPage] = useState(0);
  const [detail, setDetail] = useState<any>(null);
  const [caseId, setCaseId] = useState<string | null>(null);
  useEffect(() => {
    setCaseId(null);
  }, [page]);
  useEffect(() => {
    let alive = true;
    setDetail(null);
    api(`/api/datasets/${taskId}?offset=${page * PAGE_SIZE}&limit=${PAGE_SIZE}`)
      .then((result) => {
        if (alive) setDetail(result);
      })
      .catch(() => {
        if (alive) setDetail({ error: true });
      });
    return () => {
      alive = false;
    };
  }, [taskId, page]);
  const openRow = (id: string) => setCaseId((prior) => (prior === id ? null : id));
  const rowEvents = (id: string) => ({
    onClick: () => openRow(id),
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      openRow(id);
    },
  });
  if (detail?.error)
    return (
      <section id="dataset-detail" className="panel">
        <p className="hint">数据集读取失败,请刷新重试。</p>
      </section>
    );
  if (!detail)
    return (
      <section id="dataset-detail" className="panel">
        <p className="hint">正在读取数据集…</p>
      </section>
    );
  const header = detail.dataset;
  const active = detail.cases.find((item: any) => item.case_id === caseId) || null;
  const lastPage = Math.max(0, Math.ceil(detail.total / PAGE_SIZE) - 1);
  return (
    <section id="dataset-detail" className="panel">
      <div className="panel-title">
        <h3>
          {header.dataset_id} · {header.source_version}
        </h3>
        <span className="pill">{adapterNames[header.adapter_id] || header.adapter_id}</span>
      </div>
      <p className="hint">
        {`共 ${format(detail.total)} 条 · 已选 ${format(header.N_selected ?? 0)} 条 · 协议 ${header.protocol_id}`}
      </p>
      <button id="back-to-datasets" className="secondary" onClick={onBack}>
        ← 返回数据集列表
      </button>
      <table className="visual-table">
        <thead>
          <tr>
            <th>条目</th>
            <th>样本</th>
            <th>已选</th>
            <th>可评</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody>
          {detail.cases.map((item: any) => (
            <tr
              key={item.case_id}
              className={"dataset-row" + (item.case_id === caseId ? " selected" : "")}
              tabIndex={0}
              {...rowEvents(item.case_id)}
            >
              <td>{item.case_id}</td>
              <td>{item.sample_id}</td>
              <td>{item.selected ? "✓" : "—"}</td>
              <td>{item.eligible ? "✓" : "—"}</td>
              <td>{item.error || item.exclusion_reason || item.reference_quality || item.checker_availability || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {detail.total > PAGE_SIZE ? (
        <div className="dataset-pager">
          <button
            type="button"
            className="secondary"
            disabled={page <= 0}
            onClick={() => setPage((prior) => Math.max(0, prior - 1))}
          >
            ← 上一页
          </button>
          <span className="hint">{`第 ${page + 1} / ${lastPage + 1} 页 · 共 ${format(detail.total)} 条`}</span>
          <button
            type="button"
            className="secondary"
            disabled={page >= lastPage}
            onClick={() => setPage((prior) => prior + 1)}
          >
            下一页 →
          </button>
        </div>
      ) : null}
      {active ? <DatasetCase value={active} /> : null}
    </section>
  );
}

export function Datasets({
  datasets,
  refresh,
}: {
  datasets: any[];
  refresh: () => Promise<void>;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const openDataset = (id: string) => setOpenId(id);
  if (openId) return <DatasetDetail taskId={openId} onBack={() => setOpenId(null)} />;
  return (
    <section id="datasets" className="panel">
      <div className="panel-title">
        <h3>已导入数据集</h3>
        <button
          type="button"
          className="secondary"
          onClick={() => {
            refresh().catch(() => {});
          }}
        >
          刷新
        </button>
      </div>
      {datasets.length ? (
        <table className="visual-table">
          <thead>
            <tr>
              <th>数据集</th>
              <th>版本</th>
              <th>适配器</th>
              <th>样本</th>
              <th>已选</th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((item) => (
              <tr
                key={item.task_id}
                className="dataset-row"
                tabIndex={0}
                onClick={() => openDataset(item.task_id)}
                onKeyDown={(event) => {
                  if (event.key !== "Enter" && event.key !== " ") return;
                  event.preventDefault();
                  openDataset(item.task_id);
                }}
              >
                <td>{item.dataset_id}</td>
                <td>{item.source_version}</td>
                <td>{adapterNames[item.adapter_id] || item.adapter_id}</td>
                <td>{format(item.N_cases)}</td>
                <td>{format(item.N_selected)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="hint">还没有已导入的数据集。冻结导入后,你的数据集会出现在这里。</p>
      )}
    </section>
  );
}
