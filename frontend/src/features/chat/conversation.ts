import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useStream } from "@langchain/langgraph-sdk/react";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import type { BagTemplate, Message, ThreadState } from "@langchain/langgraph-sdk";
import type { GetConfigurableType, GetCustomEventType, GetUpdateType } from "@langchain/langgraph-sdk/ui";
import { toast } from "sonner";
import { client } from "@/features/runs/sdk";
import { errorText } from "@/format";
import { useChatDraft } from "./draft";

type ConversationState = Record<string, unknown> & { messages?: Message[] };

export type ConversationTurn<State extends ConversationState, Bag extends BagTemplate = BagTemplate> = {
  /** Graph context for this turn, such as the preset and model options. */
  context?: GetConfigurableType<Bag>;
  /** Business state submitted with the message; the hook adds the message itself. */
  values?: Partial<State>;
  /** Thread metadata saved before the run starts. */
  metadata?: Record<string, unknown>;
  /** Resend the last user message with its original ID instead of the draft. */
  retry?: boolean;
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
  const threadId = options.threadId;
  const { value: input, setValue: setInput, prepare, acknowledge, savePending } = useChatDraft(
    threadId ?? `${options.assistantId}-new`, threadId ? "" : options.initialInput);
  const thread = useQuery({
    queryKey: ["conversation", options.assistantId, threadId],
    enabled: !!threadId,
    queryFn: () => client.threads.get<State>(threadId!),
  });
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState(false);
  const sendingRef = useRef(false);
  const stoppingRef = useRef(false);
  const runId = useRef<string | null>(null);
  const createdThread = useRef<string | undefined>(undefined);
  // The SDK's generic resolver keeps conditional state types unresolved inside this generic hook; the runtime object
  // is the normal `UseStream` for this state.
  const stream = useStream<State, Bag>({
    client, assistantId: options.assistantId, threadId: threadId ?? null, reconnectOnMount: options.reconnectOnMount ?? true,
    fetchStateHistory: false, throttle: 50,
    onMetadataEvent: event => { runId.current = event.run_id; },
    onCreated: event => { runId.current = event.run_id; options.onCreated?.(); },
    onCheckpointEvent: (event, { namespace }) => {
      if (!namespace?.length) acknowledge((event.values as unknown as State).messages);
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
  useEffect(() => { join.current = stream.joinStream; });

  // The thread query is also the confirmation that survives a reload. A new draft is never cleared here: the
  // draft module compares the acknowledged message ID with the text it is still holding. Do not confirm from
  // `stream.values`: an optimistic message is not persisted and must not clear the draft.
  const persisted = thread.data?.values?.messages;
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
    if (turn.retry ? !question : !input.trim()) return false;
    sendingRef.current = true;
    setSending(true);
    // A later message must never cancel or join the finished run that came before it.
    runId.current = null;
    try {
      if (turn.metadata) await client.threads.update(active, { metadata: turn.metadata });
      const message = question ?? prepare(input);
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

  /** Persist the first message natively, then start its run before the page navigates to the new thread. */
  const startThread = async (turn: ConversationTurn<State, Bag>) => {
    if (threadId || sendingRef.current || stoppingRef.current || !input.trim()) return undefined;
    sendingRef.current = true;
    setSending(true);
    try {
      const message = prepare(input);
      let created: string;
      try {
        created = (await client.threads.create({ graphId: options.assistantId, metadata: turn.metadata,
          supersteps: [{ updates: [{ asNode: "discuss", values: { ...turn.values, messages: [message] } }] }] })).thread_id;
      } catch (error) { toast.error(errorText(error)); return undefined; }
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
      if (runId.current) {
        await client.runs.cancel(active, runId.current, true);
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
    startThread,
    reconnect,
    stop,
  };
}
