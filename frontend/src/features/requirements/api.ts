import { t } from "@/i18n";
import type { RequirementsMeta } from "@/features/runs/types";
import type { Preset } from "@/types";

export type RequirementsDraft = { description: string; data: Record<string, string> };

/** A native thread holds the conversation and editable draft, even before the first message. */
export async function createRequirements(draft: RequirementsDraft, preset: Preset | undefined): Promise<string> {
  const { client } = await import("@/features/runs/sdk");
  const metadata: RequirementsMeta = { kind: "requirements",
    title: draft.description.trim().split("\n")[0].replace(/^#{1,6}\s+/, "").slice(0, 120) || t("新需求对话"),
    preset: preset?.id ?? null, provider: preset?.provider ?? null, model: preset?.name || preset?.model || null };
  const thread = await client.threads.create({ graphId: "requirements", metadata,
    supersteps: [{ updates: [{ asNode: "discuss", values: { ...draft, messages: [] } }] }] });
  return thread.thread_id;
}
