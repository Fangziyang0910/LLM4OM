import { useState } from "react";
import { Plus, RefreshCw, Trash2 } from "lucide-react";
import { api, errorText } from "../api";
import type { Provider, Settings } from "../types";
import { Dialog } from "./Dialog";

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

  return <Dialog open title="LLM 服务" onClose={onClose} wide flush footer={<>
    {profile?.saved && !adding ? <button className="button danger-text" disabled={!!busy} onClick={() => void remove()}>
      <Trash2 size={15} />删除这项设置</button> : null}
    <span className="spacer" />
    <button className="button" onClick={onClose}>取消</button>
    <button className="button primary" disabled={!!busy || !!extraError || !form.model.trim()} onClick={() => void save()}>
      {busy === "save" ? <span className="spinner" /> : null}保存并设为默认</button>
  </>}>
    <div className="settings">
      <nav className="settings-list" aria-label="已配置的服务">
        {configured.map(id => <button key={id} className={"set" + (!adding && editing === id ? " selected" : "")} onClick={() => select(id)}>
          <strong>{label(id)}{settings.selected === id ? <span className="tag accent">默认</span> : null}</strong>
          <span className="muted">{settings.profiles[id].model}{settings.profiles[id].saved ? "" : " · 环境变量"}</span>
        </button>)}
        <button className={"set add" + (adding ? " selected" : "")} onClick={() => select(firstNew, true)}>
          <strong><Plus size={15} />添加服务</strong>
        </button>
      </nav>

      <div className="settings-form">
        {adding ? <label className="field">服务商
          <select value={form.provider} onChange={event => select(event.target.value, true)}>
            {providers.map(item => <option key={item.id} value={item.id}>{item.label}{settings.profiles[item.id] ? "（已配置）" : ""}</option>)}
          </select>
        </label> : <h3>{label(form.provider)}</h3>}
        {profile && !profile.saved ? <p className="note">这项设置来自环境变量 <code>LLM4OM_LLM_*</code>。在这里保存后，本机设置优先。</p> : null}

        <label className="field">接口地址
          <input value={preset?.base_url || form.base_url} readOnly={!!preset?.base_url} onChange={set("base_url")} placeholder="https://example.com/v1" />
          {preset?.base_url ? <span className="help">使用该服务商的官方地址。</span> : null}
        </label>
        <label className="field">API 密钥
          <input type="password" autoComplete="off" value={form.api_key} onChange={set("api_key")}
            placeholder={profile?.api_key_preview ? `已保存 ${profile.api_key_preview}，留空则不变` : "输入密钥"} />
          <span className="help">密钥只保存在本机工作区的私有文件中，不进入运行记录和生成代码。</span>
        </label>
        <div className="field">
          <label htmlFor="model-id">默认模型 ID</label>
          <div className="inline">
            <input id="model-id" value={form.model} onChange={set("model")} placeholder="例如 deepseek-chat" />
            <button type="button" className="button" disabled={!!busy} onClick={() => void listModels()}>
              {busy === "models" ? <span className="spinner" /> : <RefreshCw size={14} />}读取可用模型</button>
          </div>
          {models ? <div className="model-options">
            {filtered.slice(0, 60).map(item => <button key={item} type="button" className={"chip-button" + (item === form.model ? " selected" : "")}
              onClick={() => setForm({ ...form, model: item })}>{item}</button>)}
            {!filtered.length ? <span className="help">{models.length ? "没有匹配的模型。" : "服务没有返回模型列表，请直接填写。"}</span> : null}
          </div> : null}
        </div>

        <details className="disclosure">
          <summary>高级参数</summary>
          <div className="field-row">
            <label className="field">温度<input type="number" step="0.1" min="0" value={form.temperature} onChange={set("temperature")} placeholder="服务默认" /></label>
            <label className="field">最大输出 token<input type="number" min="1" value={form.max_tokens} onChange={set("max_tokens")} placeholder="服务默认" /></label>
          </div>
          <label className="field">额外请求参数（JSON）
            <input value={form.extra_body} onChange={set("extra_body")} placeholder='例如 {"thinking": {"type": "disabled"}}' aria-invalid={!!extraError} />
            <span className={"help" + (extraError ? " bad" : "")}>{extraError ?? "填写所选服务商支持的请求参数。DeepSeek 运行 TriVAL 时需要关闭思考模式。"}</span>
          </label>
        </details>
        {problem ? <div className="callout bad" role="alert">{problem}</div> : null}
      </div>
    </div>
  </Dialog>;
}
