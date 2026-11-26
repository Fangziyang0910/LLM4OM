import { useMemo, useRef, useState } from "react";
import { useDefaultLayout } from "react-resizable-panels";
import type { Message } from "@langchain/langgraph-sdk";
import { ArrowDown, ArrowRight, CalendarDays, Check, Factory, Globe, MessageSquareText, Paperclip, Save, Sparkles, Truck } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ProblemEditor } from "@/features/composer/ProblemEditor";
import { type ModelingConfigProps, useRunLauncher } from "@/features/composer/RunSettings";
import { DATA_FILE_ACCEPT, readDataFiles } from "@/features/composer/files";
import { saveThreadValues, type RequirementsDraft } from "@/features/runs/api";
import { errorText } from "@/format";
import { locale, t } from "@/i18n";
import { useDesktop } from "@/lib/useDesktop";
import { cn } from "@/lib/utils";
import type { RequirementsMeta, Usage } from "@/features/runs/types";
import { ChatMessages, ThreadLoadError } from "@/features/chat/Messages";
import { ChatInput, ToolToggle } from "@/features/chat/ChatInput";
import { inputFingerprint } from "@/features/chat/inputFingerprint";
import { useChatModel, useConversation } from "@/features/chat/conversation";
import { useChatScroll } from "@/features/chat/scroll";
import { visibleDraft } from "./visibleDraft";

type Values = Partial<RequirementsDraft> & { messages?: Message[]; usage?: Usage; failure?: string | null };
const STARTERS = [
  { icon: CalendarDays, title: "门店排班", text: "我想给门店排班，尽量少花人工费，又能保证每个时段有人。" },
  { icon: Factory, title: "生产安排", text: "我想安排几种产品的生产，在现有设备和原料限制下赚更多利润。" },
  { icon: Truck, title: "运输配送", text: "我有几个仓库和一批客户订单，希望安排一个运费更低的方案。" },
];

