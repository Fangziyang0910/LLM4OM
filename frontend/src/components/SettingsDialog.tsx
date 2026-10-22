import { useState } from "react";
import { ChevronDown, Plus, RefreshCw, Trash2 } from "lucide-react";
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
import { errorText } from "@/format";
import type { Provider, Settings } from "@/types";

type Form = { provider: string; model: string; api_key: string; base_url: string; temperature: string; max_tokens: string; extra_body: string };

function formFor(provider: string, settings: Settings, providers: Provider[]): Form {
  const saved = settings.profiles[provider];
  const preset = providers.find(item => item.id === provider);
  return {
    provider, model: saved?.model ?? "", api_key: "", base_url: saved?.base_url || preset?.base_url || "",
    temperature: saved?.temperature == null ? "" : String(saved.temperature),
    max_tokens: saved?.max_tokens == null ? "" : String(saved.max_tokens),
    extra_body: saved && Object.keys(saved.extra_body).length ? JSON.stringify(saved.extra_body) : "",
  };
}

function Field({ label, htmlFor, help, error, children }: { label: string; htmlFor: string; help?: string; error?: string | null; children: React.ReactNode }) {
  return <div className="flex flex-col gap-1.5">
    <Label htmlFor={htmlFor} className="text-xs">{label}</Label>
    {children}
    {error || help ? <p className={cn("text-xs", error ? "text-destructive" : "text-muted-foreground")}>{error ?? help}</p> : null}
  </div>;
}

