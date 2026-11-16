import { type Dispatch, type ReactNode, type SetStateAction, useEffect, useRef, useState } from "react";
import { ArrowRight, BookOpen, CalendarClock, Columns3, Factory, MessageSquareText, Play, Settings2, SlidersHorizontal, Sparkles, Truck } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { useDefaultLayout } from "react-resizable-panels";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { useDesktop } from "@/lib/useDesktop";
import { api } from "@/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { errorText } from "@/format";
import { t } from "@/i18n";
import { ProblemEditor } from "@/features/composer/ProblemEditor";
import { readDataFiles } from "@/features/composer/files";
import type { Draft } from "@/features/composer/types";
import type { BackendCatalog, Method, Options, Preset } from "@/types";

const DRAFT_KEY = "llm4om-draft";
export const MAX_COMPARED = 12;

const STARTERS = [
  {
    icon: Factory,
    title: "生产计划",
    tag: "提升利润",
    summary: "在有限设备与工序额度下，合理安排多种产品的产量，让总利润最高。",
    description: "工厂生产 A、B 两种产品，数量必须是非负整数。每件 A 利润为 3，每件 B 利润为 2。A 消耗 2 单位切割资源和 1 单位加工资源，" +
      "B 消耗 1 单位切割资源和 2 单位加工资源。两种资源各有 8 单位。请确定生产数量，使总利润最大。",
  },
  {
    icon: Truck,
    title: "运输问题",
    tag: "附数据表",
    summary: "三个仓库向四个客户发货，自动读取表格算出总运费最低的调拨方案。",
    description: "三个仓库向四个客户运送同一种货物。各仓库的供应量、各客户的需求量和单位运费见数据文件 transport.csv：" +
      "前三行是仓库到客户的单位运费，supply 列是仓库供应量，最后一行 demand 是客户需求量。每个客户的需求必须恰好满足，" +
      "仓库发货不能超过供应量。请制定运输方案，使总运费最小。",
    data: { "transport.csv": "from,C1,C2,C3,C4,supply\nW1,4,6,9,5,120\nW2,7,3,4,8,150\nW3,6,5,7,3,100\ndemand,80,90,110,70,\n" },
  },
  {
    icon: CalendarClock,
    title: "任务指派",
    tag: "缩短工时",
    summary: "根据每位员工处理各项任务的耗时差异，安排一对一指派使总耗时最短。",
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
    solver: saved.solver ?? legacy?.[1].toUpperCase(), origin: saved.origin,
    comparing: saved.comparing ?? false, methods: saved.methods ?? [], presets: saved.presets ?? [] };
}

/** Methods declare the modeling libraries they support. */
const unsupported = (method: Method, language: string) => !!method.languages && !method.languages.includes(language);

function revealMethod(list: HTMLElement | null) {
  const selected = list?.querySelector<HTMLElement>('[data-state="checked"]')?.closest("label");
  selected?.scrollIntoView({ block: "nearest" });
}

export type ComposerProps = {
  options: Options; presets: Preset[]; draft: Draft; setDraft: Dispatch<SetStateAction<Draft>>; onStart: (draft: Draft) => Promise<void>;
  onCompare: (draft: Draft, runs: { method: string; preset: Preset }[]) => Promise<void>;
  openPresets: () => void; openExamples: () => void; onDiscuss?: () => Promise<void>;
  editor?: ReactNode; assistant?: ReactNode; disabled?: boolean;
  presetsStatus?: "loading" | "error" | "ready";
};

