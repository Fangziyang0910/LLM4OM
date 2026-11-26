import { type Dispatch, type SetStateAction, useEffect, useLayoutEffect, useRef, useState } from "react";
import { ArrowRight, ChevronDown, Clock, Columns3, Play, Settings2, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import { errorText } from "@/format";
import { t } from "@/i18n";
import type { BackendCatalog, Draft, Method, Options, Preset } from "@/types";

import { saveDraft } from "./draft";

const MAX_COMPARED = 12;
const CORE_METHODS = new Set(["direct", "or_llm_agent", "llmopt", "trival", "bind", "autoco"]);
const TIME_LIMITS = [
  { seconds: 15, label: "15 秒" },
  { seconds: 60, label: "60 秒" },
  { seconds: 180, label: "180 秒" },
] as const;

/** Self-contained methods ship their own built-in solver pool and need no external modeling library. */
const isSelfContained = (method: Method) => !!method.builtin_solver;
/** Methods declare the modeling libraries they support. */
const unsupported = (method: Method, language: string) =>
  !method.builtin_solver && !!method.languages && !method.languages.includes(language);

function revealMethod(list: HTMLElement | null) {
  const selected = list?.querySelector<HTMLElement>('[data-state="checked"]')?.closest("label");
  selected?.scrollIntoView?.({ block: "nearest" });
}

export type ModelingConfigProps = {
  options: Options;
  presets: Preset[];
  draft: Draft;
  setDraft: Dispatch<SetStateAction<Draft>>;
  onStart: (draft: Draft) => Promise<void>;
  onCompare: (draft: Draft, runs: { method: string; language: string; solver: string; preset: Preset }[]) => Promise<void>;
  openPresets: () => void;
  presetsStatus?: "loading" | "error" | "ready";
};

export function useRunLauncher({
  options,
  presets,
  draft,
  setDraft,
  onStart,
  onCompare,
  openPresets,
  presetsStatus = "ready",
  problem,
  disabled = false,
  reading = false,
  reviewFirst = false,
  onReview,
  beforeLaunch,
}: ModelingConfigProps & {
  problem: { description: string; data: Record<string, string>; origin?: string };
  disabled?: boolean;
  reading?: boolean;
  reviewFirst?: boolean;
  onReview?: () => void;
  beforeLaunch?: () => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [moreMethodsOpen, setMoreMethodsOpen] = useState(false);
  const methodList = useRef<HTMLDivElement>(null);
  const set = (change: Partial<Draft>) => setDraft(current => ({ ...current, ...change }));

  const comparing = !!draft.comparing;
  const preset = presets.find(item => item.id === draft.preset) ?? presets[0];
  const providerLabel = (id: string) => options.providers.find(item => item.id === id)?.label ?? id;
  const method = options.methods.find(item => item.id === draft.method) ?? options.methods[0];
  const coreMethods = options.methods.filter(item => CORE_METHODS.has(item.id));
  const extraMethods = options.methods.filter(item => !CORE_METHODS.has(item.id));
  const hasSelectedExtra = !CORE_METHODS.has(method.id) || (comparing && !!draft.methods?.some(id => !CORE_METHODS.has(id)));
  const showMoreMethods = moreMethodsOpen || hasSelectedExtra;
  const timeLimit = draft.time_limit ?? 60;
  const selfContained = isSelfContained(method);
  const supports = (language: string) => comparing || selfContained || !unsupported(method, language);
  const language = options.languages.find(item => item.id === draft.language && supports(item.id))
    ?? options.languages.find(item => supports(item.id))!;
  const backend = draft.solver ?? "AUTO";
  const catalog = useQuery({ queryKey: ["backends"], queryFn: () => api<BackendCatalog>("/api/backends"),
    enabled: (!selfContained || comparing) && (settingsOpen || !!problem.description.trim() || backend !== "AUTO"),
    staleTime: Infinity, retry: false });
  const backends = catalog.data?.libraries[language.id];
  const backendUnavailable = (!selfContained || comparing) && !!backends && !backends.some(item => item.id === backend && item.available);
  const compared = options.methods.filter(item => draft.methods?.includes(item.id) && !unsupported(item, language.id));
  const comparedPresets = presets.filter(item => draft.presets?.includes(item.id));
  const runs = compared.flatMap(item => (comparedPresets.length ? comparedPresets : preset ? [preset] : [])
    .map(chosen => ({
      method: item.id,
      language: isSelfContained(item) ? item.id : language.id,
      solver: isSelfContained(item) ? "AUTO" : backend,
      preset: chosen,
    })));

  useEffect(() => {
    const nextLanguage = selfContained && !comparing ? draft.language : language.id;
    if (method.id !== draft.method || nextLanguage !== draft.language) {
      setDraft(current => ({
        ...current,
        method: method.id,
        language: nextLanguage,
        solver: nextLanguage !== current.language ? undefined : current.solver,
      }));
    }
  }, [method.id, language.id, selfContained, comparing, draft.method, draft.language, setDraft]);
  useLayoutEffect(() => {
    void saveDraft(draft).catch(error => toast.error(t("草稿未保存到浏览器：{error}", { error: errorText(error) }), { id: "draft-save" }));
  }, [draft]);
  useEffect(() => {
    revealMethod(methodList.current);
  }, [method.id, comparing]);

  const ready = problem.description.trim().length > 0 && !disabled && !reading && !backendUnavailable && presetsStatus === "ready"
    && (!comparing || (runs.length >= 2 && runs.length <= MAX_COMPARED));

  const start = async () => {
    if (busy) return;
    if (reviewFirst) { onReview?.(); return; }
    if (!ready) return;
    if (!preset) { toast.error(t("请先配置一个可用的 AI 模型。")); openPresets(); return; }
    setBusy(true);
    try {
      await beforeLaunch?.();
      const request: Draft = {
        ...draft,
        description: problem.description,
        data: problem.data,
        origin: problem.origin,
        method: method.id,
        language: !comparing && selfContained ? method.id : language.id,
        solver: !comparing && selfContained ? "AUTO" : backend,
        preset: preset.id,
      };
      setDraft(request);
      await (comparing ? onCompare(request, runs) : onStart(request));
    } catch (error) { toast.error(errorText(error)); setBusy(false); }
  };

  const startRef = useRef(start);
  useEffect(() => { startRef.current = start; });
  useEffect(() => {
    if (disabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (!event.defaultPrevented && event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.isComposing && event.keyCode !== 229 && !document.querySelector("[role=dialog]")) {
        event.preventDefault(); void startRef.current();
      }
    };
    addEventListener("keydown", onKey);
    return () => removeEventListener("keydown", onKey);
  }, [disabled]);

  const toggle = (key: "methods" | "presets", id: string, on: boolean) =>
    set({ [key]: on ? [...(draft[key] ?? []).filter(item => item !== id), id] : (draft[key] ?? []).filter(item => item !== id) });

  const isDefaultConfig = !comparing && method.id === "direct" && language.id === "pyomo" && backend === "AUTO" && timeLimit === 60;
  const limitSuffix = timeLimit !== 60 ? ` · ${timeLimit}s` : "";
  const settingsBadge = comparing
    ? t("已选 {count} 个方案", { count: runs.length })
    : selfContained
      ? `${method.name}${limitSuffix}`
      : `${method.name} · ${language.name}${backend !== "AUTO" ? ` (${backend})` : ""}${limitSuffix}`;

  const label = reviewFirst ? t("检查需求稿") : reading ? t("正在读取数据……") : busy ? t("正在启动求解…")
    : comparing ? t("开始对比（{count} 个方案）", { count: runs.length }) : t("立即求解");

  const choiceClass = "relative flex min-h-11 min-w-0 cursor-pointer items-center gap-2.5 rounded-xl border px-3 py-2 text-sm font-normal transition-all duration-150 hover:bg-accent/50 has-focus-visible:border-ring has-focus-visible:ring-2 has-focus-visible:ring-ring/50 sm:min-h-9 sm:py-1.5";
  const renderChoice = (item: Method) => {
    const blocked = comparing && unsupported(item, language.id);
    const selected = comparing ? !blocked && !!draft.methods?.includes(item.id) : item.id === method.id;
    const id = `${comparing ? "compare" : "method"}-${item.id}`;
    return <Label key={item.id} htmlFor={id} title={blocked ? t("{method}：当前策略暂不支持所选求解引擎", { method: item.name }) : t(item.description)}
      className={cn(choiceClass, selected && "border-primary/50 bg-primary/8 shadow-2xs hover:bg-primary/10", blocked && "cursor-not-allowed opacity-45 hover:bg-transparent")}>
      {comparing ? <Checkbox id={id} checked={selected} disabled={blocked} onCheckedChange={on => toggle("methods", item.id, on === true)} />
        : <RadioGroupItem id={id} value={item.id} />}
      <span className="min-w-0 flex-1 truncate font-medium">{item.name}</span>
      {item.id === "direct" && !comparing ? <Badge variant="secondary" className="h-4.5 shrink-0 px-1.5 text-[10px] font-normal text-primary">{t("默认")}</Badge>
        : isSelfContained(item) ? <Badge variant="outline" className="h-4.5 shrink-0 px-1.5 text-[10px] font-normal text-primary/80">{t("智能优化")}</Badge>
          : item.linear_only ? <Badge variant="outline" className="h-4.5 shrink-0 px-1.5 text-[10px] font-normal text-muted-foreground">{t("线性/整数")}</Badge> : null}
    </Label>;
  };
  const methodListClass = "grid grid-cols-1 gap-1.5 sm:grid-cols-2";
  const groupedMethods = <div className="flex flex-col gap-3">
    <div className={methodListClass}>{(coreMethods.length ? coreMethods : options.methods).map(renderChoice)}</div>
    {extraMethods.length > 0 && coreMethods.length > 0 ? <Collapsible open={showMoreMethods} onOpenChange={setMoreMethodsOpen}>
      <CollapsibleTrigger className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground">
        <ChevronDown className={cn("size-3.5 transition-transform", !showMoreMethods && "-rotate-90")} />
        {t("更多研究方法（{count}）", { count: extraMethods.length })}
      </CollapsibleTrigger>
      <CollapsibleContent className={cn(methodListClass, "pt-2")}>{extraMethods.map(renderChoice)}</CollapsibleContent>
    </Collapsible> : null}
  </div>;

  const changeMode = (on: boolean) => set({ comparing: on, methods: on && !draft.methods?.length ? [method.id] : draft.methods });
  const settingsTrigger = <><ToggleGroup type="single" variant="outline" size="sm" aria-label={t("运行模式")} disabled={busy || disabled}
    value={comparing ? "compare" : "single"} onValueChange={value => { if (value) changeMode(value === "compare"); }}
    className="h-8 rounded-xl bg-background/80 shadow-2xs *:data-[slot=toggle-group-item]:h-8 *:data-[slot=toggle-group-item]:px-2.5 *:data-[slot=toggle-group-item]:text-xs">
    <ToggleGroupItem value="single" className="data-[spacing=0]:first:rounded-l-xl">{t("单次求解")}</ToggleGroupItem>
    <ToggleGroupItem value="compare" className="data-[spacing=0]:last:rounded-r-xl">{t("多方案对比")}</ToggleGroupItem>
  </ToggleGroup><button type="button" aria-label={t("查看运行设置")} aria-haspopup="dialog" onClick={() => setSettingsOpen(true)}
    title={t("点击调整 AI 模型、多方案对比或底层求解引擎")}
    className={cn(
      "inline-flex h-8 max-w-full items-center gap-1.5 rounded-xl border bg-background/80 px-2.5 text-xs font-normal shadow-2xs transition-colors hover:border-primary/40 hover:bg-accent/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
      (!isDefaultConfig || comparing) ? "border-primary/35 bg-primary/8 text-primary font-medium" : "text-muted-foreground")}>
    <SlidersHorizontal className="size-3.5 shrink-0" />
    <span className="truncate">{settingsBadge}</span>
  </button></>;

  const startButton = <div className="flex w-full flex-col items-end gap-1 sm:w-auto">
    {comparing && runs.length < 2 && !reviewFirst ? <button type="button" className="text-left text-xs text-primary underline" onClick={() => presets.length ? setSettingsOpen(true) : openPresets()}>
      {presets.length ? t("至少选择两个方案以开始对比") : t("配置 AI 模型")}</button> : null}
    {comparing && runs.length > MAX_COMPARED ? <p className="text-xs text-destructive">
      {t("一次最多对比 {max} 个方案，当前已选 {count} 个。", { max: MAX_COMPARED, count: runs.length })}</p> : null}
    <Button size="default" className="h-9 w-full gap-1.5 rounded-xl px-5 font-medium shadow-xs sm:w-auto"
      disabled={busy || (reviewFirst ? disabled || reading || !problem.description.trim() : !ready)} onClick={() => void start()}>
      {busy || reading ? <Spinner /> : reviewFirst ? <ArrowRight className="size-4" /> : comparing ? <Columns3 className="size-4" /> : <Play className="size-3.5 fill-current" />}
      <span>{label}</span>
    </Button>
  </div>;

  const settingsDialog = <Dialog open={settingsOpen} onOpenChange={setSettingsOpen}>
    <DialogContent onOpenAutoFocus={() => revealMethod(methodList.current)} className="flex max-h-[90dvh] flex-col gap-0 overflow-hidden rounded-2xl p-0 sm:max-w-2xl lg:max-w-5xl">
      <DialogTitle className="sr-only">{t("运行设置")}</DialogTitle>
      <DialogDescription className="sr-only">{t("选择建模方法、建模求解器和预设模型。")}</DialogDescription>
      <aside aria-label={t("运行设置")} className="flex min-h-0 min-w-0 flex-1 flex-col">
        <Card className="min-h-0 flex-1 gap-0 overflow-hidden border-0 py-0 shadow-none">
          <div className="flex h-14 shrink-0 items-center gap-2 border-b bg-muted/20 pr-12 pl-5">
            <div className="min-w-0">
              <h2 className="flex items-center gap-2 text-sm font-semibold"><Settings2 className="size-4 text-primary" />{t("求解偏好与高级设置")}</h2>
              <p className="hidden text-[11px] text-muted-foreground sm:block">{t("一般保持默认即可；需要对比不同策略或指定求解引擎时可在此调整。")}</p>
            </div>
            <Label className="ml-auto shrink-0 cursor-pointer gap-2 rounded-full border bg-background px-3 py-1 text-xs font-medium shadow-2xs" title={t("同一问题同时用多个策略或模型计算，并排核对结果")}>
              <Columns3 className="size-3.5 text-primary" />{t("多方案对比")}
              <Switch size="sm" checked={comparing} aria-label={t("对比多个方法")} onCheckedChange={changeMode} />
            </Label>
          </div>
          <div className="grid min-h-0 flex-1 grid-cols-1 divide-y overflow-y-auto lg:grid-cols-[1.2fr_1fr] lg:divide-y-0">
            <section aria-labelledby="methods-label" className="min-w-0 px-5 py-4 lg:row-span-2 lg:border-r">
              <h3 id="methods-label" className="mb-3 text-xs font-semibold text-foreground/80">{comparing ? t("建模策略（可多选）") : t("建模策略")}</h3>
              {comparing ? <div ref={methodList} role="group" aria-label={t("建模方法")}>{groupedMethods}</div>
                : <RadioGroup ref={methodList} value={method.id} onValueChange={value => set({ method: value })} aria-label={t("建模方法")}
                  aria-describedby="method-description">{groupedMethods}</RadioGroup>}
              <p id="method-description" title={comparing ? undefined : t(method.description)} className="mt-3 line-clamp-2 text-xs leading-relaxed text-muted-foreground">
                {comparing ? t("开启对比后，系统会并行运行所选策略并自动比对目标结果是否一致。") : t(method.description)}</p>
              <div className="mt-4 border-t pt-3.5">
                <Label className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-foreground/80">
                  <Clock className="size-3.5 text-muted-foreground" />{t("单次求解限时")}
                </Label>
                <div role="group" aria-label={t("单次求解限时")} className="grid grid-cols-3 gap-1.5">
                  {TIME_LIMITS.map(option => <button key={option.seconds} type="button" aria-pressed={timeLimit === option.seconds}
                    onClick={() => set({ time_limit: option.seconds === 60 ? undefined : option.seconds })}
                    className={cn("h-8 rounded-xl border text-xs font-medium transition-colors",
                      timeLimit === option.seconds ? "border-primary/50 bg-primary/10 text-primary" : "bg-background text-muted-foreground hover:bg-accent/60 hover:text-foreground")}>
                    {t(option.label)}
                  </button>)}
                </div>
              </div>
            </section>

            <section aria-labelledby="presets-label" className="min-w-0 px-5 py-4">
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 id="presets-label" className="text-xs font-semibold text-foreground/80">{comparing ? t("AI 模型（可多选）") : t("AI 模型")}</h3>
                <Button variant="link" size="sm" className="h-auto p-0 text-xs" onClick={() => { setSettingsOpen(false); openPresets(); }}>{t("管理模型")}</Button>
              </div>
              {!preset && presetsStatus !== "ready" ? <p role="status" className="flex items-center gap-2 text-xs text-muted-foreground">
                {presetsStatus === "loading" ? <Spinner /> : null}{presetsStatus === "loading" ? t("正在加载模型列表……") : t("模型列表暂不可用，请重试加载。")}
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
              {selfContained && !comparing ? <div className="rounded-xl border border-primary/25 bg-primary/5 p-3.5 text-xs leading-relaxed text-muted-foreground">
                <p className="font-medium text-foreground">{t("{method} 内置智能优化算法池", { method: method.name })}</p>
                <p className="mt-1">{t("内置 12 类启发式与进化算法（SA、TS、ILS、LNS、GA、CMA-ES、DE、PSO、ACO 及多目标 NSGA-II、MOEA/D、NSGA-III），由特征知识图谱与沙箱试跑自动选配，无需选择外部建模求解器。")}</p>
              </div> : <>
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
                    <SelectContent>{(backends
                      ? (backends.some(item => item.id === backend) ? backends : [{ id: backend, available: false, detail: "" }, ...backends])
                      : [{ id: backend, available: true, detail: "" }]).map(item =>
                      <SelectItem key={item.id} value={item.id} disabled={!item.available} title={item.detail}>
                        {item.id === "AUTO" ? t("自动匹配最优计算器") : item.id}{!item.available ? ` · ${t("当前环境未安装")}` : ""}
                      </SelectItem>)}</SelectContent>
                  </Select>
                  {catalog.isPending ? <p className="text-xs text-muted-foreground">{t("正在检查可用计算器……")}</p> : null}
                  {catalog.error ? <p className="text-xs text-destructive">{errorText(catalog.error)}</p> : null}
                  {backendUnavailable ? <p className="text-xs text-destructive">{t("所选计算器在当前环境不可用，请切换为自动匹配或其他选项。")}</p> : null}
                </div>
              </>}
            </section>
          </div>
        </Card>
      </aside>
      <div className="flex shrink-0 justify-end border-t bg-muted/20 px-5 py-3"><Button className="rounded-xl px-5" onClick={() => setSettingsOpen(false)}>{t("完成")}</Button></div>
    </DialogContent>
  </Dialog>;

  return { busy, setBusy, settingsTrigger, startButton, settingsDialog };
}
