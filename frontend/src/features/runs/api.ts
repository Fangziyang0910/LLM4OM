import { outcome } from "@/format";
import { locale, t } from "@/i18n";
import type { Entry, OptimizationMeta, RequirementsMeta, RunMeta, RunSpec, RunValues, SolutionChatMeta, SourceRun, Usage } from "@/features/runs/types";
import type { Draft, Preset } from "@/types";

export type RequirementsDraft = { description: string; data: Record<string, string> };

/** The LangGraph SDK client, loaded on first use so the initial page entry stays lightweight. */
const sdk = () => import("@/features/runs/sdk").then(module => module.client);

export const chatDraftKey = (threadId: string) => `llm4om-message-${threadId}`;

export function clearChatDraft(threadId: string): void {
  const key = chatDraftKey(threadId);
  try {
    sessionStorage.removeItem(key);
    sessionStorage.removeItem(`${key}-pending`);
  } catch { /* storage may be unavailable */ }
}

/** Centralize the conversation graph node name for native LangGraph checkpoint writes. */
export const discussSupersteps = (values: Record<string, unknown>) => [{ updates: [{ asNode: "discuss", values }] }];

export async function saveThreadValues(threadId: string, values: Record<string, unknown>): Promise<void> {
  await (await sdk()).threads.updateState(threadId, { values, asNode: "discuss" });
}

export async function getThreadKind(threadId: string): Promise<string | undefined> {
  const thread = await (await sdk()).threads.get(threadId);
  return thread.metadata?.kind as string | undefined;
}

