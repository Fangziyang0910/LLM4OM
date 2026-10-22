import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ExternalLink } from "lucide-react";
import { api } from "../api";
import { errorText } from "../format";
import type { Dataset } from "../types";
import { Dialog } from "./Dialog";

type Case = { id: string; sample_id: string; subset: string; description: string };
const PAGE = 20;

/** Public benchmark problems to read and try. Only for trying the platform; nothing is scored. */
export function Examples({ open, onClose, datasets, onUse }: {
  open: boolean; onClose: () => void; datasets: Dataset[]; onUse: (description: string) => void;
}) {
  const [dataset, setDataset] = useState<Dataset>(datasets[0]);
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);
  const { data: page, error } = useQuery({
    queryKey: ["dataset", dataset?.id, offset], enabled: open && !!dataset, placeholderData: keepPreviousData, staleTime: Infinity,
    queryFn: () => api<{ total: number; cases: Case[] }>(`/api/datasets/${dataset.id}?offset=${offset}&limit=${PAGE}`),
  });
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => { list.current?.scrollTo(0, 0); }, [page]);
  const choose = (item: Dataset) => { setDataset(item); setOffset(0); };

  return <Dialog open={open} onClose={onClose} wide title="示例题库" flush>
    <div className="examples">
      <nav className="examples-sets" aria-label="题库">
        {datasets.map(item => <button key={item.id} className={"set" + (item.id === dataset?.id ? " selected" : "")}
          aria-current={item.id === dataset?.id} onClick={() => choose(item)}>
          <strong>{item.title}</strong><span className="muted">{item.count} 题 · {item.license}</span>
        </button>)}
      </nav>
      <div className="examples-cases" ref={list}>
        {dataset ? <div className="examples-intro">
          <p>{dataset.description}</p>
          <a href={dataset.source_url} target="_blank" rel="noreferrer">来源<ExternalLink size={13} /></a>
        </div> : null}
        {error ? <div className="callout bad" role="alert">{errorText(error)}</div>
          : !page ? <div className="page-loading small"><span className="spinner" />正在读取……</div> : <>
          <ol className="cases">{page.cases.map(item => <li key={item.id} className="case">
            <div className="case-head">
              <span className="tag">#{item.sample_id}{item.subset && item.subset !== dataset.id ? ` · ${item.subset}` : ""}</span>
              <span className="spacer" />
              <button className="button small primary" onClick={() => onUse(item.description)}>使用这道题</button>
            </div>
            <p className={"case-text" + (expanded === item.id ? " open" : "")}>{item.description}</p>
            {item.description.length > 280 ? <button className="link" onClick={() => setExpanded(expanded === item.id ? null : item.id)}>
              {expanded === item.id ? "收起" : "展开全文"}</button> : null}
          </li>)}</ol>
          <div className="pager">
            <button className="button small" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
              <ChevronLeft size={14} />上一页</button>
            <span className="muted">{offset + 1}–{Math.min(offset + PAGE, page.total)} / {page.total}</span>
            <button className="button small" disabled={offset + PAGE >= page.total} onClick={() => setOffset(offset + PAGE)}>
              下一页<ChevronRight size={14} /></button>
          </div>
        </>}
      </div>
    </div>
  </Dialog>;
}
