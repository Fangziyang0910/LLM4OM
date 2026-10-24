import { outcome } from "@/format";
import { locale, t } from "@/i18n";
import type { Draft } from "@/features/composer/types";
import type { Entry, RequirementsMeta, SolutionChatMeta, OptimizationMeta, RunMeta, RunSpec, RunValues, SourceRun, Usage } from "@/features/runs/types";
import type { Preset } from "@/types";

/** The LangGraph SDK client, loaded on first use. */
const sdk = () => import("@/features/runs/sdk").then(module => module.client);

/** Create a thread for the draft and start its run in the background; returns the thread id. */
export async function startRun(draft: Draft, preset: Preset | undefined, group: string | null = null,
    revision?: { instruction: string; source: SourceRun; name?: string }): Promise<string> {
  if (draft.preset && !preset) throw new Error(t("原预设已删除，请重新选择预设模型。"));
  const title = draft.description.trim().split("\n")[0].replace(/^#{1,6}\s+/, "").slice(0, 120);
  const meta: RunMeta = { title: revision ? `${title} · ${revision.name || revision.instruction.slice(0, 60)}` : title,
    method: draft.method, language: draft.language, preset: preset?.id ?? null,
    ...(draft.solver ? { solver: draft.solver } : {}),
    ...(draft.origin ? { origin: draft.origin } : {}),
    provider: preset?.provider ?? null, model: preset?.name || preset?.model || null, ...(group ? { group } : {}),
    ...(revision ? { parent: revision.source, ...(revision.name ? { scenario: { name: revision.name, instruction: revision.instruction } } : {}) } : {}) };
  const client = await sdk();
  const thread = await client.threads.create({ metadata: meta });
  try {
    await client.runs.create(thread.thread_id, draft.method, {
      input: { description: draft.description, data: draft.data, ...(revision ? { change: revision.instruction } : {}) },
      context: { language: draft.language, solver: draft.solver, preset: preset?.id ?? null, explain: true, locale },
      streamMode: ["custom"], streamResumable: true,
    });
  } catch (error) {
    // A lost response can hide an accepted run, including a retry rejected because that run is now active.
    const accepted = await client.runs.list(thread.thread_id, { limit: 1 }).catch(() => null);
    if (accepted?.length) return thread.thread_id;
    if (accepted && error instanceof Error && "status" in error && typeof error.status === "number"
        && error.status >= 400 && error.status < 500)
      await client.threads.delete(thread.thread_id).catch(() => undefined);
    throw error;
  }
  return thread.thread_id;
}

/** Revise a saved checkpoint in a new thread; the source's problem, attachments and choices remain intact. */
export async function startRevision(threadId: string, instruction: string, presets: Preset[]): Promise<string> {
  if (!instruction.trim()) throw new Error(t("请描述要调整的条件。"));
  const source = await revisionSource(threadId, presets);
  return startRun(source.draft, source.preset, null, { instruction: instruction.trim(), source: source.source });
}

async function revisionSource(threadId: string, presets: Preset[]) {
  const client = await sdk();
  const [state, thread] = await Promise.all([client.threads.getState<RunValues>(threadId), client.threads.get(threadId)]);
  if (thread.status === "busy") throw new Error(t("请等待当前运行结束后再调整条件。"));
  const values = state.values as RunValues;
  if (!values.description || !state.checkpoint.checkpoint_id) throw new Error(t("原问题尚未保存，请稍后重试。"));
  const meta = runMeta(thread.metadata as RunMeta, values.spec);
  const preset = meta.preset ? presets.find(item => item.id === meta.preset) : presets[0];
  return { draft: { description: values.description, data: values.data ?? {}, method: meta.method,
    language: meta.language, solver: meta.solver, preset: meta.preset ?? null }, preset,
    source: { thread_id: threadId, checkpoint_id: state.checkpoint.checkpoint_id } };
}

const comparisonId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");

/** Every alternative starts from one frozen source, including when the source is rerun during the batch. */
export async function startScenarios(threadId: string, scenarios: { name: string; instruction: string }[], presets: Preset[]) {
  if (scenarios.length < 2 || scenarios.length > 6 || scenarios.some(item => !item.name.trim() || !item.instruction.trim()))
    throw new Error(t("请填写 2 至 6 个完整的场景。"));
  const source = await revisionSource(threadId, presets), group = comparisonId();
  let started = 0;
  try {
    for (const scenario of scenarios) {
      await startRun(source.draft, source.preset, group, { ...scenario, source: source.source }); started++;
    }
  } catch (error) {
    if (!started) throw error;
    return { group, started, error };
  }
  return { group, started, error: null };
}

/** Start one run of the same problem for each method and preset, as one comparison. If a start fails after others
 * started, those runs stay in the comparison and `error` says why the rest did not start. */
export async function startComparison(draft: Draft, runs: { method: string; preset: Preset | undefined }[]):
    Promise<{ group: string; started: number; error: unknown }> {
  // crypto.randomUUID needs HTTPS; the workbench is often opened over plain HTTP on the network.
  const group = comparisonId();
  let started = 0;
  try {
    for (const item of runs) { await startRun({ ...draft, method: item.method }, item.preset, group); started++; }
  } catch (error) {
    if (!started) throw error;
    return { group, started, error };
  }
  return { group, started, error: null };
}

/** Merge `change` into a run's metadata: its note and tags. */
export async function updateMeta(threadId: string, change: Partial<Pick<RunMeta, "note" | "tags">>): Promise<void> {
  await (await sdk()).threads.update(threadId, { metadata: change });
}

/** Recorded configuration owns these fields; thread metadata also holds editable notes and legacy records. */
export function runMeta(metadata: RunMeta, spec?: RunSpec | null): RunMeta {
  return spec ? { ...metadata, method: spec.method, language: spec.language, solver: spec.solver, preset: spec.preset,
    provider: spec.llm.provider, model: spec.preset_name || spec.llm.model } : metadata;
}

export async function deleteRun(threadId: string): Promise<void> {
  try { await (await sdk()).threads.delete(threadId); }
  catch (error) {
    // A retry also clears progress left after the thread was already deleted.
    if (!(error instanceof Error && "status" in error && error.status === 404)) throw error;
  }
}

const PAGE_SIZE = 100;
export async function history(metadata?: Record<string, unknown>, offset = 0): Promise<{ entries: Entry[]; nextOffset: number | undefined }> {
  const threads = await (await sdk()).threads.search({ limit: PAGE_SIZE, offset, sortBy: "created_at", sortOrder: "desc", metadata,
    select: ["thread_id", "created_at", "updated_at", "status", "metadata"],
    extract: { objective: "values.solve.objective", solved: "values.solve.status", failure: "values.failure", usage: "values.usage",
      elapsed: "values.timing.elapsed", finished_at: "values.timing.finished_at", spec: "values.spec", actual_solver: "values.solve.solver" } });
  const entries = threads.filter(thread => thread.metadata?.title).map(thread => {
    const extracted = (thread as unknown as { extracted?: Record<string, unknown> }).extracted ?? {};
    // A thread is idle once its run finished; interrupted and error keep the run's own status.
    const state = outcome(thread.status === "busy", thread.status === "idle" ? "success" : thread.status, extracted.failure,
      extracted.solved as string | undefined);
    const spec = extracted.spec as RunSpec | undefined;
    const meta = ["requirements", "solution_chat", "optimization"].includes(String(thread.metadata?.kind))
      ? thread.metadata as RequirementsMeta | SolutionChatMeta | OptimizationMeta : runMeta(thread.metadata as RunMeta, spec);
    if ((meta.kind == null || meta.kind === "run") && typeof extracted.actual_solver === "string") (meta as RunMeta).solver = extracted.actual_solver;
    return { id: thread.thread_id, created: thread.created_at, updated: thread.updated_at, meta, state,
      objective: typeof extracted.objective === "number" ? extracted.objective : null,
      elapsed: extracted.finished_at && typeof extracted.elapsed === "number" ? extracted.elapsed : null,
      failure: typeof extracted.failure === "string" ? extracted.failure : null, usage: (extracted.usage as Usage | undefined) ?? null };
  });
  return { entries, nextOffset: threads.length === PAGE_SIZE ? offset + PAGE_SIZE : undefined };
}
