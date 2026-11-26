import type { Message } from "@langchain/langgraph-sdk";
import { memo, type ReactNode, useEffect, useState } from "react";
import { ArrowRight, Brain, Check, ChevronRight, Pencil, RefreshCw, TriangleAlert } from "lucide-react";
import { CopyButton, Markdown } from "@/components/Content";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { Textarea } from "@/components/ui/textarea";
import { duration, errorText } from "@/format";
import { t } from "@/i18n";
import { cn } from "@/lib/utils";
import type { SourceRun, Step } from "@/features/runs/types";
import { phases } from "@/features/runs/steps";
import { Timeline } from "@/features/runs/Timeline";
import type { Options } from "@/types";
import { activity, resultType, resultViews, type ToolArtifact } from "./results";

export type ModelingTask = { name: string; method: string; language: string; steps: Step[] };
export type ModelingEvent = Omit<ModelingTask, "steps"> & { type: "modeling_step"; tool_call_id: string; step: Step };

export type ChatProgress = {
  type: "scenario_progress"; tool_call_id: string; name: string; index: number; total: number;
  stage: Stage;
};
type Stage = "revise" | "model" | "solve" | "explain";

/**
 * A next question offered after a turn. A complete question is sent at once; otherwise `text` and `after` go to the
 * input around the cursor, where the user adds their own condition.
 */
export type Suggestion = { label: string; text: string; after?: string; send: boolean };

/** The stage of a modeling task, read from its latest step the way the server reports scenario progress. */
export function taskStage(steps: Step[]): Stage {
  const step = steps.at(-1);
  if (!step) return "model";
  if (step.title === "revise_problem") return "revise";
  if (step.title === "explain_result" || step.title === "explain_infeasibility") return "explain";
  return step.type === "solve" ? "solve" : "model";
}

function useNow(active: boolean) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  return now;
}

/** Where a running modeling task is: its stages so far, and how long it has run since its first step. */
function TaskProgress({ steps, stage, revising }: { steps: Step[]; stage: Stage; revising: boolean }) {
  const now = useNow(true);
  const stages: Stage[] = revising ? ["revise", "model", "solve", "explain"] : ["model", "solve", "explain"];
  const labels: Record<Stage, string> = { revise: t("理解调整"), model: t("建模"), solve: t("求解"), explain: t("解读") };
  const current = Math.max(0, stages.indexOf(stage));
  const started = steps[0]?.time;
  return <div className="mt-1.5 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
    <ol aria-label={t("求解阶段")} className="flex min-w-0 items-center gap-1.5 text-[11px]">
      {stages.map((item, index) => <li key={item} className="flex items-center gap-1.5" aria-current={index === current ? "step" : undefined}>
        {index ? <span aria-hidden className={cn("h-px w-3", index <= current ? "bg-primary/50" : "bg-border")} /> : null}
        <span className={cn("inline-flex items-center gap-1", index < current ? "text-foreground/80" : index === current ? "font-medium text-primary" : "text-muted-foreground/70")}>
          {index < current ? <Check className="size-3" /> : <span aria-hidden className={cn("size-1.5 rounded-full", index === current ? "animate-pulse bg-primary" : "bg-border")} />}
          {labels[item]}
        </span>
      </li>)}
    </ol>
    {/* The clock changes every second; it stays out of the live region so screen readers are not interrupted. */}
    {started ? <span aria-hidden className="ml-auto text-[11px] text-muted-foreground tabular">{t("已用时 {time}", { time: duration(Math.max(0, now / 1000 - started)) })}</span> : null}
  </div>;
}

