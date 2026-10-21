import { useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, Check, CodeXml, Cpu, FileText, Layers, Paperclip, Play, SlidersHorizontal, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { errorText } from "../api";
import type { Draft, Options, Settings } from "../types";
import { Popover } from "./Popover";

const DRAFT_KEY = "llm4om-draft";
const MILP_ONLY = "原方法的提示只覆盖 LP/MILP，不支持 CPMpy";

const STARTERS: { title: string; tag: string; description: string; data?: Record<string, string> }[] = [
  {
    title: "生产计划", tag: "整数规划",
    description: "工厂生产 A、B 两种产品，数量必须是非负整数。每件 A 利润为 3，每件 B 利润为 2。A 消耗 2 单位切割资源和 1 单位加工资源，" +
      "B 消耗 1 单位切割资源和 2 单位加工资源。两种资源各有 8 单位。请确定生产数量，使总利润最大。",
  },
  {
    title: "运输问题", tag: "附数据文件",
    description: "三个仓库向四个客户运送同一种货物。各仓库的供应量、各客户的需求量和单位运费见数据文件 transport.csv：" +
      "前三行是仓库到客户的单位运费，supply 列是仓库供应量，最后一行 demand 是客户需求量。每个客户的需求必须恰好满足，" +
      "仓库发货不能超过供应量。请制定运输方案，使总运费最小。",
    data: { "transport.csv": "from,C1,C2,C3,C4,supply\nW1,4,6,9,5,120\nW2,7,3,4,8,150\nW3,6,5,7,3,100\ndemand,80,90,110,70,\n" },
  },
  {
    title: "任务指派", tag: "0-1 规划",
    description: "把 4 名员工分配到 4 项任务，每人恰好做一项，每项恰好由一人完成。完成时间（小时）如下：" +
      "员工 1：9、2、7、8；员工 2：6、4、3、7；员工 3：5、8、1、8；员工 4：7、6、9、4（依次对应任务 1–4）。" +
      "请给出总完成时间最短的分配方案。",
  },
];

export function initialDraft(): Draft {
  let saved: Partial<Draft> = {};
  try { saved = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "{}"); } catch { /* storage may be unavailable */ }
  return { description: saved.description ?? "", data: saved.data ?? {}, method: saved.method ?? "direct",
    language: saved.language ?? "pyomo", provider: saved.provider ?? null, model: saved.model ?? "" };
}

