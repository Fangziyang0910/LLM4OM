import { useEffect, useState } from "react";
import type { Run } from "@langchain/langgraph-sdk";
import { client } from "@/features/runs/sdk";
import { runMeta } from "@/features/runs/api";
import { errorText } from "@/format";
import { t } from "@/i18n";
import type { RunMeta, RunValues, Step } from "@/features/runs/types";

/** Text an LLM call has written so far, by step id; it goes away when the step finishes. */
export type Live = Record<string, { text: string; reasoning: string }>;
export type RunData = {
  meta: RunMeta | null; values: RunValues; steps: Step[]; live: Live;
  run: Run | null; streaming: boolean; error: string | null;
};

const EMPTY: RunData = { meta: null, values: {}, steps: [], live: {}, run: null, streaming: false, error: null };
type Event = { step?: Step; delta?: { id: string; text: string; reasoning: string } };

/**
 * One run, live. The server keeps each run's stream, so joining from the first event shows a running run the same
 * way whether this page started it or opened it later. Completed runs use thread state; interrupted runs also
 * load the saved public progress, which survives after their event stream expires.
 */
export function useRun(threadId: string, onFinished: () => void): RunData {
  const [data, setData] = useState<RunData>(EMPTY);

  useEffect(() => {
    const controller = new AbortController();
    const steps = new Map<string, Step>();
    let live: Live = {};
    let inputRead = false;
    setData(EMPTY);

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
    const replay = async (run: Run) => {
      const stream = client.runs.joinStream(threadId, run.run_id, { signal: controller.signal, lastEventId: "-1", streamMode: ["custom"] });
      for await (const part of stream) {
        if (part.event === "custom") receive(part.data);
        else if (part.event === "error") setData(current => ({ ...current, error: part.data?.message ?? errorText(part.data) }));
      }
    };

    (async () => {
      try {
        const { run, values } = await load();
        if (controller.signal.aborted) return;
        if (!run) return;
        if (run.status === "pending" || run.status === "running") {
          setData(current => ({ ...current, streaming: true }));
          let streamError: unknown;
          try { await replay(run); } catch (error) { streamError = error; }
          if (controller.signal.aborted) return;
          const latest = (await load()).run;
          if (streamError && (latest?.status === "pending" || latest?.status === "running")) throw streamError;
          onFinished();
        } else if (run.status !== "success" && !values.steps?.length) {
          inputRead = true;
          await replay(run).catch(() => undefined);  // the server may no longer hold the stream
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
  }, [threadId]); // eslint-disable-line react-hooks/exhaustive-deps

  return data;
}
