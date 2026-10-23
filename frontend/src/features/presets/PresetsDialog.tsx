import { useState } from "react";
import { ChevronDown, KeyRound, Plus, RefreshCw, Trash2 } from "lucide-react";
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
    <Label htmlFor={htmlFor} className="text-xs">{label}</Label>
    {children}
    {error || help ? <p className={cn("text-xs", error ? "text-destructive" : "text-muted-foreground")}>{error ?? help}</p> : null}
  </div>;
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="grid grid-cols-1 gap-1 border-b py-2.5 text-sm last:border-0 sm:grid-cols-[7rem_minmax(0,1fr)] sm:gap-3">
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
  const set = (field: keyof Form) => (event: { target: { value: string } }) => setForm({ ...form, [field]: event.target.value });
  const show = (id: string | null) => { setViewing(id); setProblem(null); setConfirming(false); };
  let extraError: string | null = null;
  try { if (form.extra_body.trim()) JSON.parse(form.extra_body); } catch { extraError = t("不是有效的 JSON。"); }
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
    <DialogContent showCloseButton={!busy} className="flex max-h-[90dvh] flex-col gap-0 p-0 sm:max-w-3xl">
      <DialogHeader className="border-b px-6 py-4">
        <DialogTitle>{t("预设模型")}</DialogTitle>
        <DialogDescription>{t("选择用于对话和建模的模型，密钥仅保存在服务器。")}</DialogDescription>
      </DialogHeader>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav aria-label={t("预设列表")} className="flex shrink-0 gap-1 overflow-x-auto border-b p-2 md:w-56 md:flex-col md:overflow-y-auto md:border-r md:border-b-0">
          {presets.map((item, index) => <button key={item.id} disabled={!!busy} aria-current={viewing === item.id} onClick={() => show(item.id)}
            className={cn("flex shrink-0 flex-col items-start gap-0.5 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent",
              viewing === item.id && "bg-accent")}>
            <span className="flex max-w-44 items-center gap-2 font-medium"><span className="truncate">{item.name || item.model}</span>
              {index === 0 ? <Badge className="h-4 shrink-0 px-1.5 text-[10px]">{t("默认")}</Badge> : null}</span>
            <span className="max-w-44 truncate text-[11px] text-muted-foreground">{label(item.provider)}{item.source === "env" ? t(" · 服务器") : ""}</span>
          </button>)}
          <button disabled={!!busy} aria-current={viewing === null} onClick={() => show(null)}
            className={cn("flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
              viewing === null && "bg-accent text-foreground")}><Plus className="size-4" />{t("添加预设")}</button>
        </nav>

        <div className="flex min-h-0 min-w-0 flex-1 flex-col gap-4 overflow-y-auto p-4 sm:p-6">
          {shown ? <>
            <h3 className="text-base font-semibold break-all">{shown.name || shown.model}</h3>
            <dl>
              <Fact label={t("模型 ID")}>{shown.model}</Fact>
              <Fact label={t("服务商")}>{label(shown.provider)}</Fact>
              <Fact label={t("接口地址")}><span className="font-mono text-xs">{shown.base_url || providers.find(item => item.id === shown.provider)?.base_url}</span></Fact>
              <Fact label={t("API 密钥")}><span className="flex items-center gap-1.5 text-muted-foreground"><KeyRound className="size-3.5" />{t("已保存在服务器，不可查看")}</span></Fact>
              <Fact label={t("温度")}>{shown.temperature ?? t("服务默认")}</Fact>
              <Fact label={t("最大输出 token")}>{shown.max_tokens ?? t("服务默认")}</Fact>
              <Fact label={t("额外请求参数")}>{Object.keys(shown.extra_body).length
                ? <code className="font-mono text-xs">{JSON.stringify(shown.extra_body)}</code> : t("无")}</Fact>
              <Fact label={t("今日用量")}><span className="tabular">{dailyTokens
                ? t("{used} / {limit} token（每日上限）", { used: formatTokens(shown.tokens_today), limit: formatTokens(dailyTokens) })
                : t("{used} token（不限量）", { used: formatTokens(shown.tokens_today) })}</span></Fact>
            </dl>
            {shown.source === "env" ? <Alert><AlertDescription className="text-xs"><p>
              {t("这个预设来自服务器的 LLM4OM_LLM_* 环境变量，只能在服务器上修改或删除。")}</p></AlertDescription></Alert> : null}
          </> : <form id="preset-form" className="flex flex-col gap-4" onSubmit={event => {
            event.preventDefault(); if (!busy && !extraError && form.model.trim() && form.api_key.trim()) void add();
          }}>
            <fieldset disabled={!!busy} className="flex min-w-0 flex-col gap-4">
            <Field label={t("服务商")} htmlFor="provider">
              <Select value={form.provider} onValueChange={value => { setForm(emptyForm(providers.find(item => item.id === value)!)); setModels(null); }}>
                <SelectTrigger id="provider" className="w-full"><SelectValue /></SelectTrigger>
                <SelectContent>{providers.map(item => <SelectItem key={item.id} value={item.id}>{item.label}</SelectItem>)}</SelectContent>
              </Select>
            </Field>
            <Field label={t("接口地址")} htmlFor="base-url">
              <Input id="base-url" value={form.base_url} onChange={set("base_url")}
                placeholder="https://example.com/v1" />
            </Field>
            <Field label={t("API 密钥")} htmlFor="api-key" help={t("保存后不再显示。")}>
              <Input id="api-key" type="password" autoComplete="off" value={form.api_key} onChange={set("api_key")} placeholder={t("输入密钥")} />
            </Field>
            <Field label={t("预设名称")} htmlFor="preset-name" help={t("仅用于显示；留空时使用模型 ID。")}>
              <Input id="preset-name" value={form.name} onChange={set("name")} />
            </Field>
            <Field label={t("模型 ID")} htmlFor="model-id">
              <div className="flex flex-col gap-2 sm:flex-row">
                <Input id="model-id" value={form.model} onChange={set("model")} placeholder={t("例如 deepseek-chat")} />
                <Button type="button" variant="outline" disabled={!!busy || !!extraError || !form.api_key.trim()} onClick={() => void listModels()}>
                  {busy === "models" ? <Spinner /> : <RefreshCw />}{t("读取可用模型")}</Button>
              </div>
              {models ? <div className="flex max-h-36 flex-wrap gap-1.5 overflow-y-auto pt-1">
                {filtered.slice(0, 60).map(item => <Button key={item} type="button" size="xs" variant={item === form.model ? "default" : "secondary"}
                  className="font-mono font-normal" onClick={() => setForm({ ...form, model: item })}>{item}</Button>)}
                {!filtered.length ? <p className="text-xs text-muted-foreground">{models.length ? t("没有匹配的模型。") : t("服务没有返回模型列表，请直接填写。")}</p> : null}
              </div> : null}
            </Field>

            <Collapsible className="group/advanced rounded-lg border">
              <CollapsibleTrigger type="button" className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium">
                {t("高级参数")}<ChevronDown className="ml-auto size-4 text-muted-foreground transition-transform group-data-[state=open]/advanced:rotate-180" /></CollapsibleTrigger>
              <CollapsibleContent className="flex flex-col gap-4 border-t p-3">
                <div className="grid grid-cols-2 gap-3">
                  <Field label={t("温度")} htmlFor="temperature"><Input id="temperature" type="number" step="0.1" min="0" value={form.temperature} onChange={set("temperature")} placeholder={t("服务默认")} /></Field>
                  <Field label={t("最大输出 token")} htmlFor="max-tokens"><Input id="max-tokens" type="number" min="1" value={form.max_tokens} onChange={set("max_tokens")} placeholder={t("服务默认")} /></Field>
                </div>
                <Field label={t("额外请求参数（JSON）")} htmlFor="extra-body" error={extraError}
                  help={t("填写所选服务商支持的请求参数。DeepSeek 运行 TriVAL 时需要关闭思考模式。")}>
                  <Input id="extra-body" value={form.extra_body} onChange={set("extra_body")} className="font-mono text-xs"
                    placeholder={t("例如 {example}", { example: '{"thinking": {"type": "disabled"}}' })} aria-invalid={!!extraError} />
                </Field>
              </CollapsibleContent>
            </Collapsible>
            </fieldset>
          </form>}
          {problem ? <Alert variant="destructive" role="alert"><AlertDescription>{problem}</AlertDescription></Alert> : null}
        </div>
      </div>
      <DialogFooter className="border-t px-6 py-3 sm:justify-between">
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
