import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { v7 } from "@langchain/core/utils/uuid";
import { useStream } from "@langchain/langgraph-sdk/react";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import type { BagTemplate, Checkpoint, Config, Message, ThreadState } from "@langchain/langgraph-sdk";
import type { GetConfigurableType, GetCustomEventType, GetUpdateType } from "@langchain/langgraph-sdk/ui";
import { toast } from "sonner";
import { chatDraftKey, discussSupersteps, saveThreadValues, threadHeader } from "@/features/runs/api";
import { client } from "@/features/runs/sdk";
import { errorText } from "@/format";
import { t } from "@/i18n";
import type { Preset } from "@/types";

type Pending = { id: string; text: string };
type ConversationState = Record<string, unknown> & { messages?: Message[] };

/** Shared preset and DeepSeek thinking selection for conversation pages. */
export function useChatModel(presets: Preset[], meta?: { preset?: string | null; thinking?: boolean | null }) {
  const [selected, setSelected] = useState<string>();
  const [thinking, setThinking] = useState<boolean>();
  const preset = presets.find(item => item.id === (selected ?? meta?.preset)) ?? presets[0];
  const thinkingMode = preset?.provider === "deepseek" ? thinking ?? meta?.thinking ?? null : null;
  return { preset, presetId: preset?.id, setSelected, thinkingMode, setThinking };
}

/** Unsent messages stay in this browser tab and never enter the conversation history. */
export function useChatDraft(threadId: string, initial = "") {
  const key = chatDraftKey(threadId);
  const [value, setValue] = useState(() => { try { return initial || sessionStorage.getItem(key) || ""; } catch { return initial; } });
  const [recovered] = useState<Pending | null>(() => {
    try { return JSON.parse(sessionStorage.getItem(`${key}-pending`) ?? "null") as Pending | null; }
    catch { return null; }
  });
  const pending = useRef(recovered);
  useEffect(() => {
    try { if (value) sessionStorage.setItem(key, value); else sessionStorage.removeItem(key); } catch { /* storage may be unavailable */ }
  }, [key, value]);
  const prepare = (text: string): Message => {
    const message: Message = { type: "human", id: v7(), content: text.trim() };
    pending.current = { id: message.id!, text };
    try { sessionStorage.setItem(`${key}-pending`, JSON.stringify(pending.current)); } catch { /* storage may be unavailable */ }
    return message;
  };
  const acknowledge = useCallback((messages?: Message[]) => {
    const sent = pending.current;
    if (!sent || !messages?.some(message => message.id === sent.id)) return;
    // Run creation precedes the input checkpoint; only a checkpoint confirms the question was saved.
    setValue(current => current === sent.text ? "" : current);
    pending.current = null;
    try { sessionStorage.removeItem(`${key}-pending`); } catch { /* storage may be unavailable */ }
  }, [key]);
  /** Save the unconfirmed question; `target` covers a thread created just before navigation. */
  const savePending = async (target = threadId) => {
    const sent = pending.current;
    if (!sent) return;
    const message: Message = { type: "human", id: sent.id, content: sent.text.trim() };
    // Immediate cancellation can precede the graph's first input checkpoint.
    await saveThreadValues(target, { messages: [message] });
    acknowledge([message]);
  };
  return { value, setValue, prepare, acknowledge, savePending, needsRecovery: () => !!recovered && pending.current?.id === recovered.id };
}

export type ConversationTurn<State extends ConversationState, Bag extends BagTemplate = BagTemplate> = {
  /** Graph context for this turn, such as the preset and model options. */
  context?: GetConfigurableType<Bag>;
  /** Business state submitted with the message; the hook adds the message itself. */
  values?: Partial<State>;
  /** Thread metadata saved before the run starts. */
  metadata?: Record<string, unknown>;
  /** Resend the last user message with its original ID instead of the draft. */
  retry?: boolean;
  /** Send this text instead of the draft, which stays as it is. */
  text?: string;
};

