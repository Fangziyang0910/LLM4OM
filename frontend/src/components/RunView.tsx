import { useEffect, useState } from "react";
import { ArrowRight, Check, Clock, CodeXml, Cpu, Layers, Pencil, RefreshCw, Square, Trash2, TriangleAlert } from "lucide-react";
import { toast } from "sonner";
import { STATUS, client, duration, errorText, formatNumber, formatTokens, outcome, tone } from "../api";
import { phases, working } from "../steps";
import type { Draft, Options, RunValues, Step } from "../types";
import { useRun } from "../useRun";
import { Outputs, type Tab } from "./Outputs";
import { Timeline } from "./Timeline";

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

export function RunView({ threadId, options, onFinished, onEdit, onRerun, onDelete }: {
  threadId: string; options: Options; onFinished: () => void;
  onEdit: (draft: Draft) => void; onRerun: (draft: Draft) => Promise<void>; onDelete: () => void;
}) {
  const { meta, values, steps, live, run, streaming, error } = useRun(threadId, onFinished);
  const [chosen, setTab] = useState<Tab | null>(null);  // null follows the run
  const [picked, setPicked] = useState<Partial<Record<"formulation" | "code", string>>>({});
  const [view, setView] = useState<"outputs" | "process">("outputs");  // narrow screens show one pane at a time
  const [stopping, setStopping] = useState(false);
  const [busy, setBusy] = useState(false);
  const active = streaming || run?.status === "pending" || run?.status === "running";
  const now = useNow(active);

  if (!meta) return error ? <div className="page-error"><TriangleAlert size={22} /><p>{error}</p></div>
    : <div className="page-loading"><span className="spinner" />正在读取运行……</div>;

  const method = options.methods.find(item => item.id === meta.method);
  const language = options.languages.find(item => item.id === meta.language);
  const provider = options.providers.find(item => item.id === meta.provider);
  const solve = values.solve ?? null;
  const state = outcome(active, run?.status, values.failure, solve?.status);
  const finished = !active && run?.status === "success";
  const hasFormulation = !!values.formulation || steps.some(step => step.formulation);
  const hasCode = !!values.code || steps.some(step => step.code);
  const tab: Tab = chosen ?? (active ? (hasCode ? "code" : hasFormulation ? "formulation" : "problem")
    : solve ? "solution" : hasFormulation ? "formulation" : hasCode ? "code" : "problem");
  const started = run ? Date.parse(run.created_at) : now;
  const elapsed = ((active ? now : run ? Date.parse(run.updated_at) : now) - started) / 1000;
  const usage = values.usage;
  const calls = usage?.llm_calls ?? steps.filter(step => step.type === "llm").length;
  const tokens = usage ? usage.input_tokens + usage.output_tokens : null;

  const draft = (): Draft => ({ description: values.description ?? "", data: values.data ?? {}, method: meta.method,
    language: meta.language, provider: meta.provider, model: meta.model ?? "" });
  const stop = async () => {
    if (!run) return;
    setStopping(true);
    await client.runs.cancel(threadId, run.run_id).catch(reason => { toast.error(errorText(reason)); setStopping(false); });
  };
  const rerun = async () => {
    setBusy(true);
    try { await onRerun(draft()); } catch (reason) { toast.error(errorText(reason)); setBusy(false); }
  };
  const show = (key: "formulation" | "code", id: string) => {
    setPicked(current => ({ ...current, [key]: id }));
    setTab(key);
    setView("outputs");
  };

  return <section className={`run view-${view}`}>
    <header className="run-header">
      <div className="run-heading">
        <h1 title={values.description}>{meta.title}</h1>
        <div className="facts">
          <span className="fact"><Layers size={14} />{method?.name ?? meta.method}</span>
          <span className="fact"><CodeXml size={14} />{language ? <>{language.name}<span className="muted"> → {language.solver}</span></> : meta.language}</span>
          <span className="fact" title={provider?.label}><Cpu size={14} />{meta.model ?? provider?.label ?? "默认模型"}</span>
          <span className="fact"><Clock size={14} />{duration(Math.max(0, elapsed))}</span>
          {calls ? <span className="fact">{calls} 次 LLM 调用{tokens ? ` · ${formatTokens(tokens)} token` : ""}</span> : null}
        </div>
      </div>
      <div className="run-actions">
        {active ? <button className="button" disabled={stopping} onClick={() => void stop()}>
          {stopping ? <span className="spinner" /> : <Square size={14} />}{stopping ? "正在停止" : "停止"}</button> : <>
          <button className="button" disabled={busy || !values.description} onClick={() => void rerun()} title="用同样的问题和设置再运行一次">
            <RefreshCw size={15} />再运行一次</button>
          <button className="button" disabled={!values.description} onClick={() => onEdit(draft())} title="把问题和设置带回编辑页">
            <Pencil size={15} />修改后运行</button>
        </>}
        <button className="icon-button" aria-label="删除这次运行" title="删除" onClick={onDelete}><Trash2 size={16} /></button>
      </div>
    </header>

    <Verdict state={state} values={values} steps={steps} error={error} active={active} onSolution={() => { setTab("solution"); setView("outputs"); }} />

    <div className="segmented" role="tablist" aria-label="视图">
      <button role="tab" aria-selected={view === "outputs"} className={view === "outputs" ? "active" : ""} onClick={() => setView("outputs")}>结果</button>
      <button role="tab" aria-selected={view === "process"} className={view === "process" ? "active" : ""} onClick={() => setView("process")}>
        过程{active ? <span className="live-dot" /> : null}</button>
    </div>

    <div className="run-panes">
      <section className="pane process-pane pane-scroll" aria-label="建模过程">
        <Timeline steps={steps} live={live} active={active} onShow={show} />
      </section>
      <section className="pane outputs-pane" aria-label="运行产物">
        <Outputs values={values} steps={steps} active={active} tab={tab} setTab={setTab} picked={picked} language={language}
          finished={finished} setPicked={(key, id) => setPicked(current => ({ ...current, [key]: id }))} />
      </section>
    </div>
  </section>;
}

