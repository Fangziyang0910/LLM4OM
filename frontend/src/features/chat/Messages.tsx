import type { Message } from "@langchain/langgraph-sdk";
import { memo, useState } from "react";
import { Brain, ChevronRight, RefreshCw, Sparkles, TriangleAlert } from "lucide-react";
import { CopyButton, Markdown } from "@/components/Content";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { errorText } from "@/format";
import { t } from "@/i18n";
import type { Step } from "@/features/runs/types";
import { Timeline } from "@/features/runs/Timeline";
import { activity, resultType, resultViews, type ToolArtifact } from "./results";

export type ModelingTask = { name: string; method: string; language: string; steps: Step[] };
export type ModelingEvent = Omit<ModelingTask, "steps"> & { type: "modeling_step"; tool_call_id: string; step: Step };

export type ChatProgress = {
  type: "scenario_progress"; tool_call_id: string; name: string; index: number; total: number;
  stage: "revise" | "model" | "solve" | "explain";
};

export function messageText(message: Message): string {
  return typeof message.content === "string" ? message.content : (message.content ?? [])
    .filter(block => block.type === "text").map(block => block.text).join("\n");
}

function messageReasoning(message: Message): string {
  if (message.type !== "ai") return "";
  const native = message.additional_kwargs?.reasoning_content ?? message.additional_kwargs?.reasoning;
  if (typeof native === "string") return native;
  const blocks: { type: string; reasoning?: unknown; thinking?: unknown }[] = Array.isArray(message.content) ? message.content : [];
  return blocks.map(block =>
    block.type === "reasoning" && typeof block.reasoning === "string" ? block.reasoning
      : block.type === "thinking" && typeof block.thinking === "string" ? block.thinking : "").join("");
}

const Reasoning = memo(function Reasoning({ text, active }: { text: string; active: boolean }) {
  const [open, setOpen] = useState(false);
  return <details className="group/thinking mb-3 rounded-xl border border-border/70 bg-muted/25" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="flex cursor-pointer list-none items-center gap-2 rounded-xl px-3 py-2 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {active ? <Spinner className="size-3.5" aria-hidden="true" role="presentation" /> : <Brain className="size-3.5" />}
      <span>{t(active ? "正在思考……" : "思考过程")}</span><ChevronRight className="ml-auto size-3.5 transition-transform group-open/thinking:rotate-90" />
    </summary>
    {open ? <div className="max-h-64 overflow-y-auto border-t border-border/60 px-3 py-2.5"><Markdown text={text} className="text-muted-foreground" /></div> : null}
  </details>;
});

/** Source and plan cards come from tool artifacts, never from model-written links or numbers. */
function ToolResult({ message, onOpenPlan, onCompare }: {
  message: Extract<Message, { type: "tool" }>; onOpenPlan?: (id: string) => void; onCompare?: (group: string) => void;
}) {
  if (message.status === "error") return <details className="ml-9 rounded-lg border border-destructive/20 p-3 text-xs">
    <summary className="flex cursor-pointer items-center gap-2 text-muted-foreground"><TriangleAlert className="size-3.5 text-destructive" />{t("这一步未完成")}</summary>
    <p className="mt-2 whitespace-pre-wrap break-words text-destructive">{messageText(message)}</p>
  </details>;
  const artifact = message.artifact as ToolArtifact | undefined;
  const type = resultType(artifact, message.name);
  const Result = Object.hasOwn(resultViews, type) ? resultViews[type] : undefined;
  return Result ? <Result artifact={artifact} onOpenPlan={onOpenPlan} onCompare={onCompare} /> : null;
}