/** Conversation state and checkpoints belong to LangGraph; only unsaved editing lives in React. */
export function Requirements({ threadId, searchConfigured, onFinished, onUse, ...modeling }: ModelingConfigProps & {
  threadId: string; searchConfigured: boolean; onFinished: () => void; onUse: (draft: RequirementsDraft) => void;
}) {
  const { presets, openPresets } = modeling;
  const desktop = useDesktop();
  const layout = useDefaultLayout({ id: "llm4om-requirements", panelIds: ["conversation", "problem"], onlySaveAfterUserInteractions: true });
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [focusPane, setFocusPane] = useState("assistant");
  const [search, setSearch] = useState<boolean>();
  const [edited, setEdited] = useState<RequirementsDraft | null>(null);
  const conversation = useConversation<Values>({ assistantId: "requirements", threadId,
    onCreated: onFinished, onError: onFinished, onFinish: state => {
      if (!state.values.failure && !state.tasks?.some(task => task.error)) {
        setEdited(null);
        saved.current = null;
        setSavedDraft(null);
        setSaveError(null);
      }
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
  const storedDescription = conversation.values.description ?? "";
  const description = useMemo(() => visibleDraft(storedDescription), [storedDescription]);
  const draft = edited ?? { description, data: conversation.values.data ?? {} };
  const messages = conversation.messages;
  const { preset, presetId, setSelected, thinkingMode, setThinking } = useChatModel(presets, meta);
  const canSearch = searchConfigured || preset?.provider === "deepseek";
  const searchOn = !!canSearch && (search ?? meta?.search ?? false);
  const busy = conversation.busy || action || reading;
  const failure = conversation.error || conversation.values.failure;
  const reviewFirst = assistantOpen && !desktop && focusPane === "assistant";

  const save = (snapshot = edited) => {
    const task = saveQueue.current.catch(() => undefined).then(async () => {
      if (!snapshot || saved.current === snapshot) return;
      setSaving(true);
      try {
        await saveThreadValues(threadId, snapshot);
        saved.current = snapshot;
        setSavedDraft(snapshot);
        setSaveError(null);
      } catch (error) { setSaveError(errorText(error)); throw error; }
      finally { setSaving(false); }
    });
    saveQueue.current = task;
    return task;
  };

  const { busy: launching, settingsTrigger, startButton, settingsDialog } = useRunLauncher({
    ...modeling,
    problem: { description: draft.description, data: draft.data, origin: threadId },
    disabled: busy || !!conversation.thread.error,
    reading,
    reviewFirst,
    onReview: () => setFocusPane("problem"),
    beforeLaunch: () => save(),
  });

  const submit = async (retry = false) => {
    if (busy || launching || (!retry && !input.trim())) return;
    if (!preset) { toast.error(t("请先配置可用的 AI 模型。")); openPresets(); return; }
    setAction(true);
    followLatest();
    try {
      await save();
      const shouldTitle = !messages.length && (!meta?.title || meta.title === t("新需求对话"));
      const firstLine = input.trim().split(/\r?\n/).map(line => line.replace(/^#+\s*/, "").trim()).find(Boolean) ?? "";
      await conversation.send({ retry, context: { preset: preset.id, locale, search: searchOn, thinking: thinkingMode,
        input_fingerprint: inputFingerprint(draft.data, edited?.description ?? storedDescription) },
        metadata: { preset: preset.id, provider: preset.provider, model: preset.name || preset.model,
          thinking: thinkingMode, search: searchOn, ...(shouldTitle && firstLine ? { title: firstLine.slice(0, 120) } : {}) } });
    } catch (error) { toast.error(errorText(error)); }
    finally { setAction(false); }
  };
  const attach = async (files: FileList | null) => {
    setReading(true);
    try {
      const data = await readDataFiles(files, draft.data);
      if (!Object.keys(data).length) return;
      const next = { ...draft, data: { ...draft.data, ...data } };
      setEdited(next);
      await save(next);
    } catch (error) { toast.error(errorText(error)); }
    finally { setReading(false); }
  };
  const stop = async () => { if (await conversation.stop()) onFinished(); };

  if (conversation.thread.error) return <ThreadLoadError error={conversation.thread.error} onReload={conversation.thread.reload} />;

  const conversationPanel = <TabsContent value="assistant" forceMount className={cn("mt-0 h-full min-h-0 min-w-0 data-[state=inactive]:hidden", assistantOpen ? "lg:data-[state=inactive]:block" : "hidden")}>
    <aside aria-label={t("需求助手")} className="flex h-full min-h-0 flex-col overflow-hidden rounded-2xl border bg-card shadow-xs">
      <div className="flex h-full min-h-0 flex-col gap-3 p-3.5">
        <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border/70 pb-3">
          <h2 className="flex items-center gap-2 text-sm font-semibold"><Sparkles className="size-4 text-primary" />{t("需求梳理助手")}</h2>
          <Button variant="secondary" size="xs" className="rounded-lg" disabled={busy || launching || !draft.description.trim()} onClick={async () => {
            setAction(true);
            try { await save(); onUse(draft); } catch (error) { toast.error(errorText(error)); } finally { setAction(false); }
          }}>{t("带入手动建模")}<ArrowRight /></Button>
        </div>
        <div className="relative flex min-h-0 flex-1 flex-col">
          <div ref={log} role="log" aria-label={t("对话记录")} aria-busy={conversation.loading} className="min-h-0 chat-scroll flex-1 overflow-y-auto overscroll-contain">
            <div ref={content} className="grid min-h-full grid-cols-1">
              {!messages.length && !failure ? <div className="mx-auto flex min-h-full flex-col justify-center gap-4 py-6">
                <h2 className="text-base font-semibold">{t("先聊聊，你想优化什么事项？")}</h2>
                <div className="grid gap-2">{STARTERS.map(item => <button key={item.title} type="button"
                  disabled={busy || launching} onClick={() => { setInput(t(item.text)); inputArea.current?.focus(); }}
                  className="flex items-center gap-3 rounded-xl border border-border/80 bg-card p-3 text-left text-sm shadow-2xs transition-all hover:-translate-y-0.5 hover:border-primary/40 hover:bg-primary/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50">
                  <span className="grid size-7 place-items-center rounded-lg bg-primary/10 text-primary"><item.icon className="size-4" /></span>
                  <span className="font-medium">{t(item.title)}</span></button>)}</div>
              </div> : <ChatMessages messages={messages} loading={conversation.loading} label={t("需求助手")}
                failure={failure} disabled={busy || launching} onRetry={() => void submit(true)} />}
            </div>
          </div>
          {!follow ? <Button type="button" variant="outline" size="icon-sm" aria-label={t("回到最新消息")}
            className="absolute right-3 bottom-3 rounded-full bg-background shadow-sm" onClick={followLatest}><ArrowDown /></Button> : null}
        </div>
        <ChatInput value={input} onChange={setInput} disabled={conversation.busy || action || launching} sendingDisabled={reading} loading={conversation.loading} stopping={conversation.stopping} label={t("发送给需求助手")}
          inputRef={inputArea} presets={presets} presetId={presetId} onPreset={setSelected} thinking={thinkingMode} onThinking={setThinking} openPresets={openPresets}
          searchActive={canSearch && searchOn} attachment={<Button asChild type="button" variant="ghost" size="icon-sm" title={reading ? t("正在读取数据……") : Object.keys(draft.data).join(", ") || t("添加附件")}>
            <label className={cn("relative cursor-pointer", (busy || launching) && "pointer-events-none opacity-50")}>{reading ? <Spinner /> : <Paperclip />}
              {Object.keys(draft.data).length ? <span className="absolute -top-0.5 -right-0.5 rounded-full bg-primary px-1 text-[9px] text-primary-foreground">{Object.keys(draft.data).length}</span> : null}
              <input type="file" className="sr-only" aria-label={t("添加附件")} multiple accept={DATA_FILE_ACCEPT} disabled={busy || launching}
                onChange={event => { void attach(event.target.files); event.target.value = ""; }} />
            </label>
          </Button>}
          onSend={() => void submit()} onStop={() => void stop()}>

          <span title={canSearch ? t("搜索公开资料，并在回复中展示来源。") : t("选择支持搜索的模型或由管理员开启搜索服务。")}>
            <ToolToggle label={t("联网搜索")} icon={<Globe />} pressed={searchOn} disabled={busy || launching || !canSearch} onPressedChange={setSearch} />
          </span>
        </ChatInput>
      </div>
    </aside>
  </TabsContent>;

  const problemPanel = <TabsContent value="problem" forceMount className="mt-0 flex h-full min-h-0 min-w-0 flex-col gap-3 data-[state=inactive]:hidden lg:data-[state=inactive]:flex">
    {saveError ? <p role="alert" className="shrink-0 text-xs text-destructive">{t("需求稿未保存：{error}", { error: saveError })}</p> : null}
    <div className="flex min-h-0 flex-1 flex-col"
      onBlur={event => {
        if (!busy && !launching && event.currentTarget.contains(event.target) && !event.currentTarget.contains(event.relatedTarget)) void save().catch(() => undefined);
      }}>
      <ProblemEditor value={draft.description} data={draft.data} disabled={busy || launching} reading={reading} onChange={description => setEdited({ ...draft, description })}
        label={t("当前需求稿")} placeholder={t("对话中确认的目标和条件会自动同步整理到这里，您也可以随时手动修改…")}
        toolbarExtra={settingsTrigger}
        primaryAction={startButton}
        actions={<Button variant="ghost" size="icon-sm" aria-label={t("保存需求稿")}
          title={saving ? t("正在保存…") : t("保存需求稿")} disabled={busy || launching || saving || !edited || edited === savedDraft}
          onClick={() => void save().catch(() => undefined)}>
          {saving ? <Spinner /> : edited && edited !== savedDraft ? <Save /> : <Check />}</Button>}
        onFiles={files => void attach(files)} onDataChange={async (name, content) => {
          const next = { ...draft, data: { ...draft.data, [name]: content } }; await save(next); setEdited(next);
        }} onClear={() => { const next = { description: "", data: {} }; setEdited(next); void save(next).catch(() => undefined); }}
        onRemove={name => { const data = { ...draft.data }; delete data[name]; const next = { ...draft, data }; setEdited(next); void save(next).catch(() => undefined); }} />
    </div>
  </TabsContent>;

  return <div className="flex h-full flex-col">
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex h-full min-h-full max-w-6xl flex-col gap-4 p-4 sm:px-6 sm:py-5">
        <header className="animate-fade-up flex shrink-0 flex-wrap items-center justify-between gap-2">
          <h1 className="hidden text-lg font-semibold tracking-tight lg:block">{t("边聊边梳理需求")}</h1>
          <Button variant="ghost" size="sm" className="ml-auto rounded-xl text-xs text-muted-foreground" disabled={busy || launching}
            aria-expanded={assistantOpen} onClick={() => { setAssistantOpen(value => !value); setFocusPane("assistant"); }}>
            <MessageSquareText className="size-3.5" />{assistantOpen ? t("收起对话助手") : t("展开对话助手")}
          </Button>
        </header>

        <Tabs value={assistantOpen ? focusPane : "problem"} onValueChange={setFocusPane} className="min-h-0 flex-1 gap-3">
          {assistantOpen ? <TabsList className="grid shrink-0 grid-cols-2 rounded-xl lg:hidden" aria-label={t("问题与助手")}>
            <TabsTrigger value="assistant" className="rounded-lg">{t("对话助手")}</TabsTrigger>
            <TabsTrigger value="problem" className="rounded-lg">{t("当前需求稿")}</TabsTrigger>
          </TabsList> : null}
          {desktop && assistantOpen ? <ResizablePanelGroup orientation="horizontal" defaultLayout={layout.defaultLayout} onLayoutChanged={layout.onLayoutChanged} className="min-h-0 flex-1">
            <ResizablePanel id="conversation" defaultSize="42%" minSize="320px">{conversationPanel}</ResizablePanel>
            <ResizableHandle withHandle aria-label={t("调整对话与需求稿的宽度")} className="mx-2 bg-transparent" />
            <ResizablePanel id="problem" defaultSize="58%" minSize="35%">{problemPanel}</ResizablePanel>
          </ResizablePanelGroup> : <div className="grid min-h-0 flex-1 grid-cols-1 items-stretch gap-4">{conversationPanel}{problemPanel}</div>}
        </Tabs>

        {reviewFirst ? <div className="shrink-0 pt-1">{startButton}</div> : null}
      </div>
    </div>
    {settingsDialog}
  </div>;
}