/** The answer to "what came of this run?", in one line, with the next thing to look at. */
function Verdict({ state, values, steps, error, active, onSolution }: {
  state: string; values: RunValues; steps: Step[]; error: string | null; active: boolean; onSolution: () => void;
}) {
  if (error) return <div className="verdict bad"><TriangleAlert size={20} /><div><strong>无法读取运行</strong><p>{error}</p>
    <button className="button" onClick={() => location.reload()}>重新连接</button></div></div>;
  if (active) {
    const current = phases(steps).at(-1);
    const calls = current ? working(current.calls) : null;
    const doing = calls ? `LLM 正在处理：${calls}`
      : current?.step?.running ? "正在沙箱中求解代码" : current?.step ? `刚完成：${current.step.title}` : "正在准备";
    return <div className="verdict live"><span className="spinner large" /><div><strong>正在建模</strong><p>{doing}</p></div></div>;
  }
  const solve = values.solve;
  if (state === "interrupted") return <div className="verdict warn"><Square size={20} /><div><strong>运行已停止</strong>
    <p>{steps.length ? "停止前的过程仍可查看。停止的运行不保存结果；服务器重启后，这些过程也不再保留。" : "停止前的过程没有保存。"}</p></div></div>;
  if (state === "failed") return <div className="verdict bad"><TriangleAlert size={20} /><div><strong>没有得到可求解的代码</strong>
    <p>{values.failure}</p></div></div>;
  if (!solve) return <div className={`verdict ${tone(state)}`}><TriangleAlert size={20} /><div><strong>{STATUS[state] ?? state}</strong>
    <p>运行没有正常结束。</p></div></div>;
  if (solve.error) return <div className="verdict bad"><TriangleAlert size={20} /><div><strong>代码执行出错</strong>
    <p>{solve.error.trim().split("\n").pop()}</p></div><button className="link" onClick={onSolution}>查看详情</button></div>;
  const good = tone(solve.status) === "good";
  return <div className={`verdict ${tone(solve.status)}`}>
    {good ? <Check size={20} /> : <TriangleAlert size={20} />}
    <div>
      <strong>{solve.objective != null ? <>目标值 <span className="number">{formatNumber(solve.objective)}</span></> : STATUS[solve.status] ?? solve.status}</strong>
      <p>{good ? `${solve.status === "optimal" ? "最优解" : STATUS[solve.status]} · ${Object.values(solve.variables).filter(value => value !== 0).length} 个非零变量`
        : solve.status === "infeasible" ? "求解器判定模型不可行：约束之间互相矛盾。请检查数学模型的约束与数据。"
        : solve.status === "unbounded" ? "求解器判定模型无界：目标可以无限改进，通常是缺少约束。"
        : STATUS[solve.status] ?? solve.status}</p>
    </div>
    <button className="link" onClick={onSolution}>查看解<ArrowRight size={14} /></button>
  </div>;
}