/** The last question, edited in place and sent again as the same turn. */
function QuestionEditor({ text, disabled, onCancel, onSend }: { text: string; disabled?: boolean; onCancel: () => void; onSend: (text: string) => void }) {
  const [value, setValue] = useState(text);
  const send = () => { if (!disabled && value.trim() && value.trim() !== text.trim()) onSend(value.trim()); };
  return <div className="ml-auto flex w-full max-w-[85%] flex-col gap-2 rounded-2xl border border-primary/30 bg-card p-2.5 shadow-xs">
    <Textarea autoFocus aria-label={t("编辑问题")} value={value} onChange={event => setValue(event.target.value)}
      className="max-h-48 min-h-16 resize-none border-0 bg-transparent px-1.5 py-1 text-sm leading-relaxed shadow-none field-sizing-content focus-visible:ring-0 dark:bg-transparent"
      onKeyDown={event => {
        if (event.key === "Escape") { event.preventDefault(); onCancel(); }
        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.nativeEvent.keyCode !== 229) { event.preventDefault(); send(); }
      }} />
    <div className="flex justify-end gap-1.5">
      <Button type="button" variant="ghost" size="sm" className="rounded-lg" onClick={onCancel}>{t("取消")}</Button>
      <Button type="button" size="sm" className="rounded-lg" disabled={disabled || !value.trim() || value.trim() === text.trim()} onClick={send}>{t("重新发送")}</Button>
    </div>
  </div>;
}

function messageText(message: Message): string {
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
  return <details className="group/thinking mb-3 min-w-0" onToggle={event => setOpen(event.currentTarget.open)}>
    <summary className="flex w-fit max-w-full cursor-pointer list-none items-center gap-1.5 rounded-lg border border-border/60 bg-muted/30 px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      {active ? <Spinner className="size-3.5 text-primary" aria-hidden="true" role="presentation" /> : <Brain className="size-3.5 text-primary" />}
      <span>{t(active ? "正在思考……" : "思考过程")}</span><ChevronRight className="size-3.5 transition-transform group-open/thinking:rotate-90" />
    </summary>
    {open ? <div className="mt-2 max-h-64 overflow-y-auto border-l-2 border-primary/25 pl-3"><Markdown text={text} className="text-muted-foreground" /></div> : null}
  </details>;
});

/** Source and plan cards come from tool artifacts, never from model-written links or numbers. */
function ToolResult({ message, options, onOpenPlan, onCompare }: {
  message: Extract<Message, { type: "tool" }>; options?: Options; onOpenPlan?: (source: SourceRun) => void; onCompare?: (group: string) => void;
}) {
  if (message.status === "error") return <details className="group/error min-w-0 rounded-xl border border-destructive/20 bg-card px-3.5 py-2.5 text-xs">
    <summary className="flex cursor-pointer list-none items-center gap-2 text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <TriangleAlert className="size-3.5 shrink-0 text-destructive" /><span>{t("这一步未完成")}</span>
      <ChevronRight className="ml-auto size-3.5 shrink-0 transition-transform group-open/error:rotate-90" />
    </summary>
    <p className="mt-2 whitespace-pre-wrap break-words text-destructive">{messageText(message)}</p>
  </details>;
  const artifact = message.artifact as ToolArtifact | undefined;
  const type = resultType(artifact, message.name);
  const Result = Object.hasOwn(resultViews, type) ? resultViews[type] : undefined;
  return Result ? <Result artifact={artifact} options={options} onOpenPlan={onOpenPlan} onCompare={onCompare} /> : null;
}

export function ThreadLoadError({ error, onReload, header }: { error: unknown; onReload: () => void; header?: ReactNode }) {
  const body = <div role="alert" className="flex h-full flex-1 flex-col items-center justify-center gap-3 p-6 text-center text-sm text-destructive">
    <p>{errorText(error)}</p>
    <Button variant="outline" onClick={onReload}><RefreshCw />{t("重试")}</Button>
  </div>;
  return header ? <div className="flex h-full flex-col">{header}{body}</div> : body;
}