export type ConversationOptions<State extends ConversationState, Bag extends BagTemplate = BagTemplate> = {
  assistantId: string;
  threadId?: string;
  /** Initial text for a conversation that has not been created yet. */
  initialInput?: string;
  /** Let the SDK restore an active run from its local stream receipt; Agent resumes by listing native runs instead. */
  reconnectOnMount?: boolean;
  onCustomEvent?: (event: GetCustomEventType<Bag>, options: { namespace: string[] | undefined }) => void;
  onCreated?: () => void;
  onFinish?: (state: ThreadState<State>) => void;
  onError?: () => void;
};

/**
 * The earliest checkpoint of a thread whose last message is `questionId`. History lists every branch newest first; a
 * question can be asked again only while it is the last one, so all checkpoints after its first save still contain it.
 * A run's own input checkpoint holds the question as a pending write, so only the next checkpoint ends with it.
 */
async function questionCheckpoint(threadId: string, questionId: string) {
  const size = 20;
  let found: Checkpoint | undefined, before: Config | undefined;
  for (;;) {
    const states = await client.threads.getHistory<ConversationState>(threadId, { limit: size, ...(before ? { before } : {}) });
    for (const state of states) {
      const messages = state.values?.messages ?? [];
      if (!messages.some(message => message.id === questionId)) return found;
      if (messages.at(-1)?.id === questionId) found = state.checkpoint;
    }
    if (states.length < size) return found;
    before = { configurable: { checkpoint_id: states.at(-1)!.checkpoint.checkpoint_id ?? undefined } };
  }
}

/**
 * The conversation lifecycle shared by the requirements, plan and optimization conversations.
 *
 * The hook owns the correctness rules callers would otherwise repeat:
 * - a prepared message is kept until a root checkpoint or the final persisted state confirms it; optimistic
 *   messages never do;
 * - retry resends the last user message with its original ID, and keeps the draft written meanwhile;
 * - stop cancels the server run first, then saves an unconfirmed message, and only then stops the local stream;
 * - each turn drops the previous run reference before it starts.
 *
 * Graphs, business state, layouts and custom events stay with the page. New-thread creation and reconnecting to a
 * run started before navigation remain explicit adapters (`startThread`, `reconnect`) over native SDK calls.
 */
