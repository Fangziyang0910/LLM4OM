import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useStream } from "@langchain/langgraph-sdk/react";
import type { Message } from "@langchain/langgraph-sdk";
import { ArrowDown, ArrowRight, CalendarDays, Check, Factory, Globe, Paperclip, RefreshCw, Save, Sparkles, Truck } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ProblemEditor } from "@/features/composer/ProblemEditor";
import { DATA_FILE_ACCEPT, readDataFiles } from "@/features/composer/files";
import { client } from "@/features/runs/sdk";
import { errorText } from "@/format";
import { locale, t } from "@/i18n";
import { cn } from "@/lib/utils";
import type { RequirementsMeta, Usage } from "@/features/runs/types";
import type { Preset } from "@/types";
import type { RequirementsDraft } from "./api";
import { ChatMessages } from "@/features/chat/Messages";
import { ChatInput } from "@/features/chat/ChatInput";
import { useChatDraft } from "@/features/chat/draft";

type Values = Partial<RequirementsDraft> & { messages?: Message[]; usage?: Usage; failure?: string | null };
const STARTERS = [
  { icon: CalendarDays, title: "门店排班", text: "我想给门店排班，尽量少花人工费，又能保证每个时段有人。" },
  { icon: Factory, title: "生产安排", text: "我想安排几种产品的生产，在现有设备和原料限制下赚更多利润。" },
  { icon: Truck, title: "运输配送", text: "我有几个仓库和一批客户订单，希望安排一个运费更低的方案。" },
];

