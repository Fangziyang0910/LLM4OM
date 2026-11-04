import { useRef, useState } from "react";
import type { Message } from "@langchain/langgraph-sdk";
import { ArrowDown, ArrowRight, CalendarDays, Check, Factory, Globe, Paperclip, RefreshCw, Save, Sparkles, Truck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Composer, type ComposerProps } from "@/features/composer/Composer";
import { ProblemEditor } from "@/features/composer/ProblemEditor";
import { DATA_FILE_ACCEPT, readDataFiles } from "@/features/composer/files";
import { client } from "@/features/runs/sdk";
import { errorText } from "@/format";
import { locale, t } from "@/i18n";
import { cn } from "@/lib/utils";
import type { RequirementsMeta, Usage } from "@/features/runs/types";
import type { RequirementsDraft } from "./api";
import { ChatMessages } from "@/features/chat/Messages";
import { ChatInput } from "@/features/chat/ChatInput";
import { useConversation } from "@/features/chat/conversation";
import { useChatScroll } from "@/features/chat/scroll";

type Values = Partial<RequirementsDraft> & { messages?: Message[]; usage?: Usage; failure?: string | null };
const STARTERS = [
  { icon: CalendarDays, title: "门店排班", text: "我想给门店排班，尽量少花人工费，又能保证每个时段有人。" },
  { icon: Factory, title: "生产安排", text: "我想安排几种产品的生产，在现有设备和原料限制下赚更多利润。" },
  { icon: Truck, title: "运输配送", text: "我有几个仓库和一批客户订单，希望安排一个运费更低的方案。" },
];

