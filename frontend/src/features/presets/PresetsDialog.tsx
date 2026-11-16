import { useState } from "react";
import { ChevronDown, Cpu, KeyRound, Plus, RefreshCw, ShieldCheck, Trash2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Spinner } from "@/components/ui/spinner";
import { cn } from "@/lib/utils";
import { api } from "@/api";
import { errorText, formatTokens } from "@/format";
import { t } from "@/i18n";
import type { Preset, Presets, Provider } from "@/types";

type Form = { name: string; provider: string; model: string; api_key: string; base_url: string; temperature: string; max_tokens: string; extra_body: string };

const emptyForm = (provider: Provider): Form =>
  ({ name: "", provider: provider.id, model: "", api_key: "", base_url: provider.base_url, temperature: "", max_tokens: "", extra_body: "" });

function Field({ label, htmlFor, help, error, children }: { label: string; htmlFor: string; help?: string; error?: string | null; children: React.ReactNode }) {
  return <div className="flex flex-col gap-1.5">
    <Label htmlFor={htmlFor} className="text-xs font-medium">{label}</Label>
    {children}
    {error || help ? <p className={cn("text-xs", error ? "text-destructive" : "text-muted-foreground")}>{error ?? help}</p> : null}
  </div>;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="grid grid-cols-1 gap-1 border-b border-border/60 py-2.5 text-sm last:border-0 sm:grid-cols-[7.5rem_minmax(0,1fr)] sm:gap-3">
    <dt className="text-xs text-muted-foreground sm:text-sm">{label}</dt><dd className="min-w-0 [overflow-wrap:anywhere]">{children}</dd>
  </div>;
}

