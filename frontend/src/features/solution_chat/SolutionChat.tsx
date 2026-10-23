import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useStream } from "@langchain/langgraph-sdk/react";
import type { Message } from "@langchain/langgraph-sdk";
import { ArrowDown, ArrowUpRight, Columns3, RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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

export function SolutionChat({ threadId, presets, openPresets, onFinished, onOpen, onCompare }: {
  threadId: string; presets: Preset[]; openPresets: () => void; onFinished: () => void;
  onOpen: (id: string) => void; onCompare: (group: string) => void;
}) {
  const thread = useQuery({ queryKey: ["solution-chat", threadId], queryFn: () => client.threads.get(threadId) });
  const meta = thread.data?.metadata as SolutionChatMeta | undefined;
  const [input, setInput] = useChatDraft(threadId);
  const [selected, setSelected] = useState<string>();
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
    setAction(true); setFollow(true);
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
  return <div className="flex h-full flex-col gap-4 p-4 sm:gap-5 sm:p-6">
    <header className="grid shrink-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
      <h1 className="flex items-center gap-2 text-xl font-semibold tracking-tight"><Sparkles className="size-5 text-primary" />{t("方案对话")}</h1>
      <Button variant="outline" size="sm" disabled={!meta?.parent} onClick={() => onOpen(meta!.parent.thread_id)}>{t("打开原运行")}<ArrowUpRight /></Button>
      <p className="col-span-2 text-xs leading-relaxed text-muted-foreground sm:text-sm">{t("围绕实际结果提问，提出具体条件后可重新计算。")}</p>
    </header>
    <Tabs defaultValue="conversation" className="min-h-0 flex-1 gap-3">
      <TabsList className="grid w-full shrink-0 grid-cols-2 lg:hidden"><TabsTrigger value="conversation">{t("对话")}</TabsTrigger><TabsTrigger value="plans">{t("方案")}</TabsTrigger></TabsList>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-5 lg:grid-cols-[minmax(0,1fr)_360px]">
        <TabsContent value="conversation" forceMount className="mt-0 flex min-h-0 min-w-0 flex-col gap-3 data-[state=inactive]:hidden lg:data-[state=inactive]:flex">
          <div className="relative flex min-h-0 flex-1 flex-col">
            <div ref={log} role="log" aria-label={t("对话记录")} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-1 sm:px-3"
              onScroll={event => { const node = event.currentTarget; setFollow(node.scrollHeight - node.scrollTop - node.clientHeight < 80); }}>
              {messages.length ? <ChatMessages messages={messages} loading={stream.isLoading} label={t("方案助手")} />
                : <div className="mx-auto flex min-h-full max-w-xl flex-col justify-center gap-4 py-6">
                  <span className="grid size-11 place-items-center rounded-2xl bg-primary/10 text-primary"><Sparkles className="size-5" /></span>
                  <h2 className="text-xl font-semibold">{t("接下来，想了解或调整什么？")}</h2>
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
        </TabsContent>
        <TabsContent value="plans" forceMount className="mt-0 min-h-0 min-w-0 overflow-y-auto data-[state=inactive]:hidden lg:data-[state=inactive]:block">
          <Card className="gap-3 py-4 shadow-sm"><CardHeader><CardTitle className="text-sm">{t("当前方案")}</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3">
              {current.error ? <p role="alert" className="text-sm text-destructive">{errorText(current.error)}</p>
                : !values ? <Spinner /> : <>
                  <StatusBadge status={values.failure ? "failed" : values.solve?.status ?? "unknown"} />
                  <div><p className="text-xs text-muted-foreground">{values.explanation?.objective_label || t("目标值")}</p>
                    <p className="mt-1 text-2xl font-semibold tabular">{values.solve?.objective == null ? "—" : formatNumber(values.solve.objective)}
                      <span className="ml-1 text-xs font-normal text-muted-foreground">{values.explanation?.objective_unit}</span></p></div>
                  <p className="line-clamp-6 text-xs leading-5 whitespace-pre-wrap text-muted-foreground">{values.description}</p>
                  <Button variant="outline" size="sm" onClick={() => onOpen(source!.thread_id)}>{t("查看完整方案")}<ArrowUpRight /></Button>
                </>}
            </CardContent>
          </Card>
          {plans.length ? <section className="mt-5 flex flex-col gap-2" aria-label={t("已生成的方案")}>
            <h2 className="text-sm font-medium">{t("已生成的方案")}</h2>
            {plans.map(plan => <Button key={plan.source.thread_id} variant="outline" className="h-auto justify-between gap-2 py-3 text-left whitespace-normal" onClick={() => onOpen(plan.source.thread_id)}>
              <span className="min-w-0"><span className="block text-sm font-medium">{plan.name}</span><span className="mt-1 line-clamp-2 block text-xs font-normal text-muted-foreground">{plan.instruction}</span></span><ArrowUpRight className="shrink-0" /></Button>)}
            {groups.map((group, i) => <Button key={group} variant="secondary" size="sm" onClick={() => onCompare(group)}><Columns3 />{t("查看场景对比 {number}", { number: i + 1 })}</Button>)}
          </section> : null}
        </TabsContent>
      </div>
    </Tabs>
  </div>;
}