export function ChatMessages({ messages, loading, label, failure, disabled, onRetry, progress, onOpenPlan, onCompare, tasks, activeTaskId, onShowTask,
  options, suggestions, onSuggest, onEdit, onRegenerate }: {
  messages: Message[]; loading: boolean; label: string; failure?: unknown; disabled?: boolean; onRetry: () => void;
  progress?: ChatProgress; onOpenPlan?: (source: SourceRun) => void; onCompare?: (group: string) => void;
  tasks?: Record<string, ModelingTask>; activeTaskId?: string; onShowTask?: (id: string) => void;
  options?: Options; suggestions?: Suggestion[]; onSuggest?: (item: Suggestion) => void;
  /** Send the last question again, edited or unchanged, in place of the answer it received. */
  onEdit?: (text: string) => void; onRegenerate?: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const completed = new Set(messages.filter(message => message.type === "tool").map(message => message.tool_call_id));
  const last = messages.at(-1);
  const pending = last?.type === "ai" ? last : undefined;
  let turnAi: Extract<Message, { type: "ai" }> | undefined;
  for (let i = messages.length - 1; i >= 0; i--) {
    const message = messages[i];
    if (message.type === "human") break;
    if (message.type === "ai") { turnAi = message; break; }
  }
  const calls = loading ? turnAi?.tool_calls?.filter(call => !completed.has(call.id ?? "")) ?? [] : [];
  const unanswered = last?.type === "human";
  const stopped = failure && /^CancelledError(?:\(\))?$/.test(errorText(failure));
  const failed = !!failure && !stopped;
  const canRetry = unanswered || ((failed || stopped) && messages.some(message => message.type === "human"));
  // Only the latest finished turn can be asked again: earlier answers led to the plans the conversation now builds on.
  const lastIndex = (match: (message: Message) => boolean) => messages.reduce((found, message, index) => match(message) ? index : found, -1);
  const lastQuestion = lastIndex(message => message.type === "human");
  const lastAnswer = lastIndex(message => message.type === "ai" && !!messageText(message));
  const rewritable = !loading && !failure && lastQuestion >= 0 && lastAnswer > lastQuestion;
  // Plan conversations stream no modeling steps, so their scenario progress names the stage in words.
  const stages = { revise: t("整理调整后的问题"), model: t("正在建模"), solve: t("正在求解"), explain: t("解读求解结果") };
  return <div className="mx-auto flex w-full min-w-0 max-w-[46rem] flex-col gap-5 py-4">
    {messages.map((message, index) => {
      if (message.type === "tool") return <ToolResult key={message.id ?? index} message={message} options={options} onOpenPlan={onOpenPlan} onCompare={onCompare} />;
      if (message.type !== "human" && message.type !== "ai") return null;
      const text = messageText(message);
      const reasoning = messageReasoning(message);
      if (!text && !reasoning) return null;
      const human = message.type === "human";
      if (human && editing && index === lastQuestion && rewritable && onEdit) return <QuestionEditor key={message.id ?? index} text={text} disabled={disabled}
        onCancel={() => setEditing(false)} onSend={edited => { setEditing(false); onEdit(edited); }} />;
      return <article key={message.id ?? index} aria-label={human ? t("你") : label}
        className={human ? cn("group relative ml-auto w-fit min-w-0 max-w-[85%] rounded-2xl rounded-br-md border border-primary/15 bg-primary/[0.08] px-4 py-2.5 shadow-2xs",
            rewritable && index === lastQuestion && onEdit && "mb-6")
          : "group w-full min-w-0"}>
        {/* The assistant name stays available to readers and browser tests without repeating a visual header. */}
        {human ? null : <h3 className="sr-only select-none">{label}</h3>}
        {reasoning ? <Reasoning text={reasoning} active={loading && message === last && !text && !calls.length} /> : null}
        {text ? <Markdown text={text} /> : null}
        {text && !human && (!loading || message !== last) ? <div className="mt-1 flex items-center opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 pointer-coarse:opacity-100 max-sm:opacity-100">
          <CopyButton text={text} label={t("复制回复")} />
          {rewritable && index === lastAnswer && onRegenerate ? <Button type="button" variant="ghost" size="icon-sm" aria-label={t("重新生成")} title={t("重新生成")}
            disabled={disabled} onClick={onRegenerate}><RefreshCw /></Button> : null}
        </div> : null}
        {human && rewritable && index === lastQuestion && onEdit ? <div className="absolute -bottom-7 right-0 flex opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100 pointer-coarse:opacity-100 max-sm:opacity-100">
          <Button type="button" variant="ghost" size="icon-sm" aria-label={t("编辑问题")} title={t("编辑问题")} disabled={disabled} onClick={() => setEditing(true)}><Pencil /></Button>
        </div> : null}
      </article>;
    })}
    {loading && !(pending && messageReasoning(pending) && !messageText(pending) && !calls.length) ? <div role="status" className="flex min-w-0 flex-col gap-2.5 text-xs text-muted-foreground">
      {calls.length ? calls.map(call => {
        const live = call.id ? tasks?.[call.id] : undefined;
        const shownInPanel = !!call.id && activeTaskId === call.id;
        const currentStep = live ? phases(live.steps).at(-1)?.step?.title : undefined;
        const scenario = progress && progress.tool_call_id === call.id ? progress : undefined;
        return <div key={call.id ?? call.name} className="flex min-w-0 flex-col gap-2">
          <div className="flex items-start gap-2 rounded-xl border border-primary/20 bg-primary/5 px-3 py-2 text-foreground/90">
            <Spinner aria-hidden="true" role="presentation" className="mt-0.5 shrink-0 text-primary" /><div className="min-w-0 flex-1"><p className="font-medium">{live?.name || activity(call.name)}</p>
              {scenario ? <p className="mt-1 break-words text-muted-foreground">{t("方案 {index}/{total}：{name}", { index: scenario.index, total: scenario.total, name: scenario.name })}
                {live ? null : ` · ${stages[scenario.stage]}`}</p>
                : shownInPanel ? <p className="mt-0.5 break-words text-muted-foreground">{currentStep ? t("正在执行：{step}…", { step: t(currentStep) }) : t("右侧方案面板正在实时展示求解进度…")}</p>
                  : call.name === "web_search" && typeof call.args?.query === "string" ? <p className="mt-1 break-words text-muted-foreground">{call.args.query}</p> : null}
              {live ? <TaskProgress steps={live.steps} stage={scenario?.stage ?? taskStage(live.steps)} revising={call.name === "solve_scenarios"} /> : null}
            </div>
            {live && !shownInPanel && onShowTask ? <Button variant="link" size="xs" className="h-auto shrink-0 p-0 text-xs" onClick={() => onShowTask(call.id!)}>{t("查看详情")}</Button> : null}
          </div>
          {live && !shownInPanel ? <details className="min-w-0 overflow-hidden rounded-2xl border border-border/80 bg-card shadow-xs">
            <summary className="cursor-pointer bg-muted/20 px-3.5 py-2.5 text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">{live.name}</summary>
            <div className="h-64 border-t"><Timeline steps={live.steps} live={{}} active={loading}
              onShow={() => onShowTask?.(call.id!)} /></div>
            <div className="border-t px-3 py-1.5"><Button variant="link" size="sm" className="px-0" onClick={() => onShowTask?.(call.id!)}>{t("在方案面板中查看详情")}</Button></div>
          </details> : null}
        </div>;
      }) : <p className="flex items-center gap-2"><Spinner aria-hidden="true" role="presentation" className="text-primary" />{pending && messageText(pending) ? t("正在输出……") : t("正在准备回复……")}</p>}
    </div> : failed || stopped || unanswered ? <div className="min-w-0 rounded-2xl border border-border/80 bg-muted/30 p-3.5 text-xs" role={failed ? "alert" : "status"}>
      <p className="font-medium">{failed ? t("这轮回复未完成，可以重试。") : t("这轮回复已停止，可以重新回答。")}</p>
      <p className="mt-1 text-muted-foreground">{canRetry ? t("重试使用原问题，输入框中的草稿会保留。") : t("请从输入框重新发送，草稿会保留。")}</p>
      {failed ? <details className="mt-2 text-muted-foreground"><summary className="cursor-pointer hover:text-foreground">{t("查看错误详情")}</summary><p className="mt-1 max-h-32 overflow-auto whitespace-pre-wrap break-words">{errorText(failure)}</p></details> : null}
      {canRetry ? <Button variant="outline" size="sm" className="mt-3 rounded-lg" disabled={disabled} onClick={onRetry}><RefreshCw />{t("重试这一轮")}</Button> : null}
    </div> : suggestions?.length && onSuggest && rewritable ? <div role="group" aria-label={t("接下来可以")} className="animate-fade-up flex min-w-0 flex-wrap gap-2">
      {suggestions.map(item => <Button key={item.label} type="button" variant="outline" size="sm" disabled={disabled}
        className="h-8 rounded-full bg-card px-3 text-xs font-normal text-foreground/85 shadow-2xs hover:border-primary/40 hover:text-primary" onClick={() => onSuggest(item)}>
        {item.label}<ArrowRight className="size-3 opacity-60" /></Button>)}
    </div> : null}
  </div>;
}