export function Composer({ options, presets, draft, setDraft, onStart, onCompare, openPresets, openExamples, onDiscuss, presetsStatus = "ready", editor, assistant, disabled = false }: ComposerProps) {
  const desktop = useDesktop();
  const layout = useDefaultLayout({ id: "llm4om-requirements", panelIds: ["conversation", "problem"], onlySaveAfterUserInteractions: true });
  const [busy, setBusy] = useState(false);
  const [reading, setReading] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [assistantOpen, setAssistantOpen] = useState(!!assistant);
  const [focusPane, setFocusPane] = useState(assistant ? "assistant" : "problem");
  const reviewFirst = !!assistant && assistantOpen && !desktop && focusPane === "assistant";
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
  const compared = options.methods.filter(item => draft.methods?.includes(item.id) && !unsupported(item, language.id));
  const comparedPresets = presets.filter(item => draft.presets?.includes(item.id));
  const runs = compared.flatMap(item => (comparedPresets.length ? comparedPresets : preset ? [preset] : [])
    .map(chosen => ({ method: item.id, preset: chosen })));

  useEffect(() => {
    if (method.id !== draft.method || language.id !== draft.language)
      set({ method: method.id, language: language.id, solver: language.id !== draft.language ? undefined : draft.solver });
  }, [method.id, language.id]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (disabled) return;
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch { /* storage may be unavailable or full */ }
  }, [draft, disabled]);
  useEffect(() => {
    revealMethod(methodList.current);
  }, [method.id, comparing]);

  const attach = async (list: FileList | null) => {
    setReading(true);
    try {
      const data = await readDataFiles(list, draft.data);
      setDraft(current => ({ ...current, data: { ...current.data, ...data } }));
    } finally { setReading(false); }
  };
  const ready = draft.description.trim().length > 0 && !disabled && !reading && !backendUnavailable && presetsStatus === "ready"
    && (!comparing || (runs.length > 0 && runs.length <= MAX_COMPARED));
  const start = async () => {
    if (busy) return;
    if (reviewFirst) { setFocusPane("problem"); return; }
    if (!ready) return;
    if (!preset) { toast.error(t("请先配置一个可用的 AI 模型。")); openPresets(); return; }
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
      if (!event.defaultPrevented && event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing && event.keyCode !== 229 && !document.querySelector("[role=dialog]")) {
        event.preventDefault(); void startRef.current();
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, []);
  const toggle = (key: "methods" | "presets", id: string, on: boolean) =>
    set({ [key]: on ? [...(draft[key] ?? []).filter(item => item !== id), id] : (draft[key] ?? []).filter(item => item !== id) });

  const isDefaultConfig = !comparing && method.id === "direct" && language.id === "pyomo" && backend === "AUTO";
  const settingsBadge = comparing
    ? t("多方案对比（{count}）", { count: runs.length })
    : isDefaultConfig
      ? t("智能推荐配置")
      : `${method.name} · ${language.name}`;

  const label = reviewFirst ? t("检查需求稿") : reading ? t("正在读取数据……") : busy ? t("正在启动求解…")
    : comparing ? t("开始对比（{count} 个方案）", { count: runs.length }) : t("立即求解");

  const choiceClass = "relative flex min-h-11 min-w-0 cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2 text-sm font-normal transition-all duration-150 hover:bg-accent/50 has-focus-visible:border-ring has-focus-visible:ring-2 has-focus-visible:ring-ring/50 sm:min-h-9 sm:py-1.5";
  const methodChoices = options.methods.map(item => {
    const blocked = unsupported(item, language.id);
    const selected = comparing ? !blocked && !!draft.methods?.includes(item.id) : item.id === method.id;
    const id = `${comparing ? "compare" : "method"}-${item.id}`;
    return <Label key={item.id} htmlFor={id} title={blocked ? t("{method}：当前策略暂不支持所选求解引擎", { method: item.name }) : t(item.description)}
      className={cn(choiceClass, selected && "border-primary/50 bg-primary/8 shadow-2xs hover:bg-primary/10", blocked && "cursor-not-allowed opacity-45 hover:bg-transparent")}>
      {comparing ? <Checkbox id={id} checked={selected} disabled={blocked} onCheckedChange={on => toggle("methods", item.id, on === true)} />
        : <RadioGroupItem id={id} value={item.id} disabled={blocked} />}
      <span className="min-w-0 flex-1 truncate font-medium">{item.name}</span>
      {item.id === "direct" && !comparing ? <Badge variant="secondary" className="h-4.5 shrink-0 px-1.5 text-[10px] font-normal text-primary">{t("默认")}</Badge>
        : item.linear_only ? <Badge variant="outline" className="h-4.5 shrink-0 px-1.5 text-[10px] font-normal text-muted-foreground">{t("线性/整数")}</Badge> : null}
    </Label>;
  });
  const methodListClass = "grid grid-cols-1 gap-1.5 sm:grid-cols-2";

  const settingsPanel = <aside aria-label={t("运行设置")} className="flex min-h-0 min-w-0 flex-1 flex-col">
    <Card className="min-h-0 flex-1 gap-0 overflow-hidden border-0 py-0 shadow-none">
      <div className="flex h-14 shrink-0 items-center gap-2 border-b bg-muted/20 pr-12 pl-5">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><Settings2 className="size-4 text-primary" />{t("求解偏好与高级设置")}</h2>
          <p className="hidden text-[11px] text-muted-foreground sm:block">{t("一般保持默认即可；需要对比不同策略或指定求解引擎时可在此调整。")}</p>
        </div>
        <Label className="ml-auto shrink-0 cursor-pointer gap-2 rounded-full border bg-background px-3 py-1 text-xs font-medium shadow-2xs" title={t("同一问题同时用多个策略或模型计算，并排核对结果")}>
          <Columns3 className="size-3.5 text-primary" />{t("多方案对比")}
          <Switch size="sm" checked={comparing} aria-label={t("对比多个方法")} onCheckedChange={on => set({ comparing: on,
            methods: on && !draft.methods?.length ? [method.id] : draft.methods })} />
        </Label>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 divide-y overflow-y-auto lg:grid-cols-[1.2fr_1fr] lg:divide-y-0">
        <section aria-labelledby="methods-label" className="min-w-0 px-5 py-4 lg:row-span-2 lg:border-r">
          <h3 id="methods-label" className="mb-3 text-xs font-semibold text-foreground/80">{comparing ? t("建模策略（可多选）") : t("建模策略")}</h3>
          {comparing ? <div ref={methodList} role="group" aria-label={t("建模方法")} className={methodListClass}>{methodChoices}</div>
            : <RadioGroup ref={methodList} value={method.id} onValueChange={value => set({ method: value })} aria-label={t("建模方法")}
              aria-describedby="method-description" className={methodListClass}>{methodChoices}</RadioGroup>}
          <p id="method-description" title={comparing ? undefined : t(method.description)} className="mt-2.5 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
            {t(comparing ? "开启对比后，系统会并行运行所选策略并自动比对目标结果是否一致。" : method.description)}</p>
        </section>

        <section aria-labelledby="presets-label" className="min-w-0 px-5 py-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <h3 id="presets-label" className="text-xs font-semibold text-foreground/80">{comparing ? t("AI 模型（可多选）") : t("AI 模型")}</h3>
            <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => { setSettingsOpen(false); openPresets(); }}>{t("管理模型")}</Button>
          </div>
          {!preset && presetsStatus !== "ready" ? <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
            {presetsStatus === "loading" ? <Spinner /> : null}{t(presetsStatus === "loading" ? "正在加载模型列表……" : "模型列表暂不可用，请重试加载。")}
          </p> : !preset ? <Alert>
            <AlertDescription className="flex flex-col items-start gap-2">{t("尚未配置可用的 AI 模型。")}
              <Button size="sm" onClick={() => { setSettingsOpen(false); openPresets(); }}>{t("去添加模型")}</Button></AlertDescription>
          </Alert> : comparing ? <div role="group" aria-label={t("预设模型")} className="flex flex-col gap-1.5">
            {presets.map(item => <Label key={item.id} htmlFor={`compare-preset-${item.id}`} className={cn(choiceClass, "py-2 sm:py-2")}
              title={item.name || item.model}>
              <Checkbox id={`compare-preset-${item.id}`} checked={!!draft.presets?.includes(item.id)} onCheckedChange={on => toggle("presets", item.id, on === true)} />
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate text-sm font-medium">{item.name || item.model}</span>
                <span className="truncate text-xs text-muted-foreground">{providerLabel(item.provider)}</span>
              </span>
            </Label>)}
            {!comparedPresets.length ? <p className="text-xs text-muted-foreground">{t("未勾选时默认使用 {model}。", { model: preset.name || preset.model })}</p> : null}
          </div> : <>
            <Select value={preset.id} onValueChange={value => set({ preset: value })}>
              <SelectTrigger aria-label={t("预设模型")} className="w-full min-w-0 rounded-xl" title={preset.name || preset.model}>
                <SelectValue>{preset.name || preset.model}</SelectValue></SelectTrigger>
              <SelectContent>{presets.map(item => <SelectItem key={item.id} value={item.id}>
                <span className="font-medium">{item.name || item.model}</span><span className="text-muted-foreground">{providerLabel(item.provider)}</span>
              </SelectItem>)}</SelectContent>
            </Select>
            <p className="mt-1.5 text-xs text-muted-foreground">{providerLabel(preset.provider)}</p>
          </>}
        </section>

        <section aria-labelledby="libraries-label" className="min-w-0 px-5 py-4 lg:border-t">
          <h3 id="libraries-label" className="mb-3 text-xs font-semibold text-foreground/80">{t("底层求解引擎（专业项）")}</h3>
          <RadioGroup value={language.id} onValueChange={value => set({ language: value, solver: undefined })} aria-label={t("建模求解器")}
            className="grid grid-cols-3 gap-1.5">
            {options.languages.map(item => {
              const allowed = supports(item.id);
              const tile = <Label htmlFor={`language-${item.id}`} className={cn(choiceClass, "h-full justify-center px-1.5 text-center",
                item.id === language.id && "border-primary/50 bg-primary/8 shadow-2xs hover:bg-primary/10", !allowed && "cursor-not-allowed opacity-45 hover:bg-transparent")}>
                <RadioGroupItem id={`language-${item.id}`} value={item.id} disabled={!allowed} className="sr-only" />
                <span className="text-xs font-medium sm:text-[13px]">{item.name}</span>
              </Label>;
              return allowed ? <div key={item.id}>{tile}</div> : <Tooltip key={item.id}>
                <TooltipTrigger asChild><div>{tile}</div></TooltipTrigger>
                <TooltipContent>{t("{method}：当前策略暂不支持该求解引擎", { method: method.name })}</TooltipContent>
              </Tooltip>;
            })}
          </RadioGroup>
          <div className="mt-3.5 flex flex-col gap-1.5">
            <Label htmlFor="solver-backend" className="text-xs text-muted-foreground">{t("数值计算器")}</Label>
            <Select value={backend} onValueChange={value => set({ solver: value })}>
              <SelectTrigger id="solver-backend" aria-label={t("求解后端")} className="w-full rounded-xl"><SelectValue /></SelectTrigger>
              <SelectContent>{(backends ?? [{ id: backend, available: true, detail: "" }]).map(item =>
                <SelectItem key={item.id} value={item.id} disabled={!item.available} title={item.detail}>
                  {item.id === "AUTO" ? t("自动匹配最优计算器") : item.id}{!item.available ? ` · ${t("当前环境未安装")}` : ""}
                </SelectItem>)}</SelectContent>
            </Select>
            {catalog.isPending ? <p className="text-xs text-muted-foreground">{t("正在检查可用计算器……")}</p> : null}
            {catalog.error ? <p className="text-xs text-destructive">{errorText(catalog.error)}</p> : null}
            {backendUnavailable ? <p className="text-xs text-destructive">{t("所选计算器在当前环境不可用，请切换为自动匹配或其他选项。")}</p> : null}
          </div>
        </section>
      </div>
    </Card>
  </aside>;

  const settingsTrigger = <button type="button" aria-label={t("查看运行设置")} aria-haspopup="dialog" onClick={() => setSettingsOpen(true)}
    title={t("点击调整 AI 模型、多方案对比或底层求解引擎")}
    className={cn(
      "inline-flex h-8 max-w-full items-center gap-1.5 rounded-xl border bg-background/80 px-2.5 text-xs font-normal shadow-2xs transition-colors hover:border-primary/40 hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      (!isDefaultConfig || comparing) ? "border-primary/35 bg-primary/8 text-primary font-medium" : "text-muted-foreground")}>
    <SlidersHorizontal className="size-3.5 shrink-0" />
    <span className="truncate">{settingsBadge}</span>
  </button>;

  const discussTrigger = !assistant && onDiscuss ? <Button type="button" variant="ghost" size="sm"
    className="h-8 rounded-xl px-2.5 text-xs font-normal text-muted-foreground hover:text-foreground"
    disabled={busy || reading} onClick={async () => {
      setBusy(true);
      try { await onDiscuss(); } catch (error) { toast.error(errorText(error)); } finally { setBusy(false); }
    }}>
    <MessageSquareText className="size-3.5 text-primary/80" />{t("边聊边梳理")}
  </Button> : null;

  const startButton = <div className="flex w-full flex-col items-end gap-1 sm:w-auto">
    {comparing && runs.length > MAX_COMPARED ? <p className="text-xs text-destructive">
      {t("一次最多对比 {max} 个方案，当前已选 {count} 个。", { max: MAX_COMPARED, count: runs.length })}</p> : null}
    <Button size="default" className="h-9 w-full gap-1.5 rounded-xl px-5 font-medium shadow-xs sm:w-auto"
      disabled={busy || (reviewFirst ? disabled || reading || !draft.description.trim() : !ready)} onClick={() => void start()}>
      {busy || reading ? <Spinner /> : reviewFirst ? <ArrowRight className="size-4" /> : comparing ? <Columns3 className="size-4" /> : <Play className="size-3.5 fill-current" />}
      <span>{label}</span>
    </Button>
  </div>;

  const problemPanel = <TabsContent value="problem" forceMount className="mt-0 flex h-full min-h-0 min-w-0 flex-col gap-5 data-[state=inactive]:hidden lg:data-[state=inactive]:flex">
    {editor ? <div className="flex min-h-0 flex-1 flex-col gap-3">
      {editor}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 rounded-2xl border bg-card px-3.5 py-2.5 shadow-2xs">
        <div className="flex flex-wrap items-center gap-2">{settingsTrigger}</div>
        {startButton}
      </div>
    </div> : <ProblemEditor autoFocus value={draft.description} data={draft.data} reading={reading} onChange={description => set({ description })}
      onFiles={list => void attach(list)}
      toolbarExtra={<>{settingsTrigger}{discussTrigger}</>}
      primaryAction={startButton}
      onClear={() => {
        const previous = { description: draft.description, data: draft.data, origin: draft.origin }; set({ description: "", data: {}, origin: undefined });
        toast.success(t("已清空问题和附件。"), { action: { label: t("撤销"), onClick: () => set(previous) } });
      }}
      onDataChange={(name, content) => setDraft(current => ({ ...current, data: { ...current.data, [name]: content } }))}
      onRemove={name => setDraft(current => {
        const data = { ...current.data }; delete data[name]; return { ...current, data };
      })} />}

    {!draft.description && !assistant ? <section className="animate-fade-up flex shrink-0 flex-col gap-2.5">
      <div className="flex items-center justify-between gap-2 px-0.5">
        <h2 className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground"><Sparkles className="size-3.5 text-primary/80" />{t("不知道怎么写？点选常见场景立即体验")}</h2>
      </div>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {STARTERS.map(item => {
          const Icon = item.icon;
          return <button key={item.title} type="button" onClick={() => set({ description: t(item.description), data: item.data ?? {}, origin: undefined })}
            className="group flex min-w-0 items-start gap-3 rounded-2xl border bg-card/90 p-3.5 text-left shadow-2xs transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card hover:shadow-sm">
            <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-primary/10 text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
              <Icon className="size-4.5" />
            </span>
            <span className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="flex items-center gap-2 text-sm">
                <span className="font-semibold text-foreground">{t(item.title)}</span>
                <Badge variant="secondary" className="h-5 rounded-md px-1.5 text-[11px] font-normal">{t(item.tag)}</Badge>
                <ArrowRight className="ml-auto size-3.5 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-primary" />
              </span>
              <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{t(item.summary)}</span>
            </span>
          </button>;
        })}
        <button type="button" onClick={openExamples}
          className="group flex min-w-0 items-start gap-3 rounded-2xl border border-dashed bg-card/50 p-3.5 text-left transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/40 hover:bg-card hover:shadow-sm">
          <span className="mt-0.5 grid size-9 shrink-0 place-items-center rounded-xl bg-accent text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
            <BookOpen className="size-4.5" />
          </span>
          <span className="flex min-w-0 flex-1 flex-col gap-1">
            <span className="flex items-center gap-2 text-sm font-semibold text-foreground">
              <span>{t("浏览案例模板库")}</span>
              <ArrowRight className="ml-auto size-3.5 text-muted-foreground/60 transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-primary" />
            </span>
            <span className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">{t("涵盖生产制造、仓储配送、排班调度等真实优化场景，一键填入修改。")}</span>
          </span>
        </button>
      </div>
    </section> : null}
  </TabsContent>;

  const conversationPanel = assistant ? <TabsContent value="assistant" forceMount className={cn("mt-0 h-full min-h-0 min-w-0 data-[state=inactive]:hidden", assistantOpen ? "lg:data-[state=inactive]:block" : "hidden")}>
    <aside aria-label={t("需求助手")} className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border bg-card shadow-xs">{assistant}</aside>
  </TabsContent> : null;

  return <div className="flex h-full flex-col">
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className={cn("mx-auto flex min-h-full flex-col gap-4 p-4 sm:px-6 sm:py-5 lg:h-full",
        assistant ? "max-w-6xl h-full" : "max-w-5xl")}>
        <header className="animate-fade-up flex shrink-0 flex-col gap-2">
          {!assistant ? <>
            <div className="hidden flex-wrap items-center gap-2 text-xs text-muted-foreground sm:flex" aria-label={t("使用步骤")}>
              <span className="inline-flex items-center gap-1.5 rounded-full border bg-card/80 px-2.5 py-0.5 font-medium text-foreground/85 shadow-2xs">
                <span className="grid size-4 place-items-center rounded-full bg-primary/15 text-[10px] font-semibold text-primary">1</span>{t("描述目标与条件")}
              </span>
              <span className="text-muted-foreground/50">→</span>
              <span className="inline-flex items-center gap-1.5 rounded-full border bg-card/80 px-2.5 py-0.5">
                <span className="grid size-4 place-items-center rounded-full bg-muted text-[10px] font-semibold">2</span>{t("上传表格（可选）")}
              </span>
              <span className="text-muted-foreground/50">→</span>
              <span className="inline-flex items-center gap-1.5 rounded-full border bg-card/80 px-2.5 py-0.5">
                <span className="grid size-4 place-items-center rounded-full bg-muted text-[10px] font-semibold">3</span>{t("自动求得最优方案")}
              </span>
            </div>
            <div>
              <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">{t("你想解决什么优化问题？")}</h1>
              <p className="mt-1 hidden text-[13px] leading-relaxed text-muted-foreground sm:block">{t("无需编写公式或代码：用日常语言说明目标（如降低成本、提高利润、合理排班）与限制条件，系统将自动完成数学建模并算出最优方案。")}</p>
            </div>
          </> : <div className="flex flex-wrap items-center justify-between gap-2">
            <h1 className="hidden text-lg font-semibold tracking-tight lg:block">{t("边聊边梳理需求")}</h1>
            <Button variant="ghost" size="sm" className="ml-auto rounded-xl text-xs text-muted-foreground" disabled={busy || reading}
              aria-expanded={assistantOpen} onClick={() => { setAssistantOpen(value => !value); setFocusPane("assistant"); }}>
              <MessageSquareText className="size-3.5" />{assistantOpen ? t("收起对话助手") : t("展开对话助手")}
            </Button>
          </div>}
        </header>

        <Tabs value={assistant && assistantOpen ? focusPane : "problem"} onValueChange={setFocusPane} className="min-h-0 flex-1 gap-3">
          {assistant && assistantOpen ? <TabsList className="grid shrink-0 grid-cols-2 rounded-xl lg:hidden" aria-label={t("问题与助手")}>
            <TabsTrigger value="assistant" className="rounded-lg">{t("对话助手")}</TabsTrigger>
            <TabsTrigger value="problem" className="rounded-lg">{t("当前需求稿")}</TabsTrigger>
          </TabsList> : null}
          {desktop && assistant && assistantOpen ? <ResizablePanelGroup orientation="horizontal" defaultLayout={layout.defaultLayout} onLayoutChanged={layout.onLayoutChanged} className="min-h-0 flex-1">
            <ResizablePanel id="conversation" defaultSize="42%" minSize="320px">{conversationPanel}</ResizablePanel>
            <ResizableHandle withHandle aria-label={t("调整对话与需求稿的宽度")} className="mx-2 bg-transparent" />
            <ResizablePanel id="problem" defaultSize="58%" minSize="35%">{problemPanel}</ResizablePanel>
          </ResizablePanelGroup> : <div className="grid min-h-0 flex-1 grid-cols-1 items-stretch gap-4">{conversationPanel}{problemPanel}</div>}
        </Tabs>

        {reviewFirst ? <div className="shrink-0 pt-1">{startButton}</div> : null}
      </div>
    </div>

    <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
      <DialogContent onOpenAutoFocus={() => revealMethod(methodList.current)} className="flex max-h-[90dvh] flex-col gap-0 overflow-hidden rounded-2xl p-0 sm:max-w-2xl lg:max-w-5xl">
        <DialogTitle className="sr-only">{t("运行设置")}</DialogTitle>
        <DialogDescription className="sr-only">{t("选择建模方法、建模求解器和预设模型。")}</DialogDescription>
        {settingsPanel}
        <div className="flex shrink-0 justify-end border-t bg-muted/20 px-5 py-3"><Button className="rounded-xl px-5" onClick={() => setSettingsOpen(false)}>{t("完成")}</Button></div>
      </DialogContent>
    </Dialog>
  </div>;
}