/** Conversation state and checkpoints belong to LangGraph; only unsaved editing lives in React. */
export function Requirements({ threadId, searchConfigured, onFinished, onUse, ...composer }: Omit<ComposerProps, "editor" | "assistant" | "disabled" | "onDiscuss"> & {
  threadId: string; searchConfigured: boolean; onFinished: () => void; onUse: (draft: RequirementsDraft) => void;
}) {
  const { presets, openPresets, draft: configuration, setDraft: configure } = composer;
  const [selected, setSelected] = useState<string>();
  const [thinking, setThinking] = useState<boolean>();
  const [search, setSearch] = useState<boolean>();
  const [edited, setEdited] = useState<RequirementsDraft | null>(null);
  const conversation = useConversation<Values>({ assistantId: "requirements", threadId,
    onCreated: onFinished, onError: onFinished, onFinish: state => {
      if (!state.values.failure && !state.tasks?.some(task => task.error)) setEdited(null);
      onFinished();
    } });
  const meta = conversation.thread.metadata as RequirementsMeta | undefined;
  const { input, setInput } = conversation;
  const [action, setAction] = useState(false);
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedDraft, setSavedDraft] = useState<RequirementsDraft | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const { log, content, follow, followLatest } = useChatScroll();
  const saved = useRef<RequirementsDraft | null>(null);
  const saveQueue = useRef(Promise.resolve());
  const inputArea = useRef<HTMLTextAreaElement>(null);
  const draft = edited ?? { description: conversation.values.description ?? configuration.description, data: conversation.values.data ?? configuration.data };
  const messages = conversation.messages;
  const presetId = selected ?? meta?.preset ?? presets[0]?.id;
  const preset = presets.find(item => item.id === presetId);
  const thinkingMode = preset?.provider === "deepseek" ? thinking ?? meta?.thinking ?? null : null;
  const canSearch = searchConfigured || preset?.provider === "deepseek";
  const searchOn = !!canSearch && (search ?? meta?.search ?? false);
  const busy = conversation.busy || action || reading;
  const failure = conversation.error || conversation.values.failure;


  const save = (snapshot = edited) => {
    // Serialize a blur-save with Send/Use so an edit cannot land after a new turn has started.
    const task = saveQueue.current.catch(() => undefined).then(async () => {
      if (!snapshot || saved.current === snapshot) return;
      setSaving(true);
      try {
        await client.threads.updateState(threadId, { values: snapshot, asNode: "discuss" });
        saved.current = snapshot;
        setSavedDraft(snapshot);
        setSaveError(null);
      } catch (error) { setSaveError(errorText(error)); throw error; }
      finally { setSaving(false); }
    });
    saveQueue.current = task;
    return task;
  };
  const submit = async (retry = false) => {
    if (busy || (!retry && !input.trim())) return;
    if (!preset) { toast.error(t("先选择一个可用的预设模型。")); openPresets(); return; }
    setAction(true);
    followLatest();
    try {
      // The draft save queue must settle before the run starts; native create/updateState order is not enough.
      await save();
      await conversation.send({ retry, context: { preset: preset.id, locale, search: searchOn, thinking: thinkingMode },
        values: draft, metadata: { preset: preset.id, provider: preset.provider, model: preset.name || preset.model,
          thinking: thinkingMode, search: searchOn, ...(!messages.length ? { title: input.trim().slice(0, 120) } : {}) } });
    } catch (error) { toast.error(errorText(error)); }
    finally { setAction(false); }
  };
  const attach = async (files: FileList | null) => {
    setReading(true);
    try {
      const data = await readDataFiles(files, draft.data);
      const next = { ...draft, data: { ...draft.data, ...data } };
      setEdited(next);
      await save(next);
    } catch (error) { toast.error(errorText(error)); }
    finally { setReading(false); }
  };
  const stop = async () => { if (await conversation.stop()) onFinished(); };

  if (conversation.thread.error) return <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-sm text-destructive">
    <p>{errorText(conversation.thread.error)}</p><Button variant="outline" onClick={conversation.thread.reload}><RefreshCw />{t("重试")}</Button></div>;

  const assistant = <div className="flex h-full min-h-0 flex-col gap-2 p-3">
    <div className="flex shrink-0 items-center justify-between gap-2 border-b pb-3">
      <h2 className="flex items-center gap-2 text-sm font-medium"><Sparkles className="size-4 text-muted-foreground" />{t("需求助手")}</h2>
      <Button variant="ghost" size="xs" disabled={busy || !draft.description.trim()} onClick={async () => {
        setAction(true);
        try { await save(); onUse(draft); } catch (error) { toast.error(errorText(error)); } finally { setAction(false); }
      }}>{t("用于建模")}<ArrowRight /></Button>
    </div>
          <div className="relative flex min-h-0 flex-1 flex-col">
            <div ref={log} role="log" aria-label={t("对话记录")} aria-busy={conversation.loading} className="min-h-0 chat-scroll flex-1 overflow-y-auto overscroll-contain">
              <div ref={content} className="grid min-h-full grid-cols-1">
                {!messages.length && !failure ? <div className="mx-auto flex min-h-full flex-col justify-center gap-5 py-6">
                  <h2 className="text-base font-semibold">{t("先说说，你想安排什么？")}</h2>
                  <div className="grid gap-2 ">{STARTERS.map(item => <button key={item.title} type="button"
                    disabled={busy} onClick={() => { setInput(t(item.text)); inputArea.current?.focus(); }}
                    className="flex items-center gap-3 rounded-xl border bg-card p-3 text-left text-sm transition-colors hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 ">
                    <item.icon className="size-4 text-primary" /><span>{t(item.title)}</span></button>)}</div>
                </div> : <ChatMessages messages={messages} loading={conversation.loading} label={t("需求助手")}
                  failure={failure} disabled={busy} onRetry={() => void submit(true)} />}
              </div>
            </div>
            {!follow ? <Button type="button" variant="outline" size="icon-sm" aria-label={t("回到最新消息")}
              className="absolute right-3 bottom-3 rounded-full bg-background shadow-sm" onClick={followLatest}><ArrowDown /></Button> : null}
          </div>
          <ChatInput value={input} onChange={setInput} disabled={busy} loading={conversation.loading} stopping={conversation.stopping} label={t("发送给需求助手")}
            inputRef={inputArea} presets={presets} presetId={presetId} onPreset={setSelected} thinking={thinkingMode} onThinking={setThinking} openPresets={openPresets}
            onSend={() => void submit()} onStop={() => void stop()}>
              <Button asChild type="button" variant="ghost" size="icon-sm" title={Object.keys(draft.data).join(", ") || t("添加附件")}>
                <label className={cn("relative cursor-pointer", busy && "pointer-events-none opacity-50")}><Paperclip />
                  {Object.keys(draft.data).length ? <span className="absolute -top-0.5 -right-0.5 rounded-full bg-primary px-1 text-[9px] text-primary-foreground">{Object.keys(draft.data).length}</span> : null}
                  <input type="file" className="sr-only" aria-label={t("添加附件")} multiple accept={DATA_FILE_ACCEPT} disabled={busy}
                    onChange={event => { void attach(event.target.files); event.target.value = ""; }} />
                </label>
              </Button>
              <span title={canSearch ? t("搜索公开资料，并在回复中展示来源。") : t("选择 DeepSeek 预设或由管理员配置搜索服务。")}>
                <Button type="button" variant="ghost" size="sm" aria-label={t("联网搜索")} aria-pressed={searchOn} disabled={busy || !canSearch}
                  className={cn("h-8 gap-1.5 px-2 text-xs", searchOn && "bg-primary/10 text-primary hover:bg-primary/15 hover:text-primary")}
                  onClick={() => setSearch(!searchOn)}><Globe /><span className="hidden @lg:inline">{t("联网搜索")}</span></Button>
              </span>
          </ChatInput>
  </div>;
  const editor = <>
          {saveError ? <p role="alert" className="text-xs text-destructive">{t("需求稿未保存：{error}", { error: saveError })}</p> : null}
          <div className="flex min-h-0 flex-1 flex-col [&>div]:h-auto [&>div]:min-h-0 [&>div]:flex-1"
            onBlur={event => {
              // Dialog focus events bubble through React portals; only the draft itself triggers autosave.
              if (!busy && event.currentTarget.contains(event.target) && !event.currentTarget.contains(event.relatedTarget)) void save().catch(() => undefined);
            }}>
            <ProblemEditor value={draft.description} data={draft.data} disabled={busy} reading={reading} onChange={description => setEdited({ ...draft, description })}
              label={t("当前需求稿")} placeholder={t("对话中确认的目标和条件会整理到这里，也可以直接编辑。")}
              actions={<Button variant="ghost" size="icon-sm" aria-label={t("保存需求稿")}
                title={saving ? t("正在保存……") : t("保存需求稿")} disabled={busy || saving || !edited || edited === savedDraft}
                onClick={() => void save().catch(() => undefined)}>
                {saving ? <Spinner /> : edited && edited !== savedDraft ? <Save /> : <Check />}</Button>}
              onFiles={files => void attach(files)} onDataChange={async (name, content) => {
                const next = { ...draft, data: { ...draft.data, [name]: content } }; await save(next); setEdited(next);
              }} onClear={() => setEdited({ description: "", data: {} })}
              onRemove={name => { const data = { ...draft.data }; delete data[name]; setEdited({ ...draft, data }); }} />
          </div>
  </>;
  return <Composer {...composer} draft={{ ...configuration, ...draft, origin: threadId }} disabled={busy} editor={editor} assistant={assistant}
    setDraft={change => {
      const next = typeof change === "function" ? change({ ...configuration, ...draft, origin: threadId }) : change;
      if (next.description !== draft.description || next.data !== draft.data) setEdited({ description: next.description, data: next.data });
      configure(next);
    }}
    onStart={async request => { await save(); configure(request); await composer.onStart(request); }}
    onCompare={async (request, runs) => { await save(); configure(request); await composer.onCompare(request, runs); }} />;
}