function titleFromDescription(description: string, fallback: string): string {
  const line = description.split(/\r?\n/)
    .map(item => item.trim().replace(/^#{1,6}(?:\s+|$)/, "").trim())
    .find(Boolean);
  return (line || fallback).slice(0, 120);
}

/** Create a thread for the draft and start its run in the background; returns the thread id. */
export async function startRun(draft: Draft, preset: Preset | undefined, group: string | null = null,
    revision?: { instruction: string; source: SourceRun; name?: string }): Promise<string> {
  if (draft.preset && !preset) throw new Error(t("原预设已删除，请重新选择预设模型。"));
  const title = titleFromDescription(draft.description, t("未命名方案"));
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
      context: { language: draft.language, solver: draft.solver, preset: preset?.id ?? null, explain: true, locale,
        ...(draft.time_limit ? { time_limit: draft.time_limit } : {}) },
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

async function loadCheckpoint(threadId: string, source: SourceRun | undefined, busyMessage: string, requireSpec = false) {
  const client = await sdk();
  const targetId = source?.thread_id ?? threadId;
  const [state, thread] = await Promise.all([
    client.threads.getState<RunValues>(targetId, source?.checkpoint_id),
    client.threads.get(targetId),
  ]);
  if (!source && thread.status === "busy") throw new Error(busyMessage);
  const values = state.values as RunValues;
  if ((requireSpec && !values.spec) || !values.description || !state.checkpoint.checkpoint_id)
    throw new Error(t("原问题尚未保存，请稍后重试。"));
  return {
    values,
    meta: runMeta(thread.metadata as RunMeta, values.spec),
    pinned: source ?? { thread_id: targetId, checkpoint_id: state.checkpoint.checkpoint_id },
  };
}

async function revisionSource(threadId: string, presets: Preset[], source?: SourceRun) {
  const { values, meta, pinned } = await loadCheckpoint(threadId, source, t("请等待当前运行结束后再调整条件。"));
  const preset = meta.preset ? presets.find(item => item.id === meta.preset) : presets[0];
  return { draft: { description: values.description!, data: values.data ?? {}, method: meta.method,
    language: meta.language, solver: meta.solver, preset: meta.preset ?? null }, preset, source: pinned };
}

/** Revise a saved checkpoint in a new thread; the source's problem, attachments and choices remain intact. */
export async function startRevision(threadId: string, instruction: string, presets: Preset[], source?: SourceRun): Promise<string> {
  if (!instruction.trim()) throw new Error(t("请描述要调整的条件。"));
  const base = await revisionSource(threadId, presets, source);
  return startRun(base.draft, base.preset, null, { instruction: instruction.trim(), source: base.source });
}

/** A native thread holds the conversation and editable draft, even before the first message. */
export async function createRequirements(draft: RequirementsDraft, preset: Preset | undefined, origin?: string): Promise<string> {
  const client = await sdk();
  const metadata: RequirementsMeta = { kind: "requirements",
    title: titleFromDescription(draft.description, t("新需求对话")),
    preset: preset?.id ?? null, provider: preset?.provider ?? null, model: preset?.name || preset?.model || null,
    ...(origin ? { origin } : {}) };
  const thread = await client.threads.create({ graphId: "requirements", metadata,
    supersteps: discussSupersteps({ ...draft, messages: [] }) });
  return thread.thread_id;
}

/** Freeze the starting checkpoint; future reruns of the source cannot change this conversation's facts. */
export async function createSolutionChat(run: string | SourceRun): Promise<string> {
  const client = await sdk();
  const source = typeof run === "string" ? undefined : run;
  const threadId = typeof run === "string" ? run : run.thread_id;
  const { meta, pinned } = await loadCheckpoint(threadId, source, t("请等待当前运行结束后再讨论方案。"), true);
  const existing = await client.threads.search({ metadata: { kind: "solution_chat", parent: pinned }, limit: 1, select: ["thread_id"] });
  if (existing.length) return existing[0].thread_id;
  const metadata: SolutionChatMeta = { kind: "solution_chat", title: t("方案对话 · {title}", { title: meta.title }),
    preset: meta.preset, provider: meta.provider, model: meta.model, parent: pinned };
  const created = await client.threads.create({ graphId: "solution_chat", metadata,
    supersteps: discussSupersteps({ source: pinned, current: pinned, messages: [], plans: [] }) });
  return created.thread_id;
}

const comparisonId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, "0")).join("");

async function startBatch<T>(items: T[], launch: (item: T, group: string) => Promise<string>):
    Promise<{ group: string; started: number; error: unknown }> {
  // crypto.randomUUID needs HTTPS; the workbench is often opened over plain HTTP on the network.
  const group = comparisonId();
  let started = 0;
  try {
    for (const item of items) { await launch(item, group); started++; }
  } catch (error) {
    if (!started) throw error;
    return { group, started, error };
  }
  return { group, started, error: null };
}

/** Every alternative starts from one frozen source, including when the source is rerun during the batch. */
export async function startScenarios(threadId: string, scenarios: { name: string; instruction: string }[], presets: Preset[], source?: SourceRun) {
  if (scenarios.length < 2 || scenarios.length > 6 || scenarios.some(item => !item.name.trim() || !item.instruction.trim()))
    throw new Error(t("请填写 2 至 6 个完整的场景。"));
  const base = await revisionSource(threadId, presets, source);
  return startBatch(scenarios, (scenario, group) => startRun(base.draft, base.preset, group, { ...scenario, source: base.source }));
}

/** Start one run of the same problem for each method and preset, as one comparison. If a start fails after others
 * started, those runs stay in the comparison and `error` says why the rest did not start. */
export async function startComparison(draft: Draft, runs: { method: string; language?: string; solver?: string; preset: Preset | undefined }[]):
    Promise<{ group: string; started: number; error: unknown }> {
  return startBatch(runs, (item, group) => startRun({
    ...draft,
    method: item.method,
    ...(item.language ? { language: item.language } : {}),
    ...(item.solver ? { solver: item.solver } : {}),
  }, item.preset, group));
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
  clearChatDraft(threadId);
}

const PAGE_SIZE = 100;
export async function history(metadata?: Record<string, unknown>, offset = 0): Promise<{ entries: Entry[]; nextOffset: number | undefined }> {
  const client = await sdk();
  const threads = await client.threads.search({ limit: PAGE_SIZE, offset, sortBy: "created_at", sortOrder: "desc", metadata,
    select: ["thread_id", "created_at", "updated_at", "status", "metadata"],
    // LangGraph's /threads/search schema caps `extract` at 10 properties (`maxProperties: 10`).
    extract: { objective: "values.solve.objective", pareto_total: "values.solve.pareto.total", solved: "values.solve.status",
      failure: "values.failure", usage: "values.usage", timing: "values.timing", spec: "values.spec",
      actual_solver: "values.solve.solver", last_message_type: "values.messages[-1].type", last_message_tools: "values.messages[-1].tool_calls" } });
  const entries = (await Promise.all(threads.filter(thread => thread.metadata?.title).map(async thread => {
    const extracted = (thread as unknown as { extracted?: Record<string, unknown> }).extracted ?? {};
    const timing = (extracted.timing && typeof extracted.timing === "object" ? extracted.timing : null) as Record<string, unknown> | null;
    const finishedAt = timing?.finished_at ?? extracted.finished_at;
    const elapsed = timing?.elapsed ?? extracted.elapsed;
    const conversation = ["requirements", "solution_chat", "optimization"].includes(String(thread.metadata?.kind));
    // Cancellation can leave the thread idle. Only its run distinguishes a stopped turn from a completed one.
    // Finished replies and completed modeling runs already have their outcome in the extracted state.
    const unfinished = conversation ? extracted.last_message_type !== "ai"
      || (Array.isArray(extracted.last_message_tools) && extracted.last_message_tools.length > 0) : !extracted.solved || !finishedAt;
    let latest;
    if (thread.status === "busy" || (thread.status === "idle" && unfinished)) {
      try {
        latest = (await client.runs.list(thread.thread_id, { limit: 1, select: ["status"] }))[0];
      } catch (error) {
        if (error instanceof Error && "status" in error && error.status === 404) return null;
        throw error;
      }
    }
    const status = latest?.status ?? (thread.status === "idle" ? (conversation || !unfinished ? "success" : "interrupted") : thread.status);
    const state = outcome(latest ? status === "running" : thread.status === "busy", status, extracted.failure,
      extracted.solved as string | undefined);
    const spec = extracted.spec as RunSpec | undefined;
    const meta = conversation
      ? thread.metadata as RequirementsMeta | SolutionChatMeta | OptimizationMeta : runMeta(thread.metadata as RunMeta, spec);
    if ((meta.kind == null || meta.kind === "run") && typeof extracted.actual_solver === "string") (meta as RunMeta).solver = extracted.actual_solver;
    return { id: thread.thread_id, created: thread.created_at, updated: thread.updated_at, meta, state,
      objective: typeof extracted.objective === "number" ? extracted.objective : null,
      paretoTotal: typeof extracted.pareto_total === "number" ? extracted.pareto_total : undefined,
      elapsed: finishedAt && typeof elapsed === "number" ? elapsed : null,
      failure: typeof extracted.failure === "string" ? extracted.failure : null, usage: (extracted.usage as Usage | undefined) ?? null } as Entry;
  }))).filter((entry): entry is Entry => entry !== null);
  return { entries, nextOffset: threads.length === PAGE_SIZE ? offset + PAGE_SIZE : undefined };
}