/** Conversation state and checkpoints belong to LangGraph; only unsaved editing lives in React. */
export function Requirements({ threadId, presets, searchConfigured, openPresets, onFinished, onUse }: {
  threadId: string; presets: Preset[]; searchConfigured: boolean; openPresets: () => void; onFinished: () => void;
  onUse: (draft: RequirementsDraft) => void;
}) {
  const thread = useQuery({ queryKey: ["requirements", threadId], queryFn: () => client.threads.get(threadId) });
  const meta = thread.data?.metadata as RequirementsMeta | undefined;
  const [selected, setSelected] = useState<string>();
  const [search, setSearch] = useState<boolean>();
  const [input, setInput] = useChatDraft(threadId);
  const [edited, setEdited] = useState<RequirementsDraft | null>(null);
  const [action, setAction] = useState(false);
  const [reading, setReading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedDraft, setSavedDraft] = useState<RequirementsDraft | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const saved = useRef<RequirementsDraft | null>(null);
  const saveQueue = useRef(Promise.resolve());
  const log = useRef<HTMLDivElement>(null);
  const inputArea = useRef<HTMLTextAreaElement>(null);
  const sending = useRef<string | null>(null);
  const stream = useStream<Values>({ client, assistantId: "requirements", threadId, reconnectOnMount: true,
    fetchStateHistory: false, throttle: 50,
    onCreated: () => { if (sending.current !== null) setInput(value => value === sending.current ? "" : value); onFinished(); },
    onFinish: state => {
      if (!state.values.failure && !state.tasks?.some(task => task.error)) setEdited(null);
      onFinished();
    },
    onError: () => onFinished(),
  });
  const draft = edited ?? { description: stream.values.description ?? "", data: stream.values.data ?? {} };
  const messages = stream.messages;
  const presetId = selected ?? meta?.preset ?? presets[0]?.id;
  const preset = presets.find(item => item.id === presetId);
  const canSearch = searchConfigured || preset?.provider === "deepseek";
  const searchOn = !!canSearch && (search ?? meta?.search ?? false);
  const busy = action || reading || thread.isPending || stream.isLoading || stream.isThreadLoading;
  const failure = stream.values.failure || stream.error;

  useEffect(() => {
    if (follow && log.current) log.current.scrollTop = log.current.scrollHeight;
  }, [messages, stream.isLoading, follow]);

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
    setFollow(true);
    try {
      await save();
      await client.threads.update(threadId, { metadata: { preset: preset.id, provider: preset.provider,
        model: preset.name || preset.model, search: searchOn, ...(!messages.length ? { title: input.trim().slice(0, 120) } : {}) } });
      const last = [...messages].reverse().find(message => message.type === "human");
      sending.current = retry ? null : input;
      await stream.submit({ ...draft, messages: retry && last?.type === "human" ? [last] : [{ type: "human", content: input.trim() }] }, {
        context: { preset: preset.id, locale, search: searchOn }, multitaskStrategy: "reject", streamResumable: true, streamSubgraphs: true,
        optimisticValues: retry ? undefined : current => ({ ...draft,
          messages: [...(current.messages ?? []), { type: "human", content: input.trim() }] }),
      });
    } catch (error) { toast.error(errorText(error)); }
    finally { setAction(false); }
  };
  const attach = async (files: FileList | null) => {
    setReading(true);
    try {
      const data = await readDataFiles(files);
      const next = { ...draft, data: { ...draft.data, ...data } };
      setEdited(next);
      await save(next);
    } catch (error) { toast.error(errorText(error)); }
    finally { setReading(false); }
  };

  if (thread.error) return <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-sm text-destructive">
    <p>{errorText(thread.error)}</p><Button variant="outline" onClick={() => void thread.refetch()}><RefreshCw />{t("重试")}</Button></div>;

  return <div className="flex h-full flex-col gap-4 p-4 sm:gap-5 sm:p-6">
    <header className="grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5">
      <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><Sparkles className="size-5 text-primary" />{t("需求对话")}</h1>
      <Button size="sm" disabled={busy || !draft.description.trim()} onClick={async () => {
        setAction(true);
        try { await save(); onUse(draft); } catch (error) { toast.error(errorText(error)); } finally { setAction(false); }
      }}>{t("用于建模")}<ArrowRight /></Button>
      <p className="col-span-2 text-xs leading-relaxed text-muted-foreground sm:text-sm">{t("聊清目标与条件，确认需求稿后开始建模。")}</p>
    </header>

    <Tabs defaultValue="conversation" className="min-h-0 flex-1 gap-3">
      <TabsList className="grid w-full shrink-0 grid-cols-2 lg:hidden" aria-label={t("需求对话视图")}>
        <TabsTrigger value="conversation">{t("对话")}</TabsTrigger><TabsTrigger value="draft">{t("需求稿")}</TabsTrigger>
      </TabsList>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_400px]">
        <TabsContent value="conversation" forceMount className="mt-0 flex min-h-0 min-w-0 flex-col gap-3 data-[state=inactive]:hidden lg:data-[state=inactive]:flex">
          <div className="relative flex min-h-0 flex-1 flex-col">
            <div ref={log} role="log" aria-label={t("对话记录")} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-1 sm:px-3"
              onScroll={event => { const node = event.currentTarget; setFollow(node.scrollHeight - node.scrollTop - node.clientHeight < 80); }}>
              {!messages.length ? <div className="mx-auto flex min-h-full max-w-xl flex-col justify-center gap-5 py-6">
                <span className="grid size-11 place-items-center rounded-2xl bg-primary/10 text-primary"><Sparkles className="size-5" /></span>
                <div><h2 className="text-xl font-semibold tracking-tight sm:text-2xl">{t("先说说，你想安排什么？")}</h2>
                  <p className="mt-3 max-w-md text-sm leading-6 text-muted-foreground">{t("一个大概的想法就够了。我们边聊边把目标、条件和数据整理清楚。")}</p></div>
                <div className="grid gap-2 sm:grid-cols-3">{STARTERS.map(item => <button key={item.title} type="button"
                  disabled={busy} onClick={() => { setInput(t(item.text)); inputArea.current?.focus(); }}
                  className="flex items-center gap-3 rounded-xl border bg-card p-3 text-left text-sm transition-colors hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 sm:flex-col sm:items-start sm:gap-4 sm:p-4">
                  <item.icon className="size-4 text-primary" /><span>{t(item.title)}</span></button>)}</div>
              </div> : <ChatMessages messages={messages} loading={stream.isLoading} label={t("需求助手")} />}
            </div>
            {!follow ? <Button type="button" variant="outline" size="icon-sm" aria-label={t("回到最新消息")}
              className="absolute right-3 bottom-3 rounded-full bg-background shadow-sm" onClick={() => setFollow(true)}><ArrowDown /></Button> : null}
          </div>
          {failure && !stream.isLoading ? <Alert variant="destructive" className="mx-auto w-full max-w-3xl">
            <AlertDescription>{errorText(failure)}<Button variant="outline" size="sm" disabled={busy} onClick={() => void submit(true)}><RefreshCw />{t("重试这一轮")}</Button></AlertDescription>
          </Alert> : null}
          <ChatInput value={input} onChange={setInput} disabled={busy} loading={stream.isLoading} label={t("发送给需求助手")}
            inputRef={inputArea} presets={presets} presetId={presetId} onPreset={setSelected} openPresets={openPresets}
            onSend={() => void submit()} onStop={() => void stream.stop().catch(error => toast.error(errorText(error)))}>
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
                  onClick={() => setSearch(!searchOn)}><Globe /><span className="hidden md:inline">{searchOn ? t("联网搜索已开启") : t("联网搜索未开启")}</span></Button>
              </span>
          </ChatInput>
          <p className="shrink-0 text-center text-[11px] text-muted-foreground">{t(stream.isLoading ? "回复期间可继续输入，完成后发送。" : "Enter 发送，Shift+Enter 换行")}</p>
        </TabsContent>

        <TabsContent value="draft" forceMount className="mt-0 flex min-h-0 min-w-0 flex-col gap-3 data-[state=inactive]:hidden lg:data-[state=inactive]:flex">
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
        </TabsContent>
      </div>
    </Tabs>
  </div>;
}