export function useConversation<State extends ConversationState, Bag extends BagTemplate = BagTemplate>(
  options: ConversationOptions<State, Bag>,
) {
  const queryClient = useQueryClient();
  const threadId = options.threadId;
  const { value: input, setValue: setInput, prepare, acknowledge, savePending, needsRecovery } = useChatDraft(
    threadId ?? `${options.assistantId}-new`, threadId ? "" : options.initialInput);
  const thread = useQuery({
    queryKey: ["conversation", options.assistantId, threadId],
    enabled: !!threadId,
    queryFn: async ({ signal }) => {
      if (needsRecovery()) {
        const snapshot = await client.threads.get<State>(threadId!, { signal });
        return { metadata: snapshot.metadata, messages: snapshot.values?.messages };
      }
      const { metadata } = await threadHeader(client, threadId!, signal);
      return { metadata, messages: undefined };
    },
  });
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState(false);
  const sendingRef = useRef(false);
  const stoppingRef = useRef(false);
  const runId = useRef<string | null>(null);
  const startedRun = useRef<string | null>(null);
  const createdThread = useRef<string | undefined>(undefined);
  // The SDK's generic resolver keeps conditional state types unresolved inside this generic hook; the runtime object
  // is the normal `UseStream` for this state.
  const stream = useStream<State, Bag>({
    client, assistantId: options.assistantId, threadId: threadId ?? null, reconnectOnMount: options.reconnectOnMount ?? true,
    fetchStateHistory: false, throttle: 50,
    onMetadataEvent: event => { runId.current = event.run_id; },
    onCreated: event => { runId.current = event.run_id; options.onCreated?.(); },
    onCheckpointEvent: (event, { namespace }) => {
      if (namespace?.length) return;
      acknowledge((event.values as unknown as State).messages);
      // The first root checkpoint confirms execution has started, including a run that was queued.
      if (runId.current && startedRun.current !== runId.current) {
        startedRun.current = runId.current;
        void queryClient.invalidateQueries({ queryKey: ["history"] });
      }
    },
    onFinish: state => {
      // A stream can end without a root checkpoint event; the final state is the other persisted confirmation.
      acknowledge((state.values as unknown as State).messages);
      runId.current = null;
      options.onFinish?.(state as unknown as ThreadState<State>);
    },
    onError: () => options.onError?.(),
    onCustomEvent: options.onCustomEvent,
  }) as unknown as UseStream<State, Bag>;
  const join = useRef(stream.joinStream);
  const switchThreadRef = useRef(stream.switchThread);
  useEffect(() => {
    join.current = stream.joinStream;
    switchThreadRef.current = stream.switchThread;
  });
  useEffect(() => () => { switchThreadRef.current(null); }, []);

  // The thread query is also the confirmation that survives a reload. A new draft is never cleared here: the
  // draft module compares the acknowledged message ID with the text it is still holding. Do not confirm from
  // `stream.values`: an optimistic message is not persisted and must not clear the draft.
  const persisted = thread.data?.messages;
  useEffect(() => { acknowledge(persisted); }, [persisted, acknowledge]);

  const reconnect = useCallback(async (run: string) => {
    runId.current = run;
    await join.current(run, "-1");
  }, []);

  /** Start one turn; with `retry`, resend the last user message and its ID instead of the draft. */
  const send = async (turn: ConversationTurn<State, Bag> = {}) => {
    const active = threadId;
    const loading = stream.isLoading || stream.isThreadLoading || (!!active && thread.isPending);
    if (!active || sendingRef.current || stoppingRef.current || loading) return false;
    const question = turn.retry ? [...stream.messages].reverse().find(message => message.type === "human") : undefined;
    const text = turn.text ?? input;
    if (turn.retry ? !question : !text.trim()) return false;
    sendingRef.current = true;
    setSending(true);
    // A later message must never cancel or join the finished run that came before it.
    runId.current = null;
    try {
      if (turn.metadata) await client.threads.update(active, { metadata: turn.metadata, returnMinimal: true });
      const message = question ?? prepare(text);
      // `GetUpdateType` is conditional on the page's Bag and stays unresolved inside this generic hook.
      const update = { ...turn.values, messages: [message] } as unknown as GetUpdateType<Bag, State>;
      await stream.submit(update, {
        context: turn.context, multitaskStrategy: "reject", streamResumable: true, streamSubgraphs: true,
        optimisticValues: turn.retry ? undefined : current => ({
          ...current, ...turn.values, messages: [...(current.messages ?? []), message] }),
      });
      return true;
    } catch (error) { toast.error(errorText(error)); return false; }
    finally { sendingRef.current = false; setSending(false); }
  };

  /**
   * Ask the last question again, edited or unchanged, in place of its answer. The run forks from the earliest checkpoint
   * that ends with this question: the state just after it was saved, before any answer, plan or pending retry made for
   * it in any branch. The question keeps its ID, so the edit replaces it instead of adding a second question.
   */
  const rewrite = async (text: string, turn: ConversationTurn<State, Bag> = {}) => {
    const active = threadId;
    const loading = stream.isLoading || stream.isThreadLoading || (!!active && thread.isPending);
    const messages = stream.messages;
    const question = [...messages].reverse().find(message => message.type === "human");
    if (!active || !question?.id || !text.trim() || sendingRef.current || stoppingRef.current || loading) return false;
    sendingRef.current = true;
    setSending(true);
    runId.current = null;
    try {
      const fork = await questionCheckpoint(active, question.id);
      if (!fork?.checkpoint_id) throw new Error(t("找不到这个问题的保存记录，无法重新发送。"));
      if (turn.metadata) await client.threads.update(active, { metadata: turn.metadata, returnMinimal: true });
      const message: Message = { type: "human", id: question.id, content: text.trim() };
      const earlier = messages.slice(0, messages.indexOf(question));
      const update = { ...turn.values, messages: [message] } as unknown as GetUpdateType<Bag, State>;
      // The server rejects a null checkpoint_map, which the SDK type nonetheless requires.
      const checkpoint = { checkpoint_id: fork.checkpoint_id, checkpoint_ns: fork.checkpoint_ns ?? "",
        ...(fork.checkpoint_map ? { checkpoint_map: fork.checkpoint_map } : {}) } as Omit<Checkpoint, "thread_id">;
      await stream.submit(update, {
        context: turn.context, checkpoint,
        multitaskStrategy: "reject", streamResumable: true, streamSubgraphs: true,
        optimisticValues: current => ({ ...current, ...turn.values, messages: [...earlier, message] }),
      });
      return true;
    } catch (error) { toast.error(errorText(error)); return false; }
    finally { sendingRef.current = false; setSending(false); }
  };

  /** Persist the first message natively, then start its run before the page navigates to the new thread. */
  const startThread = async (turn: ConversationTurn<State, Bag>) => {
    if (threadId || sendingRef.current || stoppingRef.current || !input.trim()) return undefined;
    sendingRef.current = true;
    setSending(true);
    try {
      const message = prepare(input);
      const { thread_id: created } = await client.threads.create({ graphId: options.assistantId, metadata: turn.metadata,
        supersteps: discussSupersteps({ ...turn.values, messages: [message] }) });
      // `threads.create(supersteps)` is a root native checkpoint, so the question is already persisted.
      acknowledge([message]);
      createdThread.current = created;
      runId.current = null;
      try {
        const run = await client.runs.create(created, options.assistantId, {
          input: { messages: [message] }, context: turn.context,
          streamMode: ["messages", "custom", "values", "checkpoints"], streamSubgraphs: true, streamResumable: true,
        });
        runId.current = run.run_id;
        try { sessionStorage.setItem(`llm4om-agent-run-${created}`, run.run_id); } catch { /* storage may be unavailable */ }
      } catch (error) { toast.error(errorText(error)); }
      // The thread and its message remain usable even if the run could not be started.
      return created;
    } catch (error) { toast.error(errorText(error)); return undefined; }
    finally { sendingRef.current = false; setSending(false); }
  };

  /** Stop only after the server confirms cancellation and the unconfirmed question is saved. */
  const stop = async () => {
    const active = threadId ?? createdThread.current;
    if (!active || stoppingRef.current) return false;
    stoppingRef.current = true;
    setStopping(true);
    try {
      // Waiting for the server matters: only a confirmed cancellation may be followed by the local stop.
      let activeRunId = runId.current;
      if (!activeRunId) {
        try { activeRunId = sessionStorage.getItem(`lg:stream:${active}`); } catch { /* storage may be unavailable */ }
      }
      if (!activeRunId) {
        const [latest] = await client.runs.list(active, { limit: 1, select: ["run_id", "status"] });
        if (latest && (latest.status === "pending" || latest.status === "running")) activeRunId = latest.run_id;
      }
      if (activeRunId) {
        await client.runs.cancel(active, activeRunId, true);
        // The server run is stopped now; a later retry only needs to finish saving and stopping locally.
        runId.current = null;
      }
      // An immediate stop can precede the graph's first input checkpoint.
      await savePending(active);
      await stream.stop();
      return true;
    } catch (error) { toast.error(errorText(error)); return false; }
    finally { stoppingRef.current = false; setStopping(false); }
  };

  return {
    thread: {
      metadata: thread.data?.metadata as Record<string, unknown> | undefined,
      error: thread.error,
      reload: () => void thread.refetch(),
    },
    messages: stream.messages,
    values: stream.values,
    error: stream.error,
    loading: stream.isLoading,
    busy: sending || stopping || stream.isLoading || stream.isThreadLoading || (!!threadId && thread.isPending),
    stopping,
    input,
    setInput,
    send,
    rewrite,
    startThread,
    reconnect,
    stop,
  };
}
