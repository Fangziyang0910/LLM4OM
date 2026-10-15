// 内置 benchmark 样例浏览；只复制公开问题和业务数据。
import { useEffect, useState } from "react";
import { Icon } from "./Icon";
import { api } from "../api";
import { format } from "../ui";
import type { BenchmarkCase, BenchmarkInput, DatasetSummary, Notice } from "../types";

const PAGE_SIZE = 100;
type Detail = { dataset: DatasetSummary; total: number; cases: BenchmarkCase[] };

function DataValue({ value }: { value: unknown }) {
  if (value === null || typeof value !== "object") return <>{String(value ?? "—")}</>;
  return <table className="visual-table"><tbody>
    {Object.entries(value).map(([key, item]) => <tr key={key}><td>{key}</td><td><DataValue value={item} /></td></tr>)}
  </tbody></table>;
}

function DatasetCase({ value, onTry, notice }: { value: BenchmarkCase; onTry: (input: BenchmarkInput) => void; notice: Notice }) {
  const copy = async () => {
    try { await navigator.clipboard.writeText(value.copy_text); notice("问题已复制，可粘贴后尝试建模。"); }
    catch { notice("复制失败，请选中问题文本手动复制。", true); }
  };
  return <div id="dataset-case" className="dataset-case">
    <section className="model-card">
      <div className="panel-title"><h3>问题描述</h3><span>样例 {value.sample_id}</span></div>
      <p className="problem-text">{value.problem.description}</p>
      {value.input.data.map((data) => {
        const bytes = Uint8Array.from(atob(data.base64), (character) => character.charCodeAt(0));
        const text = new TextDecoder().decode(bytes);
        return <div key={data.data_id}><h4>附带数据：{data.data_id}</h4>
          {data.format === "json" ? <DataValue value={JSON.parse(text)} /> : <p className="problem-text">{text}</p>}
        </div>;
      })}
      <div className="actions">
        <button type="button" id="copy-benchmark-problem" className="secondary" onClick={copy}>复制问题</button>
        <button type="button" id="try-benchmark-problem" className="primary" onClick={() => onTry(value.input)}>带入建模</button>
      </div>
      <p className="hint">复制包含问题需要的公开数据；带入建模会自动填好问题和数据。</p>
    </section>
  </div>;
}

function DatasetDetail({ taskId, onBack, onTry, notice }: {
  taskId: string; onBack: () => void; onTry: (input: BenchmarkInput) => void; notice: Notice;
}) {
  const [page, setPage] = useState(0);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState(false);
  const [caseId, setCaseId] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    setDetail(null); setError(false); setCaseId(null);
    api<Detail>(`/api/datasets/${taskId}?offset=${page * PAGE_SIZE}&limit=${PAGE_SIZE}`)
      .then((result) => { if (alive) setDetail(result); })
      .catch(() => { if (alive) setError(true); });
    return () => { alive = false; };
  }, [taskId, page]);
  if (error) return <section id="dataset-detail" className="panel"><p>样例读取失败，请返回后重试。</p>
    <button className="secondary" onClick={onBack}>← 返回 Benchmark 列表</button></section>;
  if (!detail) return <section id="dataset-detail" className="panel"><p>正在读取样例…</p></section>;
  const header = detail.dataset;
  const active = detail.cases.find((item) => item.case_id === caseId);
  const lastPage = Math.max(0, Math.ceil(detail.total / PAGE_SIZE) - 1);
  return <section id="dataset-detail" className="panel">
    <div className="panel-title"><h3>{header.title}</h3><span className="pill">{format(detail.total)} 个问题</span></div>
    <p className="hint">{header.description}</p>
    <button id="back-to-datasets" className="secondary" onClick={onBack}>← 返回 Benchmark 列表</button>
      <div className="dataset-browser"><div className="dataset-case-list">
      <table className="visual-table"><thead><tr><th>编号</th><th>问题预览</th></tr></thead><tbody>
        {detail.cases.map((item) => <tr key={item.case_id} tabIndex={0}
          className={"dataset-row" + (item.case_id === caseId ? " selected" : "")}
          onClick={() => setCaseId(item.case_id)}
          onKeyDown={(event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); setCaseId(item.case_id); } }}>
          <td>{item.sample_id}</td><td>{item.problem.description.slice(0, 120)}{item.problem.description.length > 120 ? "…" : ""}</td>
        </tr>)}
      </tbody></table>
      {detail.total > PAGE_SIZE ? <div className="dataset-pager">
        <button className="secondary" disabled={page <= 0} onClick={() => setPage((previous) => previous - 1)}>← 上一页</button>
        <span className="hint">第 {page + 1} / {lastPage + 1} 页</span>
        <button className="secondary" disabled={page >= lastPage} onClick={() => setPage((previous) => previous + 1)}>下一页 →</button>
      </div> : null}
      </div><div className="dataset-reader">{active ? <DatasetCase value={active} onTry={onTry} notice={notice} /> : <div className="empty-view"><span className="empty-icon" aria-hidden="true">▤</span><h3>选择一个问题</h3><p className="hint">在左侧浏览题目，再复制或直接带入建模。</p></div>}</div></div>
    <p className="hint">来源：<a href={header.source_url} target="_blank" rel="noreferrer">{header.title}</a> · {header.license}</p>
  </section>;
}

export function Datasets({ datasets, refresh, onTry, notice }: {
  datasets: DatasetSummary[]; refresh: () => Promise<void>; onTry: (input: BenchmarkInput) => void; notice: Notice;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  if (openId) return <DatasetDetail key={openId} taskId={openId} onBack={() => setOpenId(null)} onTry={onTry} notice={notice} />;
  return <section id="datasets" className="panel">
    <div className="panel-title"><div><span className="eyebrow">从真实问题开始</span><h2>内置 Benchmark</h2></div>
      <button className="secondary" onClick={() => refresh().catch(() => notice("列表读取失败，请重试。", true))}>刷新</button></div>
    <p className="hint">浏览已集成的问题集，选一条题目直接试试建模。</p>
    <div className="benchmark-grid">
      {datasets.map(item => <button key={item.task_id} className="dataset-row benchmark-card" onClick={() => setOpenId(item.task_id)}>
        <div className="benchmark-card-top"><span className="benchmark-symbol"><Icon name="book" size={21} /></span><span>{format(item.N_cases)} 个问题</span></div>
        <h3>{item.title}</h3><p>{item.description}</p><span className="benchmark-open">浏览样例 <Icon name="arrow" size={16} /></span>
      </button>)}
    </div>
    {!datasets.length ? <p className="hint">正在读取平台样例，请稍后刷新。</p> : null}
  </section>;
}