export function ChatMessages({ messages, loading, label, failure, disabled, onRetry, progress, onOpenPlan, onCompare, tasks, onShowTask }: {
  messages: Message[]; loading: boolean; label: string; failure?: unknown; disabled?: boolean; onRetry: () => void;
  progress?: ChatProgress; onOpenPlan?: (id: string) => void; onCompare?: (group: string) => void;
  tasks?: Record<string, ModelingTask>; onShowTask?: (id: string) => void;
}) {
  const completed = new Set(messages.filter(message => message.type === "tool").map(message => message.tool_call_id));
  const last = messages.at(-1);
  const pending = last?.type === "ai" ? last : undefined;
  const calls = loading ? pending?.tool_calls?.filter(call => !completed.has(call.id ?? "")) ?? [] : [];
  const unanswered = last?.type === "human";
  const stopped = failure && /^CancelledError(?:\(\))?$/.test(errorText(failure));
  const failed = !!failure && !stopped;
  const stages = { revise: t("整理调整后的问题"), model: t("正在建模"), solve: t("正在求解"), explain: t("解读求解结果") };
  return <div className="mx-auto flex w-full max-w-3xl flex-col gap-5 py-4">
    {messages.map((message, index) => {
      if (message.type === "tool") return <ToolResult key={message.id ?? index} message={message} onOpenPlan={onOpenPlan} onCompare={onCompare} />;
      if (message.type !== "human" && message.type !== "ai") return null;
      const text = messageText(message);
      const reasoning = messageReasoning(message);
      if (!text && !reasoning) return null;
      return <article key={message.id ?? index} aria-label={message.type === "human" ? t("你") : label}
        className={message.type === "human" ? "group ml-auto max-w-[92%] rounded-2xl rounded-tr-sm bg-muted px-4 py-3 sm:max-w-[85%]" : "group min-w-0"}>
        {message.type === "ai" ? <div className="mb-2 flex items-center gap-2 text-xs font-medium text-muted-foreground">
          <span className="grid size-7 place-items-center rounded-lg bg-primary/10 text-primary"><Sparkles className="size-3.5" /></span>{label}</div> : null}
        <div className={message.type === "ai" ? "pl-9" : ""}>
          {reasoning ? <Reasoning text={reasoning} active={loading && message === last && !text && !calls.length} /> : null}
          {text ? <Markdown text={text} /> : null}
        </div>
        {text && message.type === "ai" && (!loading || message !== last) ? <div className="mt-1 pl-8 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:focus-within:opacity-100">
          <CopyButton text={text} label={t("复制回复")} />
        </div> : null}
      </article>;
    })}
    {loading && !(pending && messageReasoning(pending) && !messageText(pending) && !calls.length) ? <div role="status" className="flex flex-col gap-2 pl-9 text-xs text-muted-foreground">
      {calls.length ? calls.map(call => <div key={call.id ?? call.name} className="flex flex-col gap-2">
        <div className="flex items-start gap-2">
        <Spinner aria-hidden="true" role="presentation" className="mt-0.5 shrink-0" /><div className="min-w-0"><p>{activity(call.name)}</p>
          {progress && progress.tool_call_id === call.id ? <p className="mt-1 break-words">{t("方案 {index}/{total}：{name}", { index: progress.index, total: progress.total, name: progress.name })} · {stages[progress.stage]}</p>
            : call.name === "web_search" && typeof call.args?.query === "string" ? <p className="mt-1 break-words">{call.args.query}</p> : null}
        </div></div>
        {call.id && tasks?.[call.id] ? <details className="rounded-xl border bg-card" open>
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium">{tasks[call.id].name} · {tasks[call.id].language}</summary>
          <div className="h-64 border-t"><Timeline steps={tasks[call.id].steps} live={{}} active={loading}
            onShow={() => onShowTask?.(call.id!)} /></div>
          <Button variant="link" size="sm" onClick={() => onShowTask?.(call.id!)}>{t("查看正在生成的产物")}</Button>
        </details> : null}
      </div>) : <p className="flex items-center gap-2"><Spinner aria-hidden="true" role="presentation" />{pending && messageText(pending) ? t("正在输出……") : t("正在准备回复……")}</p>}
    </div> : failed || stopped || unanswered ? <div className="ml-9 rounded-xl border bg-muted/30 p-3 text-xs" role={failed ? "alert" : "status"}>
      <p>{failed ? t("这轮回复未完成，可以重试。") : t("这轮回复已停止，可以重新回答。")}</p>
      <p className="mt-1 text-muted-foreground">{unanswered ? t("重试使用原问题，输入框中的草稿会保留。") : t("请从输入框重新发送，草稿会保留。")}</p>
      {failed ? <details className="mt-2 text-muted-foreground"><summary className="cursor-pointer">{t("查看错误详情")}</summary><p className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words">{errorText(failure)}</p></details> : null}
      {unanswered ? <Button variant="outline" size="sm" className="mt-3" disabled={disabled} onClick={onRetry}><RefreshCw />{t("重试这一轮")}</Button> : null}
    </div> : null}
  </div>;
}