export function Composer({ options, settings, draft, setDraft, onStart, openSettings, openExamples }: {
  options: Options; settings: Settings; draft: Draft; setDraft: (draft: Draft) => void; onStart: (draft: Draft) => Promise<void>; openSettings: () => void; openExamples: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const set = (change: Partial<Draft>) => setDraft({ ...draft, ...change });

  const profiles = Object.entries(settings.profiles);
  const provider = draft.provider && settings.profiles[draft.provider] ? draft.provider : settings.selected;
  const profile = provider ? settings.profiles[provider] : undefined;
  const providerLabel = (id: string) => options.providers.find(item => item.id === id)?.label ?? id;
  const method = options.methods.find(item => item.id === draft.method) ?? options.methods[0];
  const supports = (language: string) => !method.languages || method.languages.includes(language);
  const language = options.languages.find(item => item.id === draft.language && supports(item.id))
    ?? options.languages.find(item => supports(item.id))!;
  const model = draft.model || profile?.model || "";

  useEffect(() => {
    if (method.id !== draft.method || language.id !== draft.language) set({ method: method.id, language: language.id });
  }, [method.id, language.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch { /* storage may be unavailable or full */ }
  }, [draft]);
  useEffect(() => { input.current?.focus(); }, []);

  const attach = async (files: FileList | null) => {
    const data = { ...draft.data };
    for (const file of Array.from(files ?? [])) {
      if (file.size > 2_000_000) { toast.error(`${file.name} 超过 2 MB，没有添加。`); continue; }
      data[file.name] = await file.text();
    }
    set({ data });
  };
  const ready = draft.description.trim().length > 0;
  const start = async () => {
    if (!ready || busy) return;
    if (!profile) { toast.error("先配置一个 LLM 服务。"); openSettings(); return; }
    setBusy(true);
    try { await onStart({ ...draft, method: method.id, language: language.id, provider, model }); }
    catch (error) { toast.error(errorText(error)); setBusy(false); }
  };
  const startRef = useRef(start);
  useEffect(() => { startRef.current = start; });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !document.querySelector("dialog[open]")) {
        event.preventDefault(); void startRef.current();
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);

  return <section className="home">
    <header className="home-head">
      <h1>描述一个优化问题</h1>
      <p>写出要做的决策、目标和约束，附上数据。建模方法会先给出数学模型，再写成求解代码，并在隔离沙箱中求解。</p>
    </header>

    <div className={"composer" + (dragging ? " dragging" : "")}
      onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
      onDrop={event => { event.preventDefault(); setDragging(false); void attach(event.dataTransfer.files); }}>
      <textarea ref={input} aria-label="问题描述" value={draft.description} rows={7}
        placeholder="例如：工厂生产 A、B 两种产品……请确定生产数量，使总利润最大。"
        onChange={event => set({ description: event.target.value })} />
      {Object.keys(draft.data).length ? <ul className="files" aria-label="数据文件">
        {Object.entries(draft.data).map(([name, content]) => <li key={name} title={`${content.length.toLocaleString()} 字符`}>
          <FileText size={14} /><span>{name}</span>
          <button className="icon-button tiny" aria-label={`移除 ${name}`} onClick={() => {
            const data = { ...draft.data }; delete data[name]; set({ data });
          }}><X size={12} /></button>
        </li>)}
      </ul> : null}
      <div className="composer-tools">
        <label className="tool" title="CSV、JSON 或文本；代码中以 data[文件名] 读取">
          <Paperclip size={16} />数据文件
          <input type="file" multiple accept=".csv,.json,.txt,.tsv" onChange={event => { void attach(event.target.files); event.target.value = ""; }} />
        </label>
        <button className="tool" onClick={openExamples}><BookOpen size={16} />题库</button>
        {draft.description || Object.keys(draft.data).length
          ? <button className="tool" onClick={() => set({ description: "", data: {} })}><Trash2 size={15} />清空</button> : null}
        <span className="spacer" />
        <span className="kbd-hint"><kbd>Ctrl</kbd> + <kbd>Enter</kbd> 开始</span>
      </div>

      <div className="composer-config">
        <Popover label="建模方法" value={method.name} icon={<Layers size={17} />} wide>
          {close => <div className="choice-grid" role="radiogroup" aria-label="建模方法">
            {options.methods.map(item => <button key={item.id} role="radio" aria-checked={item.id === method.id}
              className={"choice" + (item.id === method.id ? " selected" : "")} onClick={() => { set({ method: item.id }); close(); }}>
              <span className="choice-head"><strong>{item.name}</strong>
                {item.languages ? <span className="tag">LP / MILP</span> : null}
                {item.id === method.id ? <Check size={15} className="choice-check" /> : null}</span>
              <span className="choice-text">{item.description}</span>
            </button>)}
          </div>}
        </Popover>

        <Popover label="代码写法" value={<>{language.name} <span className="muted">→ {language.solver}</span></>} icon={<CodeXml size={17} />}>
          {close => <div className="choice-list" role="radiogroup" aria-label="代码写法">
            {options.languages.map(item => {
              const allowed = supports(item.id);
              return <button key={item.id} role="radio" aria-checked={item.id === language.id} disabled={!allowed}
                className={"choice row" + (item.id === language.id ? " selected" : "")} onClick={() => { set({ language: item.id }); close(); }}>
                <span className="choice-head"><strong>{item.name}</strong><span className="muted">由 {item.solver} 求解</span>
                  {item.id === language.id ? <Check size={15} className="choice-check" /> : null}</span>
                {!allowed ? <span className="choice-text">{method.name}：{MILP_ONLY}</span> : null}
              </button>;
            })}
          </div>}
        </Popover>

        <Popover label="LLM" value={profile ? model || "未填写模型" : "未配置"} icon={<Cpu size={17} />} align="end">
          {close => profile ? <div className="model-panel">
            <div className="choice-list" role="radiogroup" aria-label="LLM 服务">
              {profiles.map(([id, item]) => <button key={id} role="radio" aria-checked={id === provider}
                className={"choice row" + (id === provider ? " selected" : "")} onClick={() => set({ provider: id, model: "" })}>
                <span className="choice-head"><strong>{providerLabel(id)}</strong><span className="muted">{item.model}</span>
                  {id === provider ? <Check size={15} className="choice-check" /> : null}</span>
              </button>)}
            </div>
            <label className="field">本次使用的模型 ID
              <input value={draft.model} placeholder={profile.model} onChange={event => set({ model: event.target.value })} />
            </label>
            <button className="link" onClick={() => { close(); openSettings(); }}><SlidersHorizontal size={14} />管理 LLM 服务</button>
          </div> : <div className="model-panel">
            <p className="muted">还没有可用的 LLM 服务。</p>
            <button className="button primary" onClick={() => { close(); openSettings(); }}>配置 LLM 服务</button>
          </div>}
        </Popover>

        <button className="button primary start-button" disabled={!ready || busy} onClick={() => void start()}>
          {busy ? <span className="spinner" /> : <Play size={15} />}{busy ? "正在启动" : "开始建模"}
        </button>
      </div>
    </div>
    <p className="method-note"><strong>{method.name}</strong>{method.description}</p>

    {!draft.description ? <div className="starters">
      <h2>从一个例子开始</h2>
      <div className="starter-grid">
        {STARTERS.map(item => <button key={item.title} className="starter" onClick={() => set({ description: item.description, data: item.data ?? {} })}>
          <span className="starter-head"><strong>{item.title}</strong><span className="tag">{item.tag}</span></span>
          <span className="starter-text">{item.description}</span>
        </button>)}
        <button className="starter more" onClick={openExamples}>
          <span className="starter-head"><strong>公开题库</strong><ArrowRight size={15} /></span>
          <span className="starter-text">NL4Opt、MAMO、IndustryOR 等 Benchmark 的题面，可直接取用。</span>
        </button>
      </div>
    </div> : null}
  </section>;
}