/** LLM services: the configured ones on the left, the chosen one's settings on the right. Mount it to open it. */
export function SettingsDialog({ onClose, settings, providers, onChange }: {
  onClose: () => void; settings: Settings; providers: Provider[]; onChange: (settings: Settings, message: string) => void;
}) {
  const configured = Object.keys(settings.profiles);
  const firstNew = providers.find(item => !settings.profiles[item.id])?.id ?? providers[0].id;
  const [editing, setEditing] = useState<string>(settings.selected ?? firstNew);
  const [adding, setAdding] = useState(!configured.length);
  const [form, setForm] = useState<Form>(() => formFor(editing, settings, providers));
  const [models, setModels] = useState<string[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState<"save" | "models" | "delete" | null>(null);

  const select = (provider: string, add = false) => {
    setEditing(provider); setAdding(add); setForm(formFor(provider, settings, providers)); setModels(null); setProblem(null);
  };

  const label = (id: string) => providers.find(item => item.id === id)?.label ?? id;
  const preset = providers.find(item => item.id === form.provider);
  const profile = settings.profiles[form.provider];
  const set = (field: keyof Form) => (event: { target: { value: string } }) => setForm({ ...form, [field]: event.target.value });
  let extraError: string | null = null;
  try { if (form.extra_body.trim()) JSON.parse(form.extra_body); } catch { extraError = "不是有效的 JSON。"; }
  const body = () => ({
    provider: form.provider, model: form.model.trim(), api_key: form.api_key.trim(),
    base_url: preset?.base_url ? "" : form.base_url.trim(),
    temperature: form.temperature === "" ? null : Number(form.temperature),
    max_tokens: form.max_tokens === "" ? null : Number(form.max_tokens),
    extra_body: form.extra_body.trim() ? JSON.parse(form.extra_body) : {},
  });
  const act = async (kind: "save" | "models" | "delete", action: () => Promise<void>) => {
    setBusy(kind); setProblem(null);
    try { await action(); } catch (error) { setProblem(errorText(error)); } finally { setBusy(null); }
  };
  const save = () => act("save", async () => {
    const saved = await api<Settings>("/api/settings", body());
    onChange(saved, `已保存 ${label(form.provider)}，并设为默认。`);
    setAdding(false);
    onClose();
  });
  const remove = () => act("delete", async () => {
    const saved = await api<Settings>(`/api/settings/${form.provider}`, undefined, "DELETE");
    onChange(saved, `已删除 ${label(form.provider)} 的设置。`);
    const next = saved.selected ?? Object.keys(saved.profiles)[0];
    if (next) { setEditing(next); setAdding(false); setForm(formFor(next, saved, providers)); } else select(firstNew, true);
  });
  const listModels = () => act("models", async () => setModels((await api<{ models: string[] }>("/api/models", body())).models));
  const filtered = models?.filter(item => item.toLowerCase().includes(form.model.trim().toLowerCase())) ?? [];

  return <Dialog open onOpenChange={open => { if (!open) onClose(); }}>
    <DialogContent className="flex max-h-[90dvh] flex-col gap-0 p-0 sm:max-w-3xl">
      <DialogHeader className="border-b px-6 py-4">
        <DialogTitle>LLM 服务</DialogTitle>
        <DialogDescription>密钥只保存在本机工作区的私有文件中，不进入运行记录和生成代码。</DialogDescription>
      </DialogHeader>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <nav aria-label="已配置的服务" className="flex shrink-0 gap-1 overflow-x-auto border-b p-2 md:w-56 md:flex-col md:border-r md:border-b-0">
          {configured.map(id => <button key={id} onClick={() => select(id)}
            className={cn("flex shrink-0 flex-col items-start gap-0.5 rounded-md px-3 py-2 text-left text-sm transition-colors hover:bg-accent",
              !adding && editing === id && "bg-accent")}>
            <span className="flex items-center gap-2 font-medium">{label(id)}
              {settings.selected === id ? <Badge className="h-4 px-1.5 text-[10px]">默认</Badge> : null}</span>
            <span className="max-w-44 truncate text-[11px] text-muted-foreground">{settings.profiles[id].model}{settings.profiles[id].saved ? "" : " · 环境变量"}</span>
          </button>)}
          <button onClick={() => select(firstNew, true)}
            className={cn("flex shrink-0 items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground",
              adding && "bg-accent text-foreground")}><Plus className="size-4" />添加服务</button>
        </nav>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-6">
          {adding ? <Field label="服务商" htmlFor="provider">
            <Select value={form.provider} onValueChange={value => select(value, true)}>
              <SelectTrigger id="provider" className="w-full"><SelectValue /></SelectTrigger>
              <SelectContent>{providers.map(item => <SelectItem key={item.id} value={item.id}>
                {item.label}{settings.profiles[item.id] ? <span className="text-muted-foreground">已配置</span> : null}</SelectItem>)}</SelectContent>
            </Select>
          </Field> : <h3 className="text-base font-semibold">{label(form.provider)}</h3>}
          {profile && !profile.saved ? <Alert><AlertDescription className="text-xs"><p>这项设置来自环境变量 <code className="font-mono">LLM4OM_LLM_*</code>。在这里保存后，本机设置优先。</p></AlertDescription></Alert> : null}

          <Field label="接口地址" htmlFor="base-url" help={preset?.base_url ? "使用该服务商的官方地址。" : undefined}>
            <Input id="base-url" value={preset?.base_url || form.base_url} readOnly={!!preset?.base_url} onChange={set("base_url")}
              placeholder="https://example.com/v1" className={cn(preset?.base_url && "bg-muted text-muted-foreground")} />
          </Field>
          <Field label="API 密钥" htmlFor="api-key">
            <Input id="api-key" type="password" autoComplete="off" value={form.api_key} onChange={set("api_key")}
              placeholder={profile?.api_key_preview ? `已保存 ${profile.api_key_preview}，留空则不变` : "输入密钥"} />
          </Field>
          <Field label="默认模型 ID" htmlFor="model-id">
            <div className="flex gap-2">
              <Input id="model-id" value={form.model} onChange={set("model")} placeholder="例如 deepseek-chat" />
              <Button type="button" variant="outline" disabled={!!busy} onClick={() => void listModels()}>
                {busy === "models" ? <Spinner /> : <RefreshCw />}读取可用模型</Button>
            </div>
            {models ? <div className="flex max-h-36 flex-wrap gap-1.5 overflow-y-auto pt-1">
              {filtered.slice(0, 60).map(item => <Button key={item} type="button" size="xs" variant={item === form.model ? "default" : "secondary"}
                className="font-mono font-normal" onClick={() => setForm({ ...form, model: item })}>{item}</Button>)}
              {!filtered.length ? <p className="text-xs text-muted-foreground">{models.length ? "没有匹配的模型。" : "服务没有返回模型列表，请直接填写。"}</p> : null}
            </div> : null}
          </Field>

          <Collapsible className="group/advanced rounded-lg border">
            <CollapsibleTrigger className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium">
              高级参数<ChevronDown className="ml-auto size-4 text-muted-foreground transition-transform group-data-[state=open]/advanced:rotate-180" /></CollapsibleTrigger>
            <CollapsibleContent className="flex flex-col gap-4 border-t p-3">
              <div className="grid grid-cols-2 gap-3">
                <Field label="温度" htmlFor="temperature"><Input id="temperature" type="number" step="0.1" min="0" value={form.temperature} onChange={set("temperature")} placeholder="服务默认" /></Field>
                <Field label="最大输出 token" htmlFor="max-tokens"><Input id="max-tokens" type="number" min="1" value={form.max_tokens} onChange={set("max_tokens")} placeholder="服务默认" /></Field>
              </div>
              <Field label="额外请求参数（JSON）" htmlFor="extra-body" error={extraError}
                help="填写所选服务商支持的请求参数。DeepSeek 运行 TriVAL 时需要关闭思考模式。">
                <Input id="extra-body" value={form.extra_body} onChange={set("extra_body")} className="font-mono text-xs"
                  placeholder='例如 {"thinking": {"type": "disabled"}}' aria-invalid={!!extraError} />
              </Field>
            </CollapsibleContent>
          </Collapsible>
          {problem ? <Alert variant="destructive" role="alert"><AlertDescription>{problem}</AlertDescription></Alert> : null}
        </div>
      </div>
      <DialogFooter className="border-t px-6 py-3 sm:justify-between">
        {profile?.saved && !adding ? <Button variant="ghost" className="text-destructive hover:text-destructive" disabled={!!busy} onClick={() => void remove()}>
          <Trash2 />删除这项设置</Button> : <span />}
        <div className="flex gap-2">
          <Button variant="outline" onClick={onClose}>取消</Button>
          <Button disabled={!!busy || !!extraError || !form.model.trim()} onClick={() => void save()}>
            {busy === "save" ? <Spinner /> : null}保存并设为默认</Button>
        </div>
      </DialogFooter>
    </DialogContent>
  </Dialog>;
}
