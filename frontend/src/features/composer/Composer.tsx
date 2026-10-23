import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";
import { ArrowRight, Columns3, Database, MessageSquare, Play, Settings2 } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Kbd, KbdGroup } from "@/components/ui/kbd";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { errorText } from "@/format";
import { t } from "@/i18n";
import { ProblemEditor } from "@/features/composer/ProblemEditor";
import { readDataFiles } from "@/features/composer/files";
import type { Draft } from "@/features/composer/types";
import type { BackendCatalog, Method, Options, Preset } from "@/types";

const DRAFT_KEY = "llm4om-draft";
export const MAX_COMPARED = 12;  // runs one comparison may start

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
  try { saved = JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "{}") ?? {}; } catch { /* storage may be unavailable */ }
  const legacy = /^cvxpy_(osqp|scs|mosek)$/.exec(saved.language ?? "");
  return { description: saved.description ?? "", data: saved.data ?? {}, method: saved.method ?? "direct",
    language: legacy ? "cvxpy" : saved.language === "pywraplp" ? "ortools" : saved.language ?? "pyomo", preset: saved.preset ?? null,
    solver: saved.solver ?? legacy?.[1].toUpperCase(),
    comparing: saved.comparing ?? false, methods: saved.methods ?? [], presets: saved.presets ?? [] };
}

/** Methods declare the modeling libraries they support. */
const unsupported = (method: Method, language: string) => !!method.languages && !method.languages.includes(language);


