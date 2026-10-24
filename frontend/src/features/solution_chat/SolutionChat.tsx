import { type ReactNode, useEffect, useRef, useState } from "react";
import { useDefaultLayout } from "react-resizable-panels";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { useDesktop } from "@/lib/useDesktop";
import { useQuery } from "@tanstack/react-query";
import { useStream } from "@langchain/langgraph-sdk/react";
import type { Message } from "@langchain/langgraph-sdk";
import { ArrowDown, ArrowUpRight, Columns3, RefreshCw, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChatMessages, type ChatProgress } from "@/features/chat/Messages";
import { ChatInput } from "@/features/chat/ChatInput";
import { useChatDraft } from "@/features/chat/draft";
import { useChatScroll } from "@/features/chat/scroll";
import { client } from "@/features/runs/sdk";
import { StatusBadge } from "@/features/runs/status";
import { errorText, formatNumber } from "@/format";
import { locale, t } from "@/i18n";
import type { Plan, RunValues, SolutionChatMeta, SourceRun, Usage } from "@/features/runs/types";
import type { Preset } from "@/types";

type Values = { messages?: Message[]; source?: SourceRun; current?: SourceRun; plans?: Plan[]; usage?: Usage; failure?: string | null };

export function SolutionChat({ threadId, presets, openPresets, onFinished, onOpen, onCompare, renderRun }: {
  threadId: string; presets: Preset[]; openPresets: () => void; onFinished: () => void;
  onOpen: (id: string) => void; onCompare: (group: string) => void; renderRun: (id: string) => ReactNode;
}) {
  const desktop = useDesktop();
  const layout = useDefaultLayout({ id: "llm4om-discussion", panelIds: ["plan", "conversation"], onlySaveAfterUserInteractions: true });
  const thread = useQuery({ queryKey: ["solution-chat", threadId], queryFn: () => client.threads.get(threadId) });
  const meta = thread.data?.metadata as SolutionChatMeta | undefined;
  const { value: input, setValue: setInput, prepare, acknowledge, savePending } = useChatDraft(threadId);
  const [selected, setSelected] = useState<string>();
  const [thinking, setThinking] = useState<boolean>();
  const [viewed, setViewed] = useState<string>();
  const [action, setAction] = useState(false);
  const [stopping, setStopping] = useState(false);
  const { log, content, follow, followLatest } = useChatScroll();
  const [progress, setProgress] = useState<ChatProgress>();
  const inputArea = useRef<HTMLTextAreaElement>(null);
  const runId = useRef<string | null>(null);
  const stream = useStream<Values, { CustomEventType: ChatProgress }>({ client, assistantId: "solution_chat", threadId, reconnectOnMount: true,
    fetchStateHistory: false, throttle: 50,
    onMetadataEvent: event => { runId.current = event.run_id; },
    onCustomEvent: event => { if (event.type === "scenario_progress") setProgress(event); },
    onCreated: event => { runId.current = event.run_id; onFinished(); },
    onCheckpointEvent: (event, { namespace }) => { if (!namespace?.length) acknowledge(event.values.messages); },
    onFinish: state => { acknowledge(state.values.messages); onFinished(); }, onError: () => onFinished() });
  const messages = stream.messages;
  const source = stream.values.current ?? stream.values.source ?? meta?.parent;
  const current = useQuery({ queryKey: ["source-run", source?.thread_id, source?.checkpoint_id], enabled: !!source,
    queryFn: () => client.threads.getState<RunValues>(source!.thread_id, source!.checkpoint_id), staleTime: Infinity, retry: false });
  const values = current.data?.values as RunValues | undefined;
  const presetId = selected ?? meta?.preset ?? presets[0]?.id;
  const preset = presets.find(item => item.id === presetId);
  const thinkingMode = preset?.provider === "deepseek" ? thinking ?? meta?.thinking ?? null : null;
  const busy = action || stopping || stream.isLoading || stream.isThreadLoading || thread.isPending;
  const failure = stream.error || stream.values.failure;
  useEffect(() => { acknowledge((thread.data?.values as Values | undefined)?.messages); }, [thread.data?.values, acknowledge]);
  const plans = stream.values.plans ?? [];
  const groups = [...new Set(plans.flatMap(plan => plan.group ? [plan.group] : []))];

  const submit = async (retry = false) => {
    if (busy || (!retry && !input.trim())) return;
    if (!preset) { toast.error(t("先选择一个可用的预设模型。")); openPresets(); return; }
    setAction(true); followLatest(); setViewed(undefined); setProgress(undefined);
    try {
      await client.threads.update(threadId, { metadata: { preset: preset.id, provider: preset.provider, model: preset.name || preset.model, thinking: thinkingMode } });
      const last = [...messages].reverse().find(message => message.type === "human");
      const question = retry && last?.type === "human" ? last : prepare(input);
      runId.current = null;
      await stream.submit({ messages: [question] }, {
        context: { preset: preset.id, locale, thinking: thinkingMode }, multitaskStrategy: "reject", streamResumable: true, streamSubgraphs: true,
        optimisticValues: retry ? undefined : current => ({ ...current, messages: [...(current.messages ?? []), question] }),
      });
    } catch (error) { toast.error(errorText(error)); }
    finally { setAction(false); }
  };
  const stop = async () => {
    setStopping(true);
    try {
      if (runId.current) await client.runs.cancel(threadId, runId.current, true);
      await savePending();
      await stream.stop();
      onFinished();
    } catch (error) { toast.error(errorText(error)); }
    finally { setStopping(false); }
  };
  if (thread.error) return <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-sm text-destructive">
    <p>{errorText(thread.error)}</p><Button variant="outline" onClick={() => void thread.refetch()}><RefreshCw />{t("重试")}</Button></div>;
  const shown = viewed ?? source?.thread_id;
  const plan = <TabsContent value="plan" forceMount className="mt-0 h-full min-h-0 min-w-0 data-[state=inactive]:hidden lg:data-[state=inactive]:block">
    {shown ? renderRun(shown) : <div className="grid h-full place-items-center"><Spinner /></div>}
  </TabsContent>;
  const conversation = <TabsContent value="conversation" forceMount className="mt-0 h-full min-h-0 min-w-0 data-[state=inactive]:hidden lg:data-[state=inactive]:flex">
    <aside aria-label={t("方案助手")} className="flex h-full min-h-0 w-full flex-col gap-3 bg-card p-3">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b pb-3">
        <h2 className="flex items-center gap-2 text-sm font-medium"><Sparkles className="size-4 text-muted-foreground" />{t("方案助手")}</h2>
        <Button variant="ghost" size="icon-xs" disabled={!shown} aria-label={t("收起方案助手")} onClick={() => onOpen(shown!)}><X /></Button>
      </div>
      <div className="shrink-0 rounded-lg border bg-muted/30 p-3 text-xs" aria-label={t("当前讨论方案")}>
        <p className="mb-1 text-muted-foreground">{t("当前讨论方案")}</p>
        {current.error ? <p role="alert" className="text-destructive">{errorText(current.error)}</p> : !values ? <Spinner /> : <>
          <p className="truncate font-medium" title={values.description}>{values.description?.trim().split("\n")[0].replace(/^#{1,6}\s+/, "")}</p>
          <div className="mt-2 flex items-center justify-between gap-2">
            <span>{values.explanation?.objective_label || t("目标值")} <strong>{values.solve?.objective == null ? "—" : formatNumber(values.solve.objective)}</strong> {values.explanation?.objective_unit}</span>
            <StatusBadge status={values.failure ? "failed" : values.solve?.status ?? "unknown"} />
          </div>
        </>}
        {viewed && viewed !== source?.thread_id ? <Button variant="link" size="xs" className="mt-2 h-auto p-0" onClick={() => setViewed(undefined)}>{t("查看讨论中的方案")}</Button> : null}
      </div>
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div ref={log} role="log" aria-label={t("对话记录")} aria-busy={stream.isLoading} className="min-h-0 chat-scroll flex-1 overflow-y-auto overscroll-contain px-1 sm:px-3">
          <div ref={content} className="grid min-h-full grid-cols-1">
            {messages.length || failure ? <ChatMessages messages={messages} loading={stream.isLoading} label={t("方案助手")}
              failure={failure} disabled={busy} onRetry={() => void submit(true)} progress={progress}
              onOpenPlan={setViewed} onCompare={onCompare} />
              : <div className="mx-auto flex min-h-full max-w-md flex-col justify-center gap-4 py-6">
                <span className="grid size-8 place-items-center rounded-2xl bg-primary/10 text-primary"><Sparkles className="size-5" /></span>
                <h2 className="text-base font-semibold">{t("接下来，想了解或调整什么？")}</h2>
                <p className="text-sm leading-6 text-muted-foreground">{t("可以询问决策值的含义，也可以给出新的条件。新方案会实际建模求解，并单独保存。")}</p>
                <Button variant="outline" className="self-start" onClick={() => { setInput(t("请用通俗的话解释这个方案的主要决策。")); inputArea.current?.focus(); }}>{t("解释主要决策")}</Button>
              </div>}
          </div>
        </div>
        {!follow ? <Button variant="outline" size="icon-sm" aria-label={t("回到最新消息")} className="absolute right-3 bottom-3 rounded-full bg-background shadow-sm" onClick={followLatest}><ArrowDown /></Button> : null}
      </div>
      <ChatInput label={t("发送给方案助手")} value={input} onChange={setInput} disabled={busy} loading={stream.isLoading} stopping={stopping}
        inputRef={inputArea}
        presets={presets} presetId={presetId} onPreset={setSelected} thinking={thinkingMode} onThinking={setThinking} openPresets={openPresets} onSend={() => void submit()}
        placeholder={t("追问方案，或说明你想调整的条件……")} onStop={() => void stop()} />
      <p className="shrink-0 text-center text-[11px] text-muted-foreground">{t(stream.isLoading ? "回复期间可继续输入，完成后发送。" : "Enter 发送，Shift+Enter 换行")}</p>

      <details className="max-h-48 shrink-0 overflow-y-auto border-t pt-2 text-xs" aria-label={t("已生成的方案")}>
        <summary className="cursor-pointer font-medium text-muted-foreground">{t("相关方案")} · {plans.length + 1}</summary>
        <div className="mt-2 flex flex-col gap-1">
          <Button variant="ghost" size="sm" className="justify-between text-xs" disabled={!meta?.parent} onClick={() => setViewed(meta!.parent.thread_id)}>{t("打开原运行")}<ArrowUpRight /></Button>
          {plans.map(plan => <Button key={plan.source.thread_id} variant="ghost" className="h-auto justify-between py-2 text-left text-xs whitespace-normal"
            onClick={() => setViewed(plan.source.thread_id)} title={plan.instruction}><span>{plan.name}</span><ArrowUpRight className="shrink-0" /></Button>)}
          {groups.map((group, i) => <Button key={group} variant="ghost" size="sm" onClick={() => onCompare(group)}><Columns3 />{t("查看场景对比 {number}", { number: i + 1 })}</Button>)}
        </div>
      </details>
    </aside>
  </TabsContent>;
  return <Tabs defaultValue="plan" className="h-full min-h-0 gap-0">
    <TabsList className="mx-4 my-2 grid shrink-0 grid-cols-2 lg:hidden">
      <TabsTrigger value="plan">{t("建模结果")}</TabsTrigger><TabsTrigger value="conversation">{t("方案助手")}</TabsTrigger>
    </TabsList>
    {desktop ? <ResizablePanelGroup orientation="horizontal" defaultLayout={layout.defaultLayout} onLayoutChanged={layout.onLayoutChanged} className="min-h-0 flex-1">
      <ResizablePanel id="plan" defaultSize="65%" minSize="40%">{plan}</ResizablePanel>
      <ResizableHandle withHandle aria-label={t("调整结果与方案助手的宽度")} />
      <ResizablePanel id="conversation" defaultSize="35%" minSize="320px">{conversation}</ResizablePanel>
    </ResizablePanelGroup> : <div className="grid min-h-0 flex-1 grid-cols-1">{plan}{conversation}</div>}
  </Tabs>;
}
