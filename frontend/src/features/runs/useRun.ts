import { useEffect, useState } from "react";
import type { Run } from "@langchain/langgraph-sdk";
import { client } from "@/features/runs/sdk";
import { runMeta } from "@/features/runs/api";
import { errorText } from "@/format";
import { t } from "@/i18n";
import type { RunMeta, RunValues, SourceRun, Step } from "@/features/runs/types";

/** Text an LLM call has written so far, by step id; it goes away when the step finishes. */
export type Live = Record<string, { text: string; reasoning: string }>;
export type RunData = {
  meta: RunMeta | null; values: RunValues; steps: Step[]; live: Live;
  run: Run | null; streaming: boolean; error: string | null;
};

const EMPTY: RunData = { meta: null, values: {}, steps: [], live: {}, run: null, streaming: false, error: null };
type Event = { step?: Step; delta?: { id: string; text: string; reasoning: string } };

/** One run: a thread's latest run, or a saved plan at its fixed checkpoint. */
export function useRun(run: string | SourceRun, onFinished: () => void, refresh = 0): RunData {
  const threadId = typeof run === "string" ? run : run.thread_id;
  const checkpointId = typeof run === "string" ? undefined : run.checkpoint_id;
  const [data, setData] = useState<RunData>(EMPTY);

  useEffect(() => {
    const controller = new AbortController();
    setData(EMPTY);

    // A saved plan has a final state of its own. Read it from its checkpoint only: a later run of the same thread,
    // its active stream and its temporary progress are different facts and must not replace this plan.
    if (checkpointId) {
      void (async () => {
        try {
          // Thread metadata names the run and joins it to a comparison; the plan's values come from the checkpoint.
          const [thread, state] = await Promise.all([
            client.threads.get<RunValues>(threadId),
            client.threads.getState<RunValues>(threadId, checkpointId),
          ]);
          if (controller.signal.aborted) return;
          const values = (state.values ?? {}) as RunValues;
          setData({ meta: runMeta(thread.metadata as RunMeta, values.spec), values,
            steps: values.steps ?? [], live: {}, run: null, streaming: false, error: null });
        } catch (error) {
          if (!controller.signal.aborted) setData(current => ({ ...current, error: errorText(error) }));
        }
      })();
      return () => controller.abort();
    }

    const steps = new Map<string, Step>();
    let live: Live = {};
    let inputRead = false;

    const load = async () => {
      const [thread, runs] = await Promise.all([client.threads.get<RunValues>(threadId), client.runs.list(threadId, { limit: 1 })]);
      const saved = runs[0] && runs[0].status !== "success" ? await client.store.getItem(["llm4om", "progress"], threadId,
        { signal: controller.signal }) : null;
      const values = { ...(thread.values ?? {}), ...(saved?.value ?? {}) } as RunValues;
      for (const step of values.steps ?? []) steps.set(step.id, step);
      if (!controller.signal.aborted) setData(current => ({ ...current, meta: runMeta(thread.metadata as RunMeta, values.spec), values, run: runs[0] ?? null,
        steps: values.steps?.length ? values.steps : current.steps }));
      return { run: runs[0] ?? null, values };
    };
    const receive = (event: Event) => {
      if (controller.signal.aborted) return;
      if (!inputRead) {
        // The thread's values follow the run only when it ends; its latest checkpoint has the input from the first step on.
        inputRead = true;
        void client.threads.getState<RunValues>(threadId).then(state => {
          if (!controller.signal.aborted) setData(current => ({ ...current,
            values: { ...(state.values as RunValues ?? {}), ...current.values } }));
        }).catch(() => undefined);
      }
      if (event.step) {
        steps.set(event.step.id, event.step);
        if (!event.step.running) { live = { ...live }; delete live[event.step.id]; }
      } else if (event.delta) {
        const { id, text, reasoning } = event.delta;
        const before = live[id] ?? { text: "", reasoning: "" };
        live = { ...live, [id]: { text: before.text + text, reasoning: before.reasoning + reasoning } };
      }
      setData(current => ({ ...current, steps: [...steps.values()], live }));
    };
    const replay = async (active: Run) => {
      const stream = client.runs.joinStream(threadId, active.run_id, { signal: controller.signal, lastEventId: "-1", streamMode: ["custom"] });
      for await (const part of stream) {
        if (part.event === "custom") receive(part.data);
        else if (part.event === "error") setData(current => ({ ...current, error: part.data?.message ?? errorText(part.data) }));
      }
    };

    (async () => {
      try {
        const { run: latest, values } = await load();
        if (controller.signal.aborted) return;
        if (!latest) return;
        if (latest.status === "pending" || latest.status === "running") {
          setData(current => ({ ...current, streaming: true }));
          let streamError: unknown;
          try { await replay(latest); } catch (error) { streamError = error; }
          if (controller.signal.aborted) return;
          const current = (await load()).run;
          if (current?.status === "pending" || current?.status === "running") {
            throw streamError ?? new Error(t("实时连接已断开，服务器仍在运行。"));
          }
          onFinished();
        } else if (latest.status !== "success" && !values.steps?.length) {
          inputRead = true;
          await replay(latest).catch(() => undefined);  // the server may no longer hold the stream
        }
      } catch (error) {
        if (!controller.signal.aborted) setData(current => ({ ...current, error: errorText(error) }));
      } finally {
        // Only a finished run can turn an unfinished step into a stopped step.
        if (!controller.signal.aborted) setData(current => ({ ...current, streaming: false, live: {},
          steps: current.steps.map(step => step.running && current.run?.status !== "running" && current.run?.status !== "pending"
            ? { ...step, running: false, failed: true, content: step.content || t("（已停止）") } : step) }));
      }
    })();
    return () => controller.abort();
  }, [threadId, checkpointId, refresh]); // eslint-disable-line react-hooks/exhaustive-deps

  return data;
}
