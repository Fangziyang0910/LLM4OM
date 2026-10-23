import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, Columns3, Database, FileText, Paperclip, Play, Settings2, Trash2, Upload, X } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Kbd, KbdGroup } from "@/components/ui/kbd";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { errorText } from "@/format";
import { t } from "@/i18n";
import { excelToCsv } from "@/features/composer/spreadsheet";
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


export function Composer({ options, presets, draft, setDraft, onStart, onCompare, openPresets, openExamples }: {
  options: Options; presets: Preset[]; draft: Draft; setDraft: Dispatch<SetStateAction<Draft>>; onStart: (draft: Draft) => Promise<void>;
  onCompare: (draft: Draft, runs: { method: string; preset: Preset }[]) => Promise<void>;
  openPresets: () => void; openExamples: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
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
  const files = Object.entries(draft.data);
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
  useEffect(() => { input.current?.focus(); }, []);

  const attach = async (list: FileList | null) => {
    const data: Record<string, string> = {};
    for (const file of Array.from(list ?? [])) {
      if (file.size > 2_000_000) { toast.error(t("{name} 超过 2 MB，没有添加。", { name: file.name })); continue; }
      try {
        if (/\.xlsx$/i.test(file.name)) {
          const sheets = await excelToCsv(file);
          Object.assign(data, sheets);
          toast.success(t("{name} 已转换为 {count} 个 CSV 文件。", { name: file.name, count: Object.keys(sheets).length }));
        } else data[file.name] = await file.text();
      } catch (error) { toast.error(t("无法读取 {name}：{error}", { name: file.name, error: errorText(error) })); }
    }
    setDraft(current => ({ ...current, data: { ...current.data, ...data } }));
  };
  const ready = draft.description.trim().length > 0 && !backendUnavailable
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
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !document.querySelector("[role=dialog]")) {
        event.preventDefault(); void startRef.current();
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);
  const toggle = (key: "methods" | "presets", id: string, on: boolean) =>
    set({ [key]: on ? [...(draft[key] ?? []).filter(item => item !== id), id] : (draft[key] ?? []).filter(item => item !== id) });
  const label = busy ? t("正在启动") : comparing ? t("开始对比（{count} 个运行）", { count: runs.length }) : t("开始建模");

  return <div className="h-full overflow-y-auto">
    <div className="mx-auto grid max-w-6xl grid-cols-[minmax(0,1fr)] gap-6 px-4 py-6 md:px-8 md:py-10 lg:grid-cols-[minmax(0,1fr)_360px]">
      <section className="flex min-w-0 flex-col gap-6">
        <header className="flex flex-col gap-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">{t("描述一个优化问题")}</h1>
          <p className="max-w-2xl text-sm text-muted-foreground">{t("写出要做的决策、目标和约束，附上数据。建模方法先给出数学模型，再写成求解代码，并在隔离沙箱中求解。")}</p>
        </header>

        <Card className={cn("gap-0 overflow-hidden py-0 transition-shadow focus-within:border-ring/60 focus-within:ring-[3px] focus-within:ring-ring/15",
          dragging && "border-primary ring-[3px] ring-primary/20")}
          onDragOver={event => { event.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
          onDrop={event => { event.preventDefault(); setDragging(false); void attach(event.dataTransfer.files); }}>
          <div className="relative">
            <Textarea ref={input} aria-label={t("问题描述")} value={draft.description}
              placeholder={t("例如：工厂生产 A、B 两种产品……请确定生产数量，使总利润最大。")}
              onChange={event => set({ description: event.target.value })}
              className="max-h-[55vh] min-h-56 resize-none rounded-none border-0 bg-transparent px-5 py-4 text-[15px] leading-relaxed shadow-none focus-visible:ring-0 dark:bg-transparent" />
            {dragging ? <div className="pointer-events-none absolute inset-0 flex items-center justify-center gap-2 bg-primary/5 text-sm font-medium text-primary">
              <Upload className="size-4" />{t("松开以添加数据文件")}</div> : null}
          </div>
          {files.length ? <ul aria-label={t("数据文件")} className="flex flex-wrap gap-2 px-5 pb-3">
            {files.map(([name, content]) => <li key={name} title={t("{count} 字符", { count: content.length.toLocaleString() })}
              className="flex items-center gap-1.5 rounded-md border bg-muted/50 py-1 pr-1 pl-2 text-xs">
              <FileText className="size-3.5 text-muted-foreground" /><span className="font-medium">{name}</span>
              <span className="text-muted-foreground">{t("{count} 行", { count: content.split("\n").filter(Boolean).length })}</span>
              <Button variant="ghost" size="icon-xs" aria-label={t("移除 {name}", { name })} onClick={() => {
                const data = { ...draft.data }; delete data[name]; set({ data });
              }}><X /></Button>
            </li>)}
          </ul> : null}
          <div className="flex flex-wrap items-center gap-1 border-t bg-muted/30 px-3 py-2">
            <Button variant="ghost" size="sm" asChild>
              <label title={t("CSV、JSON、文本或 Excel（转换为 CSV）；代码中以 data[文件名] 读取")} className="cursor-pointer">
                <Paperclip />{t("数据文件")}
                <input type="file" multiple accept=".csv,.json,.txt,.tsv,.xlsx" className="sr-only"
                  onChange={event => { void attach(event.target.files); event.target.value = ""; }} />
              </label>
            </Button>
            <Button variant="ghost" size="sm" onClick={openExamples}><BookOpen />{t("从题库选题")}</Button>
            {draft.description || files.length
              ? <Button variant="ghost" size="sm" onClick={() => set({ description: "", data: {} })}><Trash2 />{t("清空")}</Button> : null}
            <span className="ml-auto px-2 text-xs text-muted-foreground tabular">{draft.description.length ? t("{count} 字", { count: draft.description.length }) : ""}</span>
          </div>
        </Card>

        {!draft.description ? <section className="flex flex-col gap-3">
          <h2 className="text-sm font-medium text-muted-foreground">{t("从一个例子开始")}</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {STARTERS.map(item => <button key={item.title} onClick={() => set({ description: t(item.description), data: item.data ?? {} })}
              className="group flex flex-col gap-2 rounded-xl border bg-card p-4 text-left shadow-xs transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:shadow-md">
              <span className="flex items-center gap-2">
                <span className="font-medium">{t(item.title)}</span>
                <Badge variant="secondary" className="font-normal">{t(item.tag)}</Badge>
                <ArrowRight className="ml-auto size-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
              </span>
              <span className="line-clamp-2 text-[13px] leading-relaxed text-muted-foreground">{t(item.description)}</span>
            </button>)}
            <button onClick={openExamples}
              className="group flex flex-col gap-2 rounded-xl border border-dashed p-4 text-left transition-colors hover:border-primary/40 hover:bg-accent/40">
              <span className="flex items-center gap-2 font-medium"><Database className="size-4 text-primary" />{t("公开题库")}
                <ArrowRight className="ml-auto size-4 text-muted-foreground transition-transform group-hover:translate-x-0.5" /></span>
              <span className="text-[13px] leading-relaxed text-muted-foreground">{t("NL4Opt、MAMO、IndustryOR 等 Benchmark 的题面，可直接取用。")}</span>
            </button>
          </div>
        </section> : null}
      </section>

      <aside className="lg:sticky lg:top-10 lg:self-start">
        <Card className="gap-5">
          <CardHeader className="flex items-center gap-2">
            <CardTitle className="flex items-center gap-2 text-base"><Settings2 className="size-4 text-muted-foreground" />{t("运行设置")}</CardTitle>
            <Label className="ml-auto gap-2 text-xs font-normal text-muted-foreground" title={t("同一问题同时用多个方法或预设运行，并排比较结果")}>
              <Columns3 className="size-3.5" />{t("对比")}
              <Switch size="sm" checked={comparing} aria-label={t("对比多个方法")} onCheckedChange={on => set({ comparing: on,
                methods: on && !draft.methods?.length ? [method.id] : draft.methods })} />
            </Label>
          </CardHeader>
          <CardContent className="flex flex-col gap-5">
            <fieldset className="flex min-w-0 flex-col gap-2">
              <legend className="mb-2 text-xs font-medium text-muted-foreground">{comparing ? t("建模方法（可多选）") : t("建模方法")}</legend>
              {comparing ? <div role="group" aria-label={t("建模方法")} className="flex max-h-[340px] flex-col gap-1.5 overflow-y-auto pr-1">
                {options.methods.map(item => {
                  const blocked = unsupported(item, language.id);
                  const selected = !blocked && !!draft.methods?.includes(item.id);
                  return <Label key={item.id} htmlFor={`compare-${item.id}`} title={blocked ? t("{method}：当前方法不支持这种代码写法与求解器", { method: item.name }) : undefined}
                    className={cn("flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 font-normal transition-colors hover:bg-accent/50",
                      selected && "border-primary/50 bg-primary/5 hover:bg-primary/5", blocked && "cursor-not-allowed opacity-45 hover:bg-transparent")}>
                    <Checkbox id={`compare-${item.id}`} checked={selected} disabled={blocked} onCheckedChange={on => toggle("methods", item.id, on === true)} />
                    <span className="text-sm font-medium">{item.name}</span>
                    {item.linear_only ? <Badge variant="outline" className="ml-auto h-4.5 px-1.5 text-[10px] font-normal text-muted-foreground">LP / MILP</Badge> : null}
                  </Label>;
                })}
              </div> : <RadioGroup value={method.id} onValueChange={value => set({ method: value })} aria-label={t("建模方法")}
                className="max-h-[340px] gap-1.5 overflow-y-auto pr-1">
                {options.methods.map(item => {
                  const selected = item.id === method.id;
                  return <Label key={item.id} htmlFor={`method-${item.id}`}
                    className={cn("flex cursor-pointer items-start gap-3 rounded-lg border p-3 font-normal transition-colors hover:bg-accent/50",
                      selected && "border-primary/50 bg-primary/5 hover:bg-primary/5")}>
                    <RadioGroupItem id={`method-${item.id}`} value={item.id} className="mt-0.5" />
                    <span className="flex min-w-0 flex-col gap-1">
                      <span className="flex items-center gap-2 text-sm font-medium">{item.name}
                        {item.linear_only ? <Badge variant="outline" className="h-4.5 px-1.5 text-[10px] font-normal text-muted-foreground">LP / MILP</Badge> : null}</span>
                      <span className={cn("text-xs leading-relaxed text-muted-foreground", !selected && "line-clamp-1")}>{t(item.description)}</span>
                    </span>
                  </Label>;
                })}
              </RadioGroup>}
            </fieldset>

            <fieldset className="flex min-w-0 flex-col">
              <legend className="mb-2 text-xs font-medium text-muted-foreground">{t("建模求解器")}</legend>
              <RadioGroup value={language.id} onValueChange={value => set({ language: value, solver: undefined })} aria-label={t("建模求解器")} className="grid grid-cols-2 gap-1.5">
                {options.languages.map(item => {
                  const allowed = supports(item.id);
                  const tile = <Label htmlFor={`language-${item.id}`}
                    className={cn("flex h-full cursor-pointer flex-col items-start justify-center gap-0.5 rounded-lg border px-3 py-2 font-normal transition-colors hover:bg-accent/50",
                      item.id === language.id && "border-primary/50 bg-primary/5 hover:bg-primary/5", !allowed && "cursor-not-allowed opacity-45 hover:bg-transparent")}>
                    <RadioGroupItem id={`language-${item.id}`} value={item.id} disabled={!allowed} className="sr-only" />
                    <span className="text-sm font-medium">{item.name}</span>
                  </Label>;
                  return allowed ? <div key={item.id} className="h-full">{tile}</div> : <Tooltip key={item.id}>
                    <TooltipTrigger asChild><div className="h-full">{tile}</div></TooltipTrigger>
                    <TooltipContent>{t("{method}：当前方法不支持这种代码写法与求解器", { method: method.name })}</TooltipContent>
                  </Tooltip>;
                })}
              </RadioGroup>
              <div className="mt-3 flex flex-col gap-2">
                <Label htmlFor="solver-backend">{t("求解后端")}</Label>
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
            </fieldset>

            <fieldset className="flex min-w-0 flex-col gap-2">
              <legend className="mb-2 flex w-full items-center text-xs font-medium text-muted-foreground">{comparing ? t("预设模型（可多选）") : t("预设模型")}
                <Button variant="link" size="sm" className="ml-auto h-auto p-0 text-xs" onClick={openPresets}>{t("管理")}</Button></legend>
              {!preset ? <Alert>
                <AlertDescription className="flex flex-col items-start gap-2">{t("还没有预设模型。")}
                  <Button size="sm" onClick={openPresets}>{t("添加预设模型")}</Button></AlertDescription>
              </Alert> : comparing ? <div role="group" aria-label={t("预设模型")} className="flex flex-col gap-1.5">
                {presets.map(item => <Label key={item.id} htmlFor={`compare-preset-${item.id}`}
                  className="flex cursor-pointer items-center gap-3 rounded-lg border px-3 py-2 font-normal hover:bg-accent/50">
                  <Checkbox id={`compare-preset-${item.id}`} checked={!!draft.presets?.includes(item.id)}
                    onCheckedChange={on => toggle("presets", item.id, on === true)} />
                  <span className="min-w-0 truncate text-sm font-medium">{item.name || item.model}</span>
                  <span className="ml-auto shrink-0 text-xs text-muted-foreground">{providerLabel(item.provider)}</span>
                </Label>)}
                {!comparedPresets.length ? <p className="text-xs text-muted-foreground">{t("未选择时使用默认预设 {model}。", { model: preset.name || preset.model })}</p> : null}
              </div> : <Select value={preset.id} onValueChange={value => set({ preset: value })}>
                <SelectTrigger aria-label={t("预设模型")} className="w-full min-w-0"><SelectValue /></SelectTrigger>
                <SelectContent>{presets.map(item => <SelectItem key={item.id} value={item.id}>
                  <span className="font-medium">{item.name || item.model}</span><span className="text-muted-foreground">{providerLabel(item.provider)}</span>
                </SelectItem>)}</SelectContent>
              </Select>}
            </fieldset>

            {comparing && runs.length > MAX_COMPARED ? <p className="text-xs text-destructive">
              {t("一次最多对比 {max} 个运行，当前为 {count} 个。", { max: MAX_COMPARED, count: runs.length })}</p> : null}
            <Button size="lg" className="w-full" disabled={!ready || busy} onClick={() => void start()}>
              {busy ? <Spinner /> : comparing ? <Columns3 /> : <Play />}{label}
              {!busy ? <KbdGroup className="ml-1 hidden opacity-70 sm:inline-flex"><Kbd className="bg-primary-foreground/15 text-primary-foreground">Ctrl</Kbd>
                <Kbd className="bg-primary-foreground/15 text-primary-foreground">↵</Kbd></KbdGroup> : null}
            </Button>
          </CardContent>
        </Card>
      </aside>
    </div>
  </div>;
}
