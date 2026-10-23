import { type ReactNode, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useStream } from "@langchain/langgraph-sdk/react";
import type { Message } from "@langchain/langgraph-sdk";
import { ArrowDown, ArrowUpRight, Columns3, RefreshCw, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ChatMessages } from "@/features/chat/Messages";
import { ChatInput } from "@/features/chat/ChatInput";
import { useChatDraft } from "@/features/chat/draft";
import { client } from "@/features/runs/sdk";
import { StatusBadge } from "@/features/runs/status";
import { errorText, formatNumber } from "@/format";
import { locale, t } from "@/i18n";
import type { RunValues, SolutionChatMeta, SourceRun, Usage } from "@/features/runs/types";
import type { Preset } from "@/types";

type Plan = { name: string; instruction: string; source: SourceRun; group: string | null };
type Values = { messages?: Message[]; source?: SourceRun; current?: SourceRun; plans?: Plan[]; usage?: Usage; failure?: string | null };

export function SolutionChat({ threadId, presets, openPresets, onFinished, onOpen, onCompare, renderRun }: {
  threadId: string; presets: Preset[]; openPresets: () => void; onFinished: () => void;
  onOpen: (id: string) => void; onCompare: (group: string) => void; renderRun: (id: string) => ReactNode;
}) {
  const thread = useQuery({ queryKey: ["solution-chat", threadId], queryFn: () => client.threads.get(threadId) });
  const meta = thread.data?.metadata as SolutionChatMeta | undefined;
  const [input, setInput] = useChatDraft(threadId);
  const [selected, setSelected] = useState<string>();
  const [viewed, setViewed] = useState<string>();
  const [action, setAction] = useState(false);
  const [follow, setFollow] = useState(true);
  const log = useRef<HTMLDivElement>(null);
  const inputArea = useRef<HTMLTextAreaElement>(null);
  const sending = useRef<string | null>(null);
  const stream = useStream<Values>({ client, assistantId: "solution_chat", threadId, reconnectOnMount: true,
    fetchStateHistory: false, throttle: 50,
    onCreated: () => { if (sending.current !== null) setInput(value => value === sending.current ? "" : value); onFinished(); },
    onFinish: () => onFinished(), onError: () => onFinished() });
  const messages = stream.messages;
  const source = stream.values.current ?? stream.values.source ?? meta?.parent;
  const current = useQuery({ queryKey: ["source-run", source?.thread_id, source?.checkpoint_id], enabled: !!source,
    queryFn: () => client.threads.getState<RunValues>(source!.thread_id, source!.checkpoint_id), staleTime: Infinity, retry: false });
  const values = current.data?.values as RunValues | undefined;
  const presetId = selected ?? meta?.preset ?? presets[0]?.id;
  const preset = presets.find(item => item.id === presetId);
  const busy = action || stream.isLoading || stream.isThreadLoading || thread.isPending;
  const failure = stream.values.failure || stream.error;
  const plans = stream.values.plans ?? [];
  const groups = [...new Set(plans.flatMap(plan => plan.group ? [plan.group] : []))];
  useEffect(() => { if (follow && log.current) log.current.scrollTop = log.current.scrollHeight; }, [messages, follow]);

  const submit = async (retry = false) => {
    if (busy || (!retry && !input.trim())) return;
    if (!preset) { toast.error(t("先选择一个可用的预设模型。")); openPresets(); return; }
    setAction(true); setFollow(true); setViewed(undefined);
    try {
      await client.threads.update(threadId, { metadata: { preset: preset.id, provider: preset.provider, model: preset.name || preset.model } });
      const last = [...messages].reverse().find(message => message.type === "human");
      sending.current = retry ? null : input;
      await stream.submit({ messages: retry && last?.type === "human" ? [last] : [{ type: "human", content: input.trim() }] }, {
        context: { preset: preset.id, locale }, multitaskStrategy: "reject", streamResumable: true, streamSubgraphs: true,
        optimisticValues: retry ? undefined : current => ({ ...current, messages: [...(current.messages ?? []), { type: "human", content: input.trim() }] }),
      });
    } catch (error) { toast.error(errorText(error)); }
    finally { setAction(false); }
  };
  if (thread.error) return <div role="alert" className="flex h-full flex-col items-center justify-center gap-3 p-6 text-center text-sm text-destructive">
    <p>{errorText(thread.error)}</p><Button variant="outline" onClick={() => void thread.refetch()}><RefreshCw />{t("重试")}</Button></div>;
  const shown = viewed ?? source?.thread_id;
  return <Tabs defaultValue="plan" className="h-full min-h-0 gap-0">
    <TabsList className="mx-4 my-2 grid shrink-0 grid-cols-2 lg:hidden">
      <TabsTrigger value="plan">{t("建模结果")}</TabsTrigger><TabsTrigger value="conversation">{t("方案助手")}</TabsTrigger>
    </TabsList>
    <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(0,1fr)_360px] 2xl:grid-cols-[minmax(0,1fr)_400px]">
      <TabsContent value="plan" forceMount className="mt-0 min-h-0 min-w-0 data-[state=inactive]:hidden lg:data-[state=inactive]:block">
        {shown ? renderRun(shown) : <div className="grid h-full place-items-center"><Spinner /></div>}
      </TabsContent>
      <TabsContent value="conversation" forceMount className="mt-0 min-h-0 min-w-0 data-[state=inactive]:hidden lg:data-[state=inactive]:flex">
        <aside aria-label={t("方案助手")} className="flex h-full min-h-0 w-full flex-col gap-3 border-l bg-card p-3">
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
            <div ref={log} role="log" aria-label={t("对话记录")} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-1 sm:px-3"
              onScroll={event => { const node = event.currentTarget; setFollow(node.scrollHeight - node.scrollTop - node.clientHeight < 80); }}>
              {messages.length ? <ChatMessages messages={messages} loading={stream.isLoading} label={t("方案助手")} />
                : <div className="mx-auto flex min-h-full max-w-md flex-col justify-center gap-4 py-6">
                  <span className="grid size-8 place-items-center rounded-2xl bg-primary/10 text-primary"><Sparkles className="size-5" /></span>
                  <h2 className="text-base font-semibold">{t("接下来，想了解或调整什么？")}</h2>
                  <p className="text-sm leading-6 text-muted-foreground">{t("可以询问决策值的含义，也可以给出新的条件。新方案会实际建模求解，并单独保存。")}</p>
                  <Button variant="outline" className="self-start" onClick={() => { setInput(t("请用通俗的话解释这个方案的主要决策。")); inputArea.current?.focus(); }}>{t("解释主要决策")}</Button>
                </div>}
            </div>
            {!follow ? <Button variant="outline" size="icon-sm" aria-label={t("回到最新消息")} className="absolute right-3 bottom-3 rounded-full bg-background shadow-sm" onClick={() => setFollow(true)}><ArrowDown /></Button> : null}
          </div>
          {failure && !stream.isLoading ? <Alert variant="destructive"><AlertDescription>{errorText(failure)}
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void submit(true)}><RefreshCw />{t("重试这一轮")}</Button></AlertDescription></Alert> : null}
          <ChatInput label={t("发送给方案助手")} value={input} onChange={setInput} disabled={busy} loading={stream.isLoading}
            inputRef={inputArea}
            presets={presets} presetId={presetId} onPreset={setSelected} openPresets={openPresets} onSend={() => void submit()}
            onStop={() => void stream.stop().catch(error => toast.error(errorText(error)))} />
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
      </TabsContent>
    </div>
  </Tabs>;
}