/** LLM presets: each is fixed once added. They can be added and deleted, never edited; keys are never shown again. */
export function PresetsDialog({ onClose, presets, dailyTokens, providers, onChange }: {
  onClose: () => void; presets: Preset[]; dailyTokens: number; providers: Provider[]; onChange: (presets: Presets, message: string) => void;
}) {
  const [viewing, setViewing] = useState<string | null>(presets[0]?.id ?? null);  // null: the add form
  const [form, setForm] = useState<Form>(() => emptyForm(providers[0]));
  const [models, setModels] = useState<string[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState<"add" | "models" | "delete" | null>(null);
  const [confirming, setConfirming] = useState(false);  // deleting takes a second click

  const label = (id: string) => providers.find(item => item.id === id)?.label ?? id;
  const shown = presets.find(item => item.id === viewing);
  const provider = providers.find(item => item.id === form.provider) ?? providers[0];
  const set = (field: keyof Form) => (event: { target: { value: string } }) => {
    setForm({ ...form, [field]: event.target.value });
    if (field === "base_url" || field === "api_key") setModels(null);
  };
  const show = (id: string | null) => { setViewing(id); setProblem(null); setConfirming(false); };
  let extraError: string | null = null;
  try {
    if (form.extra_body.trim()) {
      const extra: unknown = JSON.parse(form.extra_body);
      if (extra === null || Array.isArray(extra) || typeof extra !== "object")
        extraError = t("请填写 JSON 对象，不能是数组、空值或单个值。");
    }
  } catch { extraError = t("不是有效的 JSON。"); }
  const body = () => ({
    name: form.name.trim(), provider: form.provider, model: form.model.trim(), api_key: form.api_key.trim(),
    base_url: form.base_url.trim(),
    temperature: form.temperature === "" ? null : Number(form.temperature),
    max_tokens: form.max_tokens === "" ? null : Number(form.max_tokens),
    extra_body: form.extra_body.trim() ? JSON.parse(form.extra_body) : {},
  });
  const act = async (kind: "add" | "models" | "delete", action: () => Promise<void>) => {
    setBusy(kind); setProblem(null);
    try { await action(); } catch (error) { setProblem(errorText(error)); } finally { setBusy(null); }
  };
  const add = () => act("add", async () => {
    const saved = await api<Presets>("/api/presets", body());
    onChange(saved, t("已添加预设 {model}。", { model: form.name.trim() || form.model.trim() }));
    setForm(emptyForm(provider)); setModels(null);
    show(saved.presets.at(-1)?.id ?? null);
  });
  const remove = (preset: Preset) => act("delete", async () => {
    const saved = await api<Presets>(`/api/presets/${encodeURIComponent(preset.id)}`, undefined, "DELETE");
    onChange(saved, t("已删除预设 {model}。", { model: preset.name || preset.model }));
    show(saved.presets[0]?.id ?? null);
  });
  const listModels = () => act("models", async () => setModels((await api<{ models: string[] }>("/api/models", body())).models));
  const filtered = models?.filter(item => item.toLowerCase().includes(form.model.trim().toLowerCase())) ?? [];

  return <Dialog open onOpenChange={open => { if (!open && !busy) onClose(); }}>
    <DialogContent showCloseButton={!busy} className="flex max-h-[90dvh] flex-col gap-0 overflow-hidden rounded-2xl p-0 sm:max-w-3xl">
      <DialogHeader className="border-b bg-muted/20 px-6 py-4">
        <DialogTitle className="flex items-center gap-2 text-base font-semibold">
          <span className="grid size-7 place-items-center rounded-lg bg-primary/10 text-primary"><Cpu className="size-4" /></span>
          {t("AI 模型设置")}
        </DialogTitle>
        <DialogDescription>{t("选择或接入用于智能对话与优化建模的 AI 模型，密钥仅加密保存在服务端。")}</DialogDescription>
      </DialogHeader>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav aria-label={t("预设列表")} className="flex min-h-0 shrink-0 gap-1.5 overflow-auto border-b bg-muted/15 p-2.5 md:w-56 md:flex-col md:border-r md:border-b-0">
          {presets.map((item, index) => {
            const active = viewing === item.id;
            return <button key={item.id} disabled={!!busy} aria-current={active} onClick={() => show(item.id)}
              className={cn("flex min-w-0 shrink-0 flex-col items-start gap-0.5 rounded-xl px-3 py-2.5 text-left text-sm transition-all md:w-full",
                active ? "bg-primary/10 text-primary shadow-2xs ring-1 ring-primary/20" : "text-foreground/85 hover:bg-accent")}>
              <span className="flex max-w-44 items-center gap-2 font-medium"><span className="min-w-0 truncate">{item.name || item.model}</span>
                {index === 0 ? <Badge className="h-4 shrink-0 px-1.5 text-[10px]">{t("默认")}</Badge> : null}</span>
              <span className={cn("max-w-44 truncate text-[11px]", active ? "text-primary/80" : "text-muted-foreground")}>
                {label(item.provider)}{item.source === "env" ? t(" · 系统内置") : ""}
              </span>
            </button>;
          })}
          <button disabled={!!busy} aria-current={viewing === null} onClick={() => show(null)}
            className={cn("flex shrink-0 items-center gap-2 rounded-xl px-3 py-2.5 text-sm font-medium transition-all",
              viewing === null ? "bg-primary/10 text-primary ring-1 ring-primary/20" : "text-muted-foreground hover:bg-accent hover:text-foreground")}>
            <Plus className="size-4" />{t("添加模型")}</button>
        </nav>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-4 sm:p-6">
          {shown ? <>
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-2xl border border-border/80 bg-muted/20 p-4">
              <div className="min-w-0 space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-base font-semibold break-all">{shown.name || shown.model}</h3>
                  <Badge variant="secondary" className="font-normal">{label(shown.provider)}</Badge>
                </div>
                <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <ShieldCheck className="size-3.5 text-success" />
                  {shown.source === "env" ? t("由服务端统一提供，可直接用于对话与求解") : t("自定义接入模型，密钥安全存储于服务端")}
                </p>
              </div>
            </div>
            <dl className="rounded-xl border border-border/70 bg-card px-4 py-1">
              <Fact label={t("服务商")}>{label(shown.provider)}</Fact>
              <Fact label={t("模型 ID")}><span className="font-mono text-xs">{shown.model}</span></Fact>
              <Fact label={t("API 密钥")}><span className="flex items-center gap-1.5 text-muted-foreground"><KeyRound className="size-3.5" />{t("已保存在服务器，不可查看")}</span></Fact>
              <Fact label={t("今日用量")}><span className="tabular">{dailyTokens
                ? t("{used} / {limit}（每日额度）", { used: formatTokens(shown.tokens_today), limit: formatTokens(dailyTokens) })
                : t("已用 {used}（不限额度）", { used: formatTokens(shown.tokens_today) })}</span></Fact>
            </dl>
            <Collapsible className="group/tech rounded-xl border border-border/70 bg-muted/15">
              <CollapsibleTrigger type="button" className="flex w-full items-center gap-2 px-4 py-2.5 text-xs font-medium text-muted-foreground hover:text-foreground">
                {t("技术参数详情")}<ChevronDown className="ml-auto size-4 transition-transform group-data-[state=open]/tech:rotate-180" />
              </CollapsibleTrigger>
              <CollapsibleContent className="border-t border-border/60 px-4 py-2">
                <dl>
                  <Fact label={t("接口地址")}><span className="font-mono text-xs">{shown.base_url || providers.find(item => item.id === shown.provider)?.base_url}</span></Fact>
                  <Fact label={t("温度")}>{shown.temperature ?? t("服务默认")}</Fact>
                  <Fact label={t("最大输出长度")}>{shown.max_tokens ?? t("服务默认")}</Fact>
                  <Fact label={t("额外请求参数")}>{Object.keys(shown.extra_body).length
                    ? <code className="font-mono text-xs">{JSON.stringify(shown.extra_body)}</code> : t("无")}</Fact>
                </dl>
                {shown.source === "env" ? <p className="py-2 text-xs text-muted-foreground">
                  {t("该模型由服务端默认配置提供，如需更换默认配置可由管理员在服务端调整。")}
                </p> : null}
              </CollapsibleContent>
            </Collapsible>
          </> : <form id="preset-form" className="flex flex-col gap-4" onSubmit={event => {
            event.preventDefault(); if (!busy && !extraError && form.model.trim() && form.api_key.trim()) void add();
          }}>
            <fieldset disabled={!!busy} className="flex min-w-0 flex-col gap-4">
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label={t("服务商")} htmlFor="provider">
                  <Select value={form.provider} onValueChange={value => { setForm(emptyForm(providers.find(item => item.id === value)!)); setModels(null); }}>
                    <SelectTrigger id="provider" className="w-full"><SelectValue /></SelectTrigger>
                    <SelectContent>{providers.map(item => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}</SelectContent>
                  </Select>
                </Field>
                <Field label={t("预设名称")} htmlFor="preset-name" help={t("仅用于显示；留空时使用模型 ID。")}>
                  <Input id="preset-name" value={form.name} onChange={set("name")} placeholder={t("例如：主力推理模型")} />
                </Field>
              </div>
              <Field label={t("API 密钥")} htmlFor="api-key" help={t("保存后不再显示。")}>
                <Input id="api-key" type="password" autoComplete="off" value={form.api_key} onChange={set("api_key")} placeholder={t("输入密钥")} />
              </Field>
              <Field label={t("模型 ID")} htmlFor="model-id">
                <div className="flex flex-col gap-2 sm:flex-row">
                  <Input id="model-id" value={form.model} onChange={set("model")} placeholder={t("例如 deepseek-chat")} />
                  <Button type="button" variant="outline" disabled={!!busy || !!extraError || !form.api_key.trim()} onClick={() => void listModels()}>
                    {busy === "models" ? <Spinner /> : <RefreshCw />}{t("读取可用模型")}</Button>
                </div>
                {models ? <div className="flex max-h-36 flex-wrap gap-1.5 overflow-y-auto pt-1">
                  {filtered.slice(0, 60).map(item => <Button key={item} type="button" size="xs" variant={item === form.model ? "default" : "secondary"}
                    className="h-auto max-w-full font-mono font-normal whitespace-normal break-all" onClick={() => setForm({ ...form, model: item })}>{item}</Button>)}
                  {!filtered.length ? <p className="text-xs text-muted-foreground">{models.length ? t("没有匹配的模型。") : t("服务没有返回模型列表，请直接填写。")}</p> : null}
                </div> : null}
              </Field>
              <Field label={t("接口地址")} htmlFor="base-url">
                <Input id="base-url" value={form.base_url} onChange={set("base_url")} placeholder="https://example.com/v1" />
              </Field>

              <Collapsible className="group/advanced rounded-xl border border-border/70">
                <CollapsibleTrigger type="button" className="flex w-full items-center gap-2 px-3.5 py-2.5 text-sm font-medium">
                  {t("高级参数")}<ChevronDown className="ml-auto size-4 text-muted-foreground transition-transform group-data-[state=open]/advanced:rotate-180" /></CollapsibleTrigger>
                <CollapsibleContent className="flex flex-col gap-4 border-t p-3.5">
                  <div className="grid grid-cols-2 gap-3">
                    <Field label={t("温度")} htmlFor="temperature"><Input id="temperature" type="number" step="0.1" min="0" value={form.temperature} onChange={set("temperature")} placeholder={t("服务默认")} /></Field>
                    <Field label={t("最大输出 token")} htmlFor="max-tokens"><Input id="max-tokens" type="number" min="1" value={form.max_tokens} onChange={set("max_tokens")} placeholder={t("服务默认")} /></Field>
                  </div>
                  <Field label={t("额外请求参数（JSON）")} htmlFor="extra-body" error={extraError}
                    help={t("填写所选服务商支持的请求参数。所有建模方法沿用所选预设的模型和思考配置。")}>
                    <Input id="extra-body" value={form.extra_body} onChange={set("extra_body")} className="font-mono text-xs"
                      placeholder={t("例如 {example}", { example: '{"thinking": {"type": "enabled"}}' })} aria-invalid={!!extraError} />
                  </Field>
                </CollapsibleContent>
              </Collapsible>
            </fieldset>
          </form>}
          {problem ? <Alert variant="destructive" role="alert"><AlertDescription>{problem}</AlertDescription></Alert> : null}
        </div>
      </div>
      <DialogFooter className="border-t bg-card px-6 py-3 sm:justify-between">
        {shown?.source === "saved" ? <Button variant="ghost" className="text-destructive hover:text-destructive" disabled={!!busy}
          onClick={() => confirming ? void remove(shown) : setConfirming(true)}>
          {busy === "delete" ? <Spinner /> : <Trash2 />}{confirming ? t("确认删除？") : t("删除这个预设")}</Button> : <span />}
        <div className="flex gap-2">
          <Button variant="outline" disabled={!!busy} onClick={onClose}>{t("关闭")}</Button>
          {!shown ? <Button type="submit" form="preset-form" disabled={!!busy || !!extraError || !form.model.trim() || !form.api_key.trim()}>
            {busy === "add" ? <Spinner /> : <Plus />}{t("添加预设")}</Button> : null}
        </div>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
