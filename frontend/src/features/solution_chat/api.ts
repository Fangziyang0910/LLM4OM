import { runMeta } from "@/features/runs/api";
import type { RunMeta, RunValues, SolutionChatMeta } from "@/features/runs/types";
import { t } from "@/i18n";

/** Freeze the starting checkpoint; future reruns of the source cannot change this conversation's facts. */
export async function createSolutionChat(threadId: string): Promise<string> {
  const { client } = await import("@/features/runs/sdk");
  const [thread, state] = await Promise.all([client.threads.get(threadId), client.threads.getState<RunValues>(threadId)]);
  if (thread.status === "busy") throw new Error(t("请等待当前运行结束后再讨论方案。"));
  const values = state.values as RunValues;
  if (!values.spec || !values.description || !state.checkpoint.checkpoint_id) throw new Error(t("原问题尚未保存，请稍后重试。"));
  const meta = runMeta(thread.metadata as RunMeta, values.spec);
  const source = { thread_id: threadId, checkpoint_id: state.checkpoint.checkpoint_id };
  const existing = await client.threads.search({ metadata: { kind: "solution_chat", parent: source }, limit: 1, select: ["thread_id"] });
  if (existing.length) return existing[0].thread_id;
  const metadata: SolutionChatMeta = { kind: "solution_chat", title: t("方案对话 · {title}", { title: meta.title }),
    preset: meta.preset, provider: meta.provider, model: meta.model, parent: source };
  const created = await client.threads.create({ graphId: "solution_chat", metadata,
    supersteps: [{ updates: [{ asNode: "discuss", values: { source, current: source, messages: [], plans: [] } }] }] });
  return created.thread_id;
}