export function Composer({ options, presets, draft, setDraft, onStart, onCompare, openPresets, openExamples, onDiscuss, presetsStatus = "ready" }: {
  options: Options; presets: Preset[]; draft: Draft; setDraft: Dispatch<SetStateAction<Draft>>; onStart: (draft: Draft) => Promise<void>;
  onCompare: (draft: Draft, runs: { method: string; preset: Preset }[]) => Promise<void>;
  openPresets: () => void; openExamples: () => void; onDiscuss: () => Promise<void>;
  presetsStatus?: "loading" | "error" | "ready";
}) {
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const settings = useRef<HTMLElement>(null);
  const methodList = useRef<HTMLDivElement>(null);
  const set = (change: Partial<Draft>) => setDraft(current => ({ ...current, ...change }));

  const comparing = !!draft.comparing;
  const preset = presets.find(item => item.id === draft.preset) ?? presets[0];
  const providerLabel = (id: string) => options.providers.find(item => item.id === id)?.label ?? id;
  const method = options.methods.find(item => item.id === draft.method) ?? options.methods[0];
  const supports = (language: string) => comparing || !unsupported(method, language);
  const language = options.languages.find(item => item.id === draft.language && supports(item.id))
    ?? options.languages.find(item => supports(item.id))!;
  const backend = draft.solver ?? "AUTO";
  const catalog = useQuery({ queryKey: ["backends"], queryFn: () => api<BackendCatalog>("/api/backends"), staleTime: Infinity, retry: false });
  const backends = catalog.data?.libraries[language.id];
  const backendUnavailable = !!backends && !backends.some(item => item.id === backend && item.available);
  // A comparison runs each chosen method that supports the language with each chosen preset.
  const compared = options.methods.filter(item => draft.methods?.includes(item.id) && !unsupported(item, language.id));
  const comparedPresets = presets.filter(item => draft.presets?.includes(item.id));
  const runs = compared.flatMap(item => (comparedPresets.length ? comparedPresets : preset ? [preset] : [])
    .map(chosen => ({ method: item.id, preset: chosen })));

  useEffect(() => {
    if (method.id !== draft.method || language.id !== draft.language)
      set({ method: method.id, language: language.id, solver: language.id !== draft.language ? undefined : draft.solver });
  }, [method.id, language.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch { /* storage may be unavailable or full */ }
  }, [draft]);
  useEffect(() => {
    const list = methodList.current;
    const selected = list?.querySelector<HTMLElement>('[data-state="checked"]')?.closest("label");
    if (list && selected) list.scrollTop += selected.getBoundingClientRect().top - list.getBoundingClientRect().top - (list.clientHeight - selected.clientHeight) / 2;
  }, [method.id, comparing]);

  const attach = async (list: FileList | null) => {
    setReading(true);
    try {
      const data = await readDataFiles(list);
      setDraft(current => ({ ...current, data: { ...current.data, ...data } }));
    } finally { setReading(false); }
  };
  const ready = draft.description.trim().length > 0 && !reading && !backendUnavailable && presetsStatus === "ready"
    && (!comparing || (runs.length > 0 && runs.length <= MAX_COMPARED));
  const start = async () => {
    if (!ready || busy) return;
    if (!preset) { toast.error(t("先添加一个预设模型。")); openPresets(); return; }
    setBusy(true);
    try {
      const request = { ...draft, method: method.id, language: language.id, solver: backend, preset: preset.id };
      await (comparing ? onCompare(request, runs) : onStart(request));
    } catch (error) { toast.error(errorText(error)); setBusy(false); }
  };
  const startRef = useRef(start);
  useEffect(() => { startRef.current = start; });
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing && event.keyCode !== 229 && !document.querySelector("[role=dialog]")) {
        event.preventDefault(); void startRef.current();
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);
  const toggle = (key: "methods" | "presets", id: string, on: boolean) =>
    set({ [key]: on ? [...(draft[key] ?? []).filter(item => item !== id), id] : (draft[key] ?? []).filter(item => item !== id) });
  const label = reading ? t("正在读取数据……") : busy ? t("正在启动") : comparing ? t("开始对比（{count} 个运行）", { count: runs.length }) : t("开始建模");

  const choiceClass = "flex min-h-11 min-w-0 cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2 text-sm font-normal transition-colors hover:bg-accent/50 sm:min-h-9 sm:py-1.5";
  const methodChoices = options.methods.map(item => {
    const blocked = unsupported(item, language.id);
    const selected = comparing ? !blocked && !!draft.methods?.includes(item.id) : item.id === method.id;
    const id = `${comparing ? "compare" : "method"}-${item.id}`;
    return <Label key={item.id} htmlFor={id} title={blocked ? t("{method}：当前方法不支持这种代码写法与求解器", { method: item.name }) : t(item.description)}
      className={cn(choiceClass, selected && "border-primary/50 bg-primary/5 hover:bg-primary/5", blocked && "cursor-not-allowed opacity-45 hover:bg-transparent")}>
      {comparing ? <Checkbox id={id} checked={selected} disabled={blocked} onCheckedChange={on => toggle("methods", item.id, on === true)} />
        : <RadioGroupItem id={id} value={item.id} disabled={blocked} />}
      <span className="min-w-0 flex-1 truncate font-medium">{item.name}</span>
      {item.linear_only ? <Badge variant="outline" className="h-4.5 shrink-0 px-1.5 text-[10px] font-normal text-muted-foreground">LP / MILP</Badge> : null}
    </Label>;
  });
  const methodListClass = "grid max-h-40 grid-cols-1 gap-1.5 overflow-y-auto pr-1 sm:grid-cols-2 lg:grid-cols-1";

  return <div className="flex h-full flex-col">
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="flex min-h-full flex-col gap-5 p-4 sm:p-6 lg:h-full">
        <header className="flex shrink-0 flex-col gap-1.5">
          <div className="flex flex-wrap items-center justify-between gap-2">
          <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{t("描述一个优化问题")}</h1>
          <Button variant="outline" size="sm" disabled={busy || reading} onClick={async () => {
            setBusy(true);
            try { await onDiscuss(); } catch (error) { toast.error(errorText(error)); } finally { setBusy(false); }
          }}><MessageSquare />{t("通过对话整理需求")}</Button>
          </div>
          <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">{t("写清要安排什么、希望达到的目标，以及必须满足的条件。需要时附上数据。")}</p>
        </header>

        <div className="grid min-h-0 flex-1 grid-cols-1 items-stretch gap-5 lg:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_384px]">
          <section className="flex min-h-0 min-w-0 flex-col gap-4">
            <ProblemEditor autoFocus value={draft.description} data={draft.data} reading={reading} onChange={description => set({ description })}
              onFiles={list => void attach(list)} onExamples={openExamples} onClear={() => {
                const previous = { description: draft.description, data: draft.data }; set({ description: "", data: {} });
                toast.success(t("已清空问题和附件。"), { action: { label: t("撤销"), onClick: () => set(previous) } });
              }}
              onDataChange={(name, content) => setDraft(current => ({ ...current, data: { ...current.data, [name]: content } }))}
              onRemove={name => setDraft(current => {
                const data = { ...current.data }; delete data[name]; return { ...current, data };
              })} />
            {!draft.description ? <section className="flex shrink-0 flex-col gap-3">
              <h2 className="text-sm font-medium text-muted-foreground">{t("从一个例子开始")}</h2>
              <div className="grid grid-cols-2 gap-2 sm:gap-3">
                {STARTERS.map(item => <button key={item.title} onClick={() => set({ description: t(item.description), data: item.data ?? {} })}
                  className="group flex min-w-0 flex-col gap-2 rounded-xl border bg-card p-4 text-left shadow-xs transition-colors hover:border-primary/40 hover:bg-accent/40">
                  <span className="flex items-center gap-2 text-sm">
                    <span className="font-medium whitespace-nowrap">{t(item.title)}</span><Badge variant="secondary" className="hidden font-normal sm:inline-flex">{t(item.tag)}</Badge>
                    <ArrowRight className="ml-auto size-4 text-muted-foreground" />
                  </span>
                  <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{t(item.description)}</span>
                </button>)}
                <button onClick={openExamples}
                  className="group flex min-w-0 flex-col gap-2 rounded-xl border border-dashed p-4 text-left transition-colors hover:border-primary/40 hover:bg-accent/40">
                  <span className="flex items-center gap-2 text-sm font-medium"><Database className="size-4 text-primary" />{t("公开题库")}
                    <ArrowRight className="ml-auto size-4 text-muted-foreground" /></span>
                  <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{t("NL4Opt、MAMO、IndustryOR 等 Benchmark 的题面，可直接取用。")}</span>
                </button>
              </div>
            </section> : null}
          </section>

          <aside ref={settings} tabIndex={-1} aria-label={t("运行设置")} className="min-h-0 min-w-0 scroll-mt-4 outline-none">
            <Card className="h-full min-h-0 gap-0 overflow-hidden py-0">
              <div className="flex h-14 shrink-0 items-center gap-2 border-b px-4">
                <h2 className="flex items-center gap-2 text-sm font-semibold"><Settings2 className="size-4 text-muted-foreground" />{t("运行设置")}</h2>
                <Label className="ml-auto gap-2 text-xs font-normal text-muted-foreground" title={t("同一问题同时用多个方法或预设运行，并排比较结果")}>
                  <Columns3 className="size-3.5" />{t("对比")}
                  <Switch size="sm" checked={comparing} aria-label={t("对比多个方法")} onCheckedChange={on => set({ comparing: on,
                    methods: on && !draft.methods?.length ? [method.id] : draft.methods })} />
                </Label>
              </div>
              <div className="flex min-h-0 flex-1 flex-col divide-y overflow-y-auto">
                <section aria-labelledby="methods-label" className="min-w-0 px-4 py-3">
                  <h3 id="methods-label" className="mb-3 text-xs font-medium text-muted-foreground">{comparing ? t("建模方法（可多选）") : t("建模方法")}</h3>
                  {comparing ? <div ref={methodList} role="group" aria-label={t("建模方法")} className={methodListClass}>{methodChoices}</div>
                    : <RadioGroup ref={methodList} value={method.id} onValueChange={value => set({ method: value })} aria-label={t("建模方法")}
                      aria-describedby="method-description" className={methodListClass}>{methodChoices}</RadioGroup>}
                  <p id="method-description" title={comparing ? undefined : t(method.description)} className="mt-3 line-clamp-2 min-h-8 text-xs leading-relaxed text-muted-foreground">
                    {t(comparing ? "同一问题同时用多个方法或预设运行，并排比较结果" : method.description)}</p>
                </section>

                <section aria-labelledby="libraries-label" className="min-w-0 px-4 py-3">
                  <h3 id="libraries-label" className="mb-3 text-xs font-medium text-muted-foreground">{t("建模求解器")}</h3>
                  <RadioGroup value={language.id} onValueChange={value => set({ language: value, solver: undefined })} aria-label={t("建模求解器")}
                    className="grid grid-cols-3 gap-1.5">
                    {options.languages.map(item => {
                      const allowed = supports(item.id);
                      const tile = <Label htmlFor={`language-${item.id}`} className={cn(choiceClass, "h-full justify-center px-1.5 text-center",
                        item.id === language.id && "border-primary/50 bg-primary/5 hover:bg-primary/5", !allowed && "cursor-not-allowed opacity-45 hover:bg-transparent")}>
                        <RadioGroupItem id={`language-${item.id}`} value={item.id} disabled={!allowed} className="sr-only" />
                        <span className="text-xs font-medium sm:text-[13px]">{item.name}</span>
                      </Label>;
                      return allowed ? <div key={item.id}>{tile}</div> : <Tooltip key={item.id}>
                        <TooltipTrigger asChild><div>{tile}</div></TooltipTrigger>
                        <TooltipContent>{t("{method}：当前方法不支持这种代码写法与求解器", { method: method.name })}</TooltipContent>
                      </Tooltip>;
                    })}
                  </RadioGroup>
                  <div className="mt-4 flex flex-col gap-2">
                    <Label htmlFor="solver-backend" className="text-xs text-muted-foreground">{t("求解后端")}</Label>
                    <Select value={backend} onValueChange={value => set({ solver: value })}>
                      <SelectTrigger id="solver-backend" aria-label={t("求解后端")} className="w-full"><SelectValue /></SelectTrigger>
                      <SelectContent>{(backends ?? [{ id: backend, available: true, detail: "" }]).map(item =>
                        <SelectItem key={item.id} value={item.id} disabled={!item.available} title={item.detail}>
                          {item.id === "AUTO" ? t("自动选择") : item.id}{!item.available ? ` · ${t("当前环境不可用")}` : ""}
                        </SelectItem>)}</SelectContent>
                    </Select>
                    {catalog.isPending ? <p className="text-xs text-muted-foreground">{t("正在检查求解后端……")}</p> : null}
                    {catalog.error ? <p className="text-xs text-destructive">{errorText(catalog.error)}</p> : null}
                    {backendUnavailable ? <p className="text-xs text-destructive">{t("所选后端在当前环境不可用，请选择其他后端。")}</p> : null}
                  </div>
                </section>

                <section aria-labelledby="presets-label" className="min-w-0 px-4 py-3">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <h3 id="presets-label" className="text-xs font-medium text-muted-foreground">{comparing ? t("预设模型（可多选）") : t("预设模型")}</h3>
                    <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={openPresets}>{t("管理")}</Button>
                  </div>
                  {!preset && presetsStatus !== "ready" ? <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
                    {presetsStatus === "loading" ? <Spinner /> : null}{t(presetsStatus === "loading" ? "正在加载预设模型……" : "预设模型暂不可用，请重试加载。")}
                  </p> : !preset ? <Alert>
                    <AlertDescription className="flex flex-col items-start gap-2">{t("还没有预设模型。")}
                      <Button size="sm" onClick={openPresets}>{t("添加预设模型")}</Button></AlertDescription>
                  </Alert> : comparing ? <div role="group" aria-label={t("预设模型")} className="flex flex-col gap-1.5">
                    {presets.map(item => <Label key={item.id} htmlFor={`compare-preset-${item.id}`} className={cn(choiceClass, "py-2 sm:py-2")}
                      title={item.name || item.model}>
                      <Checkbox id={`compare-preset-${item.id}`} checked={!!draft.presets?.includes(item.id)} onCheckedChange={on => toggle("presets", item.id, on === true)} />
                      <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                        <span className="truncate text-sm font-medium">{item.name || item.model}</span>
                        <span className="truncate text-xs text-muted-foreground">{providerLabel(item.provider)}</span>
                      </span>
                    </Label>)}
                    {!comparedPresets.length ? <p className="text-xs text-muted-foreground">{t("未选择时使用默认预设 {model}。", { model: preset.name || preset.model })}</p> : null}
                  </div> : <>
                    <Select value={preset.id} onValueChange={value => set({ preset: value })}>
                      <SelectTrigger aria-label={t("预设模型")} className="w-full min-w-0" title={preset.name || preset.model}>
                        <SelectValue>{preset.name || preset.model}</SelectValue></SelectTrigger>
                      <SelectContent>{presets.map(item => <SelectItem key={item.id} value={item.id}>
                        <span className="font-medium">{item.name || item.model}</span><span className="text-muted-foreground">{providerLabel(item.provider)}</span>
                      </SelectItem>)}</SelectContent>
                    </Select>
                    <p className="mt-2 text-xs text-muted-foreground">{providerLabel(preset.provider)}</p>
                  </>}
                </section>
              </div>
            </Card>
          </aside>
        </div>
      </div>
    </div>
    <footer className="flex shrink-0 items-center justify-between gap-2 border-t bg-card px-4 py-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] sm:gap-4 sm:px-6">
      <Button variant="ghost" className="h-auto min-w-0 max-w-[45%] shrink-0 justify-start gap-2 px-1 text-left lg:hidden"
        aria-label={t("查看运行设置")} onClick={() => { settings.current?.scrollIntoView({ block: "start" }); settings.current?.focus({ preventScroll: true }); }}>
        <Settings2 className="shrink-0" /><span className="truncate text-xs">{method.name}<span className="block truncate font-normal text-muted-foreground">{language.name}</span></span>
      </Button>
      <div className="hidden min-w-0 flex-1 flex-col gap-0.5 lg:flex">
        <span className="truncate text-sm font-medium">{comparing ? t("方法对比") : method.name} · {language.name}</span>
        <span className="truncate text-xs text-muted-foreground" title={preset?.name || preset?.model}>{preset?.name || preset?.model}</span>
      </div>
      <div className="flex w-full flex-col gap-1.5 sm:w-auto sm:min-w-56">
        {comparing && runs.length > MAX_COMPARED ? <p className="text-xs text-destructive">
          {t("一次最多对比 {max} 个运行，当前为 {count} 个。", { max: MAX_COMPARED, count: runs.length })}</p> : null}
        <Button size="lg" className="w-full" disabled={!ready || busy} onClick={() => void start()}>
          {busy || reading ? <Spinner /> : comparing ? <Columns3 /> : <Play />}{label}
          {!busy ? <KbdGroup className="ml-1 hidden opacity-70 sm:inline-flex"><Kbd className="bg-primary-foreground/15 text-primary-foreground">Ctrl</Kbd>
            <Kbd className="bg-primary-foreground/15 text-primary-foreground">↵</Kbd></KbdGroup> : null}
        </Button>
      </div>
    </footer>
  </div>;
}
